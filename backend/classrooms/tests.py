import datetime

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.factories import make_user
from accounts.models import Role
from attendance.models import AttendanceRecord
from courses.models import Course

from .models import AttendanceSession, Classroom, Enrollment, SessionStatus


class ClassroomTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("ad1", Role.ADMIN))
        self.course = Course.objects.create(code="SE101", name="SE")
        self.room = Classroom.objects.create(class_id="CL0001", name="A", course=self.course)
        self.sv1, self.sv2 = make_user("sv1"), make_user("sv2")
        self.teacher = make_user("gv1", Role.TEACHER)

    def session(self, **kw):
        d = dict(classroom=self.room, date=datetime.date(2026, 11, 9),
                 start_time=datetime.time(8, 0), room="P1")
        d.update(kw)
        return AttendanceSession.objects.create(**d)

    # ---- create / update ----
    def test_create_generates_id_and_has_no_teacher_or_student(self):
        r = self.client.post(reverse("classroom_create"), {"name": "B", "course": "SE101"})
        c = Classroom.objects.get(name="B")
        self.assertRedirects(r, reverse("classroom_detail", args=[c.pk]))
        self.assertEqual(c.class_id, "CL0002")
        self.assertIsNone(c.teacher)
        self.assertEqual(c.students.count(), 0)

    def test_create_without_course_or_name_rejected(self):
        r = self.client.post(reverse("classroom_create"), {"name": "B", "course": ""})
        self.assertIn("course", r.context["form"].errors)
        r = self.client.post(reverse("classroom_create"), {"name": "  ", "course": "SE101"})
        self.assertIn("name", r.context["form"].errors)
        self.assertEqual(Classroom.objects.count(), 1)

    def test_create_with_unknown_course_rejected(self):
        r = self.client.post(reverse("classroom_create"), {"name": "B", "course": "NOPE"})
        self.assertIn("course", r.context["form"].errors)

    def test_create_when_no_course_exists_explains_it(self):
        Classroom.objects.all().delete()
        Course.objects.all().delete()
        r = self.client.get(reverse("classroom_create"), follow=True)
        self.assertContains(r, "Create a course first")

    def test_unique_name_per_course(self):
        r = self.client.post(reverse("classroom_create"), {"name": "A", "course": "SE101"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Classroom.objects.count(), 1)

    def test_update_name_and_course_but_not_teacher_or_students(self):
        other = Course.objects.create(code="DB101", name="DB")
        self.room.assign_teacher(self.teacher.teacher_profile)
        Enrollment.objects.create(classroom=self.room, student=self.sv1.student_profile)
        self.client.post(reverse("classroom_update", args=["CL0001"]),
                         {"name": "A2", "course": "DB101", "teacher": "", "students": []})
        self.room.refresh_from_db()
        self.assertEqual((self.room.name, self.room.course_id), ("A2", "DB101"))
        self.assertEqual(self.room.teacher_id, self.teacher.teacher_id)
        self.assertEqual(self.room.students.count(), 1)

    # ---- delete ----
    def test_delete_blocked_when_attendance_exists(self):
        s = self.session()
        AttendanceRecord.objects.create(session=s, student=self.sv1.student_profile, status="PRESENT")
        r = self.client.get(reverse("classroom_delete", args=["CL0001"]), follow=True)
        self.assertContains(r, "attendance records")
        self.client.post(reverse("classroom_delete", args=["CL0001"]))
        self.assertTrue(Classroom.objects.filter(pk="CL0001").exists())
        self.assertEqual(AttendanceRecord.objects.count(), 1)

    def test_delete_ok_without_attendance_and_removes_enrollments_and_sessions(self):
        self.session()
        Enrollment.objects.create(classroom=self.room, student=self.sv1.student_profile)
        self.room.assign_teacher(self.teacher.teacher_profile)
        self.client.get(reverse("classroom_delete", args=["CL0001"]))  # confirmation page only
        self.assertTrue(Classroom.objects.filter(pk="CL0001").exists())
        self.client.post(reverse("classroom_delete", args=["CL0001"]))
        self.assertFalse(Classroom.objects.filter(pk="CL0001").exists())
        self.assertEqual(Enrollment.objects.count(), 0)
        self.assertEqual(AttendanceSession.objects.count(), 0)
        self.assertTrue(Course.objects.filter(pk="SE101").exists())      # course untouched
        self.assertTrue(self.sv1.student_profile.__class__.objects.exists())  # accounts untouched

    # ---- teacher ----
    def test_assign_and_replace_teacher(self):
        url = reverse("classroom_assign_teacher", args=["CL0001"])
        self.client.post(url, {"teacher": self.teacher.teacher_id})
        self.room.refresh_from_db()
        self.assertEqual(self.room.teacher_id, self.teacher.teacher_id)
        t2 = make_user("gv2", Role.TEACHER)
        self.client.post(url, {"teacher": t2.teacher_id})
        self.room.refresh_from_db()
        self.assertEqual(self.room.teacher_id, t2.teacher_id)  # replaced: at most one

    def test_same_teacher_changes_nothing(self):
        self.room.assign_teacher(self.teacher.teacher_profile)
        r = self.client.post(reverse("classroom_assign_teacher", args=["CL0001"]),
                             {"teacher": self.teacher.teacher_id}, follow=True)
        self.assertContains(r, "already assigned")

    def test_cannot_assign_student_admin_or_locked_teacher(self):
        url = reverse("classroom_assign_teacher", args=["CL0001"])
        for bad in (self.sv1.student_id, "nobody"):
            r = self.client.post(url, {"teacher": bad})
            self.assertIn("teacher", r.context["form"].errors)
        from accounts.services import lock_account
        lock_account(self.teacher)
        make_user("gv9", Role.TEACHER)  # an active one so the page is still shown
        r = self.client.post(url, {"teacher": self.teacher.teacher_id})
        self.assertIn("teacher", r.context["form"].errors)
        self.room.refresh_from_db()
        self.assertIsNone(self.room.teacher)

    def test_no_active_teacher_is_explained(self):
        from accounts.services import lock_account
        lock_account(self.teacher)
        r = self.client.get(reverse("classroom_assign_teacher", args=["CL0001"]), follow=True)
        self.assertContains(r, "No active Teacher")

    def test_teacher_must_be_chosen(self):
        r = self.client.post(reverse("classroom_assign_teacher", args=["CL0001"]), {"teacher": ""})
        self.assertIn("teacher", r.context["form"].errors)

    # ---- students ----
    def test_add_students_and_reject_duplicates(self):
        url = reverse("classroom_add_students", args=["CL0001"])
        self.client.post(url, {"students": [self.sv1.student_id, self.sv2.student_id]})
        self.assertEqual(Enrollment.objects.filter(classroom=self.room).count(), 2)
        make_user("sv3")
        r = self.client.post(url, {"students": [self.sv1.student_id]})  # already enrolled
        self.assertIn("students", r.context["form"].errors)
        self.assertEqual(Enrollment.objects.filter(classroom=self.room).count(), 2)

    def test_add_students_all_or_nothing(self):
        make_user("sv3")
        r = self.client.post(reverse("classroom_add_students", args=["CL0001"]),
                             {"students": [self.sv1.student_id, "SID-ghost"]})
        self.assertIn("students", r.context["form"].errors)
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_only_students_not_yet_enrolled_are_offered(self):
        Enrollment.objects.create(classroom=self.room, student=self.sv1.student_profile)
        r = self.client.get(reverse("classroom_add_students", args=["CL0001"]))
        offered = [s.student_id for s in r.context["form"].fields["students"].queryset]
        self.assertEqual(offered, ["SID-sv2"])

    def test_no_student_available_is_explained(self):
        for sv in (self.sv1, self.sv2):
            Enrollment.objects.create(classroom=self.room, student=sv.student_profile)
        r = self.client.get(reverse("classroom_add_students", args=["CL0001"]), follow=True)
        self.assertContains(r, "No Student available")

    def test_remove_student_keeps_attendance(self):
        Enrollment.objects.create(classroom=self.room, student=self.sv1.student_profile)
        s = self.session(status=SessionStatus.CLOSED)
        AttendanceRecord.objects.create(session=s, student=self.sv1.student_profile, status="LATE")
        url = reverse("classroom_remove_student", args=["CL0001", "SID-sv1"])
        self.client.get(url)  # confirmation page only
        self.assertEqual(Enrollment.objects.count(), 1)
        self.client.post(url)
        self.assertEqual(Enrollment.objects.count(), 0)
        self.assertEqual(AttendanceRecord.objects.count(), 1)
        self.assertEqual(AttendanceRecord.objects.get().status, "LATE")

    def test_re_adding_a_removed_student_keeps_old_records(self):
        Enrollment.objects.create(classroom=self.room, student=self.sv1.student_profile)
        s = self.session(status=SessionStatus.CLOSED)
        AttendanceRecord.objects.create(session=s, student=self.sv1.student_profile, status="ABSENT")
        self.client.post(reverse("classroom_remove_student", args=["CL0001", "SID-sv1"]))
        self.client.post(reverse("classroom_add_students", args=["CL0001"]), {"students": ["SID-sv1"]})
        self.assertEqual(AttendanceRecord.objects.count(), 1)
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_adding_a_student_after_a_closed_session_creates_no_record(self):
        self.session(status=SessionStatus.CLOSED)
        self.client.post(reverse("classroom_add_students", args=["CL0001"]), {"students": ["SID-sv1"]})
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_remove_unknown_enrollment_is_404(self):
        r = self.client.post(reverse("classroom_remove_student", args=["CL0001", "SID-sv1"]))
        self.assertEqual(r.status_code, 404)

    def test_enrollment_primary_key_blocks_duplicates_in_the_database(self):
        Enrollment.objects.create(classroom=self.room, student=self.sv1.student_profile)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.create(classroom=self.room, student=self.sv1.student_profile)

    def test_detail_lists_teacher_students_and_sessions(self):
        self.room.assign_teacher(self.teacher.teacher_profile)
        Enrollment.objects.create(classroom=self.room, student=self.sv1.student_profile)
        self.session()
        r = self.client.get(reverse("classroom_detail", args=["CL0001"]))
        self.assertContains(r, "Gv1")
        self.assertContains(r, "SID-sv1")
        self.assertContains(r, "room P1")

    def test_generated_ids_do_not_collide(self):
        for n in range(3):
            self.client.post(reverse("classroom_create"), {"name": f"N{n}", "course": "SE101"})
        self.assertEqual(sorted(Classroom.objects.values_list("class_id", flat=True)),
                         ["CL0001", "CL0002", "CL0003", "CL0004"])


class SessionTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("ad1", Role.ADMIN))
        course = Course.objects.create(code="SE101", name="SE")
        self.room = Classroom.objects.create(class_id="CL0001", name="A", course=course)

    def payload(self, **kw):
        d = {"date": "2026-11-09", "start_time": "08:00", "room": "P1"}
        d.update(kw)
        return d

    def create(self, **kw):
        return self.client.post(reverse("session_create", args=["CL0001"]), self.payload(**kw))

    def test_new_session_is_scheduled_even_if_status_is_posted(self):
        self.create(status="CLOSED")
        s = AttendanceSession.objects.get()
        self.assertEqual(s.status, SessionStatus.SCHEDULED)
        self.assertEqual((s.date, s.start_time, s.room), (datetime.date(2026, 11, 9), datetime.time(8, 0), "P1"))

    def test_invalid_input_rejected(self):
        for bad in ({"date": ""}, {"date": "2026-13-45"}, {"start_time": "25:99"}, {"room": ""},
                    {"room": "   "}, {"room": "R" * 51}):
            r = self.create(**bad)
            self.assertEqual(r.status_code, 200, bad)
            self.assertTrue(r.context["form"].errors, bad)
        self.assertEqual(AttendanceSession.objects.count(), 0)

    def test_same_date_and_time_rejected(self):
        self.create()
        r = self.create(room="P2")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(AttendanceSession.objects.count(), 1)

    def test_same_date_and_time_in_another_classroom_is_fine(self):
        other = Classroom.objects.create(class_id="CL0002", name="B", course=self.room.course)
        self.create()
        self.client.post(reverse("session_create", args=[other.pk]), self.payload())
        self.assertEqual(AttendanceSession.objects.count(), 2)

    def test_same_date_different_time_ok(self):
        self.create()
        self.create(start_time="10:00")
        self.assertEqual(AttendanceSession.objects.count(), 2)

    def test_database_blocks_a_duplicate_slot(self):
        self.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceSession.objects.create(classroom=self.room, date=datetime.date(2026, 11, 9),
                                             start_time=datetime.time(8, 0), room="X")

    def test_update_scheduled_ok_but_not_to_a_clashing_slot(self):
        self.create()
        self.create(start_time="10:00")
        s1, s2 = AttendanceSession.objects.order_by("start_time")
        r = self.client.post(reverse("session_update", args=[s2.pk]), self.payload())  # clashes with s1
        self.assertEqual(r.status_code, 200)
        self.client.post(reverse("session_update", args=[s2.pk]), self.payload(start_time="11:00", room="P9"))
        s2.refresh_from_db()
        self.assertEqual((s2.start_time, s2.room, s2.status),
                         (datetime.time(11, 0), "P9", SessionStatus.SCHEDULED))

    def test_saving_a_session_without_changing_its_slot_is_not_a_clash(self):
        self.create()
        s = AttendanceSession.objects.get()
        r = self.client.post(reverse("session_update", args=[s.pk]), self.payload(room="P7"))
        self.assertEqual(r.status_code, 302)

    def test_update_cannot_change_the_status(self):
        self.create()
        s = AttendanceSession.objects.get()
        self.client.post(reverse("session_update", args=[s.pk]), self.payload(status="CLOSED"))
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.SCHEDULED)

    def test_update_and_cancel_blocked_when_not_scheduled(self):
        for status in (SessionStatus.OPEN, SessionStatus.CLOSED, SessionStatus.CANCELLED):
            s = AttendanceSession.objects.create(
                classroom=self.room, date=datetime.date(2026, 12, 1),
                start_time=datetime.time(8, 0), room="P1", status=status)
            self.assertEqual(self.client.get(reverse("session_update", args=[s.pk])).status_code, 302)
            self.client.post(reverse("session_update", args=[s.pk]), self.payload(room="HACK"))
            self.client.post(reverse("session_cancel", args=[s.pk]))
            s.refresh_from_db()
            self.assertEqual(s.status, status)
            self.assertEqual(s.room, "P1")
            s.delete()

    def test_cancel_scheduled_needs_confirmation(self):
        self.create()
        s = AttendanceSession.objects.get()
        self.client.get(reverse("session_cancel", args=[s.pk]))
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.SCHEDULED)
        self.client.post(reverse("session_cancel", args=[s.pk]))
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.CANCELLED)

    def test_a_cancelled_session_can_no_longer_be_edited(self):
        self.create()
        s = AttendanceSession.objects.get()
        self.client.post(reverse("session_cancel", args=[s.pk]))
        self.client.post(reverse("session_update", args=[s.pk]), self.payload(room="HACK"))
        s.refresh_from_db()
        self.assertEqual(s.room, "P1")

    def test_list_and_detail(self):
        self.create()
        s = AttendanceSession.objects.get()
        self.assertContains(self.client.get(reverse("session_list")), "room P1")
        r = self.client.get(reverse("session_detail", args=[s.pk]))
        self.assertContains(r, "SE101")
        self.assertContains(self.client.get(reverse("session_list"), {"classroom": "CL0001"}), "room P1")
        self.assertNotContains(self.client.get(reverse("session_list"), {"classroom": "CL0002"}), "room P1")

    def test_state_machine_order(self):
        self.create()
        s = AttendanceSession.objects.get()
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            s.close()          # Scheduled -> Closed is not allowed
        s.open()
        with self.assertRaises(ValidationError):
            s.open()           # no going back / repeating
        with self.assertRaises(ValidationError):
            s.cancel()         # only a Scheduled session can be cancelled
        s.close()
        with self.assertRaises(ValidationError):
            s.open()           # never back to an earlier status
        self.assertEqual(s.status, SessionStatus.CLOSED)
