from django.db import models
from core.models import Semester


class ScheduleVersion(models.Model):
    """课表发布版本。

    每次发布成功后生成一条新版本记录，版本号在同一学期内递增。
    版本一经创建即为只读快照，后续课表调整不会改写本版本的数据。
    """

    STATUS_CHOICES = [
        ('published', '已发布'),
    ]

    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name='schedule_versions'
    )
    version_number = models.PositiveIntegerField(help_text='学期内递增的版本号，从 1 开始')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='published')
    content_hash = models.CharField(
        max_length=64, help_text='发布时刻课表内容的指纹，用于识别重复发布'
    )
    entry_count = models.PositiveIntegerField(default=0, help_text='快照条目数量')
    comment = models.CharField(max_length=255, blank=True, help_text='发布备注')
    published_by = models.CharField(max_length=150, blank=True, help_text='发布操作人')
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version_number']
        constraints = [
            models.UniqueConstraint(
                fields=['semester', 'version_number'],
                name='unique_version_number_per_semester',
            ),
        ]

    def __str__(self):
        return f'{self.semester.name} - v{self.version_number}'


class ScheduleSnapshotEntry(models.Model):
    """发布版本中的课表条目快照。

    以扁平字段保存发布时刻的数据（包括名称冗余），不依赖活的课表条目，
    因此后续自动排课、调课、代课等调整均不会影响历史快照。
    """

    version = models.ForeignKey(
        ScheduleVersion, on_delete=models.CASCADE, related_name='entries'
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name='snapshot_entries'
    )
    source_entry_id = models.PositiveIntegerField(
        null=True, blank=True, help_text='来源 ScheduleEntry 的 id（仅作追溯，不做外键约束）'
    )
    class_id = models.PositiveIntegerField()
    class_name = models.CharField(max_length=50, blank=True)
    course_id = models.PositiveIntegerField()
    course_name = models.CharField(max_length=100, blank=True)
    teacher_id = models.PositiveIntegerField()
    teacher_name = models.CharField(max_length=100, blank=True)
    classroom_id = models.PositiveIntegerField()
    classroom_name = models.CharField(max_length=100, blank=True)
    day_of_week = models.IntegerField(help_text='1-5 代表周一到周五')
    period = models.IntegerField(help_text='第几节课')
    is_locked = models.BooleanField(default=False)

    class Meta:
        ordering = ['day_of_week', 'period', 'class_id']
        indexes = [
            models.Index(fields=['version', 'day_of_week', 'period']),
            models.Index(fields=['semester', 'class_id']),
            models.Index(fields=['semester', 'teacher_id']),
            models.Index(fields=['semester', 'classroom_id']),
        ]

    def __str__(self):
        return (f'v{self.version.version_number}: {self.class_name} - {self.course_name} @ '
                f'周{self.day_of_week}第{self.period}节')
