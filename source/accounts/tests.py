from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Role, User


class UserModelTests(TestCase):
    def test_student_requires_student_id(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("sv1", "pw123456", full_name="A",
                                     email="a@x.com", role=Role.STUDENT)

    def test_teacher_cannot_have_student_id(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("gv1", "pw123456", full_name="B",
                                     email="b@x.com", role=Role.TEACHER,
                                     student_id="S1")

    def test_student_id_unique(self):
        User.objects.create_user("sv1", "pw123456", full_name="A",
                                 email="a@x.com", role=Role.STUDENT, student_id="S1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("sv2", "pw123456", full_name="B",
                                     email="b@x.com", role=Role.STUDENT,
                                     student_id="S1")

    def test_role_and_student_id_immutable(self):
        u = User.objects.create_user("sv1", "pw123456", full_name="A",
                                     email="a@x.com", role=Role.STUDENT,
                                     student_id="S1")
        u.student_id = "S2"
        with self.assertRaises(ValidationError):
            u.save()

    def test_password_is_hashed(self):
        u = User.objects.create_user("gv1", "pw123456", full_name="B",
                                     email="b@x.com", role=Role.TEACHER)
        self.assertNotEqual(u.password, "pw123456")
