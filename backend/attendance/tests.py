import datetime

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from accounts.models import Role, User
from classrooms.models import ClassSession, Classroom
from courses.models import Course

from .models import AttendanceRecord, Setting


class SchemaConstraintTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(code="SE101", name="Software Eng")
        self.room = Classroom.objects.create(name="A1", course=self.course)
        self.student = User.objects.create_user(
            "sv1", "pw123456", full_name="A", email="a@x.com",
            role=Role.STUDENT, student_id="S1")
        self.session = ClassSession.objects.create(
            classroom=self.room, date=datetime.date(2026, 11, 9),
            start_time=datetime.time(8, 0), room="P101")

    def test_one_record_per_student_per_session(self):
        AttendanceRecord.objects.create(session=self.session, student=self.student,
                                        status="PRESENT")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceRecord.objects.create(session=self.session,
                                            student=self.student, status="ABSENT")

    def test_no_duplicate_session_slot(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ClassSession.objects.create(
                classroom=self.room, date=datetime.date(2026, 11, 9),
                start_time=datetime.time(8, 0), room="P102")

    def test_cannot_delete_course_with_classrooms(self):
        with self.assertRaises(ProtectedError):
            self.course.delete()

    def test_cannot_delete_classroom_with_attendance(self):
        AttendanceRecord.objects.create(session=self.session, student=self.student,
                                        status="LATE")
        with self.assertRaises(ProtectedError):
            self.room.delete()

    def test_default_threshold_is_20(self):
        self.assertEqual(Setting.get().absence_threshold, 20)
