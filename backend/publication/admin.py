from django.contrib import admin

from .models import ScheduleVersion, ScheduleSnapshotEntry


class ScheduleSnapshotEntryInline(admin.TabularInline):
    model = ScheduleSnapshotEntry
    extra = 0
    can_delete = False
    readonly_fields = [
        'version', 'semester', 'source_entry_id',
        'class_id', 'class_name', 'course_id', 'course_name',
        'teacher_id', 'teacher_name', 'classroom_id', 'classroom_name',
        'day_of_week', 'period', 'is_locked',
    ]
    max_num = 0


@admin.register(ScheduleVersion)
class ScheduleVersionAdmin(admin.ModelAdmin):
    list_display = ('semester', 'version_number', 'status', 'entry_count',
                    'published_by', 'published_at', 'comment')
    list_filter = ('semester', 'status')
    search_fields = ('comment', 'published_by')
    readonly_fields = ('semester', 'version_number', 'status', 'content_hash',
                       'entry_count', 'comment', 'published_by', 'published_at')
    inlines = [ScheduleSnapshotEntryInline]

    def has_add_permission(self, request):
        # 版本只能通过发布接口产生，不允许在 Admin 中手工创建
        return False

    def has_delete_permission(self, request, obj=None):
        # 发布快照只读，避免从后台改写历史版本
        return False
