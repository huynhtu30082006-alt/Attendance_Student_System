import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role, Student, Teacher, UserAccount
from classrooms.models import AttendanceSession, Classroom, Enrollment, SessionStatus
from courses.models import Course

from .models import AttendanceRecord, AttendanceStatistics, AttendanceStatus, Setting
from .services import (
    close_session,
    get_classroom_attendance_report,
    get_student_classroom_summary,
    open_session,
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

    def test_oop_attendance_statistics_and_change_status(self):
        stats = AttendanceStatistics(student=self.students[0], present_count=2, late_count=1, absent_count=1)
        self.assertEqual(stats.total_recorded(), 4)
        self.assertEqual(stats.attendance_rate(), Decimal("75.00"))
        self.assertEqual(stats.absence_rate(), Decimal("25.00"))

        open_session(self.session)
        close_session(self.session, {self.students[0].student_id: AttendanceStatus.ABSENT})
        rec = AttendanceRecord.objects.get(session=self.session, student=self.students[0])
        rec.change_status(AttendanceStatus.PRESENT)
        rec.refresh_from_db()
        self.assertEqual(rec.status, AttendanceStatus.PRESENT)
        with self.assertRaises(ValidationError):
            rec.change_status("EXCUSED")

    def test_bug001_late_enrolled_student_excludes_earlier_closed_sessions(self):
        # Close 2 sessions before late_student enrols
        open_session(self.session)
        close_session(self.session, {s.student_id: AttendanceStatus.PRESENT for s in self.students})

        s2 = AttendanceSession.objects.create(
            classroom=self.classroom, date=datetime.date(2026, 11, 11),
            start_time=datetime.time(8, 0), room="Room 101", status=SessionStatus.OPEN,
        )
        close_session(s2, {s.student_id: AttendanceStatus.PRESENT for s in self.students})

        # Enrol a 4th student late
        u4 = UserAccount.objects.create_user(
            "sv4", "pw123456", full_name="Late Student", email="sv4@x.com", role=Role.STUDENT
        )
        late_student = Student.objects.create(student_id="SV004", user=u4)
        Enrollment.objects.create(classroom=self.classroom, student=late_student)

        # 3rd session where late_student is absent
        s3 = AttendanceSession.objects.create(
            classroom=self.classroom, date=datetime.date(2026, 11, 12),
            start_time=datetime.time(8, 0), room="Room 101", status=SessionStatus.OPEN,
        )
        close_session(s3, {late_student.student_id: AttendanceStatus.ABSENT})

        report = get_classroom_attendance_report(self.classroom)
        late_row = next(r for r in report["rows"] if r["student"] == late_student)
        self.assertEqual(late_row["total_sessions"], 1)
        self.assertEqual(late_row["absence_rate"], Decimal("100.00"))
        self.assertTrue(late_row["is_warned"])

        summary = get_student_classroom_summary(late_student, self.classroom)
        self.assertEqual(summary["total_sessions"], 1)
        self.assertEqual(summary["absence_rate"], Decimal("100.00"))

    def test_fr20_update_closed_session_attendance_and_recalculate(self):
        open_session(self.session)
        close_session(self.session, {
            self.students[0].student_id: AttendanceStatus.ABSENT,
            self.students[1].student_id: AttendanceStatus.PRESENT,
            self.students[2].student_id: AttendanceStatus.PRESENT,
        })
        c = Client()
        c.force_login(self.teacher_user)
        url = reverse("session_records", args=[self.session.pk])
        self.assertTrue(url.startswith("/attendance/sessions/"))
        self.assertEqual(c.get(url).status_code, 200)

        r = c.post(url, {f"status_{self.students[0].student_id}": AttendanceStatus.PRESENT})
        self.assertEqual(r.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.CLOSED)

        report = get_classroom_attendance_report(self.classroom)
        sv1_row = next(r for r in report["rows"] if r["student"] == self.students[0])
        self.assertEqual(sv1_row["absence_rate"], Decimal("0.00"))

    def test_fr13_admin_dashboard_and_url_routing_bug003(self):
        self.assertEqual(reverse("threshold_settings"), "/settings/threshold/")
        self.assertTrue(reverse("take_attendance", args=[self.session.pk]).startswith("/attendance/"))
        self.assertTrue(reverse("admin_dashboard").startswith("/attendance/"))

        admin_user = UserAccount.objects.create_user(
            "admin1", "pw123456", full_name="Admin", email="admin@x.com", role=Role.ADMIN
        )
        c = Client()
        c.force_login(admin_user)
        self.assertEqual(c.get(reverse("admin_dashboard")).status_code, 200)

        c.force_login(self.teacher_user)
        self.assertEqual(c.get(reverse("admin_dashboard")).status_code, 403)

    def test_fr26_export_excel_and_pdf(self):
        c = Client()
        c.force_login(self.teacher_user)
        # Before any closed session -> redirects with error message (no file)
        r_empty = c.get(reverse("export_attendance_excel", args=[self.classroom.pk]))
        self.assertEqual(r_empty.status_code, 302)

        open_session(self.session)
        close_session(self.session, {s.student_id: AttendanceStatus.PRESENT for s in self.students})

        r_xlsx = c.get(reverse("export_attendance_excel", args=[self.classroom.pk]))
        self.assertEqual(r_xlsx.status_code, 200)
        self.assertIn("spreadsheetml", r_xlsx["Content-Type"])

        r_pdf = c.get(reverse("export_attendance_pdf", args=[self.classroom.pk]))
        self.assertEqual(r_pdf.status_code, 200)
        self.assertEqual(r_pdf["Content-Type"], "application/pdf")

        # Student denied
        c.force_login(self.students[0].user)
        self.assertEqual(c.get(reverse("export_attendance_excel", args=[self.classroom.pk])).status_code, 403)
        self.assertEqual(c.get(reverse("export_attendance_pdf", args=[self.classroom.pk])).status_code, 403)
