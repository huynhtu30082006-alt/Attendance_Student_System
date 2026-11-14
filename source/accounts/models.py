import uuid

from django.contrib.auth.models import (
    AbstractBaseUser, BaseUserManager, PermissionsMixin
)
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    TEACHER = "TEACHER", "Teacher"
    STUDENT = "STUDENT", "Student"


class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    LOCKED = "LOCKED", "Locked"


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("Username là bắt buộc")
        if not password:
            raise ValueError("Password là bắt buộc")
        user = self.model(username=username, **extra_fields)
        user.set_password(password)  # băm mật khẩu, không lưu plaintext
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("role", Role.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """FR-04..06: 1 role duy nhất; Student có student_id; role/student_id bất biến."""

    user_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    student_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=AccountStatus.choices, default=AccountStatus.ACTIVE
    )
    is_staff = models.BooleanField(default=False)  # cần cho Django admin site
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["full_name", "email"]

    class Meta:
        constraints = [
            # Student bắt buộc có student_id; Admin/Teacher thì không được có
            models.CheckConstraint(
                condition=(
                    (Q(role="STUDENT") & Q(student_id__isnull=False))
                    | (~Q(role="STUDENT") & Q(student_id__isnull=True))
                ),
                name="user_student_id_only_for_student",
            ),
        ]

    @property
    def is_active(self):
        # Tài khoản LOCKED không đăng nhập được (FR-06)
        return self.status == AccountStatus.ACTIVE

    def clean(self):
        self.student_id = self.student_id or None  # "" -> NULL để unique hoạt động
        if self.role == Role.STUDENT and not self.student_id:
            raise ValidationError({"student_id": "Student phải có student ID."})
        if self.role != Role.STUDENT and self.student_id:
            raise ValidationError({"student_id": "Chỉ Student mới có student ID."})

    def save(self, *args, **kwargs):
        self.student_id = self.student_id or None
        if not self._state.adding:
            old = (
                User.objects.filter(pk=self.pk)
                .values("role", "student_id")
                .first()
            )
            if old and (
                old["role"] != self.role or old["student_id"] != self.student_id
            ):
                raise ValidationError("Không được đổi role hoặc student ID (FR-05).")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.role})"
