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

from accounts.models import Student, Teacher
from classrooms.models import AttendanceSession, Classroom, SessionStatus
from .models import (
    AttendanceRecord,
    AttendanceStatistics,
    AttendanceStatus,
    Setting,
    get_absence_threshold,
)


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


def update_closed_session_attendance(session: AttendanceSession, attendance_data: dict):
    """FR-20: Correct attendance statuses for an already CLOSED session.

    Keeps the session CLOSED and validates every status before updating.
    """
    with transaction.atomic():
        locked_session = AttendanceSession.objects.select_for_update().get(pk=session.pk)
        if locked_session.status != SessionStatus.CLOSED:
            raise ValidationError("Only a CLOSED session can have its attendance records updated.")

        valid_statuses = set(AttendanceStatus.values)
        for student_id, status in attendance_data.items():
            if status not in valid_statuses:
                raise ValidationError(f"Invalid attendance status: {status}")

        existing_records = {
            r.student_id: r
            for r in AttendanceRecord.objects.select_for_update().filter(session=locked_session)
        }
        enrolled_ids = set(
            Student.objects.filter(enrollments__classroom=locked_session.classroom)
            .values_list("student_id", flat=True)
        )

        updated_count = 0
        for student_id, new_status in attendance_data.items():
            if student_id in existing_records:
                rec = existing_records[student_id]
                if rec.status != new_status:
                    rec.change_status(new_status)
                    updated_count += 1
            elif student_id in enrolled_ids:
                student = Student.objects.get(student_id=student_id)
                AttendanceRecord.objects.create(
                    session=locked_session,
                    student=student,
                    status=new_status,
                )
                updated_count += 1
        return updated_count


def get_classroom_attendance_report(classroom):
    """Compute attendance matrix and absence summary for a classroom.

    Uses AttendanceStatistics per student so late-enrolled students only count Closed sessions
    in which they actually have an AttendanceRecord (BUG-001 / FR-21).
    """
    threshold = get_absence_threshold()
    closed_sessions = list(
        classroom.sessions.filter(status=SessionStatus.CLOSED).order_by("date", "start_time")
    )

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
        stats = AttendanceStatistics(
            student=s,
            present_count=sum(1 for st in s_records.values() if st == AttendanceStatus.PRESENT),
            late_count=sum(1 for st in s_records.values() if st == AttendanceStatus.LATE),
            absent_count=sum(1 for st in s_records.values() if st == AttendanceStatus.ABSENT),
        )
        counted_sessions = stats.total_recorded()
        absence_rate = stats.absence_rate()
        is_warned = counted_sessions > 0 and absence_rate >= threshold

        rows.append({
            "student": s,
            "stats": stats,
            "records": s_records,
            "session_statuses": [s_records.get(sess.session_id, "-") for sess in closed_sessions],
            "total_sessions": counted_sessions,
            "present_count": stats.present_count,
            "late_count": stats.late_count,
            "absent_count": stats.absent_count,
            "absence_rate": absence_rate,
            "attendance_rate": stats.attendance_rate(),
            "is_warned": is_warned,
        })

    return {
        "classroom": classroom,
        "sessions": closed_sessions,
        "threshold": threshold,
        "rows": rows,
    }


def get_student_classroom_summary(student, classroom):
    """Compute individual student attendance statistics for a single classroom."""
    threshold = get_absence_threshold()
    closed_sessions = classroom.sessions.filter(status=SessionStatus.CLOSED)

    records = AttendanceRecord.objects.filter(
        session__in=closed_sessions,
        student=student,
    ).select_related("session")

    stats = AttendanceStatistics(
        student=student,
        present_count=records.filter(status=AttendanceStatus.PRESENT).count(),
        late_count=records.filter(status=AttendanceStatus.LATE).count(),
        absent_count=records.filter(status=AttendanceStatus.ABSENT).count(),
    )
    counted_sessions = stats.total_recorded()
    absence_rate = stats.absence_rate()
    is_warned = counted_sessions > 0 and absence_rate >= threshold

    return {
        "student": student,
        "classroom": classroom,
        "stats": stats,
        "total_sessions": counted_sessions,
        "present_count": stats.present_count,
        "late_count": stats.late_count,
        "absent_count": stats.absent_count,
        "absence_rate": absence_rate,
        "attendance_rate": stats.attendance_rate(),
        "is_warned": is_warned,
        "records": records.order_by("session__date", "session__start_time"),
    }


def get_admin_attendance_summary():
    """FR-13: System-wide attendance overview for Admin dashboard and summary exports."""
    threshold = get_absence_threshold()
    closed_records = AttendanceRecord.objects.filter(session__status=SessionStatus.CLOSED)
    total_records = closed_records.count()
    attended_records = closed_records.filter(
        status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]
    ).count()
    overall_attendance_rate = (
        round((Decimal(attended_records) / Decimal(total_records)) * Decimal(100), 1)
        if total_records > 0
        else Decimal("0.0")
    )

    # Weekday breakdown (Mon..Sun) for closed sessions
    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_buckets = {i: [0, 0] for i in range(7)}  # [attended, total]
    for sess_date, st in closed_records.values_list("session__date", "status"):
        wd = sess_date.weekday()
        weekday_buckets[wd][1] += 1
        if st in (AttendanceStatus.PRESENT, AttendanceStatus.LATE):
            weekday_buckets[wd][0] += 1

    weekly = []
    if total_records > 0:
        for i, label in enumerate(weekday_labels):
            att, tot = weekday_buckets[i]
            val = round((att / tot) * 100) if tot > 0 else 0
            weekly.append({"label": label, "value": val})

    # Per-classroom breakdown + count of at-risk students across classrooms
    classrooms = (
        Classroom.objects.select_related("course", "teacher__user")
        .prefetch_related("enrollments")
        .order_by("course__code", "name")
    )
    classroom_summaries = []
    at_risk_student_ids = set()
    for cr in classrooms:
        rep = get_classroom_attendance_report(cr)
        cr_present = sum(r["present_count"] for r in rep["rows"])
        cr_late = sum(r["late_count"] for r in rep["rows"])
        cr_absent = sum(r["absent_count"] for r in rep["rows"])
        cr_total = cr_present + cr_late + cr_absent
        cr_abs_rate = (
            round((Decimal(cr_absent) / Decimal(cr_total)) * Decimal(100), 2)
            if cr_total > 0
            else Decimal("0.00")
        )
        for r in rep["rows"]:
            if r["is_warned"]:
                at_risk_student_ids.add(r["student"].student_id)
        classroom_summaries.append({
            "classroom": cr,
            "enrolled_count": len(rep["rows"]),
            "closed_sessions": len(rep["sessions"]),
            "present_count": cr_present,
            "late_count": cr_late,
            "absent_count": cr_absent,
            "absence_rate": cr_abs_rate,
        })

    return {
        "threshold": threshold,
        "stats": {
            "students": Student.objects.count(),
            "teachers": Teacher.objects.count(),
            "classrooms": classrooms.count(),
            "attendance_rate": overall_attendance_rate,
        },
        "weekly": weekly,
        "attention": {
            "at_risk_count": len(at_risk_student_ids),
            "open_sessions": AttendanceSession.objects.filter(status=SessionStatus.OPEN).count(),
            "unassigned_classes": Classroom.objects.filter(teacher__isnull=True).count(),
        },
        "classroom_summaries": classroom_summaries,
        "has_attendance_data": total_records > 0,
    }
