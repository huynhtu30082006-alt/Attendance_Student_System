from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from .factories import PASSWORD, make_user
from .models import AccountStatus, Role, Student, Teacher, UserAccount
from .services import create_account


class ProfileTests(TestCase):
    """ERD: UserAccount 1 -- 0..1 Teacher / Student."""

    def test_student_has_student_profile_and_no_teacher_profile(self):
        u = make_user("sv1", student_id="S1")
        self.assertEqual(u.student_profile.student_id, "S1")
        self.assertEqual(u.student_id, "S1")
        self.assertIsNone(u.teacher_id)

    def test_teacher_gets_generated_teacher_id(self):
        a, b = make_user("gv1", Role.TEACHER), make_user("gv2", Role.TEACHER)
        self.assertEqual((a.teacher_id, b.teacher_id), ("T0001", "T0002"))

    def test_admin_has_no_profile(self):
        u = make_user("ad1", Role.ADMIN)
        self.assertIsNone(u.student_id)
        self.assertIsNone(u.teacher_id)
        self.assertFalse(Student.objects.exists() or Teacher.objects.exists())

    def test_student_without_student_id_is_not_created(self):
        with self.assertRaises(ValueError):
            create_account("sv1", PASSWORD, "A", "a@x.com", Role.STUDENT)
        self.assertFalse(UserAccount.objects.exists())  # atomic: no half-created account

    def test_student_id_unique(self):
        make_user("sv1", student_id="S1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_user("sv2", student_id="S1")
        self.assertFalse(UserAccount.objects.filter(username="sv2").exists())

    def test_username_unique(self):
        make_user("sv1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_user("sv1", student_id="other")

    def test_a_student_profile_needs_a_student_account(self):
        t = make_user("gv1", Role.TEACHER)
        with self.assertRaises(ValidationError):
            Student(student_id="X", user=t).save()

    def test_student_name_and_email_come_from_the_account(self):
        s = make_user("sv1", full_name="Nguyen A", email="a@x.com").student_profile
        self.assertEqual((s.full_name, s.email), ("Nguyen A", "a@x.com"))


class ImmutabilityTests(TestCase):
    def test_role_cannot_change(self):
        u = make_user("sv1")
        u.role = Role.ADMIN
        with self.assertRaises(ValidationError):
            u.save()
        u.refresh_from_db()
        self.assertEqual(u.role, Role.STUDENT)

    def test_student_id_cannot_change(self):
        s = make_user("sv1", student_id="S1").student_profile
        s.student_id = "S2"
        with self.assertRaises((ValidationError, IntegrityError)), transaction.atomic():
            s.save()
        self.assertEqual(list(Student.objects.values_list("student_id", flat=True)), ["S1"])


class PasswordTests(TestCase):
    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"])
    def test_password_is_a_salted_pbkdf2_hash(self):
        u = make_user("gv1", Role.TEACHER)
        u2 = make_user("gv2", Role.TEACHER)
        self.assertTrue(u.password.startswith("pbkdf2_sha256$"))
        self.assertNotIn(PASSWORD, u.password)
        self.assertTrue(u.check_password(PASSWORD))
        self.assertTrue(u.salt)
        self.assertNotEqual(u.salt, u2.salt)          # same password, different salt
        self.assertNotEqual(u.password, u2.password)


class StatusTests(TestCase):
    def test_locked_account_is_not_active(self):
        u = make_user("sv1")
        self.assertTrue(u.is_active)
        u.status = AccountStatus.LOCKED
        self.assertFalse(u.is_active)
