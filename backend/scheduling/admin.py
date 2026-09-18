from django.contrib import admin
from .models import (
    ClassCourse, ScheduleEntry, Conflict, SwapRequest, Substitute,
    ScheduleVersion, SchedulePublishLock
)


@admin.register(ScheduleVersion)
class ScheduleVersionAdmin(admin.ModelAdmin):
    """已发布快照只读：不允许通过后台改写历史版本。"""
    list_display = (
        'semester', 'version_number', 'entry_count',
        'published_by', 'created_at'
    )
    list_filter = ('semester',)
    readonly_fields = (
        'semester', 'version_number', 'snapshot', 'entry_count',
        'content_hash', 'published_by', 'note', 'created_at'
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SchedulePublishLock)
class SchedulePublishLockAdmin(admin.ModelAdmin):
    list_display = ('semester', 'locked_at')
    readonly_fields = ('semester', 'locked_at')

    def has_add_permission(self, request):
        return False


admin.site.register(ClassCourse)
admin.site.register(ScheduleEntry)
admin.site.register(Conflict)
admin.site.register(SwapRequest)
admin.site.register(Substitute)
