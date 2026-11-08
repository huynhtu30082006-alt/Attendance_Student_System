import datetime

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from accounts.factories import make_user
from accounts.models import Role
from classrooms.models import Classroom

from .models import Course


class CourseCrudTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("ad1", Role.ADMIN))

    def test_create_and_unique_code(self):
        r = self.client.post(reverse("course_create"), {"code": "SE101", "name": "SE"})
        self.assertRedirects(r, reverse("course_detail", args=["SE101"]))
        r = self.client.post(reverse("course_create"), {"code": "SE101", "name": "Khac"})
        self.assertIn("code", r.context["form"].errors)
        r = self.client.post(reverse("course_create"), {"code": "se101", "name": "Khac"})  # other case
        self.assertIn("code", r.context["form"].errors)
        self.assertEqual(Course.objects.count(), 1)

    def test_invalid_input_names_the_field(self):
        r = self.client.post(reverse("course_create"), {"code": "", "name": ""})
        self.assertIn("code", r.context["form"].errors)
        self.assertIn("name", r.context["form"].errors)
        r = self.client.post(reverse("course_create"), {"code": "A B/C", "name": "x"})
        self.assertIn("code", r.context["form"].errors)
        r = self.client.post(reverse("course_create"), {"code": "X" * 21, "name": "x"})
        self.assertIn("code", r.context["form"].errors)
        r = self.client.post(reverse("course_create"), {"code": "X1", "name": "n" * 51})
        self.assertIn("name", r.context["form"].errors)
        self.assertEqual(Course.objects.count(), 0)

    def test_update_name(self):
        Course.objects.create(code="SE101", name="SE")
        self.client.post(reverse("course_update", args=["SE101"]), {"code": "SE101", "name": "SE2"})
        self.assertEqual(Course.objects.get(code="SE101").name, "SE2")

    def test_update_code_moves_the_classrooms(self):
        c = Course.objects.create(code="SE101", name="SE")
        room = Classroom.objects.create(class_id="CL0001", name="A", course=c)
        r = self.client.post(reverse("course_update", args=["SE101"]), {"code": "SE102", "name": "SE2"})
        self.assertRedirects(r, reverse("course_detail", args=["SE102"]))
        self.assertFalse(Course.objects.filter(code="SE101").exists())
        room.refresh_from_db()
        self.assertEqual(room.course_id, "SE102")
        self.assertEqual(Course.objects.get().name, "SE2")

    def test_update_code_to_a_taken_code_is_rejected_and_nothing_changes(self):
        c = Course.objects.create(code="SE101", name="SE")
        Course.objects.create(code="SE102", name="Other")
        Classroom.objects.create(class_id="CL0001", name="A", course=c)
        r = self.client.post(reverse("course_update", args=["SE101"]), {"code": "SE102", "name": "X"})
        self.assertIn("code", r.context["form"].errors)
        self.assertEqual(Classroom.objects.get().course_id, "SE101")
        self.assertEqual(Course.objects.get(code="SE101").name, "SE")

    def test_delete_blocked_when_course_has_classrooms(self):
        c = Course.objects.create(code="SE101", name="SE")
        Classroom.objects.create(class_id="CL0001", name="A", course=c)
        # rejected already at the confirmation step, and also when the POST is sent by hand
        r = self.client.get(reverse("course_delete", args=["SE101"]), follow=True)
        self.assertContains(r, "still has classrooms")
        self.client.post(reverse("course_delete", args=["SE101"]))
        self.assertTrue(Course.objects.filter(pk="SE101").exists())
        self.assertEqual(Classroom.objects.count(), 1)

    def test_delete_needs_confirmation_and_works_without_classrooms(self):
        Course.objects.create(code="SE101", name="SE")
        self.client.get(reverse("course_delete", args=["SE101"]))
        self.assertTrue(Course.objects.filter(pk="SE101").exists())
        r = self.client.post(reverse("course_delete", args=["SE101"]))
        self.assertRedirects(r, reverse("course_list"))
        self.assertFalse(Course.objects.filter(pk="SE101").exists())

    def test_database_level_protection(self):
        c = Course.objects.create(code="SE101", name="SE")
        Classroom.objects.create(class_id="CL0001", name="A", course=c)
        with self.assertRaises(ProtectedError):
            c.delete()

    def test_list_and_detail_messages(self):
        self.assertContains(self.client.get(reverse("course_list")), "no course")
        Course.objects.create(code="SE101", name="SE")
        self.assertContains(self.client.get(reverse("course_detail", args=["SE101"])), "no classroom")

    def test_missing_course_is_404(self):
        self.assertEqual(self.client.get(reverse("course_detail", args=["NOPE"])).status_code, 404)
