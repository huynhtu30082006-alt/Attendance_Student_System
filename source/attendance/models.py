from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class AttendanceStatus(models.TextChoices):
    PRESENT = "PRESENT", "Present"
    LATE = "LATE", "Late"
    ABSENT = "ABSENT", "Absent"


class AttendanceRecord(models.Model):
    # PROTECT: lớp/buổi đã có điểm danh thì không xóa được (FR-09)
    session = models.ForeignKey(
        "classrooms.ClassSession", on_delete=models.PROTECT, related_name="records"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="attendance_records"
    )
    status = models.CharField(max_length=10, choices=AttendanceStatus.choices)
    recorded_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Mỗi SV tối đa 1 bản ghi / buổi (NFR Attendance Consistency)
            models.UniqueConstraint(
                fields=["session", "student"], name="unique_record_per_student_session"
            )
        ]

    def __str__(self):
        return f"{self.student} - {self.session_id}: {self.status}"


class Setting(models.Model):
    """Cấu hình hệ thống, chỉ 1 dòng (pk=1). Dùng Setting.get()."""

    absence_threshold = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=20,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Ngưỡng cảnh báo vắng (%)",
    )

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"Ngưỡng cảnh báo: {self.absence_threshold}%"
