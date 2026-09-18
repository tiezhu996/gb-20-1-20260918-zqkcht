from django.http import HttpResponse
from django.db.models import Max
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.db import transaction
from core.models import Semester, Classroom, Teacher, Class
from .models import (
    ClassCourse, ScheduleEntry, Conflict, SwapRequest, Substitute,
    ScheduleVersion
)
from .serializers import (
    ClassCourseSerializer, ScheduleEntrySerializer,
    ScheduleEntryDetailSerializer, ConflictSerializer,
    SwapRequestSerializer, SubstituteSerializer,
    AutoScheduleRequestSerializer, ConflictCheckSerializer,
    SwapScheduleRequestSerializer, SubstituteRequestSerializer,
    PublishScheduleRequestSerializer,
    ScheduleVersionListSerializer, ScheduleVersionDetailSerializer
)
from .csp_solver import CSPScheduler, ConflictDetector, SchedulingTask, TimeSlot
from .pdf_export import (
    generate_class_timetable_pdf,
    generate_teacher_timetable_pdf,
    generate_classroom_timetable_pdf
)
from .services import (
    publish_schedule, PublishError, PublishConflictError,
    PublishInProgressError
)


class ClassCourseViewSet(viewsets.ModelViewSet):
    queryset = ClassCourse.objects.all()
    serializer_class = ClassCourseSerializer
    permission_classes = [AllowAny]


class ScheduleEntryViewSet(viewsets.ModelViewSet):
    queryset = ScheduleEntry.objects.all().select_related(
        'course', 'teacher', 'classroom', 'class_id', 'semester'
    )
    serializer_class = ScheduleEntryDetailSerializer
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return ScheduleEntryDetailSerializer
        return ScheduleEntrySerializer

    @action(detail=False, methods=['get'])
    def by_semester(self, request):
        semester_id = request.query_params.get('semester_id')
        if not semester_id:
            return Response(
                {'error': 'semester_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        entries = self.queryset.filter(semester_id=semester_id)
        serializer = ScheduleEntryDetailSerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_class(self, request):
        semester_id = request.query_params.get('semester_id')
        class_id = request.query_params.get('class_id')
        entries = self.queryset.filter(semester_id=semester_id, class_id=class_id)
        serializer = ScheduleEntryDetailSerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_teacher(self, request):
        semester_id = request.query_params.get('semester_id')
        teacher_id = request.query_params.get('teacher_id')
        entries = self.queryset.filter(semester_id=semester_id, teacher_id=teacher_id)
        serializer = ScheduleEntryDetailSerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_classroom(self, request):
        semester_id = request.query_params.get('semester_id')
        classroom_id = request.query_params.get('classroom_id')
        entries = self.queryset.filter(semester_id=semester_id, classroom_id=classroom_id)
        serializer = ScheduleEntryDetailSerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def auto_schedule(self, request):
        req_serializer = AutoScheduleRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return Response(req_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        semester_id = req_serializer.validated_data['semester_id']
        respect_locked = req_serializer.validated_data['respect_locked']

        try:
            semester = Semester.objects.get(id=semester_id)
        except Semester.DoesNotExist:
            return Response(
                {'error': 'Semester not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        class_courses = ClassCourse.objects.filter(
            semester=semester
        ).select_related('class_id', 'course', 'teacher')

        if not class_courses.exists():
            return Response(
                {'error': 'No class courses configured for this semester'},
                status=status.HTTP_400_BAD_REQUEST
            )

        tasks = []
        for cc in class_courses:
            tasks.append(SchedulingTask(
                class_id=cc.class_id.id,
                course_id=cc.course.id,
                teacher_id=cc.teacher.id,
                weekly_hours=cc.course.weekly_hours,
                preferred_room_type=cc.course.preferred_room_type,
                priority=cc.course.priority,
                available_time_slots=[],
                classroom_capacity=cc.class_id.student_count or 40
            ))

        classrooms_data = {
            c.id: {
                'room_type': c.room_type,
                'capacity': c.capacity,
                'name': c.name
            } for c in Classroom.objects.filter(is_active=True)
        }

        teachers_data = {
            t.id: {
                'name': t.name,
                'available_time_slots': t.available_time_slots if t.available_time_slots else []
            } for t in Teacher.objects.filter(is_active=True)
        }

        locked_entries = []
        if respect_locked:
            locked = ScheduleEntry.objects.filter(
                semester=semester, is_locked=True
            ).values(
                'id', 'class_id', 'teacher_id', 'classroom_id',
                'day_of_week', 'period', 'is_locked'
            )
            locked_entries = list(locked)

        scheduler = CSPScheduler(semester)
        assignments, scheduling_conflicts = scheduler.schedule(
            tasks, classrooms_data, teachers_data, locked_entries
        )

        with transaction.atomic():
            if respect_locked:
                ScheduleEntry.objects.filter(
                    semester=semester, is_locked=False
                ).delete()
            else:
                ScheduleEntry.objects.filter(semester=semester).delete()

            bulk_entries = []
            for a in assignments:
                if a.get('is_locked'):
                    continue
                bulk_entries.append(ScheduleEntry(
                    semester_id=a['semester_id'],
                    class_id_id=a['class_id'],
                    course_id=a['course_id'],
                    teacher_id=a['teacher_id'],
                    classroom_id=a['classroom_id'],
                    day_of_week=a['day_of_week'],
                    period=a['period'],
                    is_locked=False
                ))
            ScheduleEntry.objects.bulk_create(bulk_entries)

            all_entries = ScheduleEntry.objects.filter(
                semester=semester
            ).values('id', 'teacher_id', 'classroom_id', 'class_id', 'day_of_week', 'period')

            detector = ConflictDetector()
            conflicts = detector.detect_conflicts(list(all_entries))

            Conflict.objects.filter(semester=semester).delete()
            bulk_conflicts = []
            for c in conflicts:
                bulk_conflicts.append(Conflict(
                    semester=semester,
                    conflict_type=c['conflict_type'],
                    day_of_week=c['day_of_week'],
                    period=c['period'],
                    involved_entries=c['involved_entries'],
                    message=c['message']
                ))
            Conflict.objects.bulk_create(bulk_conflicts)

            for c in conflicts:
                for eid in c['involved_entries']:
                    try:
                        entry = ScheduleEntry.objects.get(id=eid)
                        entry.is_conflict = True
                        entry.conflict_type = c['conflict_type']
                        entry.save()
                    except ScheduleEntry.DoesNotExist:
                        pass

        final_entries = ScheduleEntry.objects.filter(semester=semester)
        serializer = ScheduleEntryDetailSerializer(final_entries, many=True)

        return Response({
            'schedule': serializer.data,
            'conflicts': conflicts,
            'scheduling_messages': scheduling_conflicts,
            'total_entries': len(serializer.data)
        })

    @action(detail=False, methods=['post'])
    def check_conflicts(self, request):
        req_serializer = ConflictCheckSerializer(data=request.data)
        if not req_serializer.is_valid():
            return Response(req_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        semester_id = req_serializer.validated_data['semester_id']
        entries = ScheduleEntry.objects.filter(
            semester_id=semester_id
        ).values('id', 'teacher_id', 'classroom_id', 'class_id', 'day_of_week', 'period')

        detector = ConflictDetector()
        conflicts = detector.detect_conflicts(list(entries))

        return Response({'conflicts': conflicts})

    @action(detail=False, methods=['post'])
    def swap(self, request):
        req_serializer = SwapScheduleRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return Response(req_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        entry1_id = req_serializer.validated_data['entry1_id']
        entry2_id = req_serializer.validated_data['entry2_id']
        reason = req_serializer.validated_data.get('reason', '')

        try:
            entry1 = ScheduleEntry.objects.get(id=entry1_id)
            entry2 = ScheduleEntry.objects.get(id=entry2_id)
        except ScheduleEntry.DoesNotExist:
            return Response(
                {'error': 'One or both entries not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        with transaction.atomic():
            day1, period1 = entry1.day_of_week, entry1.period
            day2, period2 = entry2.day_of_week, entry2.period

            entry1.day_of_week, entry1.period = day2, period2
            entry2.day_of_week, entry2.period = day1, period1

            entry1.save()
            entry2.save()

            if reason:
                SwapRequest.objects.create(
                    semester=entry1.semester,
                    requesting_teacher=entry1.teacher,
                    target_teacher=entry2.teacher,
                    entry1=entry1,
                    entry2=entry2,
                    reason=reason,
                    status='approved'
                )

        return Response({'status': 'success', 'message': 'Swap completed'})

    @action(detail=False, methods=['post'])
    def substitute(self, request):
        req_serializer = SubstituteRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return Response(req_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        entry_id = req_serializer.validated_data['entry_id']
        substitute_teacher_id = req_serializer.validated_data['substitute_teacher_id']
        start_date = req_serializer.validated_data['start_date']
        end_date = req_serializer.validated_data['end_date']
        reason = req_serializer.validated_data['reason']

        try:
            entry = ScheduleEntry.objects.get(id=entry_id)
            substitute_teacher = Teacher.objects.get(id=substitute_teacher_id)
        except (ScheduleEntry.DoesNotExist, Teacher.DoesNotExist):
            return Response(
                {'error': 'Entry or teacher not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        original_teacher = entry.teacher

        with transaction.atomic():
            Substitute.objects.create(
                semester=entry.semester,
                original_teacher=original_teacher,
                substitute_teacher=substitute_teacher,
                affected_entry=entry,
                start_date=start_date,
                end_date=end_date,
                reason=reason
            )

            entry.original_teacher = original_teacher
            entry.teacher = substitute_teacher
            entry.save()

        serializer = ScheduleEntryDetailSerializer(entry)
        return Response({'status': 'success', 'entry': serializer.data})

    @action(detail=False, methods=['get'])
    def export_pdf(self, request):
        semester_id = request.query_params.get('semester_id')
        entity_type = request.query_params.get('type')
        entity_id = request.query_params.get('id')

        try:
            semester = Semester.objects.get(id=semester_id)
        except Semester.DoesNotExist:
            return Response(
                {'error': 'Semester not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        pdf_buffer = None
        filename = 'timetable.pdf'

        try:
            if entity_type == 'class':
                class_obj = Class.objects.get(id=entity_id)
                pdf_buffer = generate_class_timetable_pdf(class_obj, semester)
                filename = f'{class_obj.name}_课表.pdf'
            elif entity_type == 'teacher':
                teacher = Teacher.objects.get(id=entity_id)
                pdf_buffer = generate_teacher_timetable_pdf(teacher, semester)
                filename = f'{teacher.name}_课表.pdf'
            elif entity_type == 'classroom':
                classroom = Classroom.objects.get(id=entity_id)
                pdf_buffer = generate_classroom_timetable_pdf(classroom, semester)
                filename = f'{classroom.name}_课表.pdf'
            else:
                return Response(
                    {'error': 'Invalid type. Must be class, teacher, or classroom'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (Class.DoesNotExist, Teacher.DoesNotExist, Classroom.DoesNotExist):
            return Response(
                {'error': 'Entity not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        response = HttpResponse(pdf_buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class ConflictViewSet(viewsets.ModelViewSet):
    queryset = Conflict.objects.all().select_related('semester')
    serializer_class = ConflictSerializer
    permission_classes = [AllowAny]


class ScheduleVersionViewSet(viewsets.ReadOnlyModelViewSet):
    """课表发布版本：提供发布入口和版本（快照）回读入口。"""
    queryset = ScheduleVersion.objects.all().select_related('semester')
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action == 'list':
            return ScheduleVersionListSerializer
        return ScheduleVersionDetailSerializer

    def get_queryset(self):
        queryset = self.queryset
        semester_id = self.request.query_params.get('semester_id')
        if semester_id:
            queryset = queryset.filter(semester_id=semester_id)
        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # 每个学期版本号最高的一条即最新发布版本
        context['latest_version_ids'] = set(
            ScheduleVersion.objects.values('semester_id')
            .annotate(latest_id=Max('id'))
            .values_list('latest_id', flat=True)
        )
        return context

    @action(detail=False, methods=['post'])
    def publish(self, request):
        """发布课表：重新核对冲突，全部通过才保存快照并生成新版本。"""
        req_serializer = PublishScheduleRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return Response(
                req_serializer.errors, status=status.HTTP_400_BAD_REQUEST
            )

        published_by = (
            request.user.username
            if request.user and request.user.is_authenticated
            else ''
        )
        note = req_serializer.validated_data.get('note') or ''

        try:
            version, created = publish_schedule(
                semester_id=req_serializer.validated_data['semester_id'],
                published_by=published_by,
                note=note,
            )
        except PublishConflictError as exc:
            return Response({
                'error': 'conflicts_present',
                'message': str(exc),
                'conflicts': exc.conflicts,
            }, status=status.HTTP_409_CONFLICT)
        except PublishInProgressError as exc:
            return Response({
                'error': 'publish_in_progress',
                'message': str(exc),
            }, status=status.HTTP_409_CONFLICT)
        except PublishError as exc:
            return Response(
                {'error': 'publish_failed', 'message': str(exc)},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ScheduleVersionDetailSerializer(
            version, context=self.get_serializer_context()
        )
        return Response({
            'status': 'created' if created else 'unchanged',
            'message': (
                '发布成功，已生成新版本' if created
                else '课表内容与最新发布版本一致，未重复生成版本'
            ),
            'version': serializer.data,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def latest(self, request):
        """回读指定学期的最新发布版本（含完整快照）。"""
        semester_id = request.query_params.get('semester_id')
        if not semester_id:
            return Response(
                {'error': 'semester_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        version = (
            ScheduleVersion.objects.select_related('semester')
            .filter(semester_id=semester_id)
            .first()
        )
        if version is None:
            return Response(
                {'error': '该学期尚无发布版本'},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = ScheduleVersionDetailSerializer(
            version, context=self.get_serializer_context()
        )
        return Response(serializer.data)


class SwapRequestViewSet(viewsets.ModelViewSet):
    queryset = SwapRequest.objects.all().select_related(
        'semester', 'requesting_teacher', 'target_teacher'
    )
    serializer_class = SwapRequestSerializer
    permission_classes = [AllowAny]


class SubstituteViewSet(viewsets.ModelViewSet):
    queryset = Substitute.objects.all().select_related(
        'semester', 'original_teacher', 'substitute_teacher'
    )
    serializer_class = SubstituteSerializer
    permission_classes = [AllowAny]
