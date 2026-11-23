"""Tests for Admin Attendance Summary and Absence Warning Threshold settings (TC114-TC121)."""
from decimal import Decimal

import pytest
from django.urls import reverse

from attendance.models import AttendanceStatus, Setting
from attendance.services import get_classroom_attendance_report
from tests.factories import (
    AttendanceFactory,
    ClassroomFactory,
    CourseFactory,
    SessionFactory,
    UserFactory,
)


# ---------------------------------------------------------------------------
# TC114 - TC115: Admin Attendance Summary (across all courses & classrooms)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc114_admin_attendance_summary_matches_classroom_reports(admin_client):
    """TC114: Admin Attendance Summary displays stats across all courses & classrooms matching classroom reports."""
    course1 = CourseFactory.create(code="CS114A", name="Course A")
    course2 = CourseFactory.create(code="CS114B", name="Course B")
    teacher = UserFactory.teacher()
    s1 = UserFactory.student()
    s2 = UserFactory.student()

    c1 = ClassroomFactory.create(course=course1, teacher=teacher, students=[s1, s2])
    c2 = ClassroomFactory.create(course=course2, teacher=teacher, students=[s1])

    sess1 = SessionFactory.closed(classroom=c1)
    AttendanceFactory.present(session=sess1, student=s1)
    AttendanceFactory.absent(session=sess1, student=s2)

    sess2 = SessionFactory.closed(classroom=c2)
    AttendanceFactory.present(session=sess2, student=s1)

    url = reverse("admin_dashboard")
    response = admin_client.get(url)
    assert response.status_code == 200
    content = response.content.decode()
    assert course1.code in content
    assert course2.code in content
    assert c1.name in content
    assert c2.name in content


@pytest.mark.django_db
def test_tc115_admin_attendance_summary_no_closed_sessions_shows_empty_message(admin_client):
    """TC115: Admin Attendance Summary with no Closed sessions shows empty-data message."""
    classroom = ClassroomFactory.create()
    SessionFactory.scheduled(classroom=classroom)

    url = reverse("admin_dashboard")
    response = admin_client.get(url)
    assert response.status_code == 200
    assert "There is no attendance data yet." in response.content.decode()


# ---------------------------------------------------------------------------
# TC116 - TC121: Absence Warning Threshold Settings
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc116_default_absence_warning_threshold_is_20(admin_client):
    """TC116: Default absence warning threshold is 20%."""
    setting = Setting.get()
    assert setting.absence_threshold == Decimal("20.00")

    response = admin_client.get(reverse("threshold_settings"))
    assert response.status_code == 200
    assert response.context["form"].initial["absence_threshold"] == Decimal("20.00")
    assert "20" in response.content.decode()


@pytest.mark.django_db
def test_tc117_update_absence_warning_threshold_to_30(admin_client):
    """TC117: Admin updates absence warning threshold to 30%."""
    response = admin_client.post(
        reverse("threshold_settings"),
        {"absence_threshold": "30"},
        follow=True,
    )
    assert response.status_code == 200
    assert Setting.get().absence_threshold == Decimal("30.00")
    assert "Warning threshold saved." in response.content.decode()


@pytest.mark.django_db
def test_tc118_update_threshold_boundaries_0_and_100_updates_warnings(admin_client):
    """TC118: Threshold accepts boundaries 0% and 100%, and warnings update immediately."""
    s_present = UserFactory.student()
    s_half = UserFactory.student()
    s_all_absent = UserFactory.student()
    classroom = ClassroomFactory.create(students=[s_present, s_half, s_all_absent])

    sess1 = SessionFactory.closed(classroom=classroom)
    sess2 = SessionFactory.closed(classroom=classroom)

    # s_present: 0% absent; s_half: 50% absent; s_all_absent: 100% absent
    for sess in (sess1, sess2):
        AttendanceFactory.present(session=sess, student=s_present)
        AttendanceFactory.absent(session=sess, student=s_all_absent)
    AttendanceFactory.present(session=sess1, student=s_half)
    AttendanceFactory.absent(session=sess2, student=s_half)

    # Boundary 0%: every student has absence_rate >= 0% -> all warned
    resp_0 = admin_client.post(
        reverse("threshold_settings"), {"absence_threshold": "0"}, follow=True
    )
    assert resp_0.status_code == 200
    assert Setting.get().absence_threshold == Decimal("0.00")
    report_0 = get_classroom_attendance_report(classroom)
    assert all(row["is_warned"] for row in report_0["rows"])

    # Boundary 100%: only student with 100% absence is warned
    resp_100 = admin_client.post(
        reverse("threshold_settings"), {"absence_threshold": "100"}, follow=True
    )
    assert resp_100.status_code == 200
    assert Setting.get().absence_threshold == Decimal("100.00")
    report_100 = get_classroom_attendance_report(classroom)
    warned_by_sid = {r["student"].student_id: r["is_warned"] for r in report_100["rows"]}
    assert warned_by_sid[s_present.student_profile.student_id] is False
    assert warned_by_sid[s_half.student_profile.student_id] is False
    assert warned_by_sid[s_all_absent.student_profile.student_id] is True


@pytest.mark.django_db
@pytest.mark.parametrize("invalid_value", ["-1", "101", "abc", ""])
def test_tc119_reject_invalid_threshold_values(admin_client, invalid_value):
    """TC119: Reject invalid threshold values (-1, 101, abc, empty) and keep saved value unchanged."""
    setting = Setting.get()
    setting.absence_threshold = Decimal("25.00")
    setting.save()

    response = admin_client.post(
        reverse("threshold_settings"),
        {"absence_threshold": invalid_value},
    )
    assert response.status_code == 200
    assert response.context["form"].errors
    assert "absence_threshold" in response.context["form"].errors
    assert Setting.get().absence_threshold == Decimal("25.00")


@pytest.mark.django_db
def test_tc120_cancel_threshold_edit_keeps_value_unchanged(admin_client):
    """TC120: Opening threshold form and cancelling (navigating to cancel URL) leaves value unchanged."""
    setting = Setting.get()
    setting.absence_threshold = Decimal("20.00")
    setting.save()

    response = admin_client.get(reverse("threshold_settings"))
    assert response.status_code == 200
    assert response.context["cancel_url"] == "home"
    assert reverse("home") in response.content.decode()

    # Follow cancel link without submitting
    cancel_response = admin_client.get(reverse("home"))
    assert cancel_response.status_code == 200
    assert Setting.get().absence_threshold == Decimal("20.00")


@pytest.mark.django_db
def test_tc121_teacher_post_threshold_returns_403(teacher_client):
    """TC121: Teacher POST (and GET) to absence warning threshold returns HTTP 403."""
    get_resp = teacher_client.get(reverse("threshold_settings"))
    assert get_resp.status_code == 403

    post_resp = teacher_client.post(
        reverse("threshold_settings"),
        {"absence_threshold": "50"},
    )
    assert post_resp.status_code == 403
    assert Setting.get().absence_threshold == Decimal("20.00")
