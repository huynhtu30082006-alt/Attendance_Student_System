import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from accounts.models import AccountStatus, Role, Student, Teacher, UserAccount
from classrooms.models import AttendanceSession, Classroom, Enrollment, SessionStatus
from courses.models import Course

from .models import AttendanceRecord, AttendanceStatus, Setting
from .services import (
    close_session,
    get_classroom_attendance_report,
    get_student_classroom_summary,
    open_session,
    take_attendance,
)


class SchemaConstraintTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(code="SE101", name="Software Eng")
        self.room = Classroom.objects.create(class_id="CL999", name="A1", course=self.course)
        
        self.user_sv = UserAccount.objects.create_user(
            "sv1", "pw123456", full_name="A", email="a@x.com", role=Role.STUDENT
        )
        self.student = Student.objects.create(student_id="S1", user=self.user_sv)
        
        self.session = AttendanceSession.objects.create(
            classroom=self.room, date=datetime.date(2026, 11, 9),
            start_time=datetime.time(8, 0), room="P101"
        )

    def test_one_record_per_student_per_session(self):
        AttendanceRecord.objects.create(
            session=self.session, student=self.student, status=AttendanceStatus.PRESENT
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceRecord.objects.create(
                session=self.session, student=self.student, status=AttendanceStatus.ABSENT
            )

    def test_no_duplicate_session_slot(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceSession.objects.create(
                classroom=self.room, date=datetime.date(2026, 11, 9),
                start_time=datetime.time(8, 0), room="P102"
            )

    def test_cannot_delete_course_with_classrooms(self):
        with self.assertRaises(ProtectedError):
            self.course.delete()

    def test_cannot_delete_classroom_with_attendance(self):
        AttendanceRecord.objects.create(
            session=self.session, student=self.student, status=AttendanceStatus.LATE
        )
        with self.assertRaises(ProtectedError):
            self.room.delete()

    def test_default_threshold_is_20(self):
        self.assertEqual(Setting.get().absence_threshold, Decimal("20.00"))


class AttendanceLogicTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(code="CS101", name="Intro to CS")
        self.teacher_user = UserAccount.objects.create_user(
            "gv1", "pw123456", full_name="Teacher 1", email="gv1@x.com", role=Role.TEACHER
        )
        self.teacher = Teacher.objects.create(teacher_id="GV001", user=self.teacher_user)
        self.classroom = Classroom.objects.create(
            class_id="CL001", name="Class 1", course=self.course, teacher=self.teacher
        )

        self.students = []
        for i in range(1, 4):
            u = UserAccount.objects.create_user(
                f"sv{i}", "pw123456", full_name=f"Student {i}", email=f"sv{i}@x.com", role=Role.STUDENT
            )
            s = Student.objects.create(student_id=f"SV00{i}", user=u)
            Enrollment.objects.create(classroom=self.classroom, student=s)
            self.students.append(s)

        self.session = AttendanceSession.objects.create(
            classroom=self.classroom,
            date=datetime.date(2026, 11, 10),
            start_time=datetime.time(8, 0),
            room="Room 101",
            status=SessionStatus.SCHEDULED
        )

    def test_open_session(self):
        open_session(self.session)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.OPEN)

    def test_take_attendance_and_close(self):
        open_session(self.session)
        # SV1 present, SV2 late, SV3 unrecorded
        attendance_data = {
            self.students[0].student_id: AttendanceStatus.PRESENT,
            self.students[1].student_id: AttendanceStatus.LATE,
        }
        close_session(self.session, attendance_data)
        self.session.refresh_from_db()

        self.assertEqual(self.session.status, SessionStatus.CLOSED)
        # SV3 should be auto-marked ABSENT
        sv3_record = AttendanceRecord.objects.get(session=self.session, student=self.students[2])
        self.assertEqual(sv3_record.status, AttendanceStatus.ABSENT)

    def test_report_and_warning_threshold(self):
        open_session(self.session)
        # Mark SV1 absent, SV2 present, SV3 present
        attendance_data = {
            self.students[0].student_id: AttendanceStatus.ABSENT,
            self.students[1].student_id: AttendanceStatus.PRESENT,
            self.students[2].student_id: AttendanceStatus.PRESENT,
        }
        close_session(self.session, attendance_data)

        report = get_classroom_attendance_report(self.classroom)
        self.assertEqual(len(report["rows"]), 3)

        # SV1 has 1 absence out of 1 session = 100% -> should be warned (threshold=20%)
        sv1_row = next(r for r in report["rows"] if r["student"] == self.students[0])
        self.assertEqual(sv1_row["absence_rate"], Decimal("100.00"))
        self.assertTrue(sv1_row["is_warned"])

        # SV2 has 0 absence -> good standing
        sv2_row = next(r for r in report["rows"] if r["student"] == self.students[1])
        self.assertEqual(sv2_row["absence_rate"], Decimal("0.00"))
        self.assertFalse(sv2_row["is_warned"])
