from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ScheduleVersionViewSet

router = DefaultRouter()
router.register(r'schedule-versions', ScheduleVersionViewSet, basename='scheduleversion')

urlpatterns = [
    path('', include(router.urls)),
]
