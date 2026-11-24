from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class AttendanceStatus(models.TextChoices):
    PRESENT = "PRESENT", "Present"
    LATE = "LATE", "Late"
    ABSENT = "ABSENT", "Absent"


class AttendanceRecord(models.Model):
    """ERD: AttendanceRecord, composite PK (sessionId, studentId).

    The primary key itself guarantees at most one record per Student per session (NFR Attendance
    Consistency), also under simultaneous requests. PROTECT on both foreign keys means a session, a
    classroom (through its sessions) or a Student that has records cannot be deleted (FR-09, FR-06)."""

    pk = models.CompositePrimaryKey("session", "student")
    session = models.ForeignKey(
        "classrooms.AttendanceSession", on_delete=models.PROTECT, related_name="records"
    )
    student = models.ForeignKey(
        "accounts.Student", on_delete=models.PROTECT, related_name="attendance_records"
    )
    status = models.CharField(max_length=10, choices=AttendanceStatus.choices)

    def __str__(self):
        return f"{self.student_id} - session {self.session_id}: {self.status}"

    # class diagram: AttendanceRecord.changeStatus(newStatus: AttendanceStatus): void
    def change_status(self, new_status):
        if new_status not in AttendanceStatus.values:
            raise ValidationError(f"Invalid attendance status: {new_status}")
        if self.status != new_status:
            self.status = new_status
            self.save(update_fields=["status"])
        return self


@dataclass
class AttendanceStatistics:
    """Class diagram: AttendanceStatistics (computed from AttendanceRecord, not a DB table)."""

    student: object
    present_count: int = 0
    absent_count: int = 0
    late_count: int = 0

    def total_recorded(self) -> int:
        return self.present_count + self.absent_count + self.late_count

    def attendance_rate(self) -> Decimal:
        total = self.total_recorded()
        if total == 0:
            return Decimal("0.00")
        attended = self.present_count + self.late_count
        return round((Decimal(attended) / Decimal(total)) * Decimal(100), 2)

    def absence_rate(self) -> Decimal:
        total = self.total_recorded()
        if total == 0:
            return Decimal("0.00")
        return round((Decimal(self.absent_count) / Decimal(total)) * Decimal(100), 2)


class Setting(models.Model):
    """System settings, a single row (pk=1). Holds the absence-warning threshold (FR-14).
    Supporting table, not part of the ERD."""

    DEFAULT_THRESHOLD = 20

    absence_threshold = models.DecimalField(
        max_digits=5, decimal_places=2, default=DEFAULT_THRESHOLD,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Absence warning threshold (%)",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(absence_threshold__gte=0) & Q(absence_threshold__lte=100),
                name="threshold_between_0_and_100",
            )
        ]

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"Warning threshold: {self.absence_threshold}%"


def get_absence_threshold():
    """The single threshold (percent, Decimal) for all classrooms. BE2 uses it for the warnings:
    a Student has reached it when the absence rate is >= this value."""
    return Setting.get().absence_threshold
