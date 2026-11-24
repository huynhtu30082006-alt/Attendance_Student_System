"""Tests for Classroom Reports, Absence Warnings, Student Views, and Report Exports (TC157-TC179)."""
import csv
import io
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from attendance.models import AttendanceRecord, AttendanceStatus, Setting
from attendance.services import get_classroom_attendance_report, get_student_classroom_summary
from tests.factories import (
    AttendanceFactory,
    ClassroomFactory,
    SessionFactory,
    UserFactory,
)


def _row_by_student(report, student_user):
    sid = student_user.student_profile.student_id
    return next(r for r in report["rows"] if r["student"].student_id == sid)


# ---------------------------------------------------------------------------
# TC157 - TC163: Classroom attendance report
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc157_classroom_report_counts_and_absence_rate_late_counts_as_attended(
    teacher_user, teacher_client
):
    """TC157: Classroom report counts & absence rate (Late counts as attended: 2P+2L=0%, 1P+3A=75%, 2P+2A=50%)."""
    s1 = UserFactory.student()
    s2 = UserFactory.student()
    s3 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1, s2, s3])
    sessions = [SessionFactory.closed(classroom=classroom) for _ in range(4)]

    # s1: 2P + 2L = 0% absent
    for sess in sessions[:2]:
        AttendanceFactory.present(session=sess, student=s1)
    for sess in sessions[2:]:
        AttendanceFactory.late(session=sess, student=s1)

    # s2: 1P + 3A = 75% absent
    AttendanceFactory.present(session=sessions[0], student=s2)
    for sess in sessions[1:]:
        AttendanceFactory.absent(session=sess, student=s2)

    # s3: 2P + 2A = 50% absent
    for sess in sessions[:2]:
        AttendanceFactory.present(session=sess, student=s3)
    for sess in sessions[2:]:
        AttendanceFactory.absent(session=sess, student=s3)

    report = get_classroom_attendance_report(classroom)
    r1 = _row_by_student(report, s1)
    r2 = _row_by_student(report, s2)
    r3 = _row_by_student(report, s3)

    assert (r1["present_count"], r1["late_count"], r1["absent_count"]) == (2, 2, 0)
    assert r1["absence_rate"] == Decimal("0.00")

    assert (r2["present_count"], r2["late_count"], r2["absent_count"]) == (1, 0, 3)
    assert r2["absence_rate"] == Decimal("75.00")

    assert (r3["present_count"], r3["late_count"], r3["absent_count"]) == (2, 0, 2)
    assert r3["absence_rate"] == Decimal("50.00")

    resp = teacher_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "75%" in content
    assert "50%" in content
    assert "0%" in content


@pytest.mark.django_db
def test_tc158_classroom_report_ignores_cancelled_sessions(teacher_user, teacher_client):
    """TC158: Cancelled sessions are excluded from closed-session counts and absence rate."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])

    closed1 = SessionFactory.closed(classroom=classroom)
    closed2 = SessionFactory.closed(classroom=classroom)
    SessionFactory.cancelled(classroom=classroom)
    SessionFactory.scheduled(classroom=classroom)
    SessionFactory.open(classroom=classroom)

    AttendanceFactory.present(session=closed1, student=s1)
    AttendanceFactory.absent(session=closed2, student=s1)

    report = get_classroom_attendance_report(classroom)
    assert len(report["sessions"]) == 2
    row = _row_by_student(report, s1)
    assert row["total_sessions"] == 2
    assert row["absence_rate"] == Decimal("50.00")

    resp = teacher_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_tc159_late_enrolled_student_excludes_earlier_closed_sessions():
    """TC159: Late-enrolled student excludes earlier Closed sessions from denominator (1A out of 2 = 50%, not 1/4 = 25%)."""
    s_early = UserFactory.student()
    s_late = UserFactory.student()
    classroom = ClassroomFactory.create(students=[s_early])

    # 2 earlier Closed sessions before s_late enrolled
    early1 = SessionFactory.closed(classroom=classroom)
    early2 = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.present(session=early1, student=s_early)
    AttendanceFactory.present(session=early2, student=s_early)

    # s_late enrolls after early1 & early2 were closed
    ClassroomFactory.enrol_student(classroom, s_late)

    # 2 subsequent Closed sessions for both students
    later1 = SessionFactory.closed(classroom=classroom)
    later2 = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.present(session=later1, student=s_early)
    AttendanceFactory.present(session=later2, student=s_early)
    AttendanceFactory.present(session=later1, student=s_late)
    AttendanceFactory.absent(session=later2, student=s_late)

    report = get_classroom_attendance_report(classroom)
    late_row = _row_by_student(report, s_late)
    assert late_row["total_sessions"] == 2
    assert late_row["absence_rate"] == Decimal("50.00")


@pytest.mark.django_db
def test_tc160_classroom_report_zero_closed_sessions_no_zero_division(teacher_user, teacher_client):
    """TC160: 0 Closed sessions displays 0% and message with no ZeroDivisionError."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    SessionFactory.scheduled(classroom=classroom)

    report = get_classroom_attendance_report(classroom)
    row = _row_by_student(report, s1)
    assert row["total_sessions"] == 0
    assert row["absence_rate"] == Decimal("0.00")

    resp = teacher_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "0%" in content
    assert "No session has been closed yet, so every rate is 0%." in content


@pytest.mark.django_db
def test_tc161_recalculate_absence_rate_immediately_on_record_edit(teacher_user, teacher_client):
    """TC161: Changing a student's record from Absent to Present immediately recalculates absence rate."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    sess1 = SessionFactory.closed(classroom=classroom)
    sess2 = SessionFactory.closed(classroom=classroom)

    rec1 = AttendanceFactory.absent(session=sess1, student=s1)
    AttendanceFactory.present(session=sess2, student=s1)

    report_before = get_classroom_attendance_report(classroom)
    assert _row_by_student(report_before, s1)["absence_rate"] == Decimal("50.00")

    # Edit record Absent -> Present
    AttendanceRecord.objects.filter(session=sess1, student=s1.student_profile).update(
        status=AttendanceStatus.PRESENT
    )
    assert rec1 is not None

    report_after = get_classroom_attendance_report(classroom)
    assert _row_by_student(report_after, s1)["absence_rate"] == Decimal("0.00")
    assert _row_by_student(report_after, s1)["is_warned"] is False

    resp = teacher_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    assert "0%" in resp.content.decode()


@pytest.mark.django_db
def test_tc162_classroom_report_only_cancelled_sessions_shows_0_percent_and_message(
    teacher_user, teacher_client
):
    """TC162: Classroom with only Cancelled sessions shows 0% absence rate and no-closed-sessions message."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    SessionFactory.cancelled(classroom=classroom)
    SessionFactory.cancelled(classroom=classroom)

    report = get_classroom_attendance_report(classroom)
    assert len(report["sessions"]) == 0
    assert _row_by_student(report, s1)["absence_rate"] == Decimal("0.00")

    resp = teacher_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    assert "No session has been closed yet, so every rate is 0%." in resp.content.decode()


@pytest.mark.django_db
def test_tc163_classroom_report_access_control(teacher_user, teacher_client, make_authenticated_client):
    """TC163: Assigned Teacher accesses report (200); other Teacher & non-existent classroom get 403."""
    other_teacher = UserFactory.teacher()
    other_client = make_authenticated_client(other_teacher)
    classroom = ClassroomFactory.create(teacher=teacher_user)

    assert teacher_client.get(reverse("classroom_attendance_report", args=[classroom.pk])).status_code == 200
    assert other_client.get(reverse("classroom_attendance_report", args=[classroom.pk])).status_code == 403
    assert teacher_client.get(reverse("classroom_attendance_report", args=["CL999999"])).status_code == 403


# ---------------------------------------------------------------------------
# TC164 - TC166: Absence warning boundary & filtering
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc164_absence_warning_boundary_20_percent_vs_16_67_percent():
    """TC164: At default 20% threshold, 1/5 (20.00%) is warned while 1/6 (16.67%) is not warned."""
    Setting.get()  # default 20.00%

    # 1/5 = 20.00% -> warned
    s_warned = UserFactory.student()
    c5 = ClassroomFactory.create(students=[s_warned])
    s5_list = [SessionFactory.closed(classroom=c5) for _ in range(5)]
    AttendanceFactory.absent(session=s5_list[0], student=s_warned)
    for sess in s5_list[1:]:
        AttendanceFactory.present(session=sess, student=s_warned)

    r5 = _row_by_student(get_classroom_attendance_report(c5), s_warned)
    assert r5["absence_rate"] == Decimal("20.00")
    assert r5["is_warned"] is True

    # 1/6 = 16.67% -> not warned
    s_safe = UserFactory.student()
    c6 = ClassroomFactory.create(students=[s_safe])
    s6_list = [SessionFactory.closed(classroom=c6) for _ in range(6)]
    AttendanceFactory.absent(session=s6_list[0], student=s_safe)
    for sess in s6_list[1:]:
        AttendanceFactory.present(session=sess, student=s_safe)

    r6 = _row_by_student(get_classroom_attendance_report(c6), s_safe)
    assert r6["absence_rate"] == Decimal("16.67")
    assert r6["is_warned"] is False


@pytest.mark.django_db
def test_tc165_view_students_reaching_warning_and_filter(teacher_user, teacher_client):
    """TC165: Report highlights students reaching warning threshold and provides filter control."""
    s_risk = UserFactory.student(full_name="At Risk Student")
    s_ok = UserFactory.student(full_name="Good Standing Student")
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s_risk, s_ok])
    sess = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.absent(session=sess, student=s_risk)
    AttendanceFactory.present(session=sess, student=s_ok)

    resp = teacher_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Students who reached the warning threshold" in content
    assert 'id="only-warned"' in content
    assert 'data-warned="1"' in content
    assert 'data-warned="0"' in content
    assert s_risk.full_name in content
    assert s_ok.full_name in content
    assert "At risk" in content
    assert "Normal" in content


@pytest.mark.django_db
def test_tc166_threshold_100_when_none_reached_shows_message(teacher_user, teacher_client):
    """TC166: When threshold is 100% and no student reached it, report displays no-student-warned message."""
    setting = Setting.get()
    setting.absence_threshold = Decimal("100.00")
    setting.save()

    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    sess1 = SessionFactory.closed(classroom=classroom)
    sess2 = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.absent(session=sess1, student=s1)
    AttendanceFactory.present(session=sess2, student=s1)  # 50% < 100%

    resp = teacher_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    assert "No student has reached the threshold." in resp.content.decode()


# ---------------------------------------------------------------------------
# TC167 - TC175: Student views
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc167_student_enrolled_classrooms_list_and_detail(student_user, student_client):
    """TC167: Student sees only enrolled classrooms in list and detail (other students hidden for privacy)."""
    other_student = UserFactory.student(full_name="Secret Classmate")
    enrolled_class = ClassroomFactory.create(name="EnrolledClass", students=[student_user, other_student])
    other_class = ClassroomFactory.create(name="UnenrolledClass", students=[other_student])

    list_resp = student_client.get(reverse("classroom_list"))
    assert list_resp.status_code == 200
    list_html = list_resp.content.decode()
    assert enrolled_class.name in list_html
    assert other_class.name not in list_html

    detail_resp = student_client.get(reverse("classroom_detail", args=[enrolled_class.pk]))
    assert detail_resp.status_code == 200
    detail_html = detail_resp.content.decode()
    assert enrolled_class.name in detail_html
    assert other_student.full_name not in detail_html


@pytest.mark.django_db
def test_tc168_student_in_no_classroom_shows_empty_message(student_client):
    """TC168: Student enrolled in 0 classrooms sees empty classroom list message."""
    ClassroomFactory.create(name="SomeoneElsesClass")

    resp = student_client.get(reverse("classroom_list"))
    assert resp.status_code == 200
    assert "There is no classroom to display." in resp.content.decode()


@pytest.mark.django_db
def test_tc169_student_classroom_with_no_session_shows_empty_message(student_user, student_client):
    """TC169: Enrolled Student viewing a classroom with no sessions sees empty session message."""
    classroom = ClassroomFactory.create(students=[student_user])

    resp = student_client.get(reverse("classroom_detail", args=[classroom.pk]))
    assert resp.status_code == 200
    assert "This classroom has no session." in resp.content.decode()


@pytest.mark.django_db
def test_tc170_student_own_attendance_history_and_unenrolled_returns_403(student_user, student_client):
    """TC170: Student views own attendance history in enrolled classroom; unenrolled classroom returns 403."""
    enrolled = ClassroomFactory.create(students=[student_user])
    unenrolled = ClassroomFactory.create()
    sess = SessionFactory.closed(classroom=enrolled, room="R-HIST")
    AttendanceFactory.present(session=sess, student=student_user)

    ok_resp = student_client.get(reverse("classroom_attendance_report", args=[enrolled.pk]))
    assert ok_resp.status_code == 200
    content = ok_resp.content.decode()
    assert "My attendance" in content
    assert "R-HIST" in content

    assert student_client.get(reverse("classroom_attendance_report", args=[unenrolled.pk])).status_code == 403
    assert student_client.get(reverse("classroom_detail", args=[unenrolled.pk])).status_code == 403


@pytest.mark.django_db
def test_tc171_student_own_attendance_with_warning(student_user, student_client):
    """TC171: Student with absence rate >= threshold sees Absence warning alert."""
    classroom = ClassroomFactory.create(students=[student_user])
    sess1 = SessionFactory.closed(classroom=classroom)
    sess2 = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.absent(session=sess1, student=student_user)
    AttendanceFactory.present(session=sess2, student=student_user)  # 50% >= 20%

    resp = student_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Absence warning" in content
    assert "50%" in content


@pytest.mark.django_db
def test_tc172_student_own_attendance_without_warning(student_user, student_client):
    """TC172: Student with absence rate < threshold sees Good standing message."""
    classroom = ClassroomFactory.create(students=[student_user])
    sess1 = SessionFactory.closed(classroom=classroom)
    sess2 = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.present(session=sess1, student=student_user)
    AttendanceFactory.late(session=sess2, student=student_user)  # 0% < 20%

    resp = student_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Good standing" in content
    assert "Absence warning" not in content


@pytest.mark.django_db
def test_tc173_student_no_attendance_history_yet(student_user, student_client):
    """TC173: Student with no attendance records yet sees empty history message."""
    classroom = ClassroomFactory.create(students=[student_user])

    resp = student_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    assert "No attendance records yet." in resp.content.decode()


@pytest.mark.django_db
def test_tc174_student_classroom_with_no_closed_session_shows_0_percent_no_warning(
    student_user, student_client
):
    """TC174: Classroom with no Closed session shows 0% absence rate and no warning."""
    classroom = ClassroomFactory.create(students=[student_user])
    SessionFactory.scheduled(classroom=classroom)
    SessionFactory.open(classroom=classroom)

    summary = get_student_classroom_summary(student_user.student_profile, classroom)
    assert summary["total_sessions"] == 0
    assert summary["absence_rate"] == Decimal("0.00")
    assert summary["is_warned"] is False

    resp = student_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "0%" in content
    assert "Absence warning" not in content
    assert "Good standing" in content


@pytest.mark.django_db
def test_tc175_student_warning_at_exact_threshold_25_vs_25(student_user, student_client):
    """TC175: Absence rate equal to threshold (25% vs 25%) triggers Absence warning."""
    setting = Setting.get()
    setting.absence_threshold = Decimal("25.00")
    setting.save()

    classroom = ClassroomFactory.create(students=[student_user])
    sessions = [SessionFactory.closed(classroom=classroom) for _ in range(4)]
    AttendanceFactory.absent(session=sessions[0], student=student_user)
    for sess in sessions[1:]:
        AttendanceFactory.present(session=sess, student=student_user)

    summary = get_student_classroom_summary(student_user.student_profile, classroom)
    assert summary["absence_rate"] == Decimal("25.00")
    assert summary["is_warned"] is True

    resp = student_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Absence warning" in content
    assert "25%" in content


# ---------------------------------------------------------------------------
# TC176 - TC179: Export report
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc176_export_csv_permissions_and_content(
    admin_client, teacher_user, teacher_client, student_user, student_client, make_authenticated_client
):
    """TC176: CSV export allowed for Admin and assigned Teacher (200 text/csv); other Teacher & Student get 403."""
    other_teacher = UserFactory.teacher()
    other_teacher_client = make_authenticated_client(other_teacher)

    classroom = ClassroomFactory.create(teacher=teacher_user, students=[student_user])
    sess = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.present(session=sess, student=student_user)

    url = reverse("export_attendance_csv", args=[classroom.pk])

    for allowed_client in (admin_client, teacher_client):
        resp = allowed_client.get(url)
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/csv")
        assert f'attachment; filename="attendance_{classroom.class_id}.csv"' == resp["Content-Disposition"]
        rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
        assert rows[0][:2] == ["Student ID", "Full Name"]
        assert rows[1][0] == student_user.student_profile.student_id
        assert rows[1][-1] == "OK"

    assert other_teacher_client.get(url).status_code == 403
    assert student_client.get(url).status_code == 403


@pytest.mark.django_db
def test_tc177_export_excel_and_pdf_report(admin_client):
    """TC177: Export classroom attendance report as Excel (.xlsx) and PDF."""
    student = UserFactory.student()
    classroom = ClassroomFactory.create(students=[student])
    sess = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.present(session=sess, student=student)

    xlsx_resp = admin_client.get(reverse("export_attendance_excel", args=[classroom.pk]))
    assert xlsx_resp.status_code == 200
    assert "spreadsheetml" in xlsx_resp["Content-Type"]

    pdf_resp = admin_client.get(reverse("export_attendance_pdf", args=[classroom.pk]))
    assert pdf_resp.status_code == 200
    assert "application/pdf" in pdf_resp["Content-Type"]


@pytest.mark.django_db
def test_tc178_export_no_students_or_no_closed_sessions_shows_no_data_message(
    teacher_user, teacher_client
):
    """TC178: Exporting when classroom has no enrolled students or no Closed sessions shows no-data message."""
    c_no_students = ClassroomFactory.create(teacher=teacher_user)
    resp1 = teacher_client.get(reverse("export_attendance_csv", args=[c_no_students.pk]), follow=True)
    assert resp1["Content-Type"].startswith("text/html")
    assert "no" in resp1.content.decode().lower()

    s1 = UserFactory.student()
    c_no_closed = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    resp2 = teacher_client.get(reverse("export_attendance_csv", args=[c_no_closed.pk]), follow=True)
    assert resp2["Content-Type"].startswith("text/html")
    assert "no" in resp2.content.decode().lower()


@pytest.mark.django_db
def test_tc179_mocked_export_failure_shows_error_message_without_crashing(
    teacher_user, teacher_client
):
    """TC179: Simulated export failure shows an error message gracefully without crashing (no 500)."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    sess = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.present(session=sess, student=s1)

    with patch(
        "attendance.views_attendance.get_classroom_attendance_report",
        side_effect=RuntimeError("Disk full"),
    ):
        resp = teacher_client.get(
            reverse("export_attendance_csv", args=[classroom.pk]),
            follow=True,
        )
    assert resp.status_code == 200
    assert "error" in resp.content.decode().lower()
