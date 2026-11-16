"""BE2 Attendance Services.

Core logic for:
1. Opening a session (marking initial status, ensuring order).
2. Taking attendance (recording Present, Late, Absent for students).
3. Closing a session (finalizing records, setting auto-absent for unrecorded students).
4. Calculating attendance statistics and absence rates per classroom and per student.
5. Evaluating absence warnings against Setting.absence_threshold (FR-14, FR-24).
"""
from decimal import Decimal
from django.db import transaction
from django.db.models import Count, Q
from django.core.exceptions import ValidationError

from accounts.models import Student
from classrooms.models import AttendanceSession, SessionStatus
from .models import AttendanceRecord, AttendanceStatus, Setting, get_absence_threshold


def open_session(session: AttendanceSession):
    """Transition session status from SCHEDULED to OPEN."""
    with transaction.atomic():
        locked_session = AttendanceSession.objects.select_for_update().get(pk=session.pk)
        locked_session.open()
        return locked_session


def take_attendance(session: AttendanceSession, attendance_data: dict):
    """Save attendance records for a session.
    
    attendance_data format: {student_id_str: status_str, ...}
    e.g. {"SV001": "PRESENT", "SV002": "ABSENT"}
    """
    with transaction.atomic():
        locked_session = AttendanceSession.objects.select_for_update().get(pk=session.pk)
        if locked_session.status != SessionStatus.OPEN:
            raise ValidationError("Attendance can only be taken when session is OPEN.")
        
        valid_statuses = set(AttendanceStatus.values)
        for student_id, status in attendance_data.items():
            if status not in valid_statuses:
                raise ValidationError(f"Invalid attendance status: {status}")
            
            student = Student.objects.get(student_id=student_id)
            AttendanceRecord.objects.update_or_create(
                session=locked_session,
                student=student,
                defaults={"status": status}
            )


def close_session(session: AttendanceSession, attendance_data: dict = None):
    """Take any final attendance records and transition session from OPEN to CLOSED.
    Any enrolled student without an explicit attendance record is automatically marked ABSENT.
    """
    with transaction.atomic():
        locked_session = AttendanceSession.objects.select_for_update().get(pk=session.pk)
        if locked_session.status != SessionStatus.OPEN:
            raise ValidationError("Only an OPEN session can be closed.")
        
        if attendance_data:
            take_attendance(locked_session, attendance_data)
        
        # Auto-mark ABSENT for enrolled students who don't have a record in this session
        enrolled_students = Student.objects.filter(enrollments__classroom=locked_session.classroom)
        existing_student_ids = AttendanceRecord.objects.filter(
            session=locked_session
        ).values_list("student_id", flat=True)
        
        missing_students = enrolled_students.exclude(student_id__in=existing_student_ids)
        new_records = [
            AttendanceRecord(
                session=locked_session,
                student=s,
                status=AttendanceStatus.ABSENT
            )
            for s in missing_students
        ]
        if new_records:
            AttendanceRecord.objects.bulk_create(new_records)
        
        locked_session.close()
        return locked_session


def update_closed_attendance(session: AttendanceSession, attendance_data: dict):
    """Update a complete set of attendance statuses for an already closed session."""
    with transaction.atomic():
        locked_session = AttendanceSession.objects.select_for_update().get(pk=session.pk)
        if locked_session.status != SessionStatus.CLOSED:
            raise ValidationError("Only a CLOSED session can be edited.")

        valid_statuses = set(AttendanceStatus.values)
        enrolled_student_ids = set(
            Student.objects.filter(enrollments__classroom=locked_session.classroom)
            .values_list("student_id", flat=True)
        )
        if set(attendance_data) != enrolled_student_ids:
            raise ValidationError("Attendance must be supplied for every enrolled student.")

        for student_id, status in attendance_data.items():
            if status not in valid_statuses:
                raise ValidationError(f"Invalid attendance status: {status}")
            AttendanceRecord.objects.update_or_create(
                session=locked_session,
                student_id=student_id,
                defaults={"status": status},
            )


def get_classroom_attendance_report(classroom):
    """Compute attendance matrix and absence summary for a classroom.
    
    Returns:
    {
        "classroom": classroom,
        "sessions": closed_sessions_qs,
        "threshold": threshold_decimal,
        "rows": [
            {
                "student": student,
                "records": {session_id: record_status, ...},
                "total_sessions": int,
                "present_count": int,
                "late_count": int,
                "absent_count": int,
                "absence_rate": Decimal,
                "is_warned": bool
            },
            ...
        ]
    }
    """
    threshold = get_absence_threshold()
    closed_sessions = list(
        classroom.sessions.filter(status=SessionStatus.CLOSED).order_by("date", "start_time")
    )
    total_closed = len(closed_sessions)
    
    students = Student.objects.filter(
        enrollments__classroom=classroom
    ).select_related("user").order_by("student_id")
    
    records = AttendanceRecord.objects.filter(
        session__in=closed_sessions
    ).values("session_id", "student_id", "status")
    
    # Map (student_id, session_id) -> status
    record_map = {}
    for r in records:
        record_map.setdefault(r["student_id"], {})[r["session_id"]] = r["status"]
    
    rows = []
    for s in students:
        s_records = record_map.get(s.student_id, {})
        present_count = sum(1 for status in s_records.values() if status == AttendanceStatus.PRESENT)
        late_count = sum(1 for status in s_records.values() if status == AttendanceStatus.LATE)
        absent_count = sum(1 for status in s_records.values() if status == AttendanceStatus.ABSENT)
        
        if total_closed > 0:
            # Absence rate = absent / total_closed * 100
            absence_rate = (Decimal(absent_count) / Decimal(total_closed)) * Decimal(100)
            absence_rate = round(absence_rate, 2)
        else:
            absence_rate = Decimal("0.00")
            
        is_warned = absence_rate >= threshold
        
        rows.append({
            "student": s,
            "records": s_records,
            "session_statuses": [s_records.get(sess.session_id, "-") for sess in closed_sessions],
            "total_sessions": total_closed,
            "present_count": present_count,
            "late_count": late_count,
            "absent_count": absent_count,
            "absence_rate": absence_rate,
            "is_warned": is_warned
        })
        
    return {
        "classroom": classroom,
        "sessions": closed_sessions,
        "threshold": threshold,
        "rows": rows
    }


def get_student_classroom_summary(student, classroom):
    """Compute individual student attendance statistics for a single classroom."""
    threshold = get_absence_threshold()
    closed_sessions = classroom.sessions.filter(status=SessionStatus.CLOSED)
    total_closed = closed_sessions.count()
    
    records = AttendanceRecord.objects.filter(
        session__in=closed_sessions,
        student=student
    ).select_related("session")
    
    present_count = records.filter(status=AttendanceStatus.PRESENT).count()
    late_count = records.filter(status=AttendanceStatus.LATE).count()
    absent_count = records.filter(status=AttendanceStatus.ABSENT).count()
    
    if total_closed > 0:
        absence_rate = (Decimal(absent_count) / Decimal(total_closed)) * Decimal(100)
        absence_rate = round(absence_rate, 2)
    else:
        absence_rate = Decimal("0.00")
        
    is_warned = absence_rate >= threshold
    
    return {
        "student": student,
        "classroom": classroom,
        "total_sessions": total_closed,
        "present_count": present_count,
        "late_count": late_count,
        "absent_count": absent_count,
        "absence_rate": absence_rate,
        "is_warned": is_warned,
        "records": records.order_by("session__date", "session__start_time")
    }
