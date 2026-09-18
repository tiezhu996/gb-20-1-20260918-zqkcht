"""课表发布服务。

发布流程（整体在一个数据库事务中）：
1. 获取学期级互斥锁，同一时刻只允许一个发布操作；
2. 按当前学期重新核对教师、班级、教室三类冲突；
3. 任一冲突（或课表为空）即拒绝发布，已有发布版本保持不变；
4. 全部通过后保存课表快照并生成新版本，快照内容与上次完全相同时不产生新版本；
5. 提交事务并释放锁，此后的课表调整不会影响任何已保存的快照。
"""
import hashlib
import json

from django.db import (
    IntegrityError,
    NotSupportedError,
    OperationalError,
    transaction,
)
from django.db.models import Max

from core.models import Semester
from .csp_solver import ConflictDetector
from .models import ScheduleEntry, SchedulePublishLock, ScheduleVersion


class PublishError(Exception):
    """发布被拒绝（参数或数据问题）。"""


class PublishConflictError(PublishError):
    """课表存在冲突，拒绝发布。"""

    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__('当前课表存在 %d 处冲突，无法发布' % len(conflicts))


class PublishInProgressError(PublishError):
    """已有发布操作正在进行（并发发布）。"""


# 参与快照指纹计算的字段（只取业务值，不包含自增主键与更新时间）
_FINGERPRINT_FIELDS = (
    'class_id_id', 'course_id', 'teacher_id', 'classroom_id',
    'day_of_week', 'period', 'is_locked', 'original_teacher_id',
)


def compute_content_hash(entries):
    """根据课表条目的业务内容计算稳定指纹。"""
    rows = list(entries.order_by(
        'day_of_week', 'period', 'class_id_id', 'course_id'
    ).values(*_FINGERPRINT_FIELDS))
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def build_snapshot(entries):
    """把当前课表复制成与排课表解耦的纯数据快照。"""
    return [
        {
            'entry_key': (
                e.class_id_id, e.course_id, e.teacher_id, e.classroom_id,
                e.day_of_week, e.period
            ),
            'class_id': e.class_id_id,
            'class_name': e.class_id.name,
            'course': e.course_id,
            'course_name': e.course.name,
            'teacher': e.teacher_id,
            'teacher_name': e.teacher.name,
            'classroom': e.classroom_id,
            'classroom_name': e.classroom.name,
            'day_of_week': e.day_of_week,
            'period': e.period,
            'is_locked': e.is_locked,
            'original_teacher': e.original_teacher_id,
            'original_teacher_name': (
                e.original_teacher.name if e.original_teacher else None
            ),
        }
        for e in entries
    ]


def _acquire_publish_lock(semester):
    """获取学期级发布锁；获取失败说明已有发布在进行中。

    使用 select_for_update 的行锁，锁随外层事务提交/回滚自动释放；
    首次发布会尝试创建锁记录，创建竞争同样视为“发布进行中”。
    """
    connection = transaction.get_connection()
    # PostgreSQL 支持 NOWAIT：拿不到锁立即失败而不是排队等待；
    # 其他后端（如测试用的 SQLite 不支持行锁）退化为直接查询。
    nowait = connection.vendor == 'postgresql'
    try:
        try:
            SchedulePublishLock.objects.select_for_update(
                **({'nowait': True} if nowait else {})
            ).get(semester=semester)
        except SchedulePublishLock.DoesNotExist:
            try:
                SchedulePublishLock.objects.create(semester=semester)
            except IntegrityError as exc:
                # 并发的首次发布竞争：对端已创建锁
                raise PublishInProgressError(
                    '该学期已有发布操作正在进行，请稍后重试'
                ) from exc
    except (OperationalError, NotSupportedError) as exc:
        raise PublishInProgressError(
            '该学期已有发布操作正在进行，请稍后重试'
        ) from exc


def _current_entries(semester):
    return ScheduleEntry.objects.filter(
        semester=semester
    ).select_related(
        'class_id', 'course', 'teacher', 'classroom', 'original_teacher'
    ).order_by('day_of_week', 'period', 'class_id_id')


def publish_schedule(semester_id, published_by='', note=''):
    """发布课表新版本。

    返回 (ScheduleVersion, created, conflicts)：
    - created=True  新生成并保存了一个发布版本；
    - created=False 内容与最新版本一致，未重复产生新版本；
    - conflicts 仅在抛出 PublishConflictError 时附带。
    """
    try:
        semester = Semester.objects.get(id=semester_id)
    except Semester.DoesNotExist as exc:
        raise PublishError('学期不存在') from exc

    with transaction.atomic():
        _acquire_publish_lock(semester)

        entries_qs = _current_entries(semester)

        if not entries_qs.exists():
            raise PublishError('当前学期没有可发布的课表条目')

        # 按当前学期重新核对教师、班级、教室冲突
        entry_rows = list(entries_qs.values(
            'id', 'teacher_id', 'classroom_id', 'class_id',
            'day_of_week', 'period'
        ))
        conflicts = ConflictDetector().detect_conflicts(entry_rows)
        if conflicts:
            # 事务回滚：不会留下任何半成品，原发布版本不变
            raise PublishConflictError(conflicts)

        content_hash = compute_content_hash(entries_qs)

        # 学期发布锁已保证本事务是该学期唯一在执行的发布，
        # 因此版本号的读取-计算不会与其他发布竞争。
        latest = ScheduleVersion.objects.filter(semester=semester).first()

        if latest and latest.content_hash == content_hash:
            # 内容未变化的重复发布：幂等返回最新版本，不产生新版本
            return latest, False

        next_number = (
            ScheduleVersion.objects.filter(semester=semester)
            .aggregate(max_no=Max('version_number'))['max_no'] or 0
        ) + 1

        snapshot = build_snapshot(list(entries_qs))
        version = ScheduleVersion(
            semester=semester,
            version_number=next_number,
            snapshot=snapshot,
            entry_count=len(snapshot),
            content_hash=content_hash,
            published_by=published_by or '',
            note=note or '',
        )
        version.save()
        return version, True
