"""Security, Data Integrity, Performance, and NFR tests (TC186-TC222).

Covers:
- TC186, TC187, TC193, TC198, TC216: Docker Compose / load-test stubs (skipped)
- TC188-TC189: Data integrity (PROTECT FKs, 0 orphan records)
- TC190-TC192: Transaction atomicity & composite PK uniqueness (transaction=True)
- TC194-TC197: Response time, bulk close-session, data retrieval, CSV export performance
- TC199, TC222: Password hashing (pbkdf2_sha256$) & 0 plaintext leaks
- TC200-TC205: Brute-force protection (5 fails / 10 min -> 15 min lockout & edge cases)
- TC206-TC208: Session cookie security, 30-min idle timeout, logout invalidation
- TC209-TC210: SQL injection prevention across login, search, and CRUD forms
- TC211-TC212: XSS prevention across course, student, classroom, and session fields
- TC213-TC215: Clean 404 page, DEBUG=False default, no committed .env / hardcoded secrets
- TC217-TC221: Mandatory fields/uniqueness, attendance data retention, no 500s,
               server-side validation on crafted POSTs, and 0 raw SQL queries.
"""
import datetime
import re
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountStatus, LoginAttempt, Role, Student, Teacher, UserAccount
from accounts.views import GENERIC_LOGIN_ERROR, LOCKOUT_ERROR
from attendance.models import AttendanceRecord, AttendanceStatus
from attendance.services import close_session
from classrooms.models import AttendanceSession, Classroom, Enrollment, SessionStatus
from courses.models import Course
from tests.factories import (
    AttendanceFactory,
    ClassroomFactory,
    CourseFactory,
    SessionFactory,
    UserFactory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = REPO_ROOT / "source"


# ===========================================================================
# TC186-TC187: Docker Compose persistence & auto-restart (live Docker stubs)
# ===========================================================================

@pytest.mark.skip(reason="Requires live Docker Compose / load-test environment")
def test_tc186_docker_compose_db_persistence():
    """TC186: Verify PostgreSQL data persists across docker compose down/up."""


@pytest.mark.skip(reason="Requires live Docker Compose / load-test environment")
def test_tc187_docker_container_auto_restart():
    """TC187: Verify containers auto-restart after unexpected termination."""


# ===========================================================================
# TC188-TC189: Data Integrity (PROTECT FKs & 0 orphan records)
# ===========================================================================

@pytest.mark.django_db
def test_tc188_protect_fk_refuses_deleting_student_with_attendance():
    """TC188: PROTECT FK refuses deleting a Student or UserAccount with attendance records."""
    student_user = UserFactory.student()
    student = student_user.student_profile
    session = SessionFactory.closed()
    record = AttendanceFactory.present(session=session, student=student)

    with pytest.raises(ProtectedError):
        student.delete()

    with pytest.raises(ProtectedError):
        student_user.delete()

    assert Student.objects.filter(pk=student.pk).exists()
    assert AttendanceRecord.objects.filter(session=session, student=student).count() == 1
    assert record.status == AttendanceStatus.PRESENT


@pytest.mark.django_db
def test_tc189_fk_constraints_and_zero_orphan_records():
    """TC189: FK constraints prevent orphans and DB has 0 orphan records across core tables."""
    course = CourseFactory.create()
    teacher = UserFactory.teacher()
    student = UserFactory.student()
    classroom = ClassroomFactory.create(course=course, teacher=teacher, students=[student])
    session = SessionFactory.closed(classroom=classroom)
    AttendanceFactory.absent(session=session, student=student)

    # Course with classrooms cannot be deleted (PROTECT)
    with pytest.raises(ProtectedError):
        course.delete()

    # Session with attendance records cannot be deleted (PROTECT)
    with pytest.raises(ProtectedError):
        session.delete()

    # Classroom with sessions that have attendance records cannot be deleted (PROTECT)
    with pytest.raises(ProtectedError):
        classroom.delete()

    # Verify 0 orphan records
    assert AttendanceRecord.objects.filter(student__isnull=True).count() == 0
    assert AttendanceRecord.objects.filter(session__isnull=True).count() == 0
    assert Enrollment.objects.filter(classroom__isnull=True).count() == 0
    assert Enrollment.objects.filter(student__isnull=True).count() == 0
    assert AttendanceSession.objects.filter(classroom__isnull=True).count() == 0
    assert Classroom.objects.filter(course__isnull=True).count() == 0


# ===========================================================================
# TC190-TC192: Transaction Atomicity & DB Constraints (transaction=True)
# ===========================================================================

@pytest.mark.django_db(transaction=True)
def test_tc190_close_session_atomic_rollback_on_invalid_status(admin_client):
    """TC190: Close Session with 1 valid + 1 invalid status rolls back atomically."""
    s1 = UserFactory.student()
    s2 = UserFactory.student()
    classroom = ClassroomFactory.create(students=[s1, s2])
    session = SessionFactory.open(classroom=classroom)

    # Service-level atomicity check
    with pytest.raises(ValidationError):
        close_session(
            session,
            {
                s1.student_id: AttendanceStatus.PRESENT,
                s2.student_id: "INVALID_STATUS",
            },
        )

    session.refresh_from_db()
    assert session.status == SessionStatus.OPEN
    assert AttendanceRecord.objects.filter(session=session).count() == 0

    # View-level atomicity check
    resp = admin_client.post(
        reverse("take_attendance", args=[session.pk]),
        {
            "action": "close",
            f"status_{s1.student_id}": AttendanceStatus.PRESENT,
            f"status_{s2.student_id}": "EXCUSED",
        },
    )
    assert resp.status_code == 200
    session.refresh_from_db()
    assert session.status == SessionStatus.OPEN
    assert AttendanceRecord.objects.filter(session=session).count() == 0


@pytest.mark.django_db(transaction=True)
def test_tc191_bulk_enrolment_atomic_rollback_on_already_enrolled(admin_client):
    """TC191: Bulk Enrolment with 1 valid + 1 already-enrolled student rolls back atomically."""
    s_existing = UserFactory.student()
    s_new = UserFactory.student()
    classroom = ClassroomFactory.create(students=[s_existing])

    # Atomic bulk_create rolls back completely when one entry violates composite PK
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Enrollment.objects.bulk_create(
                [
                    Enrollment(classroom=classroom, student=s_new.student_profile),
                    Enrollment(classroom=classroom, student=s_existing.student_profile),
                ]
            )

    assert not Enrollment.objects.filter(
        classroom=classroom, student=s_new.student_profile
    ).exists()
    assert Enrollment.objects.filter(classroom=classroom).count() == 1

    # View-level concurrent race condition: s_race gets enrolled between form init & bulk_create
    s_race = UserFactory.student()
    s_other = UserFactory.student()
    orig_bulk_create = Enrollment.objects.bulk_create

    def _inject_race(objs, *args, **kwargs):
        # Simulate another admin enrolling s_race right before bulk_create executes
        Enrollment.objects.create(classroom=classroom, student=s_race.student_profile)
        return orig_bulk_create(objs, *args, **kwargs)

    with patch.object(Enrollment.objects, "bulk_create", side_effect=_inject_race):
        resp = admin_client.post(
            reverse("classroom_add_students", args=[classroom.pk]),
            {"students": [s_other.student_id, s_race.student_id]},
        )

    assert resp.status_code == 302
    # s_other must NOT have been enrolled because the transaction rolled back
    assert not Enrollment.objects.filter(
        classroom=classroom, student=s_other.student_profile
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_tc192_duplicate_attendance_record_rejected_by_db_constraint():
    """TC192: Duplicate AttendanceRecord for same (session, student) rejected by DB constraint."""
    student = UserFactory.student()
    session = SessionFactory.open()
    AttendanceFactory.present(session=session, student=student)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AttendanceRecord.objects.create(
                session=session,
                student=student.student_profile,
                status=AttendanceStatus.LATE,
            )

    assert AttendanceRecord.objects.filter(
        session=session, student=student.student_profile
    ).count() == 1


# ===========================================================================
# TC193-TC198: Performance Checks
# ===========================================================================

@pytest.mark.skip(reason="Requires live Docker Compose / load-test environment")
def test_tc193_ten_minute_load_test():
    """TC193: 10-minute sustained load test under live Docker deployment."""


@pytest.mark.django_db
def test_tc194_normal_response_time_under_2s(admin_client):
    """TC194: Normal page response time <= 2.0 seconds."""
    urls = [
        reverse("home"),
        reverse("user_list"),
        reverse("course_list"),
        reverse("classroom_list"),
        reverse("session_list"),
    ]
    for url in urls:
        start = time.perf_counter()
        resp = admin_client.get(url)
        elapsed = time.perf_counter() - start
        assert resp.status_code == 200
        assert elapsed <= 2.0, f"{url} took {elapsed:.3f}s (> 2.0s)"


@pytest.mark.django_db
def test_tc195_close_session_100_students_under_3s():
    """TC195: Closing a session with 100 enrolled students completes in < 3s with 100 Absent records."""
    classroom = ClassroomFactory.create()
    users = [
        UserAccount(
            username=f"perf195_stu_{i}",
            full_name=f"Perf Student {i}",
            email=f"perf195_{i}@example.com",
            role=Role.STUDENT,
            status=AccountStatus.ACTIVE,
            password="pbkdf2_sha256$1$salt$hash",
        )
        for i in range(100)
    ]
    created_users = UserAccount.objects.bulk_create(users)
    students = Student.objects.bulk_create(
        [Student(student_id=f"P195S{i:03d}", user=u) for i, u in enumerate(created_users)]
    )
    Enrollment.objects.bulk_create(
        [Enrollment(classroom=classroom, student=s) for s in students]
    )
    session = SessionFactory.open(classroom=classroom)

    start = time.perf_counter()
    closed = close_session(session)
    elapsed = time.perf_counter() - start

    assert closed.status == SessionStatus.CLOSED
    assert AttendanceRecord.objects.filter(
        session=session, status=AttendanceStatus.ABSENT
    ).count() == 100
    assert elapsed < 3.0, f"close_session for 100 students took {elapsed:.3f}s (>= 3.0s)"


@pytest.mark.django_db
def test_tc196_data_retrieval_under_3s(admin_client):
    """TC196: Attendance report and user list retrieval <= 3.0 seconds."""
    classroom = ClassroomFactory.create()
    users = UserAccount.objects.bulk_create(
        [
            UserAccount(
                username=f"perf196_stu_{i}",
                full_name=f"Student {i}",
                email=f"perf196_{i}@example.com",
                role=Role.STUDENT,
                status=AccountStatus.ACTIVE,
                password="pbkdf2_sha256$1$salt$hash",
            )
            for i in range(50)
        ]
    )
    students = Student.objects.bulk_create(
        [Student(student_id=f"P196S{i:03d}", user=u) for i, u in enumerate(users)]
    )
    Enrollment.objects.bulk_create(
        [Enrollment(classroom=classroom, student=s) for s in students]
    )
    base_date = datetime.date(2026, 1, 1)
    sessions = AttendanceSession.objects.bulk_create(
        [
            AttendanceSession(
                classroom=classroom,
                date=base_date + datetime.timedelta(days=d),
                start_time=datetime.time(8, 0),
                room="R101",
                status=SessionStatus.CLOSED,
            )
            for d in range(10)
        ]
    )
    AttendanceRecord.objects.bulk_create(
        [
            AttendanceRecord(session=sess, student=stu, status=AttendanceStatus.PRESENT)
            for sess in sessions
            for stu in students
        ]
    )

    start = time.perf_counter()
    resp = admin_client.get(reverse("classroom_attendance_report", args=[classroom.pk]))
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200
    assert elapsed <= 3.0, f"classroom_attendance_report took {elapsed:.3f}s (> 3.0s)"


@pytest.mark.django_db
def test_tc197_report_export_100_students_60_sessions_under_10s(admin_client):
    """TC197: CSV export for 100 students x 60 closed sessions completes in <= 10s."""
    classroom = ClassroomFactory.create()
    users = UserAccount.objects.bulk_create(
        [
            UserAccount(
                username=f"perf197_stu_{i}",
                full_name=f"Export Student {i}",
                email=f"perf197_{i}@example.com",
                role=Role.STUDENT,
                status=AccountStatus.ACTIVE,
                password="pbkdf2_sha256$1$salt$hash",
            )
            for i in range(100)
        ]
    )
    students = Student.objects.bulk_create(
        [Student(student_id=f"P197S{i:03d}", user=u) for i, u in enumerate(users)]
    )
    Enrollment.objects.bulk_create(
        [Enrollment(classroom=classroom, student=s) for s in students]
    )
    base_date = datetime.date(2026, 1, 1)
    sessions = AttendanceSession.objects.bulk_create(
        [
            AttendanceSession(
                classroom=classroom,
                date=base_date + datetime.timedelta(days=d),
                start_time=datetime.time(8, 0),
                room="R201",
                status=SessionStatus.CLOSED,
            )
            for d in range(60)
        ]
    )
    AttendanceRecord.objects.bulk_create(
        [
            AttendanceRecord(
                session=sess,
                student=stu,
                status=AttendanceStatus.ABSENT if idx % 5 == 0 else AttendanceStatus.PRESENT,
            )
            for idx, sess in enumerate(sessions)
            for stu in students
        ]
    )

    start = time.perf_counter()
    resp = admin_client.get(reverse("export_attendance_csv", args=[classroom.pk]))
    elapsed = time.perf_counter() - start

    assert resp.status_code == 200
    assert "text/csv" in resp["Content-Type"]
    lines = resp.content.decode("utf-8").strip().splitlines()
    assert len(lines) == 101  # header + 100 students
    assert elapsed <= 10.0, f"CSV export (100x60) took {elapsed:.3f}s (> 10.0s)"


@pytest.mark.skip(reason="Requires live Docker Compose / load-test environment")
def test_tc198_concurrent_users_load_test():
    """TC198: Multi-user concurrency load test under live Docker deployment."""


# ===========================================================================
# TC199 & TC222: Password Protection
# ===========================================================================

@pytest.mark.django_db
def test_tc199_password_stored_as_salted_pbkdf2_hash():
    """TC199: Passwords are stored as salted pbkdf2_sha256$ hashes, never plaintext."""
    raw = "StrongPass!2026"
    user = UserFactory.student(password=raw)
    stored = UserAccount.objects.values_list("password", flat=True).get(pk=user.pk)

    assert stored.startswith("pbkdf2_sha256$")
    assert raw not in stored
    assert user.salt != ""
    assert user.check_password(raw)

    # Production settings.py must specify PBKDF2PasswordHasher
    prod_settings = (SOURCE_DIR / "config" / "settings.py").read_text(encoding="utf-8")
    assert "PBKDF2PasswordHasher" in prod_settings


@pytest.mark.django_db
def test_tc222_zero_plaintext_passwords_in_db_or_html(admin_client):
    """TC222: 0 plaintext passwords in DB or any rendered HTML response."""
    raw = "UniqueSecretPass!987"
    target = UserFactory.student(password=raw)

    # DB check across all users
    for stored_pw in UserAccount.objects.values_list("password", flat=True):
        assert raw not in stored_pw
        assert stored_pw.startswith("pbkdf2_sha256$")

    # HTML response check across account views
    for url in [
        reverse("user_list"),
        reverse("user_detail", args=[target.pk]),
        reverse("user_update", args=[target.pk]),
        reverse("home"),
    ]:
        resp = admin_client.get(url)
        assert resp.status_code == 200
        assert raw not in resp.content.decode("utf-8")


# ===========================================================================
# TC200-TC205: Brute-Force Protection
# ===========================================================================

@pytest.mark.django_db
def test_tc200_bruteforce_5_fails_in_10_min_locks_out_correct_password(anon_client):
    """TC200: 5 failed logins in 10 min locks out even the correct password."""
    user = UserFactory.student(password="CorrectPass123!")
    login_url = reverse("login")

    for _ in range(5):
        resp = anon_client.post(
            login_url, {"username": user.username, "password": "WrongPassword!"}
        )
        assert resp.status_code == 200
        assert GENERIC_LOGIN_ERROR in resp.content.decode("utf-8")

    # 6th attempt with CORRECT password must be rejected with lockout error
    resp = anon_client.post(
        login_url, {"username": user.username, "password": user.raw_password}
    )
    assert resp.status_code == 200
    assert LOCKOUT_ERROR in resp.content.decode("utf-8")
    assert "_auth_user_id" not in anon_client.session


@pytest.mark.django_db
def test_tc201_bruteforce_4_fails_allows_correct_password(anon_client):
    """TC201: 4 failed logins still allow logging in with the correct password."""
    user = UserFactory.student(password="CorrectPass123!")
    login_url = reverse("login")

    for _ in range(4):
        resp = anon_client.post(
            login_url, {"username": user.username, "password": "WrongPassword!"}
        )
        assert resp.status_code == 200

    resp = anon_client.post(
        login_url, {"username": user.username, "password": user.raw_password}
    )
    assert resp.status_code == 302
    assert resp.url == reverse("home")
    assert "_auth_user_id" in anon_client.session


@pytest.mark.django_db
def test_tc202_bruteforce_recovery_after_15_minutes(anon_client):
    """TC202: Account recovers from brute-force lockout after 15 minutes."""
    user = UserFactory.student(password="CorrectPass123!")
    login_url = reverse("login")

    for _ in range(5):
        anon_client.post(login_url, {"username": user.username, "password": "Wrong!"})

    # Confirm locked right now
    resp_locked = anon_client.post(
        login_url, {"username": user.username, "password": user.raw_password}
    )
    assert LOCKOUT_ERROR in resp_locked.content.decode("utf-8")

    # Shift the 5 failed attempts back by 16 minutes so the 15-min lockout has expired
    past = timezone.now() - timedelta(minutes=16)
    LoginAttempt.objects.filter(username=user.username).update(attempted_at=past)

    resp_ok = anon_client.post(
        login_url, {"username": user.username, "password": user.raw_password}
    )
    assert resp_ok.status_code == 302
    assert resp_ok.url == reverse("home")


@pytest.mark.django_db
def test_tc203_bruteforce_5_failures_outside_10_min_window_do_not_lock(anon_client):
    """TC203: 5 failures spanning > 10 minutes (not all within 10-min window) do not lock."""
    user = UserFactory.student(password="CorrectPass123!")
    now = timezone.now()

    # 1st failure 12 minutes ago, next 4 failures 1 minute ago -> span is 11 min > 10 min
    LoginAttempt.objects.create(
        username=user.username, succeeded=False, attempted_at=now - timedelta(minutes=12)
    )
    for sec in range(4):
        LoginAttempt.objects.create(
            username=user.username,
            succeeded=False,
            attempted_at=now - timedelta(minutes=1, seconds=sec),
        )

    resp = anon_client.post(
        reverse("login"), {"username": user.username, "password": user.raw_password}
    )
    assert resp.status_code == 302
    assert resp.url == reverse("home")


@pytest.mark.django_db
def test_tc204_bruteforce_4_recent_plus_1_more_triggers_lock(anon_client):
    """TC204: 4 recent failures within 10 min + 1 more failure triggers lockout."""
    user = UserFactory.student(password="CorrectPass123!")
    now = timezone.now()
    for m in [8, 6, 4, 2]:
        LoginAttempt.objects.create(
            username=user.username, succeeded=False, attempted_at=now - timedelta(minutes=m)
        )

    # 5th failure within 10-minute window
    resp_fail = anon_client.post(
        reverse("login"), {"username": user.username, "password": "Wrong!"}
    )
    assert resp_fail.status_code == 200

    # Now locked out even with correct password
    resp_locked = anon_client.post(
        reverse("login"), {"username": user.username, "password": user.raw_password}
    )
    assert resp_locked.status_code == 200
    assert LOCKOUT_ERROR in resp_locked.content.decode("utf-8")


@pytest.mark.django_db
def test_tc205_bruteforce_already_locked_rejects_correct_password_without_extending(anon_client):
    """TC205: Already locked username rejects correct password and does not record extra attempt."""
    user = UserFactory.student(password="CorrectPass123!")
    now = timezone.now()
    for sec in range(5):
        LoginAttempt.objects.create(
            username=user.username,
            succeeded=False,
            attempted_at=now - timedelta(seconds=10 - sec),
        )
    before_count = LoginAttempt.objects.filter(username=user.username).count()

    resp = anon_client.post(
        reverse("login"), {"username": user.username, "password": user.raw_password}
    )
    assert resp.status_code == 200
    assert LOCKOUT_ERROR in resp.content.decode("utf-8")
    assert "_auth_user_id" not in anon_client.session
    # Rejected before checking password, so no extra attempt is recorded
    assert LoginAttempt.objects.filter(username=user.username).count() == before_count


# ===========================================================================
# TC206-TC208: Session Management
# ===========================================================================

@pytest.mark.django_db
def test_tc206_session_cookie_security_config(anon_client):
    """TC206: Session cookie configured for 30 min expiry, HttpOnly, SameSite=Lax."""
    assert settings.SESSION_COOKIE_AGE == 30 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST is True
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.CSRF_COOKIE_SAMESITE == "Lax"
    assert settings.X_FRAME_OPTIONS == "DENY"
    assert settings.SECURE_CONTENT_TYPE_NOSNIFF is True

    user = UserFactory.student()
    resp = anon_client.post(
        reverse("login"), {"username": user.username, "password": user.raw_password}
    )
    assert resp.status_code == 302
    cookie = resp.cookies[settings.SESSION_COOKIE_NAME]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert int(cookie["max-age"]) == 1800


@pytest.mark.django_db
def test_tc207_session_idle_timeout_30_min(anon_client):
    """TC207: Session expires after 30 minutes of inactivity."""
    user = UserFactory.student()
    resp = anon_client.post(
        reverse("login"), {"username": user.username, "password": user.raw_password}
    )
    assert resp.status_code == 302
    assert anon_client.get(reverse("home")).status_code == 200

    # Expire the server-side session (simulating > 30 min idle)
    session_key = anon_client.cookies[settings.SESSION_COOKIE_NAME].value
    Session.objects.filter(session_key=session_key).update(
        expire_date=timezone.now() - timedelta(minutes=1)
    )

    resp_after = anon_client.get(reverse("home"))
    assert resp_after.status_code == 302
    assert reverse("login") in resp_after.url


@pytest.mark.django_db
def test_tc208_old_session_cookie_invalid_after_logout(anon_client):
    """TC208: Old session cookie is invalidated server-side immediately after logout."""
    user = UserFactory.student()
    anon_client.post(
        reverse("login"), {"username": user.username, "password": user.raw_password}
    )
    old_session_key = anon_client.cookies[settings.SESSION_COOKIE_NAME].value
    assert Session.objects.filter(session_key=old_session_key).exists()

    logout_resp = anon_client.post(reverse("logout"))
    assert logout_resp.status_code == 302
    assert not Session.objects.filter(session_key=old_session_key).exists()

    # Replaying old session cookie must NOT grant access
    replayed = Client()
    replayed.cookies[settings.SESSION_COOKIE_NAME] = old_session_key
    resp = replayed.get(reverse("home"))
    assert resp.status_code == 302
    assert reverse("login") in resp.url


# ===========================================================================
# TC209-TC210: SQL Injection Prevention
# ===========================================================================

SQLI_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE accounts_useraccount;--",
    '" OR ""="',
]


@pytest.mark.django_db
@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_tc209_sql_injection_login_and_account_search(anon_client, admin_client, payload):
    """TC209: SQLi payloads in login and account search cause no bypass, no 500, no table drop."""
    UserFactory.student()
    before_count = UserAccount.objects.count()

    # Login endpoint
    resp_login = anon_client.post(
        reverse("login"), {"username": payload, "password": payload}
    )
    assert resp_login.status_code == 200
    assert "_auth_user_id" not in anon_client.session

    # Account search endpoint
    resp_search = admin_client.get(reverse("user_list"), {"q": payload})
    assert resp_search.status_code == 200
    assert UserAccount.objects.count() == before_count


@pytest.mark.django_db
@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_tc210_sql_injection_course_classroom_session_forms(admin_client, payload):
    """TC210: SQLi payloads in course, classroom, and session forms cause no 500 or table damage."""
    course = CourseFactory.create()
    classroom = ClassroomFactory.create(course=course)

    # Course create (code regex rejects SQLi cleanly; name is parameterized)
    resp_course = admin_client.post(
        reverse("course_create"), {"code": payload, "name": payload}
    )
    assert resp_course.status_code in (200, 302)

    # Classroom create
    resp_cls = admin_client.post(
        reverse("classroom_create"), {"course": course.pk, "name": payload}
    )
    assert resp_cls.status_code in (200, 302)

    # Session create (room)
    resp_sess = admin_client.post(
        reverse("session_create", args=[classroom.pk]),
        {"date": "2026-12-01", "start_time": "09:00", "room": payload},
    )
    assert resp_sess.status_code in (200, 302)

    # Session list filter
    resp_filter = admin_client.get(reverse("session_list"), {"classroom": payload})
    assert resp_filter.status_code == 200

    # Core tables intact
    assert Course.objects.filter(pk=course.pk).exists()
    assert Classroom.objects.filter(pk=classroom.pk).exists()


# ===========================================================================
# TC211-TC212: XSS Prevention
# ===========================================================================

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
]


@pytest.mark.django_db
@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_tc211_xss_prevention_course_and_student_names(admin_client, payload):
    """TC211: XSS payloads in course name and student full_name are HTML-escaped."""
    course = CourseFactory.create(name=payload)
    student = UserFactory.student(full_name=payload)

    for url in [
        reverse("course_list"),
        reverse("course_detail", args=[course.pk]),
        reverse("user_list"),
        reverse("user_detail", args=[student.pk]),
    ]:
        resp = admin_client.get(url)
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert payload not in html, f"Unescaped XSS payload found in {url}"
        assert "&lt;" in html


@pytest.mark.django_db
@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_tc212_xss_prevention_classroom_and_session_room(admin_client, payload):
    """TC212: XSS payloads in classroom name and session room are HTML-escaped."""
    student = UserFactory.student()
    classroom = ClassroomFactory.create(name=payload, students=[student])
    session = SessionFactory.open(classroom=classroom, room=payload)

    for url in [
        reverse("classroom_list"),
        reverse("classroom_detail", args=[classroom.pk]),
        reverse("session_list"),
        reverse("session_detail", args=[session.pk]),
        reverse("take_attendance", args=[session.pk]),
        reverse("classroom_attendance_report", args=[classroom.pk]),
    ]:
        resp = admin_client.get(url)
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert payload not in html, f"Unescaped XSS payload found in {url}"
        assert "&lt;" in html


# ===========================================================================
# TC213-TC216: Error Handling, DEBUG, Secrets, Docker Smoke
# ===========================================================================

@pytest.mark.django_db
def test_tc213_404_clean_error_page_no_stacktrace_or_secrets(admin_client):
    """TC213: 404 returns a clean error page with no stack trace or secrets."""
    assert settings.DEBUG is False
    for bad_url in ["/this-route-does-not-exist-xyz/", reverse("user_detail", args=[999999])]:
        resp = admin_client.get(bad_url)
        assert resp.status_code == 404
        body = resp.content.decode("utf-8")
        assert "404" in body
        assert "Traceback" not in body
        assert settings.SECRET_KEY not in body
        assert "DJANGO_SECRET_KEY" not in body


def test_tc214_debug_false_default_in_settings():
    """TC214: settings.py defaults DEBUG to False when DJANGO_DEBUG is unset; .env.example exists."""
    settings_text = (SOURCE_DIR / "config" / "settings.py").read_text(encoding="utf-8")
    assert 'DEBUG = os.getenv("DJANGO_DEBUG", "False") == "True"' in settings_text
    assert settings.DEBUG is False
    assert (REPO_ROOT / ".env.example").is_file()


def test_tc215_no_committed_env_or_hardcoded_secrets():
    """TC215: Repo has no committed .env and no hardcoded secrets in production source."""
    # .env must not be tracked by git
    result = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.strip() == "", ".env must not be committed to git"

    # Scan production Python files for hardcoded SECRET_KEY or DB password literals
    secret_pattern = re.compile(
        r"""^\s*(?:SECRET_KEY|DB_PASSWORD)\s*=\s*['"][^'"]{8,}['"]""",
        re.MULTILINE,
    )
    for py_file in SOURCE_DIR.rglob("*.py"):
        rel = py_file.relative_to(SOURCE_DIR)
        if rel.parts[0] == "tests" or py_file.name == "test_settings.py":
            continue
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        assert not secret_pattern.search(text), f"Hardcoded secret found in {rel}"


@pytest.mark.skip(reason="Requires live Docker Compose / load-test environment")
def test_tc216_docker_compose_up_smoke():
    """TC216: Verify docker compose up brings up web & db cleanly."""


# ===========================================================================
# TC217-TC221: Error Prevention, Retention, Resilience, Validation, Raw SQL
# ===========================================================================

@pytest.mark.django_db
def test_tc217_error_prevention_mandatory_fields_and_uniqueness(admin_client):
    """TC217: Mandatory fields and uniqueness enforced across all create forms."""
    # 1. Empty user_create (browser submits empty strings for mandatory fields)
    resp = admin_client.post(
        reverse("user_create"),
        {
            "username": "",
            "full_name": "",
            "email": "",
            "role": "",
            "student_id": "",
            "password1": "",
            "password2": "",
        },
    )
    assert resp.status_code == 200
    assert resp.context["form"].errors

    # Duplicate username & student_id
    existing = UserFactory.student(username="dup_user_217", student_id="SV21701")
    resp_dup = admin_client.post(
        reverse("user_create"),
        {
            "username": existing.username,
            "full_name": "Another Student",
            "email": "another@example.com",
            "role": Role.STUDENT,
            "student_id": existing.student_id,
            "password1": "ValidPass123!",
            "password2": "ValidPass123!",
        },
    )
    assert resp_dup.status_code == 200
    assert "username" in resp_dup.context["form"].errors
    assert "student_id" in resp_dup.context["form"].errors

    # 2. Course create: empty & duplicate code
    resp_c_empty = admin_client.post(reverse("course_create"), {"code": "", "name": ""})
    assert resp_c_empty.status_code == 200
    assert resp_c_empty.context["form"].errors

    course = CourseFactory.create(code="DUP217")
    resp_c_dup = admin_client.post(
        reverse("course_create"), {"code": "DUP217", "name": "Duplicate"}
    )
    assert resp_c_dup.status_code == 200
    assert resp_c_dup.context["form"].errors

    # 3. Classroom create: empty & duplicate name in same course
    resp_cl_empty = admin_client.post(
        reverse("classroom_create"), {"course": "", "name": ""}
    )
    assert resp_cl_empty.status_code == 200
    assert resp_cl_empty.context["form"].errors

    classroom = ClassroomFactory.create(course=course, name="Room217")
    resp_cl_dup = admin_client.post(
        reverse("classroom_create"), {"course": course.pk, "name": "Room217"}
    )
    assert resp_cl_dup.status_code == 200
    assert resp_cl_dup.context["form"].errors

    # 4. Session create: empty & duplicate slot
    resp_s_empty = admin_client.post(
        reverse("session_create", args=[classroom.pk]),
        {"date": "", "start_time": "", "room": ""},
    )
    assert resp_s_empty.status_code == 200
    assert resp_s_empty.context["form"].errors

    SessionFactory.scheduled(
        classroom=classroom,
        date=datetime.date(2026, 12, 10),
        start_time=datetime.time(9, 0),
    )
    resp_s_dup = admin_client.post(
        reverse("session_create", args=[classroom.pk]),
        {"date": "2026-12-10", "start_time": "09:00", "room": "R999"},
    )
    assert resp_s_dup.status_code == 200
    assert resp_s_dup.context["form"].errors


@pytest.mark.django_db
def test_tc218_attendance_data_retention_across_lifecycle(admin_client):
    """TC218: Lock student, remove student, attempt delete classroom & course -> 0 records lost."""
    course = CourseFactory.create()
    student = UserFactory.student()
    classroom = ClassroomFactory.create(course=course, students=[student])
    session = SessionFactory.open(classroom=classroom)
    close_session(session, {student.student_id: AttendanceStatus.PRESENT})
    assert AttendanceRecord.objects.filter(session=session, student=student.student_profile).count() == 1

    # 1. Lock student account
    resp_lock = admin_client.post(reverse("user_lock", args=[student.pk]))
    assert resp_lock.status_code == 302
    student.refresh_from_db()
    assert student.is_locked

    # 2. Remove student from classroom
    resp_remove = admin_client.post(
        reverse("classroom_remove_student", args=[classroom.pk, student.student_id])
    )
    assert resp_remove.status_code == 302
    assert not Enrollment.objects.filter(
        classroom=classroom, student=student.student_profile
    ).exists()

    # 3. Attempt to delete classroom (must be refused)
    resp_del_cls = admin_client.post(reverse("classroom_delete", args=[classroom.pk]))
    assert resp_del_cls.status_code == 302
    assert Classroom.objects.filter(pk=classroom.pk).exists()

    # 4. Attempt to delete course (must be refused)
    resp_del_course = admin_client.post(reverse("course_delete", args=[course.pk]))
    assert resp_del_course.status_code == 302
    assert Course.objects.filter(pk=course.pk).exists()

    # 0 attendance records lost
    assert AttendanceRecord.objects.filter(
        session=session, student=student.student_profile, status=AttendanceStatus.PRESENT
    ).count() == 1


@pytest.mark.django_db
def test_tc219_no_http_500_on_invalid_or_unauthorized_requests(
    anon_client, student_client, teacher_client, admin_client
):
    """TC219: Invalid IDs, unauthorized roles, and bad methods never produce HTTP 500."""
    classroom = ClassroomFactory.create()
    session = SessionFactory.open(classroom=classroom)

    checks = [
        (anon_client, "get", reverse("user_list"), {302}),
        (anon_client, "get", reverse("logout"), {405}),
        (student_client, "get", reverse("user_list"), {403}),
        (student_client, "get", reverse("course_list"), {403}),
        (student_client, "get", reverse("threshold_settings"), {403}),
        (student_client, "get", reverse("classroom_detail", args=[classroom.pk]), {403}),
        (teacher_client, "get", reverse("user_list"), {403}),
        (teacher_client, "get", reverse("take_attendance", args=[session.pk]), {403}),
        (admin_client, "get", reverse("user_detail", args=[999999]), {404}),
        (admin_client, "get", reverse("course_detail", args=["NONEXISTENT"]), {404}),
        (admin_client, "get", reverse("classroom_detail", args=["CL9999"]), {404}),
        (admin_client, "get", reverse("session_detail", args=[999999]), {404}),
        (admin_client, "get", reverse("session_open", args=[session.pk]), {405}),
    ]
    for client, method, url, expected_codes in checks:
        resp = getattr(client, method)(url)
        assert resp.status_code != 500, f"HTTP 500 on {method.upper()} {url}"
        assert resp.status_code in expected_codes, (
            f"Unexpected {resp.status_code} on {method.upper()} {url}, expected {expected_codes}"
        )


@pytest.mark.django_db
def test_tc220_server_side_validation_crafted_posts(admin_client):
    """TC220: Server-side validation rejects crafted POSTs (role=SUPERUSER, 300-char username,
    invalid date, status=EXCUSED, phone=abc)."""
    # 1. role=SUPERUSER
    resp_role = admin_client.post(
        reverse("user_create"),
        {
            "username": "crafted_super",
            "full_name": "Crafted User",
            "email": "crafted@example.com",
            "role": "SUPERUSER",
            "password1": "ValidPass123!",
            "password2": "ValidPass123!",
        },
    )
    assert resp_role.status_code == 200
    assert "role" in resp_role.context["form"].errors
    assert not UserAccount.objects.filter(username="crafted_super").exists()

    # 2. 300-char username
    long_username = "u" * 300
    resp_long = admin_client.post(
        reverse("user_create"),
        {
            "username": long_username,
            "full_name": "Long User",
            "email": "long@example.com",
            "role": Role.TEACHER,
            "password1": "ValidPass123!",
            "password2": "ValidPass123!",
        },
    )
    assert resp_long.status_code == 200
    assert "username" in resp_long.context["form"].errors
    assert not UserAccount.objects.filter(username=long_username).exists()

    # 3. Invalid date=2026-13-45
    classroom = ClassroomFactory.create()
    resp_date = admin_client.post(
        reverse("session_create", args=[classroom.pk]),
        {"date": "2026-13-45", "start_time": "08:00", "room": "R101"},
    )
    assert resp_date.status_code == 200
    assert "date" in resp_date.context["form"].errors
    assert AttendanceSession.objects.filter(classroom=classroom).count() == 0

    # 4. Invalid attendance status=EXCUSED
    student = UserFactory.student()
    ClassroomFactory.enrol_student(classroom, student)
    session = SessionFactory.open(classroom=classroom)
    resp_att = admin_client.post(
        reverse("take_attendance", args=[session.pk]),
        {"action": "save", f"status_{student.student_id}": "EXCUSED"},
    )
    assert resp_att.status_code == 200
    assert AttendanceRecord.objects.filter(session=session).count() == 0

    # 5. Invalid phone_number=abc on student update
    resp_phone = admin_client.post(
        reverse("user_update", args=[student.pk]),
        {
            "username": student.username,
            "full_name": student.full_name,
            "email": student.email,
            "phone_number": "abc",
            "gender": "",
        },
    )
    assert resp_phone.status_code == 200
    assert "phone_number" in resp_phone.context["form"].errors
    student.student_profile.refresh_from_db()
    assert student.student_profile.phone_number != "abc"


def test_tc221_code_review_zero_raw_sql_queries():
    """TC221: Static scan of app code finds 0 unsafe raw SQL calls (.raw, .extra, cursor, execute)."""
    app_dirs = ["accounts", "courses", "classrooms", "attendance", "config"]
    raw_sql_pattern = re.compile(r"\.(?:raw|extra)\s*\(|\bcursor\s*\(|\bexecute\s*\(")
    findings = []

    for app in app_dirs:
        for py_file in (SOURCE_DIR / app).rglob("*.py"):
            if "migrations" in py_file.parts or py_file.name == "tests.py":
                continue
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if raw_sql_pattern.search(line):
                    findings.append(f"{py_file.relative_to(SOURCE_DIR)}:{lineno}: {stripped}")

    assert findings == [], f"Unsafe raw SQL patterns found: {findings}"
