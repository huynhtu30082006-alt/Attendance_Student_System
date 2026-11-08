import datetime

from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from accounts.factories import make_user
from classrooms.models import AttendanceSession, Classroom
from courses.models import Course

from .models import AttendanceRecord, Setting, get_absence_threshold


class SchemaConstraintTests(TestCase):
    """ERD / NFR Data Integrity and Attendance Consistency."""

    def setUp(self):
        self.course = Course.objects.create(code="SE101", name="Software Eng")
        self.room = Classroom.objects.create(class_id="CL0001", name="A1", course=self.course)
        self.student = make_user("sv1", student_id="S1").student_profile
        self.session = AttendanceSession.objects.create(
            classroom=self.room, date=datetime.date(2026, 11, 9),
            start_time=datetime.time(8, 0), room="P101")

    def test_one_record_per_student_per_session(self):
        AttendanceRecord.objects.create(session=self.session, student=self.student, status="PRESENT")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceRecord.objects.create(session=self.session, student=self.student, status="ABSENT")
        self.assertEqual(AttendanceRecord.objects.count(), 1)

    def test_composite_primary_key(self):
        r = AttendanceRecord.objects.create(session=self.session, student=self.student, status="LATE")
        self.assertEqual(r.pk, (self.session.pk, "S1"))

    def test_no_duplicate_session_slot(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceSession.objects.create(
                classroom=self.room, date=datetime.date(2026, 11, 9),
                start_time=datetime.time(8, 0), room="P102")

    def test_cannot_delete_course_with_classrooms(self):
        with self.assertRaises(ProtectedError):
            self.course.delete()

    def test_cannot_delete_classroom_with_attendance(self):
        AttendanceRecord.objects.create(session=self.session, student=self.student, status="LATE")
        with self.assertRaises(ProtectedError):
            self.room.delete()

    def test_cannot_delete_a_student_or_session_with_attendance(self):
        AttendanceRecord.objects.create(session=self.session, student=self.student, status="LATE")
        with self.assertRaises(ProtectedError):
            self.student.delete()
        with self.assertRaises(ProtectedError):
            self.session.delete()

    def test_foreign_keys_are_enforced(self):
        # Foreign keys are checked at the end of the transaction, so force the check now
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceRecord.objects.bulk_create(
                [AttendanceRecord(session_id=999999, student_id="S1", status="PRESENT")])
            connection.check_constraints()
