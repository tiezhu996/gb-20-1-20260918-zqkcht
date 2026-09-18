from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from core.models import Classroom, Teacher, Class, Course, Semester
from scheduling.models import ScheduleEntry
from publication.models import ScheduleVersion, ScheduleSnapshotEntry
from publication.services import (
    publish_schedule,
    ConflictRejectedError,
    DuplicatePublishError,
    EmptyScheduleError,
)


class PublishTestMixin:
    def setUp(self):
        self.semester = Semester.objects.create(
            name='2026 春季学期',
            start_date='2026-02-16',
            end_date='2026-07-15',
            daily_periods=[{'name': '第1节', 'order': 1}, {'name': '第2节', 'order': 2}],
            weekly_days=5,
        )
        self.room = Classroom.objects.create(name='101', capacity=40, room_type='normal')
        self.teacher1 = Teacher.objects.create(name='张老师', subject='数学')
        self.teacher2 = Teacher.objects.create(name='李老师', subject='语文')
        self.class1 = Class.objects.create(grade=7, name='1班', student_count=38)
        self.class2 = Class.objects.create(grade=7, name='2班', student_count=36)
        self.course = Course.objects.create(name='数学', weekly_hours=1, priority='high')

    def make_entry(self, *, class_obj=None, teacher=None, room=None, day=1, period=1):
        return ScheduleEntry.objects.create(
            semester=self.semester,
            class_id=class_obj or self.class1,
            course=self.course,
            teacher=teacher or self.teacher1,
            classroom=room or self.room,
            day_of_week=day,
            period=period,
        )

    def make_clean_schedule(self):
        """构造一份无冲突课表：同一节次内 教师/班级/教室 两两不重叠。"""
        self.make_entry(class_obj=self.class1, teacher=self.teacher1, room=self.room, day=1, period=1)
        self.make_entry(class_obj=self.class2, teacher=self.teacher2,
                        room=Classroom.objects.create(name='102', capacity=40),
                        day=1, period=1)


class PublishServiceTests(PublishTestMixin, TransactionTestCase):
    def test_publish_creates_version_and_snapshot(self):
        self.make_clean_schedule()

        version = publish_schedule(self.semester.id, comment='第一次发布', published_by='jwc')

        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.status, 'published')
        self.assertEqual(version.entry_count, 2)
        self.assertEqual(version.comment, '第一次发布')
        self.assertEqual(version.published_by, 'jwc')
        self.assertEqual(ScheduleSnapshotEntry.objects.filter(version=version).count(), 2)

        snapshot = ScheduleSnapshotEntry.objects.get(version=version, class_id=self.class1.id)
        self.assertEqual(snapshot.teacher_id, self.teacher1.id)
        self.assertEqual(snapshot.teacher_name, '张老师')
        self.assertEqual(snapshot.classroom_name, '101')
        self.assertEqual(snapshot.course_name, '数学')
        self.assertEqual(snapshot.source_entry_id, ScheduleEntry.objects.first().id)

    def test_empty_schedule_rejected(self):
        with self.assertRaises(EmptyScheduleError):
            publish_schedule(self.semester.id)
        self.assertEqual(ScheduleVersion.objects.count(), 0)

    def test_teacher_conflict_rejects_and_keeps_old_version(self):
        self.make_clean_schedule()
        v1 = publish_schedule(self.semester.id)

        # 制造教师冲突：teacher1 在 周一第1节 出现两次
        self.make_entry(class_obj=self.class2, teacher=self.teacher1,
                        room=Classroom.objects.create(name='103', capacity=40),
                        day=1, period=1)

        with self.assertRaises(ConflictRejectedError) as ctx:
            publish_schedule(self.semester.id)
        conflict_types = {c['conflict_type'] for c in ctx.exception.conflicts}
        self.assertIn('teacher', conflict_types)

        # 原发布版本不变，没有新版本，没有新快照
        self.assertEqual(ScheduleVersion.objects.count(), 1)
        self.assertEqual(ScheduleVersion.objects.get().id, v1.id)
        self.assertEqual(ScheduleSnapshotEntry.objects.filter(version=v1).count(), 2)

    def test_classroom_conflict_rejects(self):
        self.make_entry(class_obj=self.class1, teacher=self.teacher1, room=self.room, day=2, period=1)
        self.make_entry(class_obj=self.class2, teacher=self.teacher2, room=self.room, day=2, period=1)

        with self.assertRaises(ConflictRejectedError) as ctx:
            publish_schedule(self.semester.id)
        self.assertIn('classroom', {c['conflict_type'] for c in ctx.exception.conflicts})

    def test_class_conflict_rejects(self):
        self.make_entry(class_obj=self.class1, teacher=self.teacher1,
                        room=self.room, day=3, period=1)
        self.make_entry(class_obj=self.class1, teacher=self.teacher2,
                        room=Classroom.objects.create(name='201', capacity=40),
                        day=3, period=1)

        with self.assertRaises(ConflictRejectedError) as ctx:
            publish_schedule(self.semester.id)
        self.assertIn('class', {c['conflict_type'] for c in ctx.exception.conflicts})

    def test_duplicate_publish_rejected(self):
        self.make_clean_schedule()
        v1 = publish_schedule(self.semester.id)

        with self.assertRaises(DuplicatePublishError):
            publish_schedule(self.semester.id)

        self.assertEqual(ScheduleVersion.objects.count(), 1)
        self.assertEqual(ScheduleVersion.objects.get().id, v1.id)

    def test_version_number_increments_after_change(self):
        self.make_clean_schedule()
        publish_schedule(self.semester.id)

        # 课表调整（调课）后再次发布，应产生 v2 且快照反映新内容
        entry = ScheduleEntry.objects.get(class_id=self.class1.id)
        entry.day_of_week = 2
        entry.save()

        v2 = publish_schedule(self.semester.id, comment='调课后发布')
        self.assertEqual(v2.version_number, 2)
        self.assertEqual(ScheduleVersion.objects.count(), 2)

        snapshot = ScheduleSnapshotEntry.objects.get(version=v2, class_id=self.class1.id)
        self.assertEqual(snapshot.day_of_week, 2)

    def test_old_snapshot_not_mutated_by_later_adjustments(self):
        self.make_clean_schedule()
        v1 = publish_schedule(self.semester.id)

        entry = ScheduleEntry.objects.get(class_id=self.class1.id)
        old_day = entry.day_of_week
        entry.day_of_week = 4
        entry.teacher = self.teacher2
        entry.save()
        entry.delete()  # 即使删除活课表条目

        snap = ScheduleSnapshotEntry.objects.get(version=v1, class_id=self.class1.id)
        self.assertEqual(snap.day_of_week, old_day)
        self.assertEqual(snap.teacher_id, self.teacher1.id)
        self.assertEqual(snap.teacher_name, '张老师')


class PublishApiTests(PublishTestMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_api_publish_success(self):
        self.make_clean_schedule()
        resp = self.client.post('/api/schedule-versions/publish/',
                                {'semester_id': self.semester.id, 'comment': 'API 发布'},
                                format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data['version_number'], 1)
        self.assertEqual(resp.data['entry_count'], 2)

    def test_api_publish_conflict_returns_409(self):
        self.make_entry(class_obj=self.class1, teacher=self.teacher1, room=self.room)
        self.make_entry(class_obj=self.class2, teacher=self.teacher1,
                        room=Classroom.objects.create(name='301', capacity=40))

        resp = self.client.post('/api/schedule-versions/publish/',
                                {'semester_id': self.semester.id}, format='json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data['code'], 'conflict_detected')
        self.assertIn('conflicts', resp.data)

    def test_api_duplicate_returns_409(self):
        self.make_clean_schedule()
        self.client.post('/api/schedule-versions/publish/',
                         {'semester_id': self.semester.id}, format='json')
        resp = self.client.post('/api/schedule-versions/publish/',
                                {'semester_id': self.semester.id}, format='json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data['code'], 'duplicate_publish')

    def test_api_readback_list_latest_and_entries(self):
        self.make_clean_schedule()
        self.client.post('/api/schedule-versions/publish/',
                         {'semester_id': self.semester.id}, format='json')

        # 版本列表
        resp = self.client.get(
            f'/api/schedule-versions/by_semester/?semester_id={self.semester.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)

        version_id = resp.data[0]['id']

        # 单版本快照回读
        resp = self.client.get(f'/api/schedule-versions/{version_id}/entries/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 2)

        # 最新版本（含条目）
        resp = self.client.get(
            f'/api/schedule-versions/latest/?semester_id={self.semester.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['version_number'], 1)
        self.assertEqual(len(resp.data['entries']), 2)

    def test_api_latest_404_when_never_published(self):
        resp = self.client.get(
            f'/api/schedule-versions/latest/?semester_id={self.semester.id}')
        self.assertEqual(resp.status_code, 404)

    def test_api_publish_unknown_semester(self):
        resp = self.client.post('/api/schedule-versions/publish/',
                                {'semester_id': 99999}, format='json')
        self.assertEqual(resp.status_code, 404)


class ConcurrentPublishTests(TransactionTestCase):
    """并发发布互斥测试（仅 PostgreSQL：用独立连接模拟两个教务员同时发布）。"""

    def test_only_one_version_from_concurrent_publish(self):
        if connection.vendor != 'postgresql':
            self.skipTest('并发行锁互斥仅在 PostgreSQL 上验证')

        semester = Semester.objects.create(
            name='并发学期', start_date='2026-02-16', end_date='2026-07-15',
            daily_periods=[{'name': '第1节', 'order': 1}], weekly_days=5)
        room = Classroom.objects.create(name='C1', capacity=40)
        teacher = Teacher.objects.create(name='王老师', subject='物理')
        cls = Class.objects.create(grade=8, name='3班', student_count=30)
        course = Course.objects.create(name='物理', weekly_hours=1)
        ScheduleEntry.objects.create(
            semester=semester, class_id=cls, course=course, teacher=teacher,
            classroom=room, day_of_week=1, period=1)

        import threading
        results = []

        def publish_in_own_connection():
            try:
                publish_schedule(semester.id)
                results.append('published')
            except DuplicatePublishError:
                results.append('duplicate')
            except Exception as exc:
                results.append(f'error:{exc!r}')
            finally:
                close_old_connections()

        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            publish_in_own_connection()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sorted(results), ['duplicate', 'published'])
        versions = ScheduleVersion.objects.filter(semester=semester)
        self.assertEqual(versions.count(), 1)
        self.assertEqual(versions.first().version_number, 1)
        self.assertEqual(
            ScheduleSnapshotEntry.objects.filter(version__semester=semester).count(), 1
        )
