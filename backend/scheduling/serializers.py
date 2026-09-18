from rest_framework import serializers
from .models import (
    ClassCourse, ScheduleEntry, Conflict, SwapRequest, Substitute,
    ScheduleVersion
)


class ClassCourseSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    teacher_name = serializers.CharField(source='teacher.name', read_only=True)
    class_name = serializers.CharField(source='class_id.name', read_only=True)
    weekly_hours = serializers.IntegerField(source='course.weekly_hours', read_only=True)

    class Meta:
        model = ClassCourse
        fields = '__all__'


class ScheduleEntrySerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    teacher_name = serializers.CharField(source='teacher.name', read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True)
    class_name = serializers.CharField(source='class_id.name', read_only=True)

    class Meta:
        model = ScheduleEntry
        fields = '__all__'


class ScheduleEntryDetailSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    teacher_name = serializers.CharField(source='teacher.name', read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True)
    class_name = serializers.CharField(source='class_id.name', read_only=True)
    original_teacher_name = serializers.CharField(
        source='original_teacher.name', read_only=True, allow_null=True
    )

    class Meta:
        model = ScheduleEntry
        fields = '__all__'


class ConflictSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conflict
        fields = '__all__'


class SwapRequestSerializer(serializers.ModelSerializer):
    requesting_teacher_name = serializers.CharField(
        source='requesting_teacher.name', read_only=True
    )
    target_teacher_name = serializers.CharField(
        source='target_teacher.name', read_only=True
    )

    class Meta:
        model = SwapRequest
        fields = '__all__'


class SubstituteSerializer(serializers.ModelSerializer):
    original_teacher_name = serializers.CharField(
        source='original_teacher.name', read_only=True
    )
    substitute_teacher_name = serializers.CharField(
        source='substitute_teacher.name', read_only=True
    )

    class Meta:
        model = Substitute
        fields = '__all__'


class AutoScheduleRequestSerializer(serializers.Serializer):
    semester_id = serializers.IntegerField()
    respect_locked = serializers.BooleanField(default=True)


class ConflictCheckSerializer(serializers.Serializer):
    semester_id = serializers.IntegerField()


class SwapScheduleRequestSerializer(serializers.Serializer):
    entry1_id = serializers.IntegerField()
    entry2_id = serializers.IntegerField()
    reason = serializers.CharField(required=False)


class SubstituteRequestSerializer(serializers.Serializer):
    entry_id = serializers.IntegerField()
    substitute_teacher_id = serializers.IntegerField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    reason = serializers.CharField()


class PublishScheduleRequestSerializer(serializers.Serializer):
    semester_id = serializers.IntegerField()
    note = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )


class ScheduleVersionListSerializer(serializers.ModelSerializer):
    semester_name = serializers.CharField(source='semester.name', read_only=True)
    is_latest = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleVersion
        fields = [
            'id', 'semester', 'semester_name', 'version_number',
            'entry_count', 'published_by', 'note', 'created_at',
            'is_latest',
        ]

    def get_is_latest(self, obj):
        # ordering 为版本号倒序，列表首项即最新版本
        versions = self.context.get('latest_version_ids')
        if versions is not None:
            return obj.id in versions
        latest = (
            ScheduleVersion.objects.filter(semester_id=obj.semester_id)
            .values_list('id', flat=True).first()
        )
        return obj.id == latest


class ScheduleVersionDetailSerializer(ScheduleVersionListSerializer):
    class Meta(ScheduleVersionListSerializer.Meta):
        fields = ScheduleVersionListSerializer.Meta.fields + ['snapshot', 'content_hash']
