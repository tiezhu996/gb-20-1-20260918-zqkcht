import threading
import time
from datetime import date
from unittest.mock import patch

from django.db import (
    transaction, OperationalError, IntegrityError,
)
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from rest_framework.test import APITestCase

from core.models import Class, Classroom, Course, Semester, Teacher
from .models import (
    ScheduleEntry, ScheduleVersion, SchedulePublishLock,
    ImmutableVersionError,
)
from .services import (
    publish_schedule, PublishConflictError, PublishInProgressError,
    _acquire_publish_lock,
)


def make_semester(name='2026 春季学期'):
    return Semester.objects.create(
        name=name,
        start_date=date(2026, 2, 16),
        end_date=date(2026, 7, 15),
        is_active=True,
        daily_periods=[{'name': f'第{i}节', 'order': i} for i in range(1, 8)],
        weekly_days=5,
    )


def make_base_data():
    semester = make_semester()
    teacher1 = Teacher.objects.create(name='张老师', subject='数学')
    teacher2 = Teacher.objects.create(name='李老师', subject='语文')
    classroom1 = Classroom.objects.create(name='101', capacity=40)
    classroom2 = Classroom.objects.create(name='102', capacity=40)
    klass1 = Class.objects.create(grade=10, name='高一1班', student_count=40)
    klass2 = Class.objects.create(grade=10, name='高一2班', student_count=40)
    course1 = Course.objects.create(name='数学', weekly_hours=1)
    course2 = Course.objects.create(name='语文', weekly_hours=1)
    return semester, teacher1, teacher2, classroom1, classroom2, klass1, klass2, course1, course2


def add_entry(semester, klass, course, teacher, classroom, day, period):
    return ScheduleEntry.objects.create(
        semester=semester, class_id=klass, course=course,
        teacher=teacher, classroom=classroom,
        day_of_week=day, period=period,
    )


class PublishServiceTests(TransactionTestCase):

    def test_first_publish_creates_version_one_with_snapshot(self):
        semester, t1, t2, r1, r2, c1, c2, course1, course2 = make_base_data()
        add_entry(semester, c1, course1, t1, r1, 1, 1)
        add_entry(semester, c2, course2, t2, r2, 1, 1)

        version, created = publish_schedule(semester.id, published_by='教务员甲')

        self.assertTrue(created)
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.entry_count, 2)
        self.assertEqual(version.published_by, '教务员甲')
        self.assertEqual(len(version.snapshot), 2)
        snap = version.snapshot[0]
        self.assertIn('course_name', snap)
        self.assertIn('teacher_name', snap)
        self.assertIn('classroom_name', snap)

    def test_conflict_blocks_publish_and_keeps_old_version(self):
        semester, t1, t2, r1, r2, c1, c2, course1, course2 = make_base_data()
        add_entry(semester, c1, course1, t1, r1, 1, 1)
        version1, _ = publish_schedule(semester.id)
        hash1 = version1.content_hash

        # 制造教师冲突：同一教师同一时间两门课
        add_entry(semester, c2, course2, t1, r2, 1, 1)

        with self.assertRaises(PublishConflictError) as ctx:
            publish_schedule(semester.id)
        self.assertTrue(
            any(c['conflict_type'] == 'teacher' for c in ctx.exception.conflicts)
        )

        # 原发布版本不变
        self.assertEqual(ScheduleVersion.objects.count(), 1)
        version1.refresh_from_db()
        self.assertEqual(version1.version_number, 1)
        self.assertEqual(version1.content_hash, hash1)
        # 没有遗留的半成品锁以外数据
        self.assertEqual(ScheduleVersion.objects.filter(semester=semester).count(), 1)

    def test_classroom_and_class_conflicts_also_block(self):
        semester, t1, t2, r1, r2, c1, c2, course1, course2 = make_base_data()
        # 教室冲突
        add_entry(semester, c1, course1, t1, r1, 2, 2)
        add_entry(semester, c2, course2, t2, r1, 2, 2)
        with self.assertRaises(PublishConflictError) as ctx:
            publish_schedule(semester.id)
        self.assertTrue(
            any(c['conflict_type'] == 'classroom' for c in ctx.exception.conflicts)
        )
        ScheduleEntry.objects.all().delete()
        # 班级冲突
        add_entry(semester, c1, course1, t1, r1, 3, 3)
        add_entry(semester, c1, course2, t2, r2, 3, 3)
        with self.assertRaises(PublishConflictError) as ctx:
            publish_schedule(semester.id)
        self.assertTrue(
            any(c['conflict_type'] == 'class' for c in ctx.exception.conflicts)
        )
        self.assertEqual(ScheduleVersion.objects.count(), 0)

    def test_empty_schedule_rejected(self):
        semester = make_semester()
        from .services import PublishError
        with self.assertRaises(PublishError):
            publish_schedule(semester.id)
        self.assertEqual(ScheduleVersion.objects.count(), 0)

    def test_version_number_increments_on_change(self):
        semester, t1, t2, r1, r2, c1, c2, course1, course2 = make_base_data()
        add_entry(semester, c1, course1, t1, r1, 1, 1)
        v1, created1 = publish_schedule(semester.id)
        self.assertTrue(created1)

        # 课表调整
        entry = ScheduleEntry.objects.get()
        entry.period = 2
        entry.save()

        v2, created2 = publish_schedule(semester.id)
        self.assertTrue(created2)
        self.assertEqual(v2.version_number, 2)
        self.assertNotEqual(v1.content_hash, v2.content_hash)

        versions = list(
            ScheduleVersion.objects.filter(semester=semester)
            .values_list('version_number', flat=True)
        )
        self.assertEqual(sorted(versions), [1, 2])

    def test_duplicate_publish_is_idempotent(self):
        semester, t1, t2, r1, r2, c1, c2, course1, course2 = make_base_data()
        add_entry(semester, c1, course1, t1, r1, 1, 1)
        v1, created1 = publish_schedule(semester.id, note='首版')
        v2, created2 = publish_schedule(semester.id)

        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(v1.id, v2.id)
        self.assertEqual(ScheduleVersion.objects.count(), 1)

    def test_old_snapshot_immutable_after_adjustment(self):
        semester, t1, t2, r1, r2, c1, c2, course1, course2 = make_base_data()
        entry = add_entry(semester, c1, course1, t1, r1, 1, 1)
        v1, _ = publish_schedule(semester.id)

        # 之后课表调整（删条目、改条目）不得影响旧快照
        entry.period = 5
        entry.save()
        add_entry(semester, c2, course2, t2, r2, 2, 2)
        v2, _ = publish_schedule(semester.id)

        v1_snapshot = ScheduleVersion.objects.get(id=v1.id).snapshot
        self.assertEqual(v1_snapshot[0]['period'], 1)
        self.assertEqual(len(v1_snapshot), 1)
        self.assertEqual(len(v2.snapshot), 2)

        # 快照行禁止改写和删除
        with self.assertRaises(ImmutableVersionError):
            v1.note = '篡改'
            v1.save()
        with self.assertRaises(ImmutableVersionError):
            v1.delete()
        with self.assertRaises(ImmutableVersionError):
            ScheduleVersion.objects.filter(id=v1.id).update(note='x')
        with self.assertRaises(ImmutableVersionError):
            ScheduleVersion.objects.all().delete()
        # 记录仍在
        self.assertEqual(ScheduleVersion.objects.filter(id=v1.id).count(), 1)

    def test_latest_version_readback_ordering(self):
        semester, t1, t2, r1, r2, c1, c2, course1, course2 = make_base_data()
        add_entry(semester, c1, course1, t1, r1, 1, 1)
        publish_schedule(semester.id)
        ScheduleEntry.objects.update(period=3)
        publish_schedule(semester.id)
        latest = ScheduleVersion.objects.filter(semester=semester).first()
        self.assertEqual(latest.version_number, 2)


class PublishApiTests(APITestCase):

    def setUp(self):
        (self.semester, self.t1, self.t2, self.r1, self.r2,
         self.c1, self.c2, self.course1, self.course2) = make_base_data()

    def test_publish_endpoint_success(self):
        add_entry(self.semester, self.c1, self.course1, self.t1, self.r1, 1, 1)
        url = reverse('scheduleversion-publish')
        resp = self.client.post(url, {'semester_id': self.semester.id, 'note': '发布'}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['status'], 'created')
        self.assertEqual(resp.data['version']['version_number'], 1)
        self.assertEqual(resp.data['version']['entry_count'], 1)

    def test_publish_endpoint_conflict_returns_409(self):
        add_entry(self.semester, self.c1, self.course1, self.t1, self.r1, 1, 1)
        add_entry(self.semester, self.c2, self.course2, self.t1, self.r2, 1, 1)
        url = reverse('scheduleversion-publish')
        resp = self.client.post(url, {'semester_id': self.semester.id}, format='json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data['error'], 'conflicts_present')
        self.assertTrue(resp.data['conflicts'])

    def test_publish_endpoint_duplicate_unchanged(self):
        add_entry(self.semester, self.c1, self.course1, self.t1, self.r1, 1, 1)
        url = reverse('scheduleversion-publish')
        self.client.post(url, {'semester_id': self.semester.id}, format='json')
        resp = self.client.post(url, {'semester_id': self.semester.id}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'unchanged')

    def test_version_list_and_filter(self):
        add_entry(self.semester, self.c1, self.course1, self.t1, self.r1, 1, 1)
        self.client.post(
            reverse('scheduleversion-publish'),
            {'semester_id': self.semester.id}, format='json'
        )
        url = reverse('scheduleversion-list')
        resp = self.client.get(url, {'semester_id': self.semester.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        row = resp.data[0]
        self.assertNotIn('snapshot', row)
        self.assertTrue(row['is_latest'])
        self.assertEqual(row['semester_name'], self.semester.name)

    def test_version_detail_returns_snapshot(self):
        add_entry(self.semester, self.c1, self.course1, self.t1, self.r1, 1, 1)
        self.client.post(
            reverse('scheduleversion-publish'),
            {'semester_id': self.semester.id}, format='json'
        )
        version = ScheduleVersion.objects.get()
        resp = self.client.get(reverse('scheduleversion-detail', args=[version.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('snapshot', resp.data)
        self.assertEqual(len(resp.data['snapshot']), 1)

    def test_latest_endpoint_readback(self):
        add_entry(self.semester, self.c1, self.course1, self.t1, self.r1, 1, 1)
        url = reverse('scheduleversion-latest')

        resp = self.client.get(url, {'semester_id': self.semester.id})
        self.assertEqual(resp.status_code, 404)

        self.client.post(
            reverse('scheduleversion-publish'),
            {'semester_id': self.semester.id}, format='json'
        )
        ScheduleEntry.objects.update(period=4)
        self.client.post(
            reverse('scheduleversion-publish'),
            {'semester_id': self.semester.id}, format='json'
        )
        resp = self.client.get(url, {'semester_id': self.semester.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['version_number'], 2)
        self.assertEqual(resp.data['snapshot'][0]['period'], 4)

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 400)

    def test_versions_are_read_only(self):
        add_entry(self.semester, self.c1, self.course1, self.t1, self.r1, 1, 1)
        self.client.post(
            reverse('scheduleversion-publish'),
            {'semester_id': self.semester.id}, format='json'
        )
        version = ScheduleVersion.objects.get()
        self.assertEqual(
            self.client.put(
                reverse('scheduleversion-detail', args=[version.id]),
                {'note': 'x'}, format='json'
            ).status_code, 405
        )
        self.assertEqual(
            self.client.patch(
                reverse('scheduleversion-detail', args=[version.id]),
                {'note': 'x'}, format='json'
            ).status_code, 405
        )
        self.assertEqual(
            self.client.delete(
                reverse('scheduleversion-detail', args=[version.id])
            ).status_code, 405
        )


class LockAcquisitionTests(TransactionTestCase):
    """不依赖具体数据库行锁能力的互斥锁分支测试（用 mock 模拟 PG 行为）。"""

    def setUp(self):
        self.semester = make_semester()

    def test_lock_row_held_by_other_transaction_is_rejected(self):
        # 模拟 PostgreSQL FOR UPDATE NOWAIT 拿不到锁时抛出的锁错误
        with transaction.atomic():
            SchedulePublishLock.objects.create(semester=self.semester)
            qs = SchedulePublishLock.objects.all()
            with patch.object(qs, 'get', side_effect=OperationalError('could not obtain lock')):
                with patch.object(SchedulePublishLock.objects, 'select_for_update', return_value=qs):
                    with self.assertRaises(PublishInProgressError):
                        _acquire_publish_lock(self.semester)

    def test_first_publish_creation_race_is_rejected(self):
        # 模拟两个首次发布并发创建锁行时的唯一约束冲突
        with patch.object(
            SchedulePublishLock.objects, 'create',
            side_effect=IntegrityError('duplicate key')
        ):
            with self.assertRaises(PublishInProgressError):
                _acquire_publish_lock(self.semester)

    def test_publish_failure_releases_lock_for_retry(self):
        # 发布因冲突回滚后，锁行随之回滚，后续可重新发布
        semester, t1, t2, r1, r2, c1, c2, course1, course2 = make_base_data()
        add_entry(semester, c1, course1, t1, r1, 1, 1)
        add_entry(semester, c2, course2, t1, r2, 1, 1)
        with self.assertRaises(PublishConflictError):
            publish_schedule(semester.id)
        # 模拟冲突发布失败后的状态（SQLite 无真实行锁，锁行也不会残留）
        ScheduleEntry.objects.filter(class_id=c2).update(teacher=t2)
        version, created = publish_schedule(semester.id)
        self.assertTrue(created)
        self.assertEqual(version.version_number, 1)


@skipUnlessDBFeature('has_select_for_update_nowait')
class ConcurrentPublishTests(TransactionTestCase):
    """并发发布：多人同时发布只能有一个成功。

    依赖行级锁 NOWAIT 能力（PostgreSQL）；SQLite 不支持行锁，自动跳过。
    """

    def setUp(self):
        (self.semester, self.t1, self.t2, self.r1, self.r2,
         self.c1, self.c2, self.course1, self.course2) = make_base_data()
        add_entry(self.semester, self.c1, self.course1, self.t1, self.r1, 1, 1)
        add_entry(self.semester, self.c2, self.course2, self.t2, self.r2, 1, 1)

    def _hold_lock_then_publish(self, barrier, results, delay=0.5):
        """在独立事务中先占住发布锁，主线程再尝试发布。"""
        try:
            with transaction.atomic():
                SchedulePublishLock.objects.create(semester=self.semester)
                barrier.wait(timeout=10)
                time.sleep(delay)
                version, created = publish_schedule(self.semester.id)
                results['holder'] = (version.version_number, created)
        except Exception as exc:  # noqa: BLE001 - 测试中记录任意异常
            results['holder_error'] = repr(exc)

    def test_concurrent_publish_only_one_succeeds(self):
        barrier = threading.Event()
        results = {}
        holder = threading.Thread(
            target=self._hold_lock_then_publish, args=(barrier, results)
        )
        holder.start()
        # 等待锁被占住
        time.sleep(0.3)
        barrier.set()

        # 主线程并发发布，应立即收到“发布进行中”
        with self.assertRaises(PublishInProgressError):
            publish_schedule(self.semester.id)

        holder.join(timeout=10)
        self.assertNotIn('holder_error', results)
        self.assertEqual(results['holder'], (1, True))
        # 只有一个版本，无半成品
        self.assertEqual(
            ScheduleVersion.objects.filter(semester=self.semester).count(), 1
        )
        self.assertEqual(SchedulePublishLock.objects.count(), 1)
