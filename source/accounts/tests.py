from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Role, Student, Teacher, UserAccount
from .services import create_account


class UserModelTests(TestCase):
    def test_student_requires_student_role_for_profile(self):
        teacher_user = UserAccount.objects.create_user(
            "gv1", "pw123456", full_name="B", email="b@x.com", role=Role.TEACHER
        )
        with self.assertRaises(ValidationError):
            Student.objects.create(student_id="S1", user=teacher_user)

    def test_teacher_profile_requires_teacher_role(self):
        student_user = UserAccount.objects.create_user(
            "sv1", "pw123456", full_name="A", email="a@x.com", role=Role.STUDENT
        )
        with self.assertRaises(ValidationError):
            Teacher.objects.create(teacher_id="T0001", user=student_user)

    def test_student_id_unique(self):
        create_account(
            username="sv1", full_name="A", email="a@x.com",
            password="pw123456", role=Role.STUDENT, student_id="S1"
        )
        u2 = UserAccount.objects.create_user(
            "sv2", "pw123456", full_name="B", email="b@x.com", role=Role.STUDENT
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Student.objects.create(student_id="S1", user=u2)

    def test_role_is_immutable(self):
        u = create_account(
            username="sv1", full_name="A", email="a@x.com",
            password="pw123456", role=Role.STUDENT, student_id="S1"
        )
        u.role = Role.ADMIN
        with self.assertRaises(ValidationError):
            u.save()

    def test_password_is_hashed_with_pbkdf2(self):
        u = UserAccount.objects.create_user(
            "gv1", "pw123456", full_name="B", email="b@x.com", role=Role.TEACHER
        )
        self.assertNotEqual(u.password, "pw123456")
        self.assertTrue(u.password.startswith("pbkdf2_sha256$"))
        self.assertTrue(bool(u.salt))
