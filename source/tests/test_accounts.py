"""Account management tests: CRUD, validation, lock/unlock, view, and search (TC20-TC52, TC56-TC58).

Covers:
  - TC20-TC22: Create Student, Teacher (auto teacher_id), Admin (can log in)
  - TC23-TC31: Create validation errors & Cancel saves nothing
  - TC32-TC42: Update account, immutability of role & student_id, password rules, Student phone/gender, Cancel
  - TC43-TC51: Lock / Unlock workflows, immediate session invalidation, self-lock block, record preservation, edge states
  - TC52: View accounts list & detail (password/hash never exposed)
  - TC56-TC58: Search by full name / username / student ID, empty keyword prompt, no-match empty state
"""
import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from accounts.models import AccountStatus, Gender, Role, Student, Teacher, UserAccount
from attendance.models import AttendanceRecord
from tests.factories import (
    AttendanceFactory,
    ClassroomFactory,
    SessionFactory,
    UserFactory,
)


def _messages_text(response):
    return [str(m) for m in response.context["messages"]]


# ---------------------------------------------------------------------------
# TC20 - TC22: Create Student, Teacher, Admin
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc20_create_student_account(admin_client):
    """TC20: Admin creates a Student account -> Active, role STUDENT, Student profile with student_id."""
    resp = admin_client.post(
        reverse("user_create"),
        {
            "username": "stu_new_tc20",
            "full_name": "Nguyen Van A",
            "email": "stu20@example.com",
            "role": Role.STUDENT,
            "student_id": "SV20001",
            "password1": "Str0ngPass!20",
            "password2": "Str0ngPass!20",
        },
        follow=True,
    )

    assert resp.status_code == 200
    user = UserAccount.objects.get(username="stu_new_tc20")
    assert user.status == AccountStatus.ACTIVE
    assert user.role == Role.STUDENT
    assert user.student_id == "SV20001"
    assert Student.objects.filter(user=user, student_id="SV20001").exists()
    assert user.password.startswith("pbkdf2_sha256$")
    assert user.password != "Str0ngPass!20"
    assert user.check_password("Str0ngPass!20")
    assert "Account created." in _messages_text(resp)


@pytest.mark.django_db
def test_tc21_create_teacher_account_auto_teacher_id(admin_client):
    """TC21: Admin creates a Teacher account -> Active, role TEACHER, auto-generated Teacher profile ID."""
    resp = admin_client.post(
        reverse("user_create"),
        {
            "username": "tch_new_tc21",
            "full_name": "Tran Thi B",
            "email": "tch21@example.com",
            "role": Role.TEACHER,
            "student_id": "",
            "password1": "Str0ngPass!21",
            "password2": "Str0ngPass!21",
        },
        follow=True,
    )

    assert resp.status_code == 200
    user = UserAccount.objects.get(username="tch_new_tc21")
    assert user.status == AccountStatus.ACTIVE
    assert user.role == Role.TEACHER
    assert user.teacher_id is not None
    assert user.teacher_id.startswith("T")
    assert Teacher.objects.filter(user=user, teacher_id=user.teacher_id).exists()
    assert user.student_id is None
    assert "Account created." in _messages_text(resp)


@pytest.mark.django_db
def test_tc22_create_admin_account_and_login(admin_client):
    """TC22: Admin creates another Admin account -> new Admin can log in and access Admin home."""
    resp = admin_client.post(
        reverse("user_create"),
        {
            "username": "adm_new_tc22",
            "full_name": "Le Van Admin",
            "email": "adm22@example.com",
            "role": Role.ADMIN,
            "student_id": "",
            "password1": "Str0ngPass!22",
            "password2": "Str0ngPass!22",
        },
        follow=True,
    )

    assert resp.status_code == 200
    user = UserAccount.objects.get(username="adm_new_tc22")
    assert user.status == AccountStatus.ACTIVE
    assert user.role == Role.ADMIN
    assert user.student_id is None
    assert user.teacher_id is None

    new_client = Client()
    login_resp = new_client.post(
        reverse("login"),
        {"username": "adm_new_tc22", "password": "Str0ngPass!22"},
        follow=True,
    )
    assert login_resp.status_code == 200
    assert login_resp.wsgi_request.user == user
    assert reverse("user_list") in login_resp.content.decode()


# ---------------------------------------------------------------------------
# TC23 - TC31: Create validation errors & Cancel
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc23_create_duplicate_username_fails(admin_client):
    """TC23: Duplicate username (case-insensitive) is rejected."""
    UserFactory.student(username="dup_user_tc23")
    before = UserAccount.objects.count()

    resp = admin_client.post(
        reverse("user_create"),
        {
            "username": "DUP_USER_TC23",
            "full_name": "Another Person",
            "email": "other23@example.com",
            "role": Role.ADMIN,
            "student_id": "",
            "password1": "Str0ngPass!23",
            "password2": "Str0ngPass!23",
        },
    )

    assert resp.status_code == 200
    assert "username" in resp.context["form"].errors
    assert "This username is already used." in resp.content.decode()
    assert UserAccount.objects.count() == before


@pytest.mark.django_db
def test_tc24_create_duplicate_student_id_fails(admin_client):
    """TC24: Duplicate student ID (case-insensitive) is rejected."""
    UserFactory.student(username="stu_orig_tc24", student_id="SV24001")
    before = UserAccount.objects.count()

    resp = admin_client.post(
        reverse("user_create"),
        {
            "username": "stu_new_tc24",
            "full_name": "Dup Student ID",
            "email": "dup24@example.com",
            "role": Role.STUDENT,
            "student_id": "sv24001",
            "password1": "Str0ngPass!24",
            "password2": "Str0ngPass!24",
        },
    )

    assert resp.status_code == 200
    assert "student_id" in resp.context["form"].errors
    assert "This student ID is already used." in resp.content.decode()
    assert UserAccount.objects.count() == before


@pytest.mark.django_db
def test_tc25_create_student_without_student_id_fails(admin_client):
    """TC25: Student account without student_id is rejected."""
    before = UserAccount.objects.count()

    resp = admin_client.post(
        reverse("user_create"),
        {
            "username": "stu_nosid_tc25",
            "full_name": "No Student ID",
            "email": "nosid25@example.com",
            "role": Role.STUDENT,
            "student_id": "",
            "password1": "Str0ngPass!25",
            "password2": "Str0ngPass!25",
        },
    )

    assert resp.status_code == 200
    assert "student_id" in resp.context["form"].errors
    assert "A Student must have a student ID." in resp.content.decode()
    assert UserAccount.objects.count() == before


@pytest.mark.django_db
def test_tc26_create_teacher_with_student_id_fails(admin_client):
    """TC26: Teacher account with a student_id is rejected."""
    before = UserAccount.objects.count()

    resp = admin_client.post(
        reverse("user_create"),
        {
            "username": "tch_sid_tc26",
            "full_name": "Teacher With SID",
            "email": "tch26@example.com",
            "role": Role.TEACHER,
            "student_id": "SV26001",
            "password1": "Str0ngPass!26",
            "password2": "Str0ngPass!26",
        },
    )

    assert resp.status_code == 200
    assert "student_id" in resp.context["form"].errors
    assert "Only a Student can have a student ID." in resp.content.decode()
    assert UserAccount.objects.count() == before


@pytest.mark.django_db
def test_tc27_create_mismatched_passwords_fails(admin_client):
    """TC27: Mismatched password1 and password2 is rejected."""
    before = UserAccount.objects.count()

    resp = admin_client.post(
        reverse("user_create"),
        {
            "username": "mismatch_tc27",
            "full_name": "Mismatch User",
            "email": "mm27@example.com",
            "role": Role.ADMIN,
            "student_id": "",
            "password1": "Str0ngPass!27",
            "password2": "DifferentPass!27",
        },
    )

    assert resp.status_code == 200
    assert "password2" in resp.context["form"].errors
    assert "The two passwords do not match." in resp.content.decode()
    assert UserAccount.objects.count() == before


@pytest.mark.django_db
def test_tc28_create_short_password_fails(admin_client):
    """TC28: Password shorter than 8 characters is rejected."""
    before = UserAccount.objects.count()

    resp = admin_client.post(
        reverse("user_create"),
        {
            "username": "shortpw_tc28",
            "full_name": "Short Pw User",
            "email": "sp28@example.com",
            "role": Role.ADMIN,
            "student_id": "",
            "password1": "Ab1!xyz",
            "password2": "Ab1!xyz",
        },
    )

    assert resp.status_code == 200
    assert "password1" in resp.context["form"].errors
    assert UserAccount.objects.count() == before


@pytest.mark.django_db
def test_tc29_create_blank_full_name_fails(admin_client):
    """TC29: Blank or whitespace-only full name is rejected."""
    before = UserAccount.objects.count()

    for blank_val in ("", "   "):
        resp = admin_client.post(
            reverse("user_create"),
            {
                "username": "blankname_tc29",
                "full_name": blank_val,
                "email": "bn29@example.com",
                "role": Role.ADMIN,
                "student_id": "",
                "password1": "Str0ngPass!29",
                "password2": "Str0ngPass!29",
            },
        )
        assert resp.status_code == 200
        assert "full_name" in resp.context["form"].errors

    assert UserAccount.objects.count() == before


@pytest.mark.django_db
def test_tc30_create_invalid_email_fails(admin_client):
    """TC30: Invalid email format is rejected."""
    before = UserAccount.objects.count()

    resp = admin_client.post(
        reverse("user_create"),
        {
            "username": "bademail_tc30",
            "full_name": "Bad Email User",
            "email": "not-an-email",
            "role": Role.ADMIN,
            "student_id": "",
            "password1": "Str0ngPass!30",
            "password2": "Str0ngPass!30",
        },
    )

    assert resp.status_code == 200
    assert "email" in resp.context["form"].errors
    assert UserAccount.objects.count() == before


@pytest.mark.django_db
def test_tc31_create_cancel_saves_nothing(admin_client):
    """TC31: Opening create form and following Cancel link saves nothing."""
    before = UserAccount.objects.count()

    get_resp = admin_client.get(reverse("user_create"))
    assert get_resp.status_code == 200
    assert get_resp.context["cancel_url"] == "user_list"
    assert reverse("user_list") in get_resp.content.decode()

    cancel_resp = admin_client.get(reverse("user_list"))
    assert cancel_resp.status_code == 200
    assert UserAccount.objects.count() == before


# ---------------------------------------------------------------------------
# TC32 - TC42: Update account
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc32_update_account_full_name_and_email(admin_client):
    """TC32: Admin updates full_name and email of an existing account."""
    target = UserFactory.teacher(
        username="upd_tc32", full_name="Old Name", email="old32@example.com"
    )

    resp = admin_client.post(
        reverse("user_update", args=[target.pk]),
        {
            "username": target.username,
            "full_name": "New Full Name",
            "email": "new32@example.com",
            "new_password": "",
        },
        follow=True,
    )

    assert resp.status_code == 200
    target.refresh_from_db()
    assert target.full_name == "New Full Name"
    assert target.email == "new32@example.com"
    assert "Account updated." in _messages_text(resp)


@pytest.mark.django_db
def test_tc33_update_role_and_student_id_immutable_even_if_tampered(admin_client):
    """TC33: Role and student_id remain unchanged even when tampered in POST payload."""
    student = UserFactory.student(
        username="imm_tc33", full_name="Immutable Stu", student_id="SV33001"
    )

    resp = admin_client.post(
        reverse("user_update", args=[student.pk]),
        {
            "username": student.username,
            "full_name": "Updated Stu",
            "email": student.email,
            "new_password": "",
            "phone_number": "",
            "gender": "",
            # Tampered fields that must be ignored
            "role": Role.ADMIN,
            "student_id": "SV99999",
        },
        follow=True,
    )

    assert resp.status_code == 200
    student.refresh_from_db()
    assert student.full_name == "Updated Stu"
    assert student.role == Role.STUDENT
    assert student.student_id == "SV33001"

    # Model-level guard also forbids changing role directly
    student.role = Role.ADMIN
    with pytest.raises(ValidationError):
        student.save()


@pytest.mark.django_db
def test_tc34_update_blank_new_password_keeps_current_password(admin_client):
    """TC34: Leaving new_password blank keeps the existing password hash unchanged."""
    target = UserFactory.student(username="keeppw_tc34", password="OrigPassword!34")
    original_hash = target.password

    resp = admin_client.post(
        reverse("user_update", args=[target.pk]),
        {
            "username": target.username,
            "full_name": "Same Pw User",
            "email": target.email,
            "new_password": "",
            "phone_number": "",
            "gender": "",
        },
        follow=True,
    )

    assert resp.status_code == 200
    target.refresh_from_db()
    assert target.password == original_hash
    assert target.check_password("OrigPassword!34")


@pytest.mark.django_db
def test_tc35_update_new_password_updates_salted_hash(admin_client):
    """TC35: Providing new_password updates salted PBKDF2 hash; old fails, new logs in."""
    target = UserFactory.student(username="newpw_tc35", password="OldPassword!35")
    old_hash = target.password
    old_salt = target.salt

    resp = admin_client.post(
        reverse("user_update", args=[target.pk]),
        {
            "username": target.username,
            "full_name": target.full_name,
            "email": target.email,
            "new_password": "NewPassword!35",
            "phone_number": "",
            "gender": "",
        },
        follow=True,
    )

    assert resp.status_code == 200
    target.refresh_from_db()
    assert target.password != old_hash
    assert target.password.startswith("pbkdf2_sha256$")
    assert target.salt != old_salt
    assert not target.check_password("OldPassword!35")
    assert target.check_password("NewPassword!35")

    client = Client()
    old_login = client.post(
        reverse("login"), {"username": target.username, "password": "OldPassword!35"}
    )
    assert not old_login.wsgi_request.user.is_authenticated

    new_login = client.post(
        reverse("login"),
        {"username": target.username, "password": "NewPassword!35"},
        follow=True,
    )
    assert new_login.status_code == 200
    assert new_login.wsgi_request.user == target


@pytest.mark.django_db
def test_tc36_update_duplicate_username_fails(admin_client):
    """TC36: Updating username to one already owned by another account fails."""
    other = UserFactory.teacher(username="taken_tc36")
    target = UserFactory.teacher(username="orig_tc36")

    resp = admin_client.post(
        reverse("user_update", args=[target.pk]),
        {
            "username": other.username,
            "full_name": target.full_name,
            "email": target.email,
            "new_password": "",
        },
    )

    assert resp.status_code == 200
    assert "username" in resp.context["form"].errors
    assert "This username is already used." in resp.content.decode()
    target.refresh_from_db()
    assert target.username == "orig_tc36"


@pytest.mark.django_db
def test_tc37_update_blank_full_name_fails(admin_client):
    """TC37: Updating full_name to blank or whitespace fails and preserves original value."""
    target = UserFactory.teacher(username="bn_tc37", full_name="Original Name")

    for blank_val in ("", "   "):
        resp = admin_client.post(
            reverse("user_update", args=[target.pk]),
            {
                "username": target.username,
                "full_name": blank_val,
                "email": target.email,
                "new_password": "",
            },
        )
        assert resp.status_code == 200
        assert "full_name" in resp.context["form"].errors

    target.refresh_from_db()
    assert target.full_name == "Original Name"


@pytest.mark.django_db
def test_tc38_update_invalid_email_fails(admin_client):
    """TC38: Updating email to invalid format fails and preserves original email."""
    target = UserFactory.teacher(username="be_tc38", email="valid38@example.com")

    resp = admin_client.post(
        reverse("user_update", args=[target.pk]),
        {
            "username": target.username,
            "full_name": target.full_name,
            "email": "invalid-email-format",
            "new_password": "",
        },
    )

    assert resp.status_code == 200
    assert "email" in resp.context["form"].errors
    target.refresh_from_db()
    assert target.email == "valid38@example.com"


@pytest.mark.django_db
def test_tc39_update_short_password_fails(admin_client):
    """TC39: Updating new_password to < 8 chars fails and preserves original password."""
    target = UserFactory.teacher(username="sp_tc39", password="ValidPassword!39")
    old_hash = target.password

    resp = admin_client.post(
        reverse("user_update", args=[target.pk]),
        {
            "username": target.username,
            "full_name": target.full_name,
            "email": target.email,
            "new_password": "Short1!",
        },
    )

    assert resp.status_code == 200
    assert "new_password" in resp.context["form"].errors
    target.refresh_from_db()
    assert target.password == old_hash


@pytest.mark.django_db
def test_tc40_update_student_invalid_phone_fails(admin_client):
    """TC40: Student update with invalid phone number (non-digits or wrong length) fails."""
    student = UserFactory.student(username="phone_tc40", phone_number="0901234567")

    for bad_phone in ("12345", "abcdefghij", "09012345678"):
        resp = admin_client.post(
            reverse("user_update", args=[student.pk]),
            {
                "username": student.username,
                "full_name": student.full_name,
                "email": student.email,
                "new_password": "",
                "phone_number": bad_phone,
                "gender": "",
            },
        )
        assert resp.status_code == 200
        assert "phone_number" in resp.context["form"].errors

    student.student_profile.refresh_from_db()
    assert student.student_profile.phone_number == "0901234567"


@pytest.mark.django_db
def test_tc41_update_student_valid_phone_and_gender_saved(admin_client):
    """TC41: Student update with valid 9/10-digit phone and gender persists and displays."""
    student = UserFactory.student(username="phone_tc41")

    resp = admin_client.post(
        reverse("user_update", args=[student.pk]),
        {
            "username": student.username,
            "full_name": student.full_name,
            "email": student.email,
            "new_password": "",
            "phone_number": "0912345678",
            "gender": Gender.FEMALE,
        },
        follow=True,
    )

    assert resp.status_code == 200
    student.student_profile.refresh_from_db()
    assert student.student_profile.phone_number == "0912345678"
    assert student.student_profile.gender == Gender.FEMALE
    content = resp.content.decode()
    assert "0912345678" in content
    assert "Female" in content


@pytest.mark.django_db
def test_tc42_update_cancel_keeps_data_unchanged(admin_client):
    """TC42: Opening edit form and cancelling without POST leaves account unchanged."""
    target = UserFactory.teacher(
        username="cancel_tc42", full_name="Keep This Name", email="keep42@example.com"
    )

    get_resp = admin_client.get(reverse("user_update", args=[target.pk]))
    assert get_resp.status_code == 200
    assert get_resp.context["cancel_url"] == "user_list"
    assert reverse("user_list") in get_resp.content.decode()

    target.refresh_from_db()
    assert target.full_name == "Keep This Name"
    assert target.email == "keep42@example.com"


# ---------------------------------------------------------------------------
# TC43 - TC51: Lock / Unlock workflows
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc43_lock_active_user_blocks_login(admin_client):
    """TC43: Locking an active user sets status to LOCKED and prevents subsequent login."""
    student = UserFactory.student(username="lock_tc43")

    resp = admin_client.post(reverse("user_lock", args=[student.pk]), follow=True)
    assert resp.status_code == 200
    student.refresh_from_db()
    assert student.status == AccountStatus.LOCKED
    assert "Account locked. The user has been logged out." in _messages_text(resp)

    client = Client()
    login_resp = client.post(
        reverse("login"),
        {"username": student.username, "password": student.raw_password},
    )
    assert login_resp.status_code == 200
    assert not login_resp.wsgi_request.user.is_authenticated


@pytest.mark.django_db
def test_tc44_locked_user_logged_out_immediately_on_next_request(admin_client):
    """TC44: An already-logged-in user is immediately logged out on next request after lock."""
    student = UserFactory.student(username="kick_tc44")
    student_client = Client()
    login_resp = student_client.post(
        reverse("login"),
        {"username": student.username, "password": student.raw_password},
    )
    assert login_resp.status_code == 302
    assert student_client.get(reverse("home")).status_code == 200

    # Admin locks the student
    lock_resp = admin_client.post(reverse("user_lock", args=[student.pk]))
    assert lock_resp.status_code == 302

    # Next request from the student is immediately redirected to login
    next_resp = student_client.get(reverse("home"))
    assert next_resp.status_code == 302
    assert next_resp["Location"].startswith(reverse("login"))


@pytest.mark.django_db
def test_tc45_admin_cannot_lock_own_account(admin_client, admin_user):
    """TC45: Admin attempting to lock their own account is blocked with an error message."""
    resp = admin_client.post(reverse("user_lock", args=[admin_user.pk]), follow=True)

    assert resp.status_code == 200
    admin_user.refresh_from_db()
    assert admin_user.status == AccountStatus.ACTIVE
    assert "You cannot lock your own account." in _messages_text(resp)


@pytest.mark.django_db
def test_tc46_unlock_locked_user_restores_login(admin_client):
    """TC46: Unlocking a locked user restores ACTIVE status and allows login again."""
    locked_user = UserFactory.locked(username="unlock_tc46")

    resp = admin_client.post(reverse("user_unlock", args=[locked_user.pk]), follow=True)
    assert resp.status_code == 200
    locked_user.refresh_from_db()
    assert locked_user.status == AccountStatus.ACTIVE
    assert "Account unlocked." in _messages_text(resp)

    client = Client()
    login_resp = client.post(
        reverse("login"),
        {"username": locked_user.username, "password": locked_user.raw_password},
        follow=True,
    )
    assert login_resp.status_code == 200
    assert login_resp.wsgi_request.user == locked_user


@pytest.mark.django_db
def test_tc47_lock_preserves_attendance_records(admin_client):
    """TC47: Locking a Student account preserves all existing AttendanceRecord rows."""
    student = UserFactory.student(username="keeprec_tc47")
    classroom = ClassroomFactory.create(students=[student])
    session = SessionFactory.closed(classroom=classroom)
    record = AttendanceFactory.present(session=session, student=student, enrol=False)

    resp = admin_client.post(reverse("user_lock", args=[student.pk]))
    assert resp.status_code == 302

    student.refresh_from_db()
    assert student.status == AccountStatus.LOCKED
    assert AttendanceRecord.objects.filter(pk=record.pk, student=student.student_profile).exists()


@pytest.mark.django_db
def test_tc48_lock_cancel_keeps_active(admin_client):
    """TC48: Viewing lock confirmation page and cancelling keeps user ACTIVE."""
    student = UserFactory.student(username="lockcancel_tc48")

    resp = admin_client.get(reverse("user_lock", args=[student.pk]))
    assert resp.status_code == 200
    assert reverse("user_detail", args=[student.pk]) in resp.content.decode()

    student.refresh_from_db()
    assert student.status == AccountStatus.ACTIVE


@pytest.mark.django_db
def test_tc49_lock_already_locked_shows_message(admin_client):
    """TC49: Locking an already-locked user redirects with info message and makes no change."""
    locked_user = UserFactory.locked(username="alreadylocked_tc49")

    resp = admin_client.post(reverse("user_lock", args=[locked_user.pk]), follow=True)
    assert resp.status_code == 200
    locked_user.refresh_from_db()
    assert locked_user.status == AccountStatus.LOCKED
    assert "This account is already locked. Nothing changed." in _messages_text(resp)


@pytest.mark.django_db
def test_tc50_unlock_cancel_keeps_locked(admin_client):
    """TC50: Viewing unlock confirmation page and cancelling keeps user LOCKED."""
    locked_user = UserFactory.locked(username="unlockcancel_tc50")

    resp = admin_client.get(reverse("user_unlock", args=[locked_user.pk]))
    assert resp.status_code == 200
    assert reverse("user_detail", args=[locked_user.pk]) in resp.content.decode()

    locked_user.refresh_from_db()
    assert locked_user.status == AccountStatus.LOCKED


@pytest.mark.django_db
def test_tc51_unlock_active_user_shows_message(admin_client):
    """TC51: Unlocking an already-active user redirects with info message and makes no change."""
    active_user = UserFactory.student(username="alreadyactive_tc51")

    resp = admin_client.post(reverse("user_unlock", args=[active_user.pk]), follow=True)
    assert resp.status_code == 200
    active_user.refresh_from_db()
    assert active_user.status == AccountStatus.ACTIVE
    assert "This account is not locked. Nothing changed." in _messages_text(resp)


# ---------------------------------------------------------------------------
# TC52: View accounts list & detail (password / hash never displayed)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc52_view_accounts_list_and_detail_never_exposes_password(admin_client):
    """TC52: Account list & detail show user metadata and never expose password or hash."""
    secret_pw = "SuperSecret!52"
    student = UserFactory.student(
        username="view_stu_tc52",
        full_name="Visible Student",
        email="vis52@example.com",
        student_id="SV52001",
        password=secret_pw,
    )

    list_resp = admin_client.get(reverse("user_list"))
    assert list_resp.status_code == 200
    list_html = list_resp.content.decode()
    assert "view_stu_tc52" in list_html
    assert "Visible Student" in list_html
    assert "SV52001" in list_html
    assert secret_pw not in list_html
    assert student.password not in list_html
    assert "pbkdf2_sha256$" not in list_html

    detail_resp = admin_client.get(reverse("user_detail", args=[student.pk]))
    assert detail_resp.status_code == 200
    detail_html = detail_resp.content.decode()
    assert "view_stu_tc52" in detail_html
    assert "Visible Student" in detail_html
    assert "vis52@example.com" in detail_html
    assert "SV52001" in detail_html
    assert secret_pw not in detail_html
    assert student.password not in detail_html
    assert "pbkdf2_sha256$" not in detail_html


# ---------------------------------------------------------------------------
# TC56 - TC58: Search accounts
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_tc56_search_account_by_full_name_username_and_student_id(admin_client):
    """TC56: Search matches by full name, username, or student ID (case-insensitive)."""
    stu_target = UserFactory.student(
        username="alpha_user_56",
        full_name="Pham Minh Quang",
        student_id="SV56789",
    )
    stu_other = UserFactory.student(
        username="beta_other_56",
        full_name="Hoang Thi Lan",
        student_id="SV56000",
    )

    # Search by full name
    r_name = admin_client.get(reverse("user_list"), {"q": "Minh Quang"})
    assert r_name.status_code == 200
    pks_name = [u.pk for u in r_name.context["page"].object_list]
    assert stu_target.pk in pks_name
    assert stu_other.pk not in pks_name

    # Search by username
    r_user = admin_client.get(reverse("user_list"), {"q": "ALPHA_USER_56"})
    assert r_user.status_code == 200
    pks_user = [u.pk for u in r_user.context["page"].object_list]
    assert stu_target.pk in pks_user
    assert stu_other.pk not in pks_user

    # Search by student ID
    r_sid = admin_client.get(reverse("user_list"), {"q": "sv56789"})
    assert r_sid.status_code == 200
    pks_sid = [u.pk for u in r_sid.context["page"].object_list]
    assert stu_target.pk in pks_sid
    assert stu_other.pk not in pks_sid


@pytest.mark.django_db
def test_tc57_search_account_empty_keyword_shows_prompt(admin_client):
    """TC57: Submitting search with an empty or whitespace keyword displays a prompt error."""
    for empty_q in ("", "   "):
        resp = admin_client.get(reverse("user_list"), {"q": empty_q})
        assert resp.status_code == 200
        assert "Please enter a keyword to search." in _messages_text(resp)


@pytest.mark.django_db
def test_tc58_search_account_non_matching_keyword_shows_empty_message(admin_client):
    """TC58: Searching with a non-matching keyword renders empty-state message without error."""
    UserFactory.student(username="exists_tc58", full_name="Existing User")

    resp = admin_client.get(reverse("user_list"), {"q": "zzznomatch999"})
    assert resp.status_code == 200
    assert list(resp.context["page"].object_list) == []
    assert _messages_text(resp) == []
    assert 'No account matches "zzznomatch999".' in resp.content.decode()
