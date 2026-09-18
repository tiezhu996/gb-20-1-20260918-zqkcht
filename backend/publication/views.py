from rest_framework import mixins, viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import serializers as drf_serializers

from core.models import Semester
from .models import ScheduleVersion
from .serializers import ScheduleVersionSerializer, ScheduleSnapshotEntrySerializer
from .services import (
    publish_schedule,
    PublicationError,
    EmptyScheduleError,
    ConflictRejectedError,
    DuplicatePublishError,
)


ERROR_STATUS_CODES = {
    'semester_not_found': status.HTTP_404_NOT_FOUND,
    'empty_schedule': status.HTTP_400_BAD_REQUEST,
    'conflict_detected': status.HTTP_409_CONFLICT,
    'duplicate_publish': status.HTTP_409_CONFLICT,
}


class PublishRequestSerializer(drf_serializers.Serializer):
    semester_id = drf_serializers.IntegerField()
    comment = drf_serializers.CharField(required=False, allow_blank=True)


class ScheduleVersionViewSet(mixins.ListModelMixin,
                             mixins.RetrieveModelMixin,
                             viewsets.GenericViewSet):
    """课表发布版本：发布与版本回读入口。"""

    queryset = ScheduleVersion.objects.all().select_related('semester')
    serializer_class = ScheduleVersionSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = super().get_queryset()
        semester_id = self.request.query_params.get('semester_id')
        if semester_id:
            queryset = queryset.filter(semester_id=semester_id)
        return queryset

    @action(detail=False, methods=['post'])
    def publish(self, request):
        """发布当前课表为新版本。

        - 有教师/班级/教室任一冲突：返回 409，原发布版本不变
        - 内容与最新版本一致（重复发布）：返回 409，不产生新版本
        - 全部通过：保存课表快照，生成新版本
        """
        req = PublishRequestSerializer(data=request.data)
        if not req.is_valid():
            return Response(req.errors, status=status.HTTP_400_BAD_REQUEST)

        semester_id = req.validated_data['semester_id']
        comment = req.validated_data.get('comment', '')
        published_by = request.user.username if not request.user.is_anonymous else ''

        try:
            version = publish_schedule(
                semester_id, comment=comment, published_by=published_by
            )
        except PublicationError as exc:
            payload = {'error': exc.message, 'code': exc.code}
            if isinstance(exc, ConflictRejectedError):
                payload['conflicts'] = exc.conflicts
            return Response(
                payload,
                status=ERROR_STATUS_CODES.get(exc.code, status.HTTP_400_BAD_REQUEST),
            )

        return Response(
            ScheduleVersionSerializer(version).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'])
    def entries(self, request, pk=None):
        """回读指定版本的课表快照条目。"""
        version = self.get_object()
        snapshots = version.entries.all()
        return Response(ScheduleSnapshotEntrySerializer(snapshots, many=True).data)

    @action(detail=False, methods=['get'])
    def latest(self, request):
        """回读某学期最新发布版本（必须传 semester_id），含全部快照条目。"""
        semester_id = request.query_params.get('semester_id')
        if not semester_id:
            return Response(
                {'error': 'semester_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        version = (
            ScheduleVersion.objects.filter(semester_id=semester_id)
            .order_by('-version_number')
            .first()
        )
        if not version:
            return Response(
                {'error': '该学期尚无已发布版本', 'code': 'no_published_version'},
                status=status.HTTP_404_NOT_FOUND,
            )

        data = ScheduleVersionSerializer(version).data
        data['entries'] = ScheduleSnapshotEntrySerializer(
            version.entries.all(), many=True
        ).data
        return Response(data)

    @action(detail=False, methods=['get'])
    def by_semester(self, request):
        """按学期列出全部发布版本（版本回读入口）。"""
        semester_id = request.query_params.get('semester_id')
        if not semester_id:
            return Response(
                {'error': 'semester_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not Semester.objects.filter(pk=semester_id).exists():
            return Response(
                {'error': '学期不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        versions = self.get_queryset().filter(semester_id=semester_id)
        return Response(ScheduleVersionSerializer(versions, many=True).data)
