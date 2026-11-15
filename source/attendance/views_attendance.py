import csv
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.models import Role, Student
from accounts.permissions import admin_or_teacher_required, role_required
from classrooms.access import classroom_scoped, get_classroom_or_403, session_scoped
from classrooms.models import AttendanceSession, Classroom, SessionStatus

from .models import AttendanceRecord, AttendanceStatus
from .services import (
    close_session,
    get_classroom_attendance_report,
    get_student_classroom_summary,
    open_session,
    take_attendance,
)


@admin_or_teacher_required
@require_http_methods(["POST"])
def session_open_view(request, pk):
    """Transition session status from SCHEDULED to OPEN."""
    session = get_object_or_404(AttendanceSession, pk=pk)
    # Check scope if teacher
    if request.user.role == Role.TEACHER and session.classroom.teacher_id != request.user.teacher_id:
        raise PermissionDenied
    try:
        open_session(session)
        messages.success(request, f"Session on {session.date} is now OPEN for attendance.")
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("session_detail", pk=session.pk)


@admin_or_teacher_required
@require_http_methods(["GET", "POST"])
def take_attendance_view(request, pk):
    """View and update attendance for an OPEN session."""
    session = get_object_or_404(
        AttendanceSession.objects.select_related("classroom__course"), pk=pk
    )
    if request.user.role == Role.TEACHER and session.classroom.teacher_id != request.user.teacher_id:
        raise PermissionDenied

    if session.status != SessionStatus.OPEN:
        messages.error(request, "Attendance can only be taken for an OPEN session.")
        return redirect("session_detail", pk=session.pk)

    enrolled_students = Student.objects.filter(
        enrollments__classroom=session.classroom
    ).select_related("user").order_by("student_id")

    existing_records = {
        r.student_id: r.status
        for r in AttendanceRecord.objects.filter(session=session)
    }

    if request.method == "POST":
        action = request.POST.get("action", "save")  # "save" or "close"
        attendance_data = {}
        for s in enrolled_students:
            val = request.POST.get(f"status_{s.student_id}")
            if val:
                attendance_data[s.student_id] = val

        try:
            if action == "close":
                close_session(session, attendance_data)
                messages.success(request, f"Attendance finalized. Session {session} is now CLOSED.")
                return redirect("classroom_attendance_report", pk=session.classroom_id)
            else:
                take_attendance(session, attendance_data)
                messages.success(request, "Attendance records saved successfully.")
                return redirect("take_attendance", pk=session.pk)
        except ValidationError as e:
            messages.error(request, str(e))

    student_rows = []
    for s in enrolled_students:
        student_rows.append({
            "student": s,
            "status": existing_records.get(s.student_id, AttendanceStatus.PRESENT)
        })

    return render(request, "attendance/take_attendance.html", {
        "session": session,
        "student_rows": student_rows,
        "status_choices": AttendanceStatus.choices,
    })


@classroom_scoped
def classroom_attendance_report(request, classroom):
    """View attendance summary and rate matrix for a classroom."""
    report = get_classroom_attendance_report(classroom)
    
    # If student, limit to personal row
    if request.user.role == Role.STUDENT:
        student_summary = get_student_classroom_summary(request.user.student_profile, classroom)
        return render(request, "attendance/student_report.html", {
            "classroom": classroom,
            "summary": student_summary,
            "threshold": report["threshold"],
        })

    return render(request, "attendance/classroom_report.html", {
        "report": report,
        "classroom": classroom,
    })


@admin_or_teacher_required
def export_attendance_csv(request, pk):
    """Export attendance report of a classroom as CSV file."""
    classroom = get_classroom_or_403(request.user, pk)
    report = get_classroom_attendance_report(classroom)

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="attendance_{classroom.class_id}.csv"'
    
    writer = csv.writer(response)
    
    # Header row
    headers = ["Student ID", "Full Name"]
    for s in report["sessions"]:
        headers.append(f"{s.date} {s.start_time.strftime('%H:%M')}")
    headers.extend(["Present", "Late", "Absent", "Absence Rate (%)", "Warning"])
    writer.writerow(headers)

    # Data rows
    for row in report["rows"]:
        s = row["student"]
        line = [s.student_id, s.full_name]
        for sess in report["sessions"]:
            line.append(row["records"].get(sess.session_id, "-"))
        line.extend([
            row["present_count"],
            row["late_count"],
            row["absent_count"],
            f"{row['absence_rate']}%",
            "EXCEEDED" if row["is_warned"] else "OK"
        ])
        writer.writerow(line)

    return response
