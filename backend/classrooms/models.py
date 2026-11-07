from django.conf import settings
from django.db import models
from django.utils import timezone


class Classroom(models.Model):
    name = models.CharField(max_length=255)
    # PROTECT: không xóa được Course khi còn Classroom (FR-08)
    course = models.ForeignKey(
        "courses.Course", on_delete=models.PROTECT, related_name="classrooms"
    )
    # Tối đa 1 Teacher; xóa/khóa Teacher không xóa lớp
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_classrooms",
        limit_choices_to={"role": "TEACHER"},
    )
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="Enrollment",
        related_name="enrolled_classrooms",
        limit_choices_to={"role": "STUDENT"},
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course", "name"], name="unique_classroom_name_per_course"
            )
        ]

    def __str__(self):
        return f"{self.course.code} / {self.name}"


class Enrollment(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE)
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="enrollments"
    )
    # Dùng để bỏ qua các buổi đã Closed trước khi SV được thêm (FR-10)
    enrolled_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["classroom", "student"], name="unique_enrollment"
            )
        ]

    def __str__(self):
        return f"{self.student} in {self.classroom}"


class SessionStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled"
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"
    CANCELLED = "CANCELLED", "Cancelled"


class ClassSession(models.Model):
    """Một buổi học. Đặt tên ClassSession để không nhầm với django.contrib.sessions."""

    classroom = models.ForeignKey(
        Classroom, on_delete=models.CASCADE, related_name="sessions"
    )
    date = models.DateField()
    start_time = models.TimeField()
    room = models.CharField(max_length=50)
    status = models.CharField(
        max_length=10, choices=SessionStatus.choices, default=SessionStatus.SCHEDULED
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["date", "start_time"]
        constraints = [
            # Một lớp không có 2 buổi cùng ngày giờ (FR-11)
            models.UniqueConstraint(
                fields=["classroom", "date", "start_time"],
                name="unique_session_slot_per_classroom",
            )
        ]

    def __str__(self):
        return f"{self.classroom} {self.date} {self.start_time} [{self.status}]"
