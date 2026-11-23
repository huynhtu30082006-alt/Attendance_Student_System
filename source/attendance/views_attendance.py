import csv
import io
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from accounts.models import Role, Student
from accounts.permissions import admin_or_teacher_required, admin_required
from classrooms.access import classroom_scoped, get_classroom_or_403, session_scoped
from classrooms.models import AttendanceSession, SessionStatus

from .models import AttendanceRecord, AttendanceStatus
from .services import (
    close_session,
    get_admin_attendance_summary,
    get_classroom_attendance_report,
    get_student_classroom_summary,
    open_session,
    take_attendance,
    update_closed_session_attendance,
)


@admin_required
def admin_dashboard_view(request):
    """FR-13: System-wide attendance overview for Admin."""
    summary = get_admin_attendance_summary()
    return render(request, "attendance/admin_dashboard.html", {
        "stats": summary["stats"],
        "weekly": summary["weekly"],
        "attention": summary["attention"],
        "classroom_summaries": summary["classroom_summaries"],
        "has_attendance_data": summary["has_attendance_data"],
        "export_excel_url": reverse("export_summary_excel"),
        "export_pdf_url": reverse("export_summary_pdf"),
    })


@admin_or_teacher_required
@require_http_methods(["POST"])
def session_open_view(request, pk):
    """Transition session status from SCHEDULED to OPEN."""
    session = get_object_or_404(AttendanceSession, pk=pk)
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

    student_rows = [
        {
            "student": s,
            "status": existing_records.get(s.student_id),  # None when not yet marked
        }
        for s in enrolled_students
    ]

    return render(request, "attendance/take_attendance.html", {
        "session": session,
        "student_rows": student_rows,
        "status_choices": AttendanceStatus.choices,
    })


@session_scoped
@require_http_methods(["GET", "POST"])
def session_records_view(request, session):
    """FR-20 & FR-21: View attendance records of a session and edit statuses of a CLOSED session."""
    if request.user.role == Role.STUDENT:
        raise PermissionDenied

    session = (
        AttendanceSession.objects.select_related("classroom__course")
        .get(pk=session.pk)
    )
    can_edit = (
        session.status == SessionStatus.CLOSED
        and request.user.role in (Role.ADMIN, Role.TEACHER)
    )

    if request.method == "POST":
        if not can_edit:
            messages.error(request, "Attendance statuses can only be edited for a CLOSED session.")
            return redirect("session_records", pk=session.pk)

        attendance_data = {}
        for key, val in request.POST.items():
            if key.startswith("status_") and val:
                attendance_data[key[len("status_"):]] = val
        try:
            changed = update_closed_session_attendance(session, attendance_data)
            if changed:
                messages.success(request, f"Updated {changed} attendance record(s). Absence rates recalculated.")
            else:
                messages.info(request, "No status was changed.")
        except ValidationError as e:
            messages.error(request, str(e))
        return redirect("session_records", pk=session.pk)

    records = list(
        AttendanceRecord.objects.filter(session=session)
        .select_related("student__user")
        .order_by("student__student_id")
    )
    rows = [{"student": r.student, "status": r.status} for r in records]

    return render(request, "attendance/session_records.html", {
        "session": session,
        "rows": rows,
        "status_choices": AttendanceStatus.choices,
        "can_edit": can_edit,
    })


@classroom_scoped
def classroom_attendance_report(request, classroom):
    """View attendance summary and rate matrix for a classroom."""
    report = get_classroom_attendance_report(classroom)

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


def _build_classroom_table(report):
    headers = ["Student ID", "Full Name"]
    for s in report["sessions"]:
        headers.append(f"{s.date} {s.start_time.strftime('%H:%M')}")
    headers.extend(["Present", "Late", "Absent", "Absence Rate (%)", "Warning"])

    data_rows = []
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
            "EXCEEDED" if row["is_warned"] else "OK",
        ])
        data_rows.append(line)
    return headers, data_rows


def _render_xlsx_bytes(sheet_title, headers, rows):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]
    ws.append(headers)

    header_fill = PatternFill("solid", fgColor="0F1D3D")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for r in rows:
        ws.append(r)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _render_pdf_bytes(title, headers, rows):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    elements = [Paragraph(title, styles["Heading2"]), Spacer(1, 10)]

    table_data = [[str(h) for h in headers]] + [[str(c) for c in r] for r in rows]
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f1d3d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(table)
    doc.build(elements)
    return buf.getvalue()


@admin_or_teacher_required
def export_attendance_csv(request, pk):
    """Export attendance report of a classroom as CSV file."""
    classroom = get_classroom_or_403(request.user, pk)
    report = get_classroom_attendance_report(classroom)

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="attendance_{classroom.class_id}.csv"'

    headers, data_rows = _build_classroom_table(report)
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(data_rows)
    return response


@admin_or_teacher_required
def export_attendance_excel(request, pk):
    """FR-26: Export attendance report of a classroom as Excel (.xlsx)."""
    classroom = get_classroom_or_403(request.user, pk)
    report = get_classroom_attendance_report(classroom)
    if not report["sessions"] or not report["rows"]:
        messages.error(request, "There is no attendance data to export for this classroom.")
        return redirect("classroom_attendance_report", pk=classroom.pk)

    try:
        headers, data_rows = _build_classroom_table(report)
        content = _render_xlsx_bytes(f"Report {classroom.class_id}", headers, data_rows)
    except Exception:
        messages.error(request, "Could not generate the Excel report. Please try again.")
        return redirect("classroom_attendance_report", pk=classroom.pk)

    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="attendance_{classroom.class_id}.xlsx"'
    return response


@admin_or_teacher_required
def export_attendance_pdf(request, pk):
    """FR-26: Export attendance report of a classroom as PDF."""
    classroom = get_classroom_or_403(request.user, pk)
    report = get_classroom_attendance_report(classroom)
    if not report["sessions"] or not report["rows"]:
        messages.error(request, "There is no attendance data to export for this classroom.")
        return redirect("classroom_attendance_report", pk=classroom.pk)

    try:
        headers, data_rows = _build_classroom_table(report)
        title = f"Attendance Report - {classroom.course.code} / {classroom.name} ({classroom.class_id})"
        content = _render_pdf_bytes(title, headers, data_rows)
    except Exception:
        messages.error(request, "Could not generate the PDF report. Please try again.")
        return redirect("classroom_attendance_report", pk=classroom.pk)

    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="attendance_{classroom.class_id}.pdf"'
    return response


def _build_summary_table(summary):
    headers = ["Course", "Classroom ID", "Classroom Name", "Enrolled", "Closed Sessions", "Present", "Late", "Absent", "Absence Rate (%)"]
    rows = []
    for item in summary["classroom_summaries"]:
        cr = item["classroom"]
        rows.append([
            f"{cr.course.code} - {cr.course.name}",
            cr.class_id,
            cr.name,
            item["enrolled_count"],
            item["closed_sessions"],
            item["present_count"],
            item["late_count"],
            item["absent_count"],
            f"{item['absence_rate']}%",
        ])
    return headers, rows


@admin_required
def export_summary_excel(request):
    """Export system-wide Admin attendance summary as Excel (.xlsx)."""
    summary = get_admin_attendance_summary()
    if not summary["has_attendance_data"]:
        messages.error(request, "There is no attendance data to export.")
        return redirect("admin_dashboard")
    try:
        headers, rows = _build_summary_table(summary)
        content = _render_xlsx_bytes("Attendance Summary", headers, rows)
    except Exception:
        messages.error(request, "Could not generate the Excel summary. Please try again.")
        return redirect("admin_dashboard")
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="attendance_summary.xlsx"'
    return response


@admin_required
def export_summary_pdf(request):
    """Export system-wide Admin attendance summary as PDF."""
    summary = get_admin_attendance_summary()
    if not summary["has_attendance_data"]:
        messages.error(request, "There is no attendance data to export.")
        return redirect("admin_dashboard")
    try:
        headers, rows = _build_summary_table(summary)
        content = _render_pdf_bytes("System-Wide Attendance Summary", headers, rows)
    except Exception:
        messages.error(request, "Could not generate the PDF summary. Please try again.")
        return redirect("admin_dashboard")
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="attendance_summary.pdf"'
    return response
