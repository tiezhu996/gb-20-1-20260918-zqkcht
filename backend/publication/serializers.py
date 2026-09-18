from rest_framework import serializers
from .models import ScheduleVersion, ScheduleSnapshotEntry


class ScheduleSnapshotEntrySerializer(serializers.ModelSerializer):
    """快照条目，字段命名与活课表条目保持一致，前端可复用课表网格渲染。"""

    course = serializers.IntegerField(source='course_id', read_only=True)
    teacher = serializers.IntegerField(source='teacher_id', read_only=True)
    classroom = serializers.IntegerField(source='classroom_id', read_only=True)

    class Meta:
        model = ScheduleSnapshotEntry
        fields = [
            'id',
            'version',
            'semester',
            'source_entry_id',
            'class_id',
            'class_name',
            'course',
            'course_name',
            'teacher',
            'teacher_name',
            'classroom',
            'classroom_name',
            'day_of_week',
            'period',
            'is_locked',
        ]


class ScheduleVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleVersion
        fields = [
            'id',
            'semester',
            'version_number',
            'status',
            'entry_count',
            'content_hash',
            'comment',
            'published_by',
            'published_at',
        ]
        read_only_fields = fields
