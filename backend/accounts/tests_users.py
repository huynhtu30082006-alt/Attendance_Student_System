from django.test import Client, TestCase
from django.urls import reverse

from .factories import PASSWORD, make_user
from .models import AccountStatus, Role, Student, UserAccount


class UserCrudTests(TestCase):
    def setUp(self):
        self.admin = make_user("ad1", Role.ADMIN)
        self.client.force_login(self.admin)

    def data(self, **kw):
        d = {"username": "sv9", "full_name": "Nguyen Van A", "email": "a@x.com",
             "role": "STUDENT", "student_id": "S9",
             "password1": PASSWORD, "password2": PASSWORD}
        d.update(kw)
        return d

    def test_create_student_ok_and_password_hashed(self):
        r = self.client.post(reverse("user_create"), self.data())
        u = UserAccount.objects.get(username="sv9")
        self.assertRedirects(r, reverse("user_detail", args=[u.pk]))
        self.assertEqual((u.role, u.status, u.student_id), (Role.STUDENT, AccountStatus.ACTIVE, "S9"))
        self.assertNotEqual(u.password, PASSWORD)
        self.assertTrue(u.check_password(PASSWORD))

    def test_create_teacher_and_admin(self):
        self.client.post(reverse("user_create"), self.data(username="gv9", role="TEACHER", student_id=""))
        self.client.post(reverse("user_create"), self.data(username="ad9", role="ADMIN", student_id=""))
        self.assertEqual(UserAccount.objects.get(username="gv9").teacher_id, "T0001")
        self.assertIsNone(UserAccount.objects.get(username="ad9").student_id)

    def test_student_without_student_id_rejected_and_nothing_saved(self):
        r = self.client.post(reverse("user_create"), self.data(student_id=""))
        self.assertEqual(r.status_code, 200)
        self.assertIn("student_id", r.context["form"].errors)
        self.assertFalse(UserAccount.objects.filter(username="sv9").exists())

    def test_teacher_with_student_id_rejected(self):
        r = self.client.post(reverse("user_create"), self.data(role="TEACHER"))
        self.assertIn("student_id", r.context["form"].errors)

    def test_duplicate_username_and_student_id_rejected(self):
        make_user("sv1")  # student_id = SID-sv1
        r = self.client.post(reverse("user_create"), self.data(username="sv1", student_id="S5"))
        self.assertIn("username", r.context["form"].errors)
        r = self.client.post(reverse("user_create"), self.data(username="SV1"))  # same name, other case
        self.assertIn("username", r.context["form"].errors)
        r = self.client.post(reverse("user_create"), self.data(student_id="SID-sv1"))
        self.assertIn("student_id", r.context["form"].errors)

    def test_missing_and_invalid_input_names_the_field(self):
        r = self.client.post(reverse("user_create"), self.data(email="not-an-email", full_name=" "))
        self.assertIn("email", r.context["form"].errors)
        self.assertIn("full_name", r.context["form"].errors)
        self.assertEqual(UserAccount.objects.count(), 1)

    def test_password_rules(self):
        r = self.client.post(reverse("user_create"), self.data(password1="abc", password2="abc"))
        self.assertIn("password1", r.context["form"].errors)
        r = self.client.post(reverse("user_create"), self.data(password2="Different1!"))
        self.assertIn("password2", r.context["form"].errors)
        self.assertFalse(UserAccount.objects.filter(username="sv9").exists())

    def test_list_and_detail_show_no_password(self):
        u = make_user("sv1")
        r = self.client.get(reverse("user_detail", args=[u.pk]))
        self.assertContains(r, "sv1")
        self.assertNotContains(r, u.password)
        r = self.client.get(reverse("user_list"))
        self.assertNotContains(r, u.password)

    # ---- update (FR-05) ----
    def test_update_info_username_and_password(self):
        u = make_user("sv1")
        r = self.client.post(reverse("user_update", args=[u.pk]), {
            "username": "sv1new", "full_name": "Ten Moi", "email": "new@x.com",
            "new_password": "NewPassw0rd!"})
        self.assertRedirects(r, reverse("user_detail", args=[u.pk]))
        u.refresh_from_db()
        self.assertEqual((u.username, u.full_name, u.email), ("sv1new", "Ten Moi", "new@x.com"))
        self.assertTrue(u.check_password("NewPassw0rd!"))

    def test_blank_password_keeps_the_old_one(self):
        u = make_user("sv1")
        self.client.post(reverse("user_update", args=[u.pk]), {
            "username": "sv1", "full_name": "X", "email": "x@x.com", "new_password": ""})
        u.refresh_from_db()
        self.assertTrue(u.check_password(PASSWORD))

    def test_update_cannot_change_role_or_student_id(self):
        u = make_user("sv1")
        self.client.post(reverse("user_update", args=[u.pk]), {
            "username": "sv1", "full_name": "Ten Moi", "email": "new@x.com",
            "role": "ADMIN", "student_id": "HACK"})
        u.refresh_from_db()
        self.assertEqual(u.full_name, "Ten Moi")
        self.assertEqual(u.role, Role.STUDENT)
        self.assertEqual(u.student_id, "SID-sv1")
        self.assertFalse(Student.objects.filter(student_id="HACK").exists())

    def test_edit_form_has_no_role_or_student_id_field(self):
        r = self.client.get(reverse("user_update", args=[make_user("sv1").pk]))
        self.assertNotIn("role", r.context["form"].fields)
        self.assertNotIn("student_id", r.context["form"].fields)

    def test_update_to_a_taken_username_is_rejected(self):
        make_user("sv2")
        u = make_user("sv1")
        r = self.client.post(reverse("user_update", args=[u.pk]), {
            "username": "sv2", "full_name": "X", "email": "x@x.com"})
        self.assertIn("username", r.context["form"].errors)
        u.refresh_from_db()
        self.assertEqual(u.username, "sv1")

    def test_keeping_own_username_is_not_a_duplicate(self):
        u = make_user("sv1")
        r = self.client.post(reverse("user_update", args=[u.pk]), {
            "username": "sv1", "full_name": "X", "email": "x@x.com"})
        self.assertEqual(r.status_code, 302)

    def test_student_phone_and_gender(self):
        u = make_user("sv1")
        self.client.post(reverse("user_update", args=[u.pk]), {
            "username": "sv1", "full_name": "X", "email": "x@x.com",
            "phone_number": "0901234567", "gender": "FEMALE"})
        p = Student.objects.get(user=u)
        self.assertEqual((p.phone_number, p.gender), ("0901234567", "FEMALE"))
        r = self.client.post(reverse("user_update", args=[u.pk]), {
            "username": "sv1", "full_name": "X", "email": "x@x.com", "phone_number": "12ab"})
        self.assertIn("phone_number", r.context["form"].errors)

    def test_changing_a_password_logs_that_user_out(self):
        u = make_user("sv1")
        victim = Client()
        victim.force_login(u)
        self.client.post(reverse("user_update", args=[u.pk]), {
            "username": "sv1", "full_name": "X", "email": "x@x.com", "new_password": "NewPassw0rd!"})
        self.assertEqual(victim.get(reverse("home")).status_code, 302)

    def test_admin_changing_own_password_stays_logged_in(self):
        self.client.post(reverse("user_update", args=[self.admin.pk]), {
            "username": "ad1", "full_name": "X", "email": "x@x.com", "new_password": "NewPassw0rd!"})
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    # ---- search ----
    def test_search_by_name_username_and_student_id(self):
        make_user("alice", full_name="Alice Nguyen", student_id="B100")
        make_user("bob", full_name="Bob Tran", student_id="B200")
        for q, want, other in [("alice", "alice", "bob"), ("Tran", "bob", "alice"),
                               ("B200", "bob", "alice")]:
            r = self.client.get(reverse("user_list"), {"q": q})
            names = [u.username for u in r.context["page"].object_list]
            self.assertIn(want, names)
            self.assertNotIn(other, names)

    def test_search_no_match_and_empty_keyword(self):
        r = self.client.get(reverse("user_list"), {"q": "zzzz"})
        self.assertContains(r, "No account matches")
        r = self.client.get(reverse("user_list"), {"q": "  "})
        self.assertContains(r, "Please enter a keyword")

    def test_search_does_not_break_on_sql_special_characters(self):
        for q in ("' OR 1=1 --", "%", "_", '"; DROP TABLE accounts_useraccount; --'):
            r = self.client.get(reverse("user_list"), {"q": q})
            self.assertEqual(r.status_code, 200)
        self.assertTrue(UserAccount.objects.exists())

    def test_filter_by_role(self):
        make_user("gv1", Role.TEACHER)
        make_user("sv1")
        r = self.client.get(reverse("user_list"), {"role": "TEACHER"})
        self.assertEqual([u.username for u in r.context["page"].object_list], ["gv1"])

    def test_xss_is_escaped(self):
        make_user("sv1", full_name="<script>alert(1)</script>")
        r = self.client.get(reverse("user_list"))
        self.assertNotContains(r, "<script>alert(1)</script>")

    # ---- lock / unlock ----
    def test_lock_needs_post_confirmation_then_unlock(self):
        u = make_user("sv1")
        self.client.get(reverse("user_lock", args=[u.pk]))  # only shows the confirmation page
        u.refresh_from_db()
        self.assertEqual(u.status, AccountStatus.ACTIVE)
        self.client.post(reverse("user_lock", args=[u.pk]))
        u.refresh_from_db()
        self.assertEqual(u.status, AccountStatus.LOCKED)
        self.client.get(reverse("user_unlock", args=[u.pk]))
        u.refresh_from_db()
        self.assertEqual(u.status, AccountStatus.LOCKED)
        self.client.post(reverse("user_unlock", args=[u.pk]))
        u.refresh_from_db()
        self.assertEqual(u.status, AccountStatus.ACTIVE)

    def test_lock_already_locked_and_unlock_already_active_change_nothing(self):
        u = make_user("sv1")
        r = self.client.post(reverse("user_unlock", args=[u.pk]), follow=True)
        self.assertContains(r, "not locked")
        self.client.post(reverse("user_lock", args=[u.pk]))
        r = self.client.post(reverse("user_lock", args=[u.pk]), follow=True)
        self.assertContains(r, "already locked")

    def test_admin_cannot_lock_self(self):
        self.client.post(reverse("user_lock", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.status, AccountStatus.ACTIVE)

    def test_locking_keeps_the_data(self):
        u = make_user("sv1")
        self.client.post(reverse("user_lock", args=[u.pk]))
        self.assertTrue(Student.objects.filter(student_id="SID-sv1").exists())
