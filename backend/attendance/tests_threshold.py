from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.factories import make_user
from accounts.models import Role

from .models import Setting, get_absence_threshold


class ThresholdTests(TestCase):
    def admin(self):
        self.client.force_login(make_user("ad1", Role.ADMIN))

    def post(self, value):
        return self.client.post(reverse("threshold_settings"), {"absence_threshold": value})

    def test_default_is_20(self):
        self.assertEqual(Setting.get().absence_threshold, 20)
        self.assertEqual(get_absence_threshold(), Decimal("20"))

    def test_page_shows_the_current_value(self):
        self.admin()
        r = self.client.get(reverse("threshold_settings"))
        self.assertContains(r, 'name="absence_threshold" value="20"')

    def test_admin_can_update_and_value_persists(self):
        self.admin()
        r = self.post("30")
        self.assertRedirects(r, reverse("threshold_settings"))
        self.assertEqual(Setting.get().absence_threshold, 30)
        self.assertEqual(Setting.objects.count(), 1)
        self.assertEqual(get_absence_threshold(), Decimal("30"))

    def test_boundaries_and_decimals_accepted(self):
        self.admin()
        for ok in ("0", "100", "12.5"):
            self.post(ok)
            self.assertEqual(Setting.get().absence_threshold, Decimal(ok))

    def test_invalid_values_rejected_and_value_unchanged(self):
        self.admin()
        for bad in ("150", "100.01", "-5", "", "abc", "NaN", "Infinity", "1e3", "20.123"):
            r = self.post(bad)
            self.assertEqual(r.status_code, 200, bad)
            self.assertIn("absence_threshold", r.context["form"].errors, bad)
        self.assertEqual(Setting.get().absence_threshold, 20)

    def test_database_rejects_out_of_range_values(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Setting.objects.filter(pk=Setting.get().pk).update(absence_threshold=500)

    def test_teacher_student_and_anonymous_cannot_use_it(self):
        self.assertEqual(self.client.get(reverse("threshold_settings")).status_code, 302)
        for user in (make_user("gv1", Role.TEACHER), make_user("sv1")):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("threshold_settings")).status_code, 403)
            self.assertEqual(self.post("50").status_code, 403)
        self.assertEqual(Setting.get().absence_threshold, 20)
