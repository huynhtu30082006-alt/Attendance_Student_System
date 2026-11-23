"""GUI Usability, Accessibility, and Development Standards tests (TC180-TC185, TC223-TC230).

Covers:
- TC180-TC181: Attendance status clarity (text label + icon/badge, not colour alone)
- TC182: Confirmation steps for all destructive actions
- TC183-TC184: Role-based navigation efficiency & consistent base template/layout
- TC185, TC227, TC229, TC230: Manual usability / process inspection stubs (skipped)
- TC223-TC226, TC228: Development standards (Python/Django/syntax, MVC separation,
                      PostgreSQL config, Dockerfile/docker-compose, pytest scripts).
"""
import ast
import shutil
import subprocess
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from attendance.models import AttendanceStatus
from tests.factories import (
    AttendanceFactory,
    ClassroomFactory,
    CourseFactory,
    SessionFactory,
    UserFactory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = REPO_ROOT / "source"
TEMPLATES_DIR = SOURCE_DIR / "templates"


# ===========================================================================
# TC180-TC182: Attendance Status Clarity & Destructive Action Confirmations
# ===========================================================================

@pytest.mark.django_db
def test_tc180_attendance_status_clarity_take_attendance_and_report(admin_client):
    """TC180: Attendance statuses display text labels + icons/badges (not colour alone)
    on take-attendance and classroom report pages."""
    s1 = UserFactory.student()
    s2 = UserFactory.student()
    s3 = UserFactory.student()
    classroom = ClassroomFactory.create(students=[s1, s2, s3])

    # 1. Take-attendance page (OPEN session)
    open_session = SessionFactory.open(classroom=classroom)
    resp_take = admin_client.get(reverse("take_attendance", args=[open_session.pk]))
    assert resp_take.status_code == 200
    take_html = resp_take.content.decode("utf-8")
    for icon, label in [
        ("bi-check-circle-fill", "Present"),
        ("bi-clock-fill", "Late"),
        ("bi-x-circle-fill", "Absent"),
    ]:
        assert icon in take_html
        assert label in take_html

    # 2. Classroom attendance report page (CLOSED session with all 3 statuses)
    closed_session = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.present(session=closed_session, student=s1)
    AttendanceFactory.late(session=closed_session, student=s2)
    AttendanceFactory.absent(session=closed_session, student=s3)

    resp_report = admin_client.get(
        reverse("classroom_attendance_report", args=[classroom.pk])
    )
    assert resp_report.status_code == 200
    report_html = resp_report.content.decode("utf-8")
    assert "status-badge" in report_html
    for icon, label in [
        ("bi-check-circle-fill", "Present"),
        ("bi-clock-fill", "Late"),
        ("bi-x-circle-fill", "Absent"),
    ]:
        assert icon in report_html
        assert label in report_html
    assert "visually-hidden" in report_html


@pytest.mark.django_db
def test_tc181_attendance_status_clarity_student_page_and_session_records(
    make_authenticated_client,
):
    """TC181: Student attendance page and session_records template show text + icon badges."""
    student = UserFactory.student()
    classroom = ClassroomFactory.create(students=[student])
    s1 = SessionFactory.closed(classroom=classroom)
    s2 = SessionFactory.closed(classroom=classroom)
    s3 = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.present(session=s1, student=student)
    AttendanceFactory.late(session=s2, student=student)
    AttendanceFactory.absent(session=s3, student=student)

    student_client = make_authenticated_client(student)
    resp = student_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")
    assert "status-badge" in html
    for icon, label in [
        ("bi-check-circle-fill", "Present"),
        ("bi-clock-fill", "Late"),
        ("bi-x-circle-fill", "Absent"),
    ]:
        assert icon in html
        assert label in html

    # Verify session_records.html template also uses status_badge.html + icon tiles
    session_records_tpl = (TEMPLATES_DIR / "attendance" / "session_records.html").read_text(
        encoding="utf-8"
    )
    assert "components/status_badge.html" in session_records_tpl
    assert "bi-check-circle-fill" in session_records_tpl
    assert "bi-clock-fill" in session_records_tpl
    assert "bi-x-circle-fill" in session_records_tpl


@pytest.mark.django_db
def test_tc182_confirmation_steps_for_destructive_actions(admin_client):
    """TC182: Confirmation modal/page exists for lock, delete course/classroom,
    remove student, cancel session, and close session."""
    target_user = UserFactory.student()
    empty_course = CourseFactory.create()
    course = CourseFactory.create()
    classroom = ClassroomFactory.create(course=course, students=[target_user])
    scheduled_session = SessionFactory.scheduled(classroom=classroom)
    open_session = SessionFactory.open(classroom=classroom)

    # 1. Lock account: modal trigger on user_detail + GET confirm page
    html_user = admin_client.get(reverse("user_detail", args=[target_user.pk])).content.decode()
    assert f'data-confirm-url="{reverse("user_lock", args=[target_user.pk])}"' in html_user
    resp_lock_get = admin_client.get(reverse("user_lock", args=[target_user.pk]))
    assert resp_lock_get.status_code == 200
    assert "Lock account" in resp_lock_get.content.decode()

    # 2. Delete course: modal trigger on course_detail + GET confirm page
    html_course = admin_client.get(reverse("course_detail", args=[empty_course.pk])).content.decode()
    assert f'data-confirm-url="{reverse("course_delete", args=[empty_course.pk])}"' in html_course
    resp_c_del = admin_client.get(reverse("course_delete", args=[empty_course.pk]))
    assert resp_c_del.status_code == 200
    assert "Delete course" in resp_c_del.content.decode()

    # 3. Delete classroom, remove student, cancel session on classroom_detail + GET confirm pages
    html_cls = admin_client.get(reverse("classroom_detail", args=[classroom.pk])).content.decode()
    assert f'data-confirm-url="{reverse("classroom_delete", args=[classroom.pk])}"' in html_cls
    assert (
        f'data-confirm-url="{reverse("classroom_remove_student", args=[classroom.pk, target_user.student_id])}"'
        in html_cls
    )
    assert f'data-confirm-url="{reverse("session_cancel", args=[scheduled_session.pk])}"' in html_cls

    for url, title in [
        (reverse("classroom_delete", args=[classroom.pk]), "Delete classroom"),
        (
            reverse("classroom_remove_student", args=[classroom.pk, target_user.student_id]),
            "Remove Student",
        ),
        (reverse("session_cancel", args=[scheduled_session.pk]), "Cancel session"),
    ]:
        resp = admin_client.get(url)
        assert resp.status_code == 200
        assert title in resp.content.decode()

    # 4. Close session: confirmation modal #closeSessionModal on take_attendance
    html_take = admin_client.get(reverse("take_attendance", args=[open_session.pk])).content.decode()
    assert 'data-bs-target="#closeSessionModal"' in html_take
    assert 'id="closeSessionModal"' in html_take


# ===========================================================================
# TC183-TC185: Navigation Efficiency, Consistent Layout, Manual Usability
# ===========================================================================

@pytest.mark.django_db
def test_tc183_navigation_efficiency_role_based_sidebar(
    admin_client, teacher_client, student_client
):
    """TC183: Each role sees direct, role-appropriate navigation links and all resolve 200."""
    admin_html = admin_client.get(reverse("home")).content.decode("utf-8")
    for name in [
        "home",
        "user_list",
        "course_list",
        "classroom_list",
        "session_list",
        "threshold_settings",
    ]:
        url = reverse(name)
        assert f'href="{url}"' in admin_html
        assert admin_client.get(url).status_code == 200

    for role_client in (teacher_client, student_client):
        html = role_client.get(reverse("home")).content.decode("utf-8")
        for allowed in ("home", "classroom_list", "session_list"):
            url = reverse(allowed)
            assert f'href="{url}"' in html
            assert role_client.get(url).status_code == 200
        # Admin-only links must not appear in Teacher/Student sidebar
        for admin_only in ("user_list", "course_list", "threshold_settings"):
            assert f'href="{reverse(admin_only)}"' not in html


@pytest.mark.django_db
def test_tc184_consistent_base_template_across_roles(
    admin_client, teacher_client, student_client
):
    """TC184: Admin, Teacher, and Student pages share consistent base.html shell & layout."""
    pages = [
        (admin_client, reverse("home")),
        (admin_client, reverse("user_list")),
        (admin_client, reverse("course_list")),
        (admin_client, reverse("classroom_list")),
        (admin_client, reverse("session_list")),
        (teacher_client, reverse("home")),
        (teacher_client, reverse("classroom_list")),
        (student_client, reverse("home")),
        (student_client, reverse("classroom_list")),
    ]
    for client, url in pages:
        resp = client.get(url)
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert 'class="app-shell"' in html
        assert 'class="sidebar"' in html
        assert 'class="main"' in html
        assert 'id="confirmModal"' in html
        assert "bootstrap" in html


@pytest.mark.skip(reason="Manual / Process inspection TC")
def test_tc185_manual_usability_walkthrough():
    """TC185: Manual end-to-end usability walkthrough with target users."""


# ===========================================================================
# TC223-TC230: Development Standards & Process Checks
# ===========================================================================

def test_tc223_python_django_requirements_and_code_quality():
    """TC223: Python & Django declared in requirements.txt/settings.py and all app modules parse cleanly."""
    reqs = (SOURCE_DIR / "requirements.txt").read_text(encoding="utf-8")
    assert "Django==" in reqs
    assert "psycopg" in reqs

    assert settings.ROOT_URLCONF == "config.urls"
    assert settings.AUTH_USER_MODEL == "accounts.UserAccount"

    # Verify every Python module under source/ parses with valid Python syntax
    for py_file in SOURCE_DIR.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))

    # Run flake8 if installed in the environment (optional linter check)
    flake8_bin = shutil.which("flake8")
    if flake8_bin:
        res = subprocess.run(
            [flake8_bin, "--select=E9,F63,F7,F82", str(SOURCE_DIR)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, res.stdout + res.stderr


def test_tc224_mvc_separation_across_django_apps():
    """TC224: MVC/MVT separation across accounts, courses, classrooms, and attendance apps."""
    apps = ["accounts", "courses", "classrooms", "attendance"]
    for app in apps:
        assert app in settings.INSTALLED_APPS
        app_dir = SOURCE_DIR / app
        assert (app_dir / "models.py").is_file(), f"Missing models.py in {app}"
        assert (app_dir / "urls.py").is_file(), f"Missing urls.py in {app}"
        assert (app_dir / "forms.py").is_file(), f"Missing forms.py in {app}"
        view_files = list(app_dir.glob("views*.py"))
        assert view_files, f"Missing views module in {app}"
        assert (TEMPLATES_DIR / app).is_dir(), f"Missing templates/{app}/ directory"


def test_tc225_postgresql_config_in_docker_compose_and_settings():
    """TC225: PostgreSQL is configured in both docker-compose.yml and source/config/settings.py."""
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "image: postgres:" in compose
    assert "POSTGRES_DB" in compose
    assert "POSTGRES_USER" in compose
    assert "POSTGRES_PASSWORD" in compose

    prod_settings = (SOURCE_DIR / "config" / "settings.py").read_text(encoding="utf-8")
    assert "django.db.backends.postgresql" in prod_settings


def test_tc226_dockerfile_and_docker_compose_define_db_and_web():
    """TC226: Dockerfile and docker-compose.yml define db and web services cleanly."""
    dockerfile = (SOURCE_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12" in dockerfile
    assert "requirements.txt" in dockerfile
    assert "EXPOSE 8000" in dockerfile

    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "  db:" in compose
    assert "  web:" in compose
    assert "depends_on:" in compose
    assert "postgres_data:" in compose


@pytest.mark.skip(reason="Manual / Process inspection TC")
def test_tc227_github_workflow_process():
    """TC227: GitHub branching, PR review, and commit history process check."""


def test_tc228_pytest_suite_and_config_exist():
    """TC228: Automated pytest configuration, fixtures, factories, and test scripts exist."""
    assert (REPO_ROOT / "pytest.ini").is_file()
    assert (SOURCE_DIR / "tests" / "conftest.py").is_file()
    assert (SOURCE_DIR / "tests" / "factories.py").is_file()
    assert (SOURCE_DIR / "tests" / "test_security_nfr.py").is_file()
    assert (SOURCE_DIR / "tests" / "test_gui_standards.py").is_file()


@pytest.mark.skip(reason="Manual / Process inspection TC")
def test_tc229_github_issues_bug_tracker_process():
    """TC229: GitHub Issues bug tracker / issue lifecycle process check."""


@pytest.mark.skip(reason="Manual / Process inspection TC")
def test_tc230_four_stage_documentation_process():
    """TC230: 4-stage documentation deliverables process check."""
