"""Classroom, teacher assignment, student enrolment, and session tests (TC54–TC55, TC72–TC113)."""
import datetime
import re

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from accounts.models import Role, Student
from attendance.models import AttendanceRecord
from classrooms.models import AttendanceSession, Classroom, Enrollment, SessionStatus
from courses.models import Course
from tests.factories import (
    AttendanceFactory,
    ClassroomFactory,
    CourseFactory,
    SessionFactory,
    UserFactory,
)


def _messages_text(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


# ---------------------------------------------------------------------------
# View Classrooms & Sessions (TC54–TC55)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tc54_view_classrooms_list_and_detail(admin_client):
    """TC54: View Classrooms list and detail shows course, teacher, and enrolled students."""
    course = CourseFactory.create(code="SE201", name="Software Design")
    teacher = UserFactory.teacher(full_name="Prof. Grace Hopper")
    s1 = UserFactory.student(full_name="Alice Nguyen", student_id="SV1001")
    s2 = UserFactory.student(full_name="Bob Tran", student_id="SV1002")
    classroom = ClassroomFactory.create(
        name="SE201-01",
        course=course,
        teacher=teacher,
        students=[s1, s2],
    )

    list_resp = admin_client.get(reverse("classroom_list"))
    assert list_resp.status_code == 200
    list_html = list_resp.content.decode()
    assert "SE201" in list_html
    assert "Software Design" in list_html
    assert "SE201-01" in list_html
    assert "Prof. Grace Hopper" in list_html

    detail_resp = admin_client.get(reverse("classroom_detail", args=[classroom.pk]))
    assert detail_resp.status_code == 200
    detail_html = detail_resp.content.decode()
    assert classroom.class_id in detail_html
    assert "SE201-01" in detail_html
    assert "Prof. Grace Hopper" in detail_html
    assert "SV1001" in detail_html
    assert "Alice Nguyen" in detail_html
    assert "SV1002" in detail_html
    assert "Bob Tran" in detail_html


@pytest.mark.django_db
def test_tc55_view_sessions_list_and_detail(admin_client):
    """TC55: View Sessions list and detail shows classroom, date, time, room, and status."""
    course = CourseFactory.create(code="SE202", name="Software Testing")
    classroom = ClassroomFactory.create(name="SE202-01", course=course)
    session = SessionFactory.scheduled(
        classroom=classroom,
        date=datetime.date(2026, 11, 20),
        start_time=datetime.time(9, 30),
        room="B305",
    )

    list_resp = admin_client.get(reverse("session_list"))
    assert list_resp.status_code == 200
    list_html = list_resp.content.decode()
    assert "SE202" in list_html
    assert "SE202-01" in list_html
    assert "20/11/2026" in list_html
    assert "09:30" in list_html
    assert "B305" in list_html
    assert "Scheduled" in list_html

    detail_resp = admin_client.get(reverse("session_detail", args=[session.pk]))
    assert detail_resp.status_code == 200
    detail_html = detail_resp.content.decode()
    assert "SE202" in detail_html
    assert "Software Testing" in detail_html
    assert "SE202-01" in detail_html
    assert "20/11/2026" in detail_html
    assert "09:30" in detail_html
    assert "B305" in detail_html
    assert "Scheduled" in detail_html


# ---------------------------------------------------------------------------
# Classroom CRUD (TC72–TC85)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tc72_create_classroom_linked_to_course(admin_client):
    """TC72: Create classroom linked to a course generates ID CLxxxx."""
    course = CourseFactory.create(code="CS401", name="Machine Learning")

    resp = admin_client.post(
        reverse("classroom_create"),
        {"name": "ML-Morning", "course": course.pk},
        follow=True,
    )

    assert resp.status_code == 200
    assert "Classroom created." in _messages_text(resp)

    classroom = Classroom.objects.get(name="ML-Morning", course=course)
    assert re.match(r"^CL\d{4}$", classroom.class_id)
    assert resp.redirect_chain == [(reverse("classroom_detail", args=[classroom.pk]), 302)]


@pytest.mark.django_db
def test_tc73_create_classroom_duplicate_name_same_course_fails(admin_client):
    """TC73: Creating a classroom with a duplicate name in the same course fails."""
    course = CourseFactory.create(code="CS402", name="Distributed Systems")
    ClassroomFactory.create(name="DS-01", course=course)

    resp = admin_client.post(
        reverse("classroom_create"),
        {"name": "DS-01", "course": course.pk},
    )

    assert resp.status_code == 200
    assert resp.context["form"].errors
    assert Classroom.objects.filter(course=course, name="DS-01").count() == 1


@pytest.mark.django_db
def test_tc74_create_classroom_without_course_fails(admin_client):
    """TC74: Creating a classroom without selecting a course fails."""
    CourseFactory.create(code="CS403", name="Security")

    resp = admin_client.post(
        reverse("classroom_create"),
        {"name": "SEC-01", "course": ""},
    )

    assert resp.status_code == 200
    assert "course" in resp.context["form"].errors
    assert Classroom.objects.count() == 0


@pytest.mark.django_db
def test_tc75_create_classroom_blank_name_fails(admin_client):
    """TC75: Creating a classroom with a blank/whitespace name fails."""
    course = CourseFactory.create(code="CS404", name="Cloud Computing")

    resp = admin_client.post(
        reverse("classroom_create"),
        {"name": "   ", "course": course.pk},
    )

    assert resp.status_code == 200
    assert "name" in resp.context["form"].errors
    assert "This field is required." in resp.content.decode()
    assert Classroom.objects.count() == 0


@pytest.mark.django_db
def test_tc76_create_classroom_no_course_exists_shows_message(admin_client):
    """TC76: Creating a classroom when no course exists redirects with an error message."""
    assert Course.objects.count() == 0

    resp = admin_client.get(reverse("classroom_create"), follow=True)
    assert resp.status_code == 200
    assert resp.redirect_chain == [(reverse("classroom_list"), 302)]
    assert "Create a course first: a classroom must belong to a course." in _messages_text(resp)
    assert Classroom.objects.count() == 0


@pytest.mark.django_db
def test_tc77_create_classroom_cancel_saves_nothing(admin_client):
    """TC77: Cancel on Create Classroom returns to list without saving anything."""
    CourseFactory.create(code="CS405", name="Graphics")

    get_resp = admin_client.get(reverse("classroom_create"))
    assert get_resp.status_code == 200
    cancel_url = reverse("classroom_list")
    assert f'href="{cancel_url}"' in get_resp.content.decode()
    assert "Cancel" in get_resp.content.decode()

    admin_client.get(cancel_url)
    assert Classroom.objects.count() == 0


@pytest.mark.django_db
def test_tc78_update_classroom_preserves_teacher_and_students(admin_client):
    """TC78: Updating classroom name/course keeps assigned Teacher and enrolled Students intact."""
    course1 = CourseFactory.create(code="CS406", name="Course A")
    course2 = CourseFactory.create(code="CS407", name="Course B")
    teacher = UserFactory.teacher(full_name="Teacher Keep")
    s1 = UserFactory.student(full_name="Student Keep 1")
    s2 = UserFactory.student(full_name="Student Keep 2")
    classroom = ClassroomFactory.create(
        name="Old Name",
        course=course1,
        teacher=teacher,
        students=[s1, s2],
    )

    resp = admin_client.post(
        reverse("classroom_update", args=[classroom.pk]),
        {"name": "New Name", "course": course2.pk},
        follow=True,
    )

    assert resp.status_code == 200
    assert resp.redirect_chain == [(reverse("classroom_detail", args=[classroom.pk]), 302)]
    assert "Classroom updated." in _messages_text(resp)

    classroom.refresh_from_db()
    assert classroom.name == "New Name"
    assert classroom.course == course2
    assert classroom.teacher == teacher.teacher_profile
    enrolled_ids = set(classroom.enrollments.values_list("student_id", flat=True))
    assert enrolled_ids == {s1.student_profile.pk, s2.student_profile.pk}


@pytest.mark.django_db
def test_tc79_update_classroom_blank_name_fails(admin_client):
    """TC79: Updating classroom with blank name fails and keeps original name."""
    classroom = ClassroomFactory.create(name="Valid Class")

    resp = admin_client.post(
        reverse("classroom_update", args=[classroom.pk]),
        {"name": "   ", "course": classroom.course_id},
    )

    assert resp.status_code == 200
    assert "name" in resp.context["form"].errors
    assert "This field is required." in resp.content.decode()
    classroom.refresh_from_db()
    assert classroom.name == "Valid Class"


@pytest.mark.django_db
def test_tc80_update_classroom_cancel_keeps_unchanged(admin_client):
    """TC80: Cancel on Update Classroom leaves the classroom unchanged."""
    course = CourseFactory.create(code="CS408", name="Original Course")
    classroom = ClassroomFactory.create(name="Unchanged Class", course=course)

    get_resp = admin_client.get(reverse("classroom_update", args=[classroom.pk]))
    assert get_resp.status_code == 200
    cancel_url = reverse("classroom_list")
    assert f'href="{cancel_url}"' in get_resp.content.decode()

    admin_client.get(cancel_url)
    classroom.refresh_from_db()
    assert classroom.name == "Unchanged Class"
    assert classroom.course == course


@pytest.mark.django_db
def test_tc81_view_classroom_detail_without_teacher_and_students(admin_client):
    """TC81: Classroom detail with no Teacher and no Students renders empty states without error."""
    classroom = ClassroomFactory.create(name="Empty Room", teacher=None)

    resp = admin_client.get(reverse("classroom_detail", args=[classroom.pk]))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Empty Room" in html
    assert "Not assigned" in html
    assert "No Student is enrolled." in html
    assert "This classroom has no session." in html


@pytest.mark.django_db
def test_tc82_view_classrooms_list_empty(admin_client):
    """TC82: Viewing Classrooms list when no classroom exists shows empty-state message."""
    assert Classroom.objects.count() == 0

    resp = admin_client.get(reverse("classroom_list"))
    assert resp.status_code == 200
    assert "There is no classroom to display." in resp.content.decode()


@pytest.mark.django_db
def test_tc83_cannot_delete_classroom_with_attendance_records(admin_client):
    """TC83: Deleting a classroom that has attendance records is blocked."""
    classroom = ClassroomFactory.create(name="Has Attendance")
    session = SessionFactory.closed(classroom=classroom)
    student = UserFactory.student()
    AttendanceFactory.present(session=session, student=student)

    delete_url = reverse("classroom_delete", args=[classroom.pk])
    detail_url = reverse("classroom_detail", args=[classroom.pk])

    get_resp = admin_client.get(delete_url, follow=True)
    assert get_resp.status_code == 200
    assert get_resp.redirect_chain == [(detail_url, 302)]
    assert (
        "This classroom already has attendance records and cannot be deleted."
        in _messages_text(get_resp)
    )

    post_resp = admin_client.post(delete_url, follow=True)
    assert post_resp.status_code == 200
    assert post_resp.redirect_chain == [(detail_url, 302)]
    assert (
        "This classroom already has attendance records and cannot be deleted."
        in _messages_text(post_resp)
    )
    assert Classroom.objects.filter(pk=classroom.pk).exists()
    assert AttendanceRecord.objects.filter(session=session).exists()


@pytest.mark.django_db
def test_tc84_delete_classroom_without_attendance_records(admin_client):
    """TC84: Deleting a classroom without attendance records removes its enrolments and sessions."""
    course = CourseFactory.create(code="CS409", name="Removable Course")
    student = UserFactory.student()
    classroom = ClassroomFactory.create(name="Removable Class", course=course, students=[student])
    session = SessionFactory.scheduled(classroom=classroom)

    delete_url = reverse("classroom_delete", args=[classroom.pk])
    confirm_resp = admin_client.get(delete_url)
    assert confirm_resp.status_code == 200
    assert f"Delete classroom {classroom}?" in confirm_resp.content.decode()

    post_resp = admin_client.post(delete_url, follow=True)
    assert post_resp.status_code == 200
    assert post_resp.redirect_chain == [(reverse("classroom_list"), 302)]
    assert "Classroom deleted." in _messages_text(post_resp)

    assert not Classroom.objects.filter(pk=classroom.pk).exists()
    assert not Enrollment.objects.filter(classroom_id=classroom.pk).exists()
    assert not AttendanceSession.objects.filter(pk=session.pk).exists()
    # Course and Student accounts themselves remain intact
    assert Course.objects.filter(pk=course.pk).exists()
    assert Student.objects.filter(pk=student.student_profile.pk).exists()


@pytest.mark.django_db
def test_tc85_delete_classroom_cancel_keeps_classroom(admin_client):
    """TC85: Cancelling at Delete Classroom confirmation keeps the classroom."""
    classroom = ClassroomFactory.create(name="Keep Me")
    delete_url = reverse("classroom_delete", args=[classroom.pk])
    detail_url = reverse("classroom_detail", args=[classroom.pk])

    confirm_resp = admin_client.get(delete_url)
    assert confirm_resp.status_code == 200
    assert f'href="{detail_url}"' in confirm_resp.content.decode()

    admin_client.get(detail_url)
    assert Classroom.objects.filter(pk=classroom.pk).exists()


# ---------------------------------------------------------------------------
# Assign Teacher (TC86–TC89, TC92–TC94)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tc86_assign_active_teacher_to_classroom(admin_client):
    """TC86: Assigning an active Teacher to a classroom saves and shows success message."""
    classroom = ClassroomFactory.create(name="No Teacher Yet", teacher=None)
    teacher = UserFactory.teacher(full_name="Active Teacher")

    resp = admin_client.post(
        reverse("classroom_assign_teacher", args=[classroom.pk]),
        {"teacher": teacher.teacher_profile.pk},
        follow=True,
    )

    assert resp.status_code == 200
    assert resp.redirect_chain == [(reverse("classroom_detail", args=[classroom.pk]), 302)]
    assert "Teacher assigned." in _messages_text(resp)

    classroom.refresh_from_db()
    assert classroom.teacher == teacher.teacher_profile


@pytest.mark.django_db
def test_tc87_replace_assigned_teacher_revokes_previous_access(
    admin_client, make_authenticated_client
):
    """TC87: Replacing the assigned Teacher immediately revokes the previous Teacher's access (403)."""
    teacher_old = UserFactory.teacher(full_name="Old Teacher")
    teacher_new = UserFactory.teacher(full_name="New Teacher")
    classroom = ClassroomFactory.create(name="Swapped Class", teacher=teacher_old)

    old_client = make_authenticated_client(teacher_old)
    new_client = make_authenticated_client(teacher_new)
    detail_url = reverse("classroom_detail", args=[classroom.pk])

    assert old_client.get(detail_url).status_code == 200
    assert new_client.get(detail_url).status_code == 403

    resp = admin_client.post(
        reverse("classroom_assign_teacher", args=[classroom.pk]),
        {"teacher": teacher_new.teacher_profile.pk},
        follow=True,
    )
    assert resp.status_code == 200
    assert "Teacher assigned." in _messages_text(resp)

    classroom.refresh_from_db()
    assert classroom.teacher == teacher_new.teacher_profile
    assert old_client.get(detail_url).status_code == 403
    assert new_client.get(detail_url).status_code == 200


@pytest.mark.django_db
def test_tc88_reject_assigning_locked_teacher(admin_client):
    """TC88: Locked Teacher is not offered in form and a crafted POST is rejected."""
    classroom = ClassroomFactory.create(name="Active Only", teacher=None)
    active_teacher = UserFactory.teacher(full_name="Active Prof")
    locked_teacher = UserFactory.locked(role=Role.TEACHER, full_name="Locked Prof")
    assign_url = reverse("classroom_assign_teacher", args=[classroom.pk])

    get_resp = admin_client.get(assign_url)
    assert get_resp.status_code == 200
    offered_ids = set(
        get_resp.context["form"].fields["teacher"].queryset.values_list("pk", flat=True)
    )
    assert active_teacher.teacher_profile.pk in offered_ids
    assert locked_teacher.teacher_profile.pk not in offered_ids
    assert "Locked Prof" not in get_resp.content.decode()

    post_resp = admin_client.post(assign_url, {"teacher": locked_teacher.teacher_profile.pk})
    assert post_resp.status_code == 200
    assert "teacher" in post_resp.context["form"].errors
    classroom.refresh_from_db()
    assert classroom.teacher is None


@pytest.mark.django_db
def test_tc89_reject_assigning_non_teacher_student(admin_client):
    """TC89: Crafted POST attempting to assign a Student account as Teacher is rejected."""
    classroom = ClassroomFactory.create(name="Teachers Only", teacher=None)
    UserFactory.teacher(full_name="Real Teacher")
    student = UserFactory.student(full_name="Not A Teacher")
    assign_url = reverse("classroom_assign_teacher", args=[classroom.pk])

    resp_profile = admin_client.post(assign_url, {"teacher": student.student_profile.pk})
    assert resp_profile.status_code == 200
    assert "teacher" in resp_profile.context["form"].errors

    resp_user = admin_client.post(assign_url, {"teacher": str(student.pk)})
    assert resp_user.status_code == 200
    assert "teacher" in resp_user.context["form"].errors

    classroom.refresh_from_db()
    assert classroom.teacher is None


@pytest.mark.django_db
def test_tc92_assign_already_assigned_teacher_shows_message(admin_client):
    """TC92: Assigning the already-assigned Teacher shows info message and changes nothing."""
    teacher = UserFactory.teacher(full_name="Current Teacher")
    classroom = ClassroomFactory.create(name="Same Teacher", teacher=teacher)

    resp = admin_client.post(
        reverse("classroom_assign_teacher", args=[classroom.pk]),
        {"teacher": teacher.teacher_profile.pk},
        follow=True,
    )

    assert resp.status_code == 200
    assert resp.redirect_chain == [(reverse("classroom_detail", args=[classroom.pk]), 302)]
    assert "This Teacher is already assigned. Nothing changed." in _messages_text(resp)
    classroom.refresh_from_db()
    assert classroom.teacher == teacher.teacher_profile


@pytest.mark.django_db
def test_tc93_assign_teacher_when_no_active_teacher_exists(admin_client):
    """TC93: Assigning a teacher when no active Teacher exists redirects with error message."""
    classroom = ClassroomFactory.create(name="No Teachers", teacher=None)
    UserFactory.locked(role=Role.TEACHER, full_name="Only Locked Teacher")

    resp = admin_client.get(
        reverse("classroom_assign_teacher", args=[classroom.pk]),
        follow=True,
    )

    assert resp.status_code == 200
    assert resp.redirect_chain == [(reverse("classroom_detail", args=[classroom.pk]), 302)]
    assert "No active Teacher account exists." in _messages_text(resp)


@pytest.mark.django_db
def test_tc94_assign_teacher_cancel_keeps_unchanged(admin_client):
    """TC94: Cancel on Assign Teacher keeps the currently assigned Teacher unchanged."""
    teacher1 = UserFactory.teacher(full_name="Original Teacher")
    UserFactory.teacher(full_name="Other Teacher")
    classroom = ClassroomFactory.create(name="Keep Teacher", teacher=teacher1)

    get_resp = admin_client.get(reverse("classroom_assign_teacher", args=[classroom.pk]))
    assert get_resp.status_code == 200
    cancel_url = reverse("classroom_list")
    assert f'href="{cancel_url}"' in get_resp.content.decode()
    assert "Cancel" in get_resp.content.decode()

    admin_client.get(cancel_url)
    classroom.refresh_from_db()
    assert classroom.teacher == teacher1.teacher_profile


# ---------------------------------------------------------------------------
# Enrol & Remove Students (TC90–TC91, TC95–TC99)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tc90_enrol_multiple_students(admin_client):
    """TC90: Enrolling multiple students in a classroom succeeds in one request."""
    classroom = ClassroomFactory.create(name="Multi Enrol")
    s1 = UserFactory.student(full_name="Student A")
    s2 = UserFactory.student(full_name="Student B")
    s3 = UserFactory.student(full_name="Student C")

    resp = admin_client.post(
        reverse("classroom_add_students", args=[classroom.pk]),
        {
            "students": [
                s1.student_profile.pk,
                s2.student_profile.pk,
                s3.student_profile.pk,
            ]
        },
        follow=True,
    )

    assert resp.status_code == 200
    assert resp.redirect_chain == [(reverse("classroom_detail", args=[classroom.pk]), 302)]
    assert "Students added to the classroom." in _messages_text(resp)

    enrolled_ids = set(classroom.enrollments.values_list("student_id", flat=True))
    assert enrolled_ids == {
        s1.student_profile.pk,
        s2.student_profile.pk,
        s3.student_profile.pk,
    }


@pytest.mark.django_db
def test_tc91_reject_duplicate_student_enrolment(admin_client):
    """TC91: Already-enrolled student is excluded from form and rejected on crafted POST."""
    s_enrolled = UserFactory.student(full_name="Already In")
    s_available = UserFactory.student(full_name="Not In Yet")
    classroom = ClassroomFactory.create(name="No Dupes", students=[s_enrolled])
    add_url = reverse("classroom_add_students", args=[classroom.pk])

    get_resp = admin_client.get(add_url)
    assert get_resp.status_code == 200
    offered_ids = set(
        get_resp.context["form"].fields["students"].queryset.values_list("pk", flat=True)
    )
    assert s_enrolled.student_profile.pk not in offered_ids
    assert s_available.student_profile.pk in offered_ids

    post_resp = admin_client.post(add_url, {"students": [s_enrolled.student_profile.pk]})
    assert post_resp.status_code == 200
    assert "students" in post_resp.context["form"].errors
    assert classroom.enrollments.count() == 1


@pytest.mark.django_db
def test_tc95_add_student_when_all_already_enrolled(admin_client):
    """TC95: Add Student when every student is already enrolled redirects with error message."""
    s1 = UserFactory.student(full_name="Only Student")
    classroom = ClassroomFactory.create(name="Full Class", students=[s1])

    resp = admin_client.get(
        reverse("classroom_add_students", args=[classroom.pk]),
        follow=True,
    )

    assert resp.status_code == 200
    assert resp.redirect_chain == [(reverse("classroom_detail", args=[classroom.pk]), 302)]
    assert "No Student available: every Student is already enrolled." in _messages_text(resp)


@pytest.mark.django_db
def test_tc96_add_student_cancel_saves_nothing(admin_client):
    """TC96: Cancel on Add Students saves no enrollments."""
    UserFactory.student(full_name="Waiting Student")
    classroom = ClassroomFactory.create(name="Cancel Add")

    get_resp = admin_client.get(reverse("classroom_add_students", args=[classroom.pk]))
    assert get_resp.status_code == 200
    cancel_url = reverse("classroom_list")
    assert f'href="{cancel_url}"' in get_resp.content.decode()
    assert "Cancel" in get_resp.content.decode()

    admin_client.get(cancel_url)
    assert classroom.enrollments.count() == 0


@pytest.mark.django_db
def test_tc97_remove_student_preserves_attendance_records(admin_client):
    """TC97: Removing a student deletes their enrollment but preserves attendance records."""
    student = UserFactory.student(full_name="Leaving Student")
    classroom = ClassroomFactory.create(name="Keep History", students=[student])
    session = SessionFactory.closed(classroom=classroom)
    record = AttendanceFactory.present(session=session, student=student)

    remove_url = reverse(
        "classroom_remove_student",
        args=[classroom.pk, student.student_profile.pk],
    )
    confirm_resp = admin_client.get(remove_url)
    assert confirm_resp.status_code == 200
    assert "Attendance records will be kept." in confirm_resp.content.decode()

    post_resp = admin_client.post(remove_url, follow=True)
    assert post_resp.status_code == 200
    assert post_resp.redirect_chain == [(reverse("classroom_detail", args=[classroom.pk]), 302)]
    assert (
        "Student removed from the classroom (attendance records kept)."
        in _messages_text(post_resp)
    )

    assert not Enrollment.objects.filter(
        classroom=classroom, student=student.student_profile
    ).exists()
    assert AttendanceRecord.objects.filter(pk=record.pk).exists()


@pytest.mark.django_db
def test_tc98_remove_student_cancel_keeps_enrolled(admin_client):
    """TC98: Cancelling at Remove Student confirmation keeps the student enrolled."""
    student = UserFactory.student(full_name="Staying Student")
    classroom = ClassroomFactory.create(name="Cancel Remove", students=[student])
    remove_url = reverse(
        "classroom_remove_student",
        args=[classroom.pk, student.student_profile.pk],
    )
    detail_url = reverse("classroom_detail", args=[classroom.pk])

    confirm_resp = admin_client.get(remove_url)
    assert confirm_resp.status_code == 200
    assert f'href="{detail_url}"' in confirm_resp.content.decode()

    admin_client.get(detail_url)
    assert Enrollment.objects.filter(
        classroom=classroom, student=student.student_profile
    ).exists()


@pytest.mark.django_db
def test_tc99_classroom_with_no_enrolled_students_shows_empty_and_no_remove_button(admin_client):
    """TC99: Classroom with no enrolled students displays empty message and no Remove button."""
    classroom = ClassroomFactory.create(name="Zero Students")

    resp = admin_client.get(reverse("classroom_detail", args=[classroom.pk]))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "No Student is enrolled." in html
    assert "Remove student" not in html
    assert "/remove/" not in html


# ---------------------------------------------------------------------------
# Session CRUD (TC100–TC113)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tc100_create_session_scheduled(admin_client):
    """TC100: Creating a session sets status to Scheduled and redirects to classroom detail."""
    classroom = ClassroomFactory.create(name="Session Class")

    resp = admin_client.post(
        reverse("session_create", args=[classroom.pk]),
        {"date": "2026-11-25", "start_time": "08:30", "room": "C201"},
        follow=True,
    )

    assert resp.status_code == 200
    assert resp.redirect_chain == [(reverse("classroom_detail", args=[classroom.pk]), 302)]
    assert "Session created." in _messages_text(resp)

    session = AttendanceSession.objects.get(
        classroom=classroom,
        date=datetime.date(2026, 11, 25),
        start_time=datetime.time(8, 30),
    )
    assert session.room == "C201"
    assert session.status == SessionStatus.SCHEDULED


@pytest.mark.django_db
def test_tc101_reject_duplicate_session_same_date_time(admin_client):
    """TC101: Creating a duplicate session at the same date & time in the same classroom fails."""
    classroom = ClassroomFactory.create(name="Slot Conflict")
    SessionFactory.scheduled(
        classroom=classroom,
        date=datetime.date(2026, 11, 26),
        start_time=datetime.time(10, 0),
        room="A101",
    )

    resp = admin_client.post(
        reverse("session_create", args=[classroom.pk]),
        {"date": "2026-11-26", "start_time": "10:00", "room": "B202"},
    )

    assert resp.status_code == 200
    assert (
        "This classroom already has a session at this date and time."
        in resp.content.decode()
    )
    assert AttendanceSession.objects.filter(classroom=classroom).count() == 1


@pytest.mark.django_db
def test_tc102_create_session_cancel_saves_nothing(admin_client):
    """TC102: Cancel on Create Session saves nothing."""
    classroom = ClassroomFactory.create(name="Cancel Session")

    get_resp = admin_client.get(reverse("session_create", args=[classroom.pk]))
    assert get_resp.status_code == 200
    cancel_url = reverse("classroom_list")
    assert f'href="{cancel_url}"' in get_resp.content.decode()
    assert "Cancel" in get_resp.content.decode()

    admin_client.get(cancel_url)
    assert AttendanceSession.objects.filter(classroom=classroom).count() == 0


@pytest.mark.django_db
def test_tc103_update_scheduled_session(admin_client):
    """TC103: Updating a Scheduled session changes date, time, and room while keeping Scheduled."""
    classroom = ClassroomFactory.create(name="Edit Session Class")
    session = SessionFactory.scheduled(
        classroom=classroom,
        date=datetime.date(2026, 11, 27),
        start_time=datetime.time(8, 0),
        room="R101",
    )

    resp = admin_client.post(
        reverse("session_update", args=[session.pk]),
        {"date": "2026-11-28", "start_time": "13:30", "room": "R202"},
        follow=True,
    )

    assert resp.status_code == 200
    assert resp.redirect_chain == [(reverse("classroom_detail", args=[classroom.pk]), 302)]
    assert "Session updated." in _messages_text(resp)

    session.refresh_from_db()
    assert session.date == datetime.date(2026, 11, 28)
    assert session.start_time == datetime.time(13, 30)
    assert session.room == "R202"
    assert session.status == SessionStatus.SCHEDULED


@pytest.mark.django_db
def test_tc104_reject_updating_session_to_conflicting_slot(admin_client):
    """TC104: Updating a Scheduled session to a date/time already taken in the same classroom fails."""
    classroom = ClassroomFactory.create(name="Conflict Update Class")
    SessionFactory.scheduled(
        classroom=classroom,
        date=datetime.date(2026, 12, 1),
        start_time=datetime.time(9, 0),
        room="R101",
    )
    session2 = SessionFactory.scheduled(
        classroom=classroom,
        date=datetime.date(2026, 12, 1),
        start_time=datetime.time(11, 0),
        room="R102",
    )

    resp = admin_client.post(
        reverse("session_update", args=[session2.pk]),
        {"date": "2026-12-01", "start_time": "09:00", "room": "R102"},
    )

    assert resp.status_code == 200
    assert (
        "This classroom already has a session at this date and time."
        in resp.content.decode()
    )
    session2.refresh_from_db()
    assert session2.start_time == datetime.time(11, 0)


@pytest.mark.django_db
def test_tc105_update_session_cancel_keeps_unchanged(admin_client):
    """TC105: Cancel on Update Session leaves the session unchanged."""
    session = SessionFactory.scheduled(
        date=datetime.date(2026, 12, 2),
        start_time=datetime.time(14, 0),
        room="R303",
    )

    get_resp = admin_client.get(reverse("session_update", args=[session.pk]))
    assert get_resp.status_code == 200
    cancel_url = reverse("classroom_list")
    assert f'href="{cancel_url}"' in get_resp.content.decode()

    admin_client.get(cancel_url)
    session.refresh_from_db()
    assert session.date == datetime.date(2026, 12, 2)
    assert session.start_time == datetime.time(14, 0)
    assert session.room == "R303"


@pytest.mark.django_db
def test_tc106_reject_updating_open_session(admin_client):
    """TC106: Updating an Open session is rejected with an error message."""
    session = SessionFactory.open(
        date=datetime.date(2026, 12, 3),
        start_time=datetime.time(8, 0),
        room="R401",
    )
    update_url = reverse("session_update", args=[session.pk])
    detail_url = reverse("classroom_detail", args=[session.classroom_id])

    get_resp = admin_client.get(update_url, follow=True)
    assert get_resp.redirect_chain == [(detail_url, 302)]
    assert "Only Scheduled sessions can be edited or cancelled." in _messages_text(get_resp)

    post_resp = admin_client.post(
        update_url,
        {"date": "2026-12-10", "start_time": "10:00", "room": "R999"},
        follow=True,
    )
    assert post_resp.redirect_chain == [(detail_url, 302)]
    assert "Only Scheduled sessions can be edited or cancelled." in _messages_text(post_resp)
    session.refresh_from_db()
    assert session.room == "R401"
    assert session.status == SessionStatus.OPEN


@pytest.mark.django_db
def test_tc107_reject_updating_closed_session(admin_client):
    """TC107: Updating a Closed session is rejected with an error message."""
    session = SessionFactory.closed(
        date=datetime.date(2026, 12, 4),
        start_time=datetime.time(8, 0),
        room="R402",
    )
    update_url = reverse("session_update", args=[session.pk])
    detail_url = reverse("classroom_detail", args=[session.classroom_id])

    post_resp = admin_client.post(
        update_url,
        {"date": "2026-12-11", "start_time": "10:00", "room": "R999"},
        follow=True,
    )
    assert post_resp.redirect_chain == [(detail_url, 302)]
    assert "Only Scheduled sessions can be edited or cancelled." in _messages_text(post_resp)
    session.refresh_from_db()
    assert session.room == "R402"
    assert session.status == SessionStatus.CLOSED


@pytest.mark.django_db
def test_tc108_reject_updating_cancelled_session(admin_client):
    """TC108: Updating a Cancelled session is rejected with an error message."""
    session = SessionFactory.cancelled(
        date=datetime.date(2026, 12, 5),
        start_time=datetime.time(8, 0),
        room="R403",
    )
    update_url = reverse("session_update", args=[session.pk])
    detail_url = reverse("classroom_detail", args=[session.classroom_id])

    post_resp = admin_client.post(
        update_url,
        {"date": "2026-12-12", "start_time": "10:00", "room": "R999"},
        follow=True,
    )
    assert post_resp.redirect_chain == [(detail_url, 302)]
    assert "Only Scheduled sessions can be edited or cancelled." in _messages_text(post_resp)
    session.refresh_from_db()
    assert session.room == "R403"
    assert session.status == SessionStatus.CANCELLED


@pytest.mark.django_db
def test_tc109_cancel_scheduled_session_with_confirmation(admin_client):
    """TC109: Cancelling a Scheduled session shows confirmation and transitions to Cancelled."""
    session = SessionFactory.scheduled()
    cancel_url = reverse("session_cancel", args=[session.pk])
    detail_url = reverse("classroom_detail", args=[session.classroom_id])

    confirm_resp = admin_client.get(cancel_url)
    assert confirm_resp.status_code == 200
    assert f"Cancel session {session}?" in confirm_resp.content.decode()

    post_resp = admin_client.post(cancel_url, follow=True)
    assert post_resp.status_code == 200
    assert post_resp.redirect_chain == [(detail_url, 302)]
    assert "Session cancelled." in _messages_text(post_resp)

    session.refresh_from_db()
    assert session.status == SessionStatus.CANCELLED


@pytest.mark.django_db
def test_tc110_cancel_scheduled_session_decline_keeps_scheduled(admin_client):
    """TC110: Declining confirmation on Cancel Session keeps status Scheduled."""
    session = SessionFactory.scheduled()
    cancel_url = reverse("session_cancel", args=[session.pk])
    detail_url = reverse("classroom_detail", args=[session.classroom_id])

    confirm_resp = admin_client.get(cancel_url)
    assert confirm_resp.status_code == 200
    assert f'href="{detail_url}"' in confirm_resp.content.decode()

    admin_client.get(detail_url)
    session.refresh_from_db()
    assert session.status == SessionStatus.SCHEDULED


@pytest.mark.django_db
def test_tc111_reject_cancelling_open_session(admin_client):
    """TC111: Cancelling an Open session is rejected with an error message."""
    session = SessionFactory.open()
    cancel_url = reverse("session_cancel", args=[session.pk])
    detail_url = reverse("classroom_detail", args=[session.classroom_id])

    get_resp = admin_client.get(cancel_url, follow=True)
    assert get_resp.redirect_chain == [(detail_url, 302)]
    assert "Only Scheduled sessions can be edited or cancelled." in _messages_text(get_resp)

    post_resp = admin_client.post(cancel_url, follow=True)
    assert post_resp.redirect_chain == [(detail_url, 302)]
    assert "Only Scheduled sessions can be edited or cancelled." in _messages_text(post_resp)
    session.refresh_from_db()
    assert session.status == SessionStatus.OPEN


@pytest.mark.django_db
def test_tc112_reject_cancelling_closed_session(admin_client):
    """TC112: Cancelling a Closed session is rejected with an error message."""
    session = SessionFactory.closed()
    cancel_url = reverse("session_cancel", args=[session.pk])
    detail_url = reverse("classroom_detail", args=[session.classroom_id])

    post_resp = admin_client.post(cancel_url, follow=True)
    assert post_resp.redirect_chain == [(detail_url, 302)]
    assert "Only Scheduled sessions can be edited or cancelled." in _messages_text(post_resp)
    session.refresh_from_db()
    assert session.status == SessionStatus.CLOSED


@pytest.mark.django_db
def test_tc113_reject_cancelling_cancelled_session(admin_client):
    """TC113: Cancelling an already-Cancelled session is rejected with an error message."""
    session = SessionFactory.cancelled()
    cancel_url = reverse("session_cancel", args=[session.pk])
    detail_url = reverse("classroom_detail", args=[session.classroom_id])

    post_resp = admin_client.post(cancel_url, follow=True)
    assert post_resp.redirect_chain == [(detail_url, 302)]
    assert "Only Scheduled sessions can be edited or cancelled." in _messages_text(post_resp)
    session.refresh_from_db()
    assert session.status == SessionStatus.CANCELLED
