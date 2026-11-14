"""Account use cases (FR-04..FR-06). Views call these functions; they never touch several tables
themselves, and every multi-table change is atomic (NFR Transaction Atomicity)."""
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from .models import AccountStatus, Role, Student, Teacher, UserAccount
from .utils import create_with_code

TEACHER_PREFIX = "T"


@transaction.atomic
def create_account(username, password, full_name, email, role, student_id=None,
                   phone_number="", gender=""):
    """Create an Active account and, for Teacher / Student, the matching profile row."""
    user = UserAccount.objects.create_user(
        username, password, full_name=full_name, email=email, role=role,
        status=AccountStatus.ACTIVE,
    )
    if role == Role.STUDENT:
        if not student_id:
            raise ValueError("A Student account needs a student ID.")
        Student.objects.create(user=user, student_id=student_id,
                               phone_number=phone_number, gender=gender)
    elif role == Role.TEACHER:
        create_with_code(Teacher, "teacher_id", TEACHER_PREFIX, user=user)
    return user


@transaction.atomic
def update_account(user, username, full_name, email, password=None,
                   phone_number=None, gender=None):
    """Update the editable information. The role and the student ID are never touched (FR-05).
    A blank password keeps the current one."""
    user.username, user.full_name, user.email = username, full_name, email
    if password:
        user.set_password(password)  # stored as a new salted hash
    user.save()
    if user.role == Role.STUDENT and (phone_number is not None or gender is not None):
        profile = user.student_profile
        if phone_number is not None:
            profile.phone_number = phone_number
        if gender is not None:
            profile.gender = gender
        profile.save()
    return user


def end_user_sessions(user):
    """Delete every active login session of the user, so the user is logged out immediately and an old
    session cannot come back to life after an unlock."""
    uid = str(user.pk)
    doomed = [
        s.pk for s in Session.objects.filter(expire_date__gt=timezone.now())
        if s.get_decoded().get("_auth_user_id") == uid
    ]
    Session.objects.filter(pk__in=doomed).delete()
    return len(doomed)


@transaction.atomic
def lock_account(user):
    """Returns False if the account was already locked (nothing changes)."""
    if user.status == AccountStatus.LOCKED:
        return False
    user.status = AccountStatus.LOCKED
    user.save(update_fields=["status"])
    end_user_sessions(user)
    return True


@transaction.atomic
def unlock_account(user):
    """Returns False if the account was not locked (nothing changes)."""
    if user.status != AccountStatus.LOCKED:
        return False
    user.status = AccountStatus.ACTIVE
    user.save(update_fields=["status"])
    return True
