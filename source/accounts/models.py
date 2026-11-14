"""Account models. ERD: UserAccount 1 --- 0..1 Teacher, UserAccount 1 --- 0..1 Student.

Mapping to the class diagram / ERD:
  UserAccount.user_id    -> userId (INT, PK)
  UserAccount.password   -> password. Django stores "algorithm$iterations$salt$hash" here, so the
                            column holds a salted PBKDF2 hash (NFR Password Protection); `salt` is exposed
                            as a read-only property that returns the salt part of that string.
  Teacher.teacher_id     -> teacherId (VARCHAR(20), PK), FK userId
  Student.student_id     -> studentId (VARCHAR(20), PK), FK userId
"""
from django.contrib.auth.models import (
    AbstractBaseUser, BaseUserManager, PermissionsMixin
)
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.hashers import check_password as _check_password
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    TEACHER = "TEACHER", "Teacher"
    STUDENT = "STUDENT", "Student"


class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    LOCKED = "LOCKED", "Locked"


class Gender(models.TextChoices):
    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"
    OTHER = "OTHER", "Other"


class UserAccountManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("Username is required")
        if not password:
            raise ValueError("Password is required")
        user = self.model(username=username, **extra_fields)
        user.set_password(password)  # salted PBKDF2 hash, never plaintext
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        # Used by `manage.py createsuperuser`: an Admin account (no Teacher/Student profile)
        extra_fields.setdefault("role", Role.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(username, password, **extra_fields)


class UserAccount(AbstractBaseUser, PermissionsMixin):
    """FR-04..06: exactly one role. The role cannot be changed after creation (FR-05)."""

    user_id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=30)
    email = models.EmailField(max_length=50)
    status = models.CharField(
        max_length=10, choices=AccountStatus.choices, default=AccountStatus.ACTIVE
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    is_staff = models.BooleanField(default=False)  # only for the Django admin site (/admin/)

    objects = UserAccountManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["full_name", "email"]

    def __str__(self):
        return f"{self.username} ({self.role})"

    # --- class diagram: UserAccount.isActive(), -salt ---
    @property
    def is_active(self):
        # A LOCKED account cannot log in, and Django treats an inactive user as anonymous on the
        # very next request, so a lock takes effect immediately (FR-06).
        return self.status == AccountStatus.ACTIVE

    @property
    def is_locked(self):
        return self.status == AccountStatus.LOCKED

    @property
    def salt(self):
        parts = (self.password or "").split("$")
        return parts[2] if len(parts) >= 4 else ""

    # --- profile shortcuts (ERD: Student / Teacher are separate tables) ---
    @property
    def student_id(self):
        profile = getattr(self, "student_profile", None)
        return profile.student_id if profile else None

    @property
    def teacher_id(self):
        profile = getattr(self, "teacher_profile", None)
        return profile.teacher_id if profile else None

    def save(self, *args, **kwargs):
        if not self._state.adding:
            old_role = (UserAccount.objects.filter(pk=self.pk)
                        .values_list("role", flat=True).first())
            if old_role is not None and old_role != self.role:
                raise ValidationError("The role cannot be changed after creation (FR-05).")
        super().save(*args, **kwargs)


class Teacher(models.Model):
    teacher_id = models.CharField(max_length=20, primary_key=True)
    # PROTECT: accounts are locked, never deleted, so attendance history stays intact
    user = models.OneToOneField(
        UserAccount, on_delete=models.PROTECT, related_name="teacher_profile"
    )

    def __str__(self):
        return f"{self.teacher_id} - {self.full_name}"

    @property
    def full_name(self):
        return self.user.full_name

    @property
    def email(self):
        return self.user.email

    def save(self, *args, **kwargs):
        if self.user.role != Role.TEACHER:
            raise ValidationError("A Teacher profile requires an account with the Teacher role.")
        super().save(*args, **kwargs)


class Student(models.Model):
    student_id = models.CharField(max_length=20, primary_key=True)
    user = models.OneToOneField(
        UserAccount, on_delete=models.PROTECT, related_name="student_profile"
    )
    phone_number = models.CharField(
        max_length=10, blank=True,
        validators=[RegexValidator(r"^\d{9,10}$", "Enter 9 or 10 digits.")],
    )
    gender = models.CharField(max_length=10, blank=True, choices=Gender.choices)

    def __str__(self):
        return f"{self.student_id} - {self.full_name}"

    # class diagram: Student.getFullName() / getEmail() read the account, so data is not duplicated
    @property
    def full_name(self):
        return self.user.full_name

    @property
    def email(self):
        return self.user.email

    def save(self, *args, **kwargs):
        if self.user.role != Role.STUDENT:
            raise ValidationError("A Student profile requires an account with the Student role.")
        if not self._state.adding:
            clash = Student.objects.filter(user=self.user).exclude(pk=self.pk).exists()
            if clash:
                raise ValidationError("The student ID cannot be changed after creation (FR-05).")
        super().save(*args, **kwargs)


class LoginAttempt(models.Model):
    """Login attempt history per username, used for brute-force protection (task 7).
    Supporting table, not part of the ERD."""

    username = models.CharField(max_length=150, db_index=True)
    attempted_at = models.DateTimeField(default=timezone.now, db_index=True)
    succeeded = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.username} {'OK' if self.succeeded else 'FAIL'} {self.attempted_at}"
