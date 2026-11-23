"""Tests for Teacher classroom/session views and Attendance lifecycle flow (TC122-TC156)."""
import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from attendance.models import AttendanceRecord, AttendanceStatus
from attendance.services import close_session, open_session
from classrooms.models import SessionStatus
from tests.factories import (
    AttendanceFactory,
    ClassroomFactory,
    CourseFactory,
    SessionFactory,
    UserFactory,
)


# ---------------------------------------------------------------------------
# TC122 - TC127: Teacher views (classrooms, students, sessions)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc122_teacher_views_only_assigned_classrooms(teacher_user, teacher_client):
    """TC122: Teacher classroom list shows only classrooms assigned to this Teacher."""
    other_teacher = UserFactory.teacher()
    own_class = ClassroomFactory.create(name="OwnClass", teacher=teacher_user)
    other_class = ClassroomFactory.create(name="OtherClass", teacher=other_teacher)
    unassigned_class = ClassroomFactory.create(name="UnassignedClass", teacher=None)

    response = teacher_client.get(reverse("classroom_list"))
    assert response.status_code == 200
    content = response.content.decode()
    assert own_class.name in content
    assert other_class.name not in content
    assert unassigned_class.name not in content


@pytest.mark.django_db
def test_tc123_teacher_classrooms_grouped_by_course(teacher_user, teacher_client):
    """TC123: Teacher classrooms are ordered and grouped by course."""
    course_a = CourseFactory.create(code="AAA101", name="Alpha Course")
    course_b = CourseFactory.create(code="BBB202", name="Beta Course")
    c_b1 = ClassroomFactory.create(name="Beta-1", course=course_b, teacher=teacher_user)
    c_a1 = ClassroomFactory.create(name="Alpha-1", course=course_a, teacher=teacher_user)
    c_a2 = ClassroomFactory.create(name="Alpha-2", course=course_a, teacher=teacher_user)

    response = teacher_client.get(reverse("classroom_list"))
    assert response.status_code == 200
    content = response.content.decode()

    pos_course_a = content.index(f"{course_a.code} - {course_a.name}")
    pos_course_b = content.index(f"{course_b.code} - {course_b.name}")
    pos_a1 = content.index(c_a1.name)
    pos_a2 = content.index(c_a2.name)
    pos_b1 = content.index(c_b1.name)

    assert pos_course_a < pos_a1 < pos_a2 < pos_course_b < pos_b1


@pytest.mark.django_db
def test_tc124_teacher_without_classroom_shows_empty_message(teacher_client):
    """TC124: Teacher with no assigned classrooms sees empty-state message."""
    ClassroomFactory.create(name="SomeoneElsesClass", teacher=UserFactory.teacher())

    response = teacher_client.get(reverse("classroom_list"))
    assert response.status_code == 200
    assert "There is no classroom to display." in response.content.decode()


@pytest.mark.django_db
def test_tc125_classroom_with_no_students_shows_empty_message(teacher_user, teacher_client):
    """TC125: Classroom detail with 0 enrolled students shows no-students message."""
    classroom = ClassroomFactory.create(teacher=teacher_user)

    response = teacher_client.get(reverse("classroom_detail", args=[classroom.pk]))
    assert response.status_code == 200
    assert "No Student is enrolled." in response.content.decode()


@pytest.mark.django_db
def test_tc126_teacher_views_session_schedule_for_assigned_classroom(teacher_user, teacher_client):
    """TC126: Teacher sees session schedule for assigned classroom(s) only."""
    other_teacher = UserFactory.teacher()
    own_class = ClassroomFactory.create(name="MyClass", teacher=teacher_user)
    other_class = ClassroomFactory.create(name="OtherClass", teacher=other_teacher)

    own_session = SessionFactory.scheduled(classroom=own_class, room="ROOM-OWN")
    other_session = SessionFactory.scheduled(classroom=other_class, room="ROOM-OTHER")

    response = teacher_client.get(reverse("session_list"))
    assert response.status_code == 200
    content = response.content.decode()
    assert own_session.room in content
    assert other_session.room not in content

    # Filtered by classroom query param
    filtered = teacher_client.get(reverse("session_list"), {"classroom": own_class.pk})
    assert filtered.status_code == 200
    assert own_session.room in filtered.content.decode()


@pytest.mark.django_db
def test_tc127_classroom_without_session_shows_empty_message(teacher_user, teacher_client):
    """TC127: Classroom with no sessions displays empty session message."""
    classroom = ClassroomFactory.create(teacher=teacher_user)

    detail_resp = teacher_client.get(reverse("classroom_detail", args=[classroom.pk]))
    assert detail_resp.status_code == 200
    assert "This classroom has no session." in detail_resp.content.decode()

    list_resp = teacher_client.get(reverse("session_list"))
    assert list_resp.status_code == 200
    assert "There is no session to display." in list_resp.content.decode()


# ---------------------------------------------------------------------------
# TC128 - TC134: Open session & lifecycle guards
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc128_assigned_teacher_opens_scheduled_session(teacher_user, teacher_client):
    """TC128: Assigned Teacher opens a Scheduled session -> status transitions to Open."""
    classroom = ClassroomFactory.create(teacher=teacher_user)
    session = SessionFactory.scheduled(classroom=classroom)

    response = teacher_client.post(reverse("session_open", args=[session.pk]), follow=True)
    assert response.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.OPEN
    assert "is now OPEN for attendance." in response.content.decode()


@pytest.mark.django_db
def test_tc129_open_session_for_classroom_with_no_enrolled_students(teacher_user, teacher_client):
    """TC129: Opening a session when classroom has 0 enrolled students succeeds and shows empty student list."""
    classroom = ClassroomFactory.create(teacher=teacher_user)
    session = SessionFactory.scheduled(classroom=classroom)

    response = teacher_client.post(reverse("session_open", args=[session.pk]), follow=True)
    assert response.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.OPEN

    take_resp = teacher_client.get(reverse("take_attendance", args=[session.pk]))
    assert take_resp.status_code == 200
    assert "No students are currently enrolled in this classroom." in take_resp.content.decode()


@pytest.mark.django_db
def test_tc130_refuse_opening_already_open_session(teacher_user, teacher_client):
    """TC130: Refuse opening a session that is already Open."""
    classroom = ClassroomFactory.create(teacher=teacher_user)
    session = SessionFactory.open(classroom=classroom)

    response = teacher_client.post(reverse("session_open", args=[session.pk]), follow=True)
    assert response.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.OPEN
    assert "Only a session with status Scheduled can become Open." in response.content.decode()


@pytest.mark.django_db
def test_tc131_refuse_opening_closed_session(teacher_user, teacher_client):
    """TC131: Refuse opening a Closed session."""
    classroom = ClassroomFactory.create(teacher=teacher_user)
    session = SessionFactory.closed(classroom=classroom)

    response = teacher_client.post(reverse("session_open", args=[session.pk]), follow=True)
    assert response.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.CLOSED
    assert "Only a session with status Scheduled can become Open." in response.content.decode()


@pytest.mark.django_db
def test_tc132_refuse_opening_cancelled_session(teacher_user, teacher_client):
    """TC132: Refuse opening a Cancelled session."""
    classroom = ClassroomFactory.create(teacher=teacher_user)
    session = SessionFactory.cancelled(classroom=classroom)

    response = teacher_client.post(reverse("session_open", args=[session.pk]), follow=True)
    assert response.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.CANCELLED
    assert "Only a session with status Scheduled can become Open." in response.content.decode()


@pytest.mark.django_db
def test_tc133_unassigned_teacher_opening_session_returns_403(teacher_client):
    """TC133: Unassigned Teacher attempting to open another Teacher's session gets HTTP 403."""
    other_teacher = UserFactory.teacher()
    classroom = ClassroomFactory.create(teacher=other_teacher)
    session = SessionFactory.scheduled(classroom=classroom)

    response = teacher_client.post(reverse("session_open", args=[session.pk]))
    assert response.status_code == 403
    session.refresh_from_db()
    assert session.status == SessionStatus.SCHEDULED


@pytest.mark.django_db
def test_tc134_session_lifecycle_one_way_closed_cannot_reopen_or_reclose(teacher_user, teacher_client):
    """TC134: Closed session lifecycle is one-way — cannot reopen, re-close, or cancel."""
    classroom = ClassroomFactory.create(teacher=teacher_user)
    session = SessionFactory.closed(classroom=classroom)

    with pytest.raises(ValidationError):
        open_session(session)
    with pytest.raises(ValidationError):
        close_session(session)
    with pytest.raises(ValidationError):
        session.cancel()

    resp = teacher_client.post(reverse("session_open", args=[session.pk]), follow=True)
    assert resp.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.CLOSED


# ---------------------------------------------------------------------------
# TC135 - TC144: Take attendance
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc135_take_attendance_lists_enrolled_students_only(teacher_user, teacher_client):
    """TC135: Take attendance page lists enrolled students only (removed and unenrolled excluded)."""
    s_enrolled = UserFactory.student(full_name="Enrolled Student")
    s_removed = UserFactory.student(full_name="Removed Student")
    s_outsider = UserFactory.student(full_name="Outsider Student")
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s_enrolled, s_removed])
    classroom.remove_student(s_removed.student_profile)
    session = SessionFactory.open(classroom=classroom)

    response = teacher_client.get(reverse("take_attendance", args=[session.pk]))
    assert response.status_code == 200
    content = response.content.decode()
    assert s_enrolled.student_profile.student_id in content
    assert s_removed.student_profile.student_id not in content
    assert s_outsider.student_profile.student_id not in content


@pytest.mark.django_db
def test_tc136_record_present_late_absent(teacher_user, teacher_client):
    """TC136: Record Present, Late, and Absent statuses for enrolled students."""
    s1 = UserFactory.student()
    s2 = UserFactory.student()
    s3 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1, s2, s3])
    session = SessionFactory.open(classroom=classroom)

    response = teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {
            "action": "save",
            f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT,
            f"status_{s2.student_profile.student_id}": AttendanceStatus.LATE,
            f"status_{s3.student_profile.student_id}": AttendanceStatus.ABSENT,
        },
        follow=True,
    )
    assert response.status_code == 200
    assert AttendanceRecord.objects.get(session=session, student=s1.student_profile).status == AttendanceStatus.PRESENT
    assert AttendanceRecord.objects.get(session=session, student=s2.student_profile).status == AttendanceStatus.LATE
    assert AttendanceRecord.objects.get(session=session, student=s3.student_profile).status == AttendanceStatus.ABSENT


@pytest.mark.django_db
def test_tc137_rerecording_replaces_previous_status_single_record(teacher_user, teacher_client):
    """TC137: Re-recording attendance for a student replaces previous status with only 1 record."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    session = SessionFactory.open(classroom=classroom)
    sid = s1.student_profile.student_id

    teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {"action": "save", f"status_{sid}": AttendanceStatus.PRESENT},
    )
    teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {"action": "save", f"status_{sid}": AttendanceStatus.LATE},
    )

    qs = AttendanceRecord.objects.filter(session=session, student=s1.student_profile)
    assert qs.count() == 1
    assert qs.first().status == AttendanceStatus.LATE


@pytest.mark.django_db
def test_tc138_record_for_some_students_only(teacher_user, teacher_client):
    """TC138: Saving attendance for only a subset of students stores only those records and keeps session Open."""
    s1 = UserFactory.student()
    s2 = UserFactory.student()
    s3 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1, s2, s3])
    session = SessionFactory.open(classroom=classroom)

    response = teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {
            "action": "save",
            f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT,
        },
        follow=True,
    )
    assert response.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.OPEN
    assert AttendanceRecord.objects.filter(session=session).count() == 1
    assert AttendanceRecord.objects.filter(session=session, student=s1.student_profile).exists()
    assert not AttendanceRecord.objects.filter(session=session, student=s2.student_profile).exists()
    assert not AttendanceRecord.objects.filter(session=session, student=s3.student_profile).exists()


@pytest.mark.django_db
def test_tc139_leave_without_saving_changes_nothing(teacher_user, teacher_client):
    """TC139: Visiting take attendance page and leaving without POSTing changes nothing."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    session = SessionFactory.open(classroom=classroom)
    AttendanceFactory.present(session=session, student=s1)

    response = teacher_client.get(reverse("take_attendance", args=[session.pk]))
    assert response.status_code == 200
    # Navigate back to session detail without submitting
    back = teacher_client.get(reverse("session_detail", args=[session.pk]))
    assert back.status_code == 200

    record = AttendanceRecord.objects.get(session=session, student=s1.student_profile)
    assert record.status == AttendanceStatus.PRESENT
    assert AttendanceRecord.objects.filter(session=session).count() == 1


@pytest.mark.django_db
def test_tc140_refuse_recording_on_scheduled_session(teacher_user, teacher_client):
    """TC140: Refuse taking attendance on a Scheduled session."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    session = SessionFactory.scheduled(classroom=classroom)

    resp = teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {"action": "save", f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT},
        follow=True,
    )
    assert resp.status_code == 200
    assert "Attendance can only be taken for an OPEN session." in resp.content.decode()
    assert AttendanceRecord.objects.filter(session=session).count() == 0


@pytest.mark.django_db
def test_tc141_refuse_recording_on_closed_session(teacher_user, teacher_client):
    """TC141: Refuse taking attendance via take_attendance on a Closed session."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    session = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.absent(session=session, student=s1)

    resp = teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {"action": "save", f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT},
        follow=True,
    )
    assert resp.status_code == 200
    assert "Attendance can only be taken for an OPEN session." in resp.content.decode()
    assert AttendanceRecord.objects.get(session=session, student=s1.student_profile).status == AttendanceStatus.ABSENT


@pytest.mark.django_db
def test_tc142_refuse_recording_on_cancelled_session(teacher_user, teacher_client):
    """TC142: Refuse taking attendance on a Cancelled session."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    session = SessionFactory.cancelled(classroom=classroom)

    resp = teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {"action": "save", f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT},
        follow=True,
    )
    assert resp.status_code == 200
    assert "Attendance can only be taken for an OPEN session." in resp.content.decode()
    assert AttendanceRecord.objects.filter(session=session).count() == 0


@pytest.mark.django_db
def test_tc143_reject_invalid_status_excused(teacher_user, teacher_client):
    """TC143: Reject invalid attendance status 'EXCUSED'."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    session = SessionFactory.open(classroom=classroom)

    resp = teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {"action": "save", f"status_{s1.student_profile.student_id}": "EXCUSED"},
    )
    assert resp.status_code == 200
    assert "Invalid attendance status: EXCUSED" in resp.content.decode()
    assert AttendanceRecord.objects.filter(session=session).count() == 0


@pytest.mark.django_db
def test_tc144_reject_non_enrolled_student(teacher_user, teacher_client):
    """TC144: Posting attendance for a non-enrolled student does not create a record for them."""
    s_enrolled = UserFactory.student()
    s_outsider = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s_enrolled])
    session = SessionFactory.open(classroom=classroom)

    resp = teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {
            "action": "save",
            f"status_{s_enrolled.student_profile.student_id}": AttendanceStatus.PRESENT,
            f"status_{s_outsider.student_profile.student_id}": AttendanceStatus.PRESENT,
        },
        follow=True,
    )
    assert resp.status_code == 200
    assert AttendanceRecord.objects.filter(session=session, student=s_enrolled.student_profile).exists()
    assert not AttendanceRecord.objects.filter(session=session, student=s_outsider.student_profile).exists()


# ---------------------------------------------------------------------------
# TC145 - TC148: Close session
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc145_close_session_auto_marks_unmarked_absent(teacher_user, teacher_client):
    """TC145: Closing a session auto-marks all unmarked enrolled students as Absent."""
    s1 = UserFactory.student()
    s2 = UserFactory.student()
    s3 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1, s2, s3])
    session = SessionFactory.open(classroom=classroom)

    resp = teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {
            "action": "close",
            f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT,
        },
        follow=True,
    )
    assert resp.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.CLOSED
    assert AttendanceRecord.objects.get(session=session, student=s1.student_profile).status == AttendanceStatus.PRESENT
    assert AttendanceRecord.objects.get(session=session, student=s2.student_profile).status == AttendanceStatus.ABSENT
    assert AttendanceRecord.objects.get(session=session, student=s3.student_profile).status == AttendanceStatus.ABSENT


@pytest.mark.django_db
def test_tc146_close_session_confirmation_dialog_and_close(teacher_user, teacher_client):
    """TC146: Take attendance page includes close confirmation modal listing unmarked students, then closes on confirm."""
    s1 = UserFactory.student()
    s2 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1, s2])
    session = SessionFactory.open(classroom=classroom)

    get_resp = teacher_client.get(reverse("take_attendance", args=[session.pk]))
    assert get_resp.status_code == 200
    html = get_resp.content.decode()
    assert 'id="closeSessionModal"' in html
    assert 'id="close-unmarked-list"' in html
    assert 'value="close"' in html

    close_resp = teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {
            "action": "close",
            f"status_{s1.student_profile.student_id}": AttendanceStatus.LATE,
        },
        follow=True,
    )
    assert close_resp.status_code == 200
    assert close_resp.redirect_chain[-1][0] == reverse("classroom_attendance_report", args=[classroom.pk])
    session.refresh_from_db()
    assert session.status == SessionStatus.CLOSED
    assert AttendanceRecord.objects.get(session=session, student=s2.student_profile).status == AttendanceStatus.ABSENT


@pytest.mark.django_db
def test_tc147_cancel_closing_keeps_session_open(teacher_user, teacher_client):
    """TC147: Cancelling close (Keep editing / not posting action=close) keeps session Open."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    session = SessionFactory.open(classroom=classroom)

    get_resp = teacher_client.get(reverse("take_attendance", args=[session.pk]))
    assert get_resp.status_code == 200
    assert "Keep editing" in get_resp.content.decode()

    # Saving without closing keeps session OPEN
    save_resp = teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {"action": "save", f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT},
        follow=True,
    )
    assert save_resp.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.OPEN


@pytest.mark.django_db
def test_tc148_close_when_all_students_recorded_none_changed_to_absent(teacher_user, teacher_client):
    """TC148: Closing when all enrolled students are already recorded changes none to Absent."""
    s1 = UserFactory.student()
    s2 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1, s2])
    session = SessionFactory.open(classroom=classroom)
    AttendanceFactory.present(session=session, student=s1)
    AttendanceFactory.late(session=session, student=s2)

    resp = teacher_client.post(
        reverse("take_attendance", args=[session.pk]),
        {
            "action": "close",
            f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT,
            f"status_{s2.student_profile.student_id}": AttendanceStatus.LATE,
        },
        follow=True,
    )
    assert resp.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.CLOSED
    assert AttendanceRecord.objects.filter(session=session, status=AttendanceStatus.ABSENT).count() == 0
    assert AttendanceRecord.objects.get(session=session, student=s1.student_profile).status == AttendanceStatus.PRESENT
    assert AttendanceRecord.objects.get(session=session, student=s2.student_profile).status == AttendanceStatus.LATE


# ---------------------------------------------------------------------------
# TC149 - TC153: Update attendance on Closed session
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc149_update_attendance_on_closed_session_absent_to_present(teacher_user, teacher_client):
    """TC149: Change Absent -> Present on a Closed session; session stays Closed."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    session = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.absent(session=session, student=s1)

    url = reverse("session_records", args=[session.pk])
    resp = teacher_client.post(
        url,
        {f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT},
        follow=True,
    )
    assert resp.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.CLOSED
    assert AttendanceRecord.objects.get(session=session, student=s1.student_profile).status == AttendanceStatus.PRESENT


@pytest.mark.django_db
def test_tc150_refuse_closed_session_update_on_scheduled_or_open(teacher_user, teacher_client):
    """TC150: Refuse closed-session attendance update on Scheduled or Open sessions."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    sched = SessionFactory.scheduled(classroom=classroom)
    open_sess = SessionFactory.open(classroom=classroom)

    for sess in (sched, open_sess):
        url = reverse("session_records", args=[sess.pk])
        resp = teacher_client.post(
            url,
            {f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT},
        )
        assert resp.status_code in (302, 400, 403)


@pytest.mark.django_db
def test_tc151_unassigned_teacher_update_closed_session_returns_403(teacher_client):
    """TC151: Unassigned Teacher attempting to update attendance on Closed session gets HTTP 403."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=UserFactory.teacher(), students=[s1])
    session = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.absent(session=session, student=s1)

    url = reverse("session_records", args=[session.pk])
    resp = teacher_client.post(
        url,
        {f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT},
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_tc152_update_closed_session_same_status_makes_no_change(teacher_user, teacher_client):
    """TC152: Submitting the same status on a Closed session makes no change."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    session = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.present(session=session, student=s1)

    url = reverse("session_records", args=[session.pk])
    resp = teacher_client.post(
        url,
        {f"status_{s1.student_profile.student_id}": AttendanceStatus.PRESENT},
        follow=True,
    )
    assert resp.status_code == 200
    assert AttendanceRecord.objects.get(session=session, student=s1.student_profile).status == AttendanceStatus.PRESENT


@pytest.mark.django_db
def test_tc153_cancel_closed_session_update_keeps_unchanged(teacher_user, teacher_client):
    """TC153: Cancelling edit on Closed session keeps existing attendance records unchanged."""
    s1 = UserFactory.student()
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1])
    session = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.absent(session=session, student=s1)

    url = reverse("session_records", args=[session.pk])
    resp = teacher_client.get(url)
    assert resp.status_code == 200
    assert AttendanceRecord.objects.get(session=session, student=s1.student_profile).status == AttendanceStatus.ABSENT


# ---------------------------------------------------------------------------
# TC154 - TC156: View session attendance record
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc154_view_closed_session_attendance_records(teacher_user, teacher_client):
    """TC154: Viewing a Closed session's attendance record displays all students and their statuses."""
    s1 = UserFactory.student(full_name="Alice Present")
    s2 = UserFactory.student(full_name="Bob Absent")
    classroom = ClassroomFactory.create(teacher=teacher_user, students=[s1, s2])
    session = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.present(session=session, student=s1)
    AttendanceFactory.absent(session=session, student=s2)

    url = reverse("session_records", args=[session.pk])
    resp = teacher_client.get(url)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert s1.student_profile.student_id in content
    assert s2.student_profile.student_id in content
    assert "Present" in content
    assert "Absent" in content


@pytest.mark.django_db
def test_tc155_view_scheduled_or_cancelled_session_shows_no_record_message(teacher_user, teacher_client):
    """TC155: Viewing Scheduled or Cancelled session attendance records shows no-record message."""
    classroom = ClassroomFactory.create(teacher=teacher_user)
    sched = SessionFactory.scheduled(classroom=classroom)
    cancelled = SessionFactory.cancelled(classroom=classroom)

    for sess in (sched, cancelled):
        url = reverse("session_records", args=[sess.pk])
        resp = teacher_client.get(url)
        assert resp.status_code == 200
        assert "No attendance records for this session." in resp.content.decode()


@pytest.mark.django_db
def test_tc156_unassigned_teacher_view_session_records_returns_403(teacher_client):
    """TC156: Unassigned Teacher attempting to view another Teacher's session records gets HTTP 403."""
    classroom = ClassroomFactory.create(teacher=UserFactory.teacher())
    session = SessionFactory.closed(classroom=classroom)

    url = reverse("session_records", args=[session.pk])
    resp = teacher_client.get(url)
    assert resp.status_code == 403
