"""ERD: Classroom, Enrollment (composite PK), AttendanceSession."""
from django.core.exceptions import ValidationError
from django.db import models


class Classroom(models.Model):
    class_id = models.CharField(max_length=20, primary_key=True)  # generated: CL0001, CL0002...
    name = models.CharField(max_length=100)  # ERD: className
    # PROTECT: a Course cannot be deleted while it still has Classrooms (FR-08)
    course = models.ForeignKey(
        "courses.Course", on_delete=models.PROTECT, related_name="classrooms"
    )
    # At most one Teacher (0..1). Deleting the Teacher row never deletes the classroom.
    teacher = models.ForeignKey(
        "accounts.Teacher", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="classrooms",
    )
    students = models.ManyToManyField(
        "accounts.Student", through="Enrollment", related_name="classrooms"
    )

    class Meta:
        ordering = ["course__code", "name"]
        constraints = [
            models.UniqueConstraint(fields=["course", "name"], name="unique_classroom_name_per_course")
        ]

    def __str__(self):
        return f"{self.course_id} / {self.name}"

    # class diagram: addStudent / removeStudent / assignTeacher
    def add_student(self, student):
        Enrollment.objects.create(classroom=self, student=student)

    def remove_student(self, student):
        # Only the enrollment is deleted: attendance records belong to (session, student) and are kept
        Enrollment.objects.filter(classroom=self, student=student).delete()

    def assign_teacher(self, teacher):
        self.teacher = teacher
        self.save(update_fields=["teacher"])

    def has_attendance_records(self):
        from attendance.models import AttendanceRecord
        return AttendanceRecord.objects.filter(session__classroom=self).exists()


class Enrollment(models.Model):
    """Composite primary key (classroom, student): the same Student cannot be enrolled twice (use case 18).

    Which earlier Closed sessions count for a Student (FR-10) is decided by the attendance records, not
    by a timestamp here: no record is created for sessions that were Closed before the Student joined."""

    pk = models.CompositePrimaryKey("classroom", "student")
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name="enrollments")
    student = models.ForeignKey(
        "accounts.Student", on_delete=models.PROTECT, related_name="enrollments"
    )

    def __str__(self):
        return f"{self.student_id} in {self.classroom_id}"


class SessionStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled"
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"
    CANCELLED = "CANCELLED", "Cancelled"


class AttendanceSession(models.Model):
    """One class meeting. Status moves only Scheduled -> Open -> Closed, or Scheduled -> Cancelled."""

    session_id = models.AutoField(primary_key=True)
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name="sessions")
    date = models.DateField()          # ERD: sessionDate
    start_time = models.TimeField()    # ERD: sessionTime
    room = models.CharField(max_length=50)
    status = models.CharField(         # ERD: sessionStatus
        max_length=10, choices=SessionStatus.choices, default=SessionStatus.SCHEDULED
    )

    class Meta:
        ordering = ["date", "start_time"]
        constraints = [
            # A classroom cannot have two sessions at the same date and time (FR-11)
            models.UniqueConstraint(
                fields=["classroom", "date", "start_time"],
                name="unique_session_slot_per_classroom",
            )
        ]

    def __str__(self):
        return f"{self.classroom} {self.date} {self.start_time:%H:%M} [{self.status}]"

    @property
    def is_scheduled(self):
        return self.status == SessionStatus.SCHEDULED

    def _move(self, expected, target):
        if self.status != expected:
            raise ValidationError(f"Only a session with status {expected.label} can become {target.label}.")
        self.status = target
        self.save(update_fields=["status"])

    # class diagram: open() / close() / cancel(). open/close here only guard the order of the statuses;
    # listing Students, marking Absent and recalculating rates are BE2's attendance logic.
    def cancel(self):
        self._move(SessionStatus.SCHEDULED, SessionStatus.CANCELLED)

    def open(self):
        self._move(SessionStatus.SCHEDULED, SessionStatus.OPEN)

    def close(self):
        self._move(SessionStatus.OPEN, SessionStatus.CLOSED)
