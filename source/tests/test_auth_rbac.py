"""Authentication, session lifecycle, RBAC, and data-privacy tests (TC01-TC19).

Covers:
  - TC01-TC03: Valid login for Admin, Teacher, Student (home page & menu visibility)
  - TC04-TC07: Failed logins (wrong password, unknown username, empty fields, locked account)
  - TC08-TC11: Logout lifecycle (session end, GET 405, data persistence, locked account logout)
  - TC12-TC13: Unauthenticated redirect to login across all protected GET & POST endpoints
  - TC14-TC16: RBAC 403 enforcement (Teacher/Student blocked from Admin & attendance actions)
  - TC17-TC19: Data privacy (URL tampering, unassigned classroom/session, student peer hiding)
"""
import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import AccountStatus, LoginAttempt
from accounts.views import GENERIC_LOGIN_ERROR
from courses.models import Course
from tests.factories import (
    ClassroomFactory,
    CourseFactory,
    SessionFactory,
    UserFactory,
)


# ---------------------------------------------------------------------------
# TC01 - TC03: Valid login per role
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc01_valid_login_admin(anon_client):
    """TC01: Admin logs in -> redirected to home with full Admin navigation menu."""
    admin = UserFactory.admin(username="auth_admin_tc01", full_name="Admin User")

    response = anon_client.post(
        reverse("login"),
        {"username": admin.username, "password": admin.raw_password},
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain == [(reverse("home"), 302)]
    assert response.wsgi_request.user.is_authenticated
    assert response.wsgi_request.user == admin

    content = response.content.decode()
    assert f"Welcome, {admin.full_name}!" in content
    for label in ("Accounts", "Courses", "Classrooms", "Sessions", "Warning threshold"):
        assert label in content
    for url_name in ("user_list", "course_list", "classroom_list", "session_list", "threshold_settings"):
        assert reverse(url_name) in content


@pytest.mark.django_db
def test_tc02_valid_login_teacher(anon_client):
    """TC02: Teacher logs in -> Teacher home page shown without Admin menu items."""
    teacher = UserFactory.teacher(username="auth_teacher_tc02", full_name="Teacher User")

    response = anon_client.post(
        reverse("login"),
        {"username": teacher.username, "password": teacher.raw_password},
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain == [(reverse("home"), 302)]
    assert response.wsgi_request.user.is_authenticated
    assert response.wsgi_request.user == teacher

    content = response.content.decode()
    assert f"Welcome, {teacher.full_name}!" in content
    assert "My classrooms" in content
    assert "Session schedule" in content
    assert reverse("classroom_list") in content
    assert reverse("session_list") in content
    for admin_only in ("Accounts", "Courses", "Warning threshold"):
        assert admin_only not in content
    for admin_url in ("user_list", "course_list", "threshold_settings"):
        assert reverse(admin_url) not in content


@pytest.mark.django_db
def test_tc03_valid_login_student(anon_client):
    """TC03: Student logs in -> Student home page shown without Admin menu items."""
    student = UserFactory.student(username="auth_student_tc03", full_name="Student User")

    response = anon_client.post(
        reverse("login"),
        {"username": student.username, "password": student.raw_password},
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain == [(reverse("home"), 302)]
    assert response.wsgi_request.user.is_authenticated
    assert response.wsgi_request.user == student

    content = response.content.decode()
    assert f"Welcome, {student.full_name}!" in content
    assert "My classrooms" in content
    assert "Session schedule" in content
    assert reverse("classroom_list") in content
    assert reverse("session_list") in content
    for admin_only in ("Accounts", "Courses", "Warning threshold"):
        assert admin_only not in content
    for admin_url in ("user_list", "course_list", "threshold_settings"):
        assert reverse(admin_url) not in content


# ---------------------------------------------------------------------------
# TC04 - TC07: Failed logins
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc04_login_wrong_password(anon_client):
    """TC04: Wrong password -> stays on login, generic error shown, failed attempt logged."""
    user = UserFactory.student(username="auth_tc04")

    response = anon_client.post(
        reverse("login"),
        {"username": user.username, "password": "WrongPassword999!"},
    )

    assert response.status_code == 200
    assert not response.wsgi_request.user.is_authenticated
    assert GENERIC_LOGIN_ERROR in response.content.decode()
    assert LoginAttempt.objects.filter(username=user.username, succeeded=False).count() == 1


@pytest.mark.django_db
def test_tc05_login_nonexistent_username(anon_client):
    """TC05: Non-existent username -> same generic error as wrong password."""
    response = anon_client.post(
        reverse("login"),
        {"username": "no_such_user_tc05", "password": "Password123!"},
    )

    assert response.status_code == 200
    assert not response.wsgi_request.user.is_authenticated
    assert GENERIC_LOGIN_ERROR in response.content.decode()
    assert LoginAttempt.objects.filter(username="no_such_user_tc05", succeeded=False).count() == 1


@pytest.mark.django_db
def test_tc06_login_empty_username_and_password(anon_client):
    """TC06: Empty username & password -> field errors shown, no LoginAttempt recorded."""
    response = anon_client.post(
        reverse("login"),
        {"username": "", "password": ""},
    )

    assert response.status_code == 200
    assert not response.wsgi_request.user.is_authenticated
    form = response.context["form"]
    assert "username" in form.errors
    assert "password" in form.errors
    assert response.context["error"] is None
    assert LoginAttempt.objects.count() == 0


@pytest.mark.django_db
def test_tc07_login_locked_account_denied(anon_client):
    """TC07: Locked account with valid password -> login denied with generic error."""
    locked_user = UserFactory.locked(username="auth_locked_tc07")

    response = anon_client.post(
        reverse("login"),
        {"username": locked_user.username, "password": locked_user.raw_password},
    )

    assert response.status_code == 200
    assert not response.wsgi_request.user.is_authenticated
    assert GENERIC_LOGIN_ERROR in response.content.decode()


# ---------------------------------------------------------------------------
# TC08 - TC11: Logout lifecycle
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc08_logout_ends_session_and_blocks_protected_pages(anon_client):
    """TC08: POST /logout/ ends session, redirects to login, and blocks /users/."""
    admin = UserFactory.admin(username="auth_admin_tc08")
    login_resp = anon_client.post(
        reverse("login"),
        {"username": admin.username, "password": admin.raw_password},
    )
    assert login_resp.status_code == 302
    assert anon_client.get(reverse("user_list")).status_code == 200

    logout_resp = anon_client.post(reverse("logout"))
    assert logout_resp.status_code == 302
    assert logout_resp["Location"] == reverse("login")

    after_logout = anon_client.get(reverse("user_list"))
    assert after_logout.status_code == 302
    assert after_logout["Location"].startswith(reverse("login"))


@pytest.mark.django_db
def test_tc09_logout_via_get_returns_405_and_stays_logged_in(admin_client):
    """TC09: GET /logout/ returns 405 Method Not Allowed and keeps user logged in."""
    resp = admin_client.get(reverse("logout"))
    assert resp.status_code == 405

    home_resp = admin_client.get(reverse("home"))
    assert home_resp.status_code == 200
    assert home_resp.wsgi_request.user.is_authenticated


@pytest.mark.django_db
def test_tc10_data_saved_before_logout_is_preserved(anon_client):
    """TC10: Data saved by user before logout remains persisted after re-login."""
    admin = UserFactory.admin(username="auth_admin_tc10")
    anon_client.post(
        reverse("login"),
        {"username": admin.username, "password": admin.raw_password},
    )

    create_resp = anon_client.post(
        reverse("course_create"),
        {"code": "TC10CS", "name": "Persistence Course"},
    )
    assert create_resp.status_code == 302
    assert Course.objects.filter(code="TC10CS").exists()

    # Log out and log back in
    anon_client.post(reverse("logout"))
    anon_client.post(
        reverse("login"),
        {"username": admin.username, "password": admin.raw_password},
    )

    assert Course.objects.filter(code="TC10CS", name="Persistence Course").exists()
    list_resp = anon_client.get(reverse("course_list"))
    assert list_resp.status_code == 200
    assert "Persistence Course" in list_resp.content.decode()


@pytest.mark.django_db
def test_tc11_logout_when_account_already_locked_redirects_cleanly(anon_client):
    """TC11: POST /logout/ when user's account was already locked redirects cleanly to login."""
    student = UserFactory.student(username="auth_student_tc11")
    anon_client.post(
        reverse("login"),
        {"username": student.username, "password": student.raw_password},
    )

    # Lock account behind the scenes
    student.status = AccountStatus.LOCKED
    student.save(update_fields=["status"])

    logout_resp = anon_client.post(reverse("logout"))
    assert logout_resp.status_code == 302
    assert logout_resp["Location"] == reverse("login")


# ---------------------------------------------------------------------------
# TC12 - TC13: Unauthenticated access redirects to login
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc12_unauthenticated_get_protected_urls_redirect_to_login(anon_client):
    """TC12: Anonymous GET requests to all protected URLs redirect to login."""
    teacher = UserFactory.teacher()
    student = UserFactory.student()
    course = CourseFactory.create()
    classroom = ClassroomFactory.create(course=course, teacher=teacher, students=[student])
    session = SessionFactory.open(classroom=classroom)

    protected_get_urls = [
        reverse("home"),
        # Accounts
        reverse("user_list"),
        reverse("user_create"),
        reverse("user_detail", args=[student.pk]),
        reverse("user_update", args=[student.pk]),
        reverse("user_lock", args=[student.pk]),
        reverse("user_unlock", args=[student.pk]),
        # Courses
        reverse("course_list"),
        reverse("course_create"),
        reverse("course_detail", args=[course.pk]),
        reverse("course_update", args=[course.pk]),
        reverse("course_delete", args=[course.pk]),
        # Classrooms & sessions
        reverse("classroom_list"),
        reverse("classroom_create"),
        reverse("classroom_detail", args=[classroom.pk]),
        reverse("classroom_update", args=[classroom.pk]),
        reverse("classroom_delete", args=[classroom.pk]),
        reverse("classroom_assign_teacher", args=[classroom.pk]),
        reverse("classroom_add_students", args=[classroom.pk]),
        reverse("classroom_remove_student", args=[classroom.pk, student.student_id]),
        reverse("session_create", args=[classroom.pk]),
        reverse("session_list"),
        reverse("session_detail", args=[session.pk]),
        reverse("session_update", args=[session.pk]),
        reverse("session_cancel", args=[session.pk]),
        # Settings, attendance, reports
        reverse("threshold_settings"),
        reverse("take_attendance", args=[session.pk]),
        reverse("classroom_attendance_report", args=[classroom.pk]),
        reverse("export_attendance_csv", args=[classroom.pk]),
    ]

    login_url = reverse("login")
    for url in protected_get_urls:
        resp = anon_client.get(url)
        assert resp.status_code == 302, f"Expected 302 for GET {url}, got {resp.status_code}"
        assert resp["Location"].startswith(login_url), (
            f"Expected redirect to {login_url} for GET {url}, got {resp['Location']}"
        )


@pytest.mark.django_db
def test_tc13_unauthenticated_post_action_endpoints_redirect_to_login(anon_client):
    """TC13: Anonymous POST requests to protected action endpoints redirect to login."""
    teacher = UserFactory.teacher()
    student = UserFactory.student()
    course = CourseFactory.create()
    classroom = ClassroomFactory.create(course=course, teacher=teacher, students=[student])
    scheduled_session = SessionFactory.scheduled(classroom=classroom)
    open_session = SessionFactory.open(classroom=classroom)

    protected_post_urls = [
        # Accounts
        reverse("user_create"),
        reverse("user_update", args=[student.pk]),
        reverse("user_lock", args=[student.pk]),
        reverse("user_unlock", args=[student.pk]),
        # Courses
        reverse("course_create"),
        reverse("course_update", args=[course.pk]),
        reverse("course_delete", args=[course.pk]),
        # Classrooms & sessions
        reverse("classroom_create"),
        reverse("classroom_update", args=[classroom.pk]),
        reverse("classroom_delete", args=[classroom.pk]),
        reverse("classroom_assign_teacher", args=[classroom.pk]),
        reverse("classroom_add_students", args=[classroom.pk]),
        reverse("classroom_remove_student", args=[classroom.pk, student.student_id]),
        reverse("session_create", args=[classroom.pk]),
        reverse("session_update", args=[scheduled_session.pk]),
        reverse("session_cancel", args=[scheduled_session.pk]),
        # Settings & attendance actions
        reverse("threshold_settings"),
        reverse("session_open", args=[scheduled_session.pk]),
        reverse("take_attendance", args=[open_session.pk]),
    ]

    login_url = reverse("login")
    for url in protected_post_urls:
        resp = anon_client.post(url, {})
        assert resp.status_code == 302, f"Expected 302 for POST {url}, got {resp.status_code}"
        assert resp["Location"].startswith(login_url), (
            f"Expected redirect to {login_url} for POST {url}, got {resp['Location']}"
        )


# ---------------------------------------------------------------------------
# TC14 - TC16: RBAC 403 enforcement
# ---------------------------------------------------------------------------
def _admin_only_urls(target_user, course, classroom, session, student_pk):
    return [
        reverse("user_list"),
        reverse("user_create"),
        reverse("user_detail", args=[target_user.pk]),
        reverse("user_update", args=[target_user.pk]),
        reverse("user_lock", args=[target_user.pk]),
        reverse("user_unlock", args=[target_user.pk]),
        reverse("course_list"),
        reverse("course_create"),
        reverse("course_detail", args=[course.pk]),
        reverse("course_update", args=[course.pk]),
        reverse("course_delete", args=[course.pk]),
        reverse("classroom_create"),
        reverse("classroom_update", args=[classroom.pk]),
        reverse("classroom_delete", args=[classroom.pk]),
        reverse("classroom_assign_teacher", args=[classroom.pk]),
        reverse("classroom_add_students", args=[classroom.pk]),
        reverse("classroom_remove_student", args=[classroom.pk, student_pk]),
        reverse("session_create", args=[classroom.pk]),
        reverse("session_update", args=[session.pk]),
        reverse("session_cancel", args=[session.pk]),
        reverse("threshold_settings"),
    ]


@pytest.mark.django_db
def test_tc14_rbac_teacher_cannot_open_admin_urls(teacher_client, teacher_user):
    """TC14: Teacher receives 403 Forbidden on all Admin-only URLs."""
    student = UserFactory.student()
    course = CourseFactory.create()
    classroom = ClassroomFactory.create(course=course, teacher=teacher_user, students=[student])
    session = SessionFactory.scheduled(classroom=classroom)

    for url in _admin_only_urls(student, course, classroom, session, student.student_id):
        resp = teacher_client.get(url)
        assert resp.status_code == 403, f"Expected 403 for Teacher GET {url}, got {resp.status_code}"


@pytest.mark.django_db
def test_tc15_rbac_student_cannot_open_admin_urls(student_client, student_user):
    """TC15: Student receives 403 Forbidden on all Admin-only URLs and CSV export."""
    teacher = UserFactory.teacher()
    course = CourseFactory.create()
    classroom = ClassroomFactory.create(course=course, teacher=teacher, students=[student_user])
    session = SessionFactory.scheduled(classroom=classroom)

    urls = _admin_only_urls(student_user, course, classroom, session, student_user.student_id)
    urls.append(reverse("export_attendance_csv", args=[classroom.pk]))

    for url in urls:
        resp = student_client.get(url)
        assert resp.status_code == 403, f"Expected 403 for Student GET {url}, got {resp.status_code}"


@pytest.mark.django_db
def test_tc16_rbac_student_cannot_open_session_or_take_attendance(student_client, student_user):
    """TC16: Student receives 403 when attempting to open a session or take attendance."""
    teacher = UserFactory.teacher()
    classroom = ClassroomFactory.create(teacher=teacher, students=[student_user])
    scheduled_session = SessionFactory.scheduled(classroom=classroom)
    open_session = SessionFactory.open(classroom=classroom)

    resp_open = student_client.post(reverse("session_open", args=[scheduled_session.pk]))
    assert resp_open.status_code == 403

    resp_take_get = student_client.get(reverse("take_attendance", args=[open_session.pk]))
    assert resp_take_get.status_code == 403

    resp_take_post = student_client.post(
        reverse("take_attendance", args=[open_session.pk]),
        {f"status_{student_user.student_id}": "PRESENT", "action": "save"},
    )
    assert resp_take_post.status_code == 403


# ---------------------------------------------------------------------------
# TC17 - TC19: Data privacy & row-level isolation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc17_student_url_tampering_returns_403(student_client, student_user):
    """TC17: Student tampering URLs (other classroom, non-existent classroom, other session) -> 403."""
    other_student = UserFactory.student()
    other_classroom = ClassroomFactory.create(students=[other_student])
    other_session = SessionFactory.scheduled(classroom=other_classroom)

    # Other classroom detail -> 403
    assert student_client.get(reverse("classroom_detail", args=[other_classroom.pk])).status_code == 403
    # Non-existent classroom -> 403 (must not leak 404 existence)
    assert student_client.get(reverse("classroom_detail", args=["CL999999"])).status_code == 403
    # Other classroom's session -> 403
    assert student_client.get(reverse("session_detail", args=[other_session.pk])).status_code == 403
    # Other classroom's attendance report -> 403
    assert (
        student_client.get(reverse("classroom_attendance_report", args=[other_classroom.pk])).status_code
        == 403
    )


@pytest.mark.django_db
def test_tc18_teacher_cannot_open_unassigned_classroom_or_session(teacher_client, teacher_user):
    """TC18: Teacher cannot access unassigned classroom, its sessions, attendance, or reports -> 403."""
    other_teacher = UserFactory.teacher()
    student = UserFactory.student()
    other_classroom = ClassroomFactory.create(teacher=other_teacher, students=[student])
    scheduled_session = SessionFactory.scheduled(classroom=other_classroom)
    open_session = SessionFactory.open(classroom=other_classroom)

    assert teacher_client.get(reverse("classroom_detail", args=[other_classroom.pk])).status_code == 403
    assert teacher_client.get(reverse("classroom_detail", args=["CL999999"])).status_code == 403
    assert teacher_client.get(reverse("session_detail", args=[scheduled_session.pk])).status_code == 403
    assert teacher_client.post(reverse("session_open", args=[scheduled_session.pk])).status_code == 403
    assert teacher_client.get(reverse("take_attendance", args=[open_session.pk])).status_code == 403
    assert (
        teacher_client.post(
            reverse("take_attendance", args=[open_session.pk]),
            {f"status_{student.student_id}": "PRESENT", "action": "save"},
        ).status_code
        == 403
    )
    assert (
        teacher_client.get(reverse("classroom_attendance_report", args=[other_classroom.pk])).status_code
        == 403
    )
    assert (
        teacher_client.get(reverse("export_attendance_csv", args=[other_classroom.pk])).status_code
        == 403
    )


@pytest.mark.django_db
def test_tc19_student_does_not_see_other_students_in_classroom_detail(make_authenticated_client):
    """TC19: Student viewing own classroom detail does not see peer students' names or IDs."""
    student_a = UserFactory.student(
        username="stu_a_tc19", full_name="Alice Private", student_id="SV9101"
    )
    student_b = UserFactory.student(
        username="stu_b_tc19", full_name="Bob SecretPeer", student_id="SV9102"
    )
    classroom = ClassroomFactory.create(students=[student_a, student_b])
    client_a = make_authenticated_client(student_a)

    resp = client_a.get(reverse("classroom_detail", args=[classroom.pk]))
    assert resp.status_code == 200
    assert resp.context["enrollments"] is None

    content = resp.content.decode()
    assert classroom.name in content
    assert "Bob SecretPeer" not in content
    assert "SV9102" not in content
