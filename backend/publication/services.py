"""课表发布领域服务。

发布流程的全部数据库写操作放在同一个原子事务中：
先锁定当前学期行，使同一学期的并发发布串行化；再按当前学期的活课表
重新核对教师 / 班级 / 教室冲突，任一冲突即抛异常回滚；全部通过才保存
快照并生成新版本。失败、重复发布、并发竞争都不会留下任何半成品。
"""
import hashlib
import json

from django.db import transaction

from core.models import Semester
from scheduling.csp_solver import ConflictDetector
from scheduling.models import ScheduleEntry
from .models import ScheduleVersion, ScheduleSnapshotEntry


class PublicationError(Exception):
    """发布失败的基类，携带可直接返回给前端的信息。"""

    def __init__(self, message, code='publication_failed'):
        self.message = message
        self.code = code
        super().__init__(message)


class EmptyScheduleError(PublicationError):
    def __init__(self):
        super().__init__('当前学期还没有课表条目，无法发布', code='empty_schedule')


class ConflictRejectedError(PublicationError):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__(
            f'课表存在 {len(conflicts)} 处冲突，发布已被拒绝，原发布版本保持不变',
            code='conflict_detected',
        )


class DuplicatePublishError(PublicationError):
    def __init__(self, version_number):
        self.version_number = version_number
        super().__init__(
            f'课表内容与最新发布版本 v{version_number} 完全一致，无需重复发布',
            code='duplicate_publish',
        )


def _current_entries(semester):
    """取发布时刻的活课表条目（带外键名称，供快照冗余存储）。"""
    return list(
        ScheduleEntry.objects.filter(semester=semester)
        .select_related('class_id', 'course', 'teacher', 'classroom')
        .order_by('id')
    )


def _entry_values_for_check(entries):
    return [
        {
            'id': e.id,
            'teacher_id': e.teacher_id,
            'classroom_id': e.classroom_id,
            'class_id': e.class_id_id,
            'day_of_week': e.day_of_week,
            'period': e.period,
        }
        for e in entries
    ]


def compute_content_hash(entries):
    """对课表条目集合计算稳定指纹，与条目顺序无关。"""
    payload = sorted(
        (
            e.class_id_id,
            e.course_id,
            e.teacher_id,
            e.classroom_id,
            e.day_of_week,
            e.period,
            1 if e.is_locked else 0,
        )
        for e in entries
    )
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


@transaction.atomic
def publish_schedule(semester_id, comment='', published_by=''):
    """发布指定学期的当前课表。

    成功返回新建的 ScheduleVersion；失败抛出 PublicationError 子类，
    事务回滚，已有发布版本与快照保持不变。
    """
    # 锁定学期行：同一学期的并发发布在此串行，保证只有一个成功结果。
    try:
        semester = Semester.objects.select_for_update().get(pk=semester_id)
    except Semester.DoesNotExist:
        raise PublicationError('学期不存在', code='semester_not_found')

    entries = _current_entries(semester)
    if not entries:
        raise EmptyScheduleError()

    # 按当前学期数据重新核对教师、班级、教室三类冲突。
    detector = ConflictDetector()
    conflicts = detector.detect_conflicts(_entry_values_for_check(entries))
    if conflicts:
        raise ConflictRejectedError(conflicts)

    content_hash = compute_content_hash(entries)

    latest = (
        ScheduleVersion.objects.select_for_update()
        .filter(semester=semester)
        .order_by('-version_number')
        .first()
    )

    # 重复发布：内容与最新版本一致时拒绝，不产生新版本也不留半成品。
    if latest and latest.content_hash == content_hash:
        raise DuplicatePublishError(latest.version_number)

    next_number = (latest.version_number + 1) if latest else 1

    version = ScheduleVersion.objects.create(
        semester=semester,
        version_number=next_number,
        status='published',
        content_hash=content_hash,
        entry_count=len(entries),
        comment=comment or '',
        published_by=published_by or '',
    )

    ScheduleSnapshotEntry.objects.bulk_create([
        ScheduleSnapshotEntry(
            version=version,
            semester=semester,
            source_entry_id=e.id,
            class_id=e.class_id_id,
            class_name=str(e.class_id) if e.class_id_id else '',
            course_id=e.course_id,
            course_name=e.course.name if e.course_id else '',
            teacher_id=e.teacher_id,
            teacher_name=e.teacher.name if e.teacher_id else '',
            classroom_id=e.classroom_id,
            classroom_name=e.classroom.name if e.classroom_id else '',
            day_of_week=e.day_of_week,
            period=e.period,
            is_locked=e.is_locked,
        )
        for e in entries
    ])

    return version
