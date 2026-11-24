"""Shared pytest fixtures for the Attendance Student System test suite.

All database-touching fixtures rely on pytest-django's transactional `db`
fixture so every test starts with a clean database and rolls back automatically.
"""
import pytest
from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.test import Client, override_settings

from tests.factories import (
    AttendanceFactory,
    ClassroomFactory,
    CourseFactory,
    SessionFactory,
    UserFactory,
)


class FastPBKDF2PasswordHasher(PBKDF2PasswordHasher):
    """Test-only PBKDF2 hasher (1 iteration) so 240+ tests run in seconds while still producing pbkdf2_sha256$ hashes."""

    iterations = 1


@pytest.fixture(scope="session", autouse=True)
def _fast_pbkdf2_hasher():
    with override_settings(PASSWORD_HASHERS=["tests.conftest.FastPBKDF2PasswordHasher"]):
        yield


# ---------------------------------------------------------------------------
# Factory fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def user_factory():
    return UserFactory


@pytest.fixture
def course_factory():
    return CourseFactory


@pytest.fixture
def classroom_factory():
    return ClassroomFactory


@pytest.fixture
def session_factory():
    return SessionFactory


@pytest.fixture
def attendance_factory():
    return AttendanceFactory


# ---------------------------------------------------------------------------
# Role user fixtures (each created fresh per test, rolled back after test)
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_user(db):
    return UserFactory.admin()


@pytest.fixture
def teacher_user(db):
    return UserFactory.teacher()


@pytest.fixture
def student_user(db):
    return UserFactory.student()


# ---------------------------------------------------------------------------
# HTTP Client fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def anon_client():
    return Client()


@pytest.fixture
def make_authenticated_client(db):
    def _make(user):
        c = Client()
        c.force_login(user)
        c.user = user
        return c

    return _make


@pytest.fixture
def admin_client(admin_user, make_authenticated_client):
    return make_authenticated_client(admin_user)


@pytest.fixture
def teacher_client(teacher_user, make_authenticated_client):
    return make_authenticated_client(teacher_user)


@pytest.fixture
def student_client(student_user, make_authenticated_client):
    return make_authenticated_client(student_user)
