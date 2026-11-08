from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db.models import F
from django.test import Client, TestCase
from django.urls import reverse

from .factories import PASSWORD, make_user
from .models import AccountStatus, LoginAttempt, Role
from .services import lock_account, unlock_account


def logged_in(client):
    return "_auth_user_id" in client.session


class LoginTests(TestCase):
    def setUp(self):
        self.user = make_user("gv1", Role.TEACHER)
        self.url = reverse("login")

    def test_login_success_goes_to_home(self):
        r = self.client.post(self.url, {"username": "gv1", "password": PASSWORD})
        self.assertRedirects(r, reverse("home"))
        self.assertTrue(logged_in(self.client))

    def test_wrong_password_shows_generic_error(self):
        r = self.client.post(self.url, {"username": "gv1", "password": "sai"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(logged_in(self.client))
        wrong_user = self.client.post(self.url, {"username": "khongco", "password": "sai"})
        # Identical messages: do not reveal whether the username exists
        self.assertEqual(r.context["error"], wrong_user.context["error"])

    def test_empty_fields_are_reported_and_not_counted(self):
        r = self.client.post(self.url, {"username": "", "password": ""})
        self.assertIn("username", r.context["form"].errors)
        self.assertIn("password", r.context["form"].errors)
        self.assertEqual(LoginAttempt.objects.count(), 0)

    def test_locked_account_cannot_login_even_with_correct_password(self):
        lock_account(self.user)
        r = self.client.post(self.url, {"username": "gv1", "password": PASSWORD})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(logged_in(self.client))
        # Same message as a wrong password: the page does not tell that the account exists
        wrong = Client().post(self.url, {"username": "gv1", "password": "sai"})
        self.assertEqual(r.context["error"], wrong.context["error"])

    def test_unlocked_account_can_login_again(self):
        lock_account(self.user)
        unlock_account(self.user)
        self.client.post(self.url, {"username": "gv1", "password": PASSWORD})
        self.assertTrue(logged_in(self.client))

    def test_logged_in_user_is_redirected_away_from_login(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(self.url), reverse("home"))

    def test_open_redirect_is_blocked(self):
        r = self.client.post(self.url + "?next=https://evil.example.com/",
                             {"username": "gv1", "password": PASSWORD})
        self.assertRedirects(r, reverse("home"))

    def test_safe_next_is_followed(self):
        r = self.client.post(self.url + "?next=/classrooms/",
                             {"username": "gv1", "password": PASSWORD})
        self.assertRedirects(r, "/classrooms/", fetch_redirect_response=False)


class LogoutTests(TestCase):
    def setUp(self):
        self.user = make_user("gv1", Role.TEACHER)

    def test_logout_requires_post_and_ends_session(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        r = self.client.post(reverse("logout"))
        self.assertRedirects(r, reverse("login"))
        self.assertFalse(logged_in(self.client))

    def test_old_session_cookie_is_useless_after_logout(self):
        self.client.post(reverse("login"), {"username": "gv1", "password": PASSWORD})
        stolen = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.client.post(reverse("logout"))
        replay = Client()
        replay.cookies[settings.SESSION_COOKIE_NAME] = stolen
        r = replay.get(reverse("home"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])

    def test_logout_without_session_goes_to_login(self):
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))

    def test_protected_page_needs_login_again_after_logout(self):
        self.client.force_login(self.user)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("classroom_list")).status_code, 302)


class LockLogsOutImmediatelyTests(TestCase):
    """Task 1: locking an account blocks it at once."""

    def setUp(self):
        self.user = make_user("gv1", Role.TEACHER)

    def test_next_request_is_rejected(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        lock_account(self.user)
        r = self.client.get(reverse("home"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])

    def test_session_is_deleted_so_unlock_does_not_revive_it(self):
        self.client.force_login(self.user)
        self.assertEqual(Session.objects.count(), 1)
        lock_account(self.user)
        self.assertEqual(Session.objects.count(), 0)
        unlock_account(self.user)
        r = self.client.get(reverse("home"))
        self.assertEqual(r.status_code, 302)  # must log in again

    def test_other_users_sessions_are_kept(self):
        other = Client()
        other.force_login(make_user("gv2", Role.TEACHER))
        self.client.force_login(self.user)
        lock_account(self.user)
        self.assertEqual(other.get(reverse("home")).status_code, 200)

    def test_locking_through_the_admin_page_logs_the_user_out(self):
        admin = Client()
        admin.force_login(make_user("ad1", Role.ADMIN))
        self.client.force_login(self.user)
        admin.post(reverse("user_lock", args=[self.user.pk]))
        self.assertEqual(self.client.get(reverse("home")).status_code, 302)


class BruteForceTests(TestCase):
    def setUp(self):
        make_user("gv1", Role.TEACHER)
        self.url = reverse("login")

    def fail(self, n, username="gv1"):
        for _ in range(n):
            self.client.post(self.url, {"username": username, "password": "sai"})

    def test_four_failures_do_not_lock(self):
        self.fail(4)
        self.client.post(self.url, {"username": "gv1", "password": PASSWORD})
        self.assertTrue(logged_in(self.client))

    def test_five_failures_lock_even_with_correct_password(self):
        self.fail(5)
        r = self.client.post(self.url, {"username": "gv1", "password": PASSWORD})
        self.assertFalse(logged_in(self.client))
        self.assertEqual(r.status_code, 200)

    def test_lock_applies_per_username(self):
        make_user("gv2", Role.TEACHER)
        self.fail(5)
        self.client.post(self.url, {"username": "gv2", "password": PASSWORD})
        self.assertTrue(logged_in(self.client))

    def test_attempts_during_the_lock_do_not_extend_it(self):
        self.fail(5)
        self.fail(3)
        LoginAttempt.objects.update(attempted_at=F("attempted_at") - timedelta(minutes=16))
        self.client.post(self.url, {"username": "gv1", "password": PASSWORD})
        self.assertTrue(logged_in(self.client))

    def test_lock_still_active_after_14_minutes(self):
        self.fail(5)
        LoginAttempt.objects.update(attempted_at=F("attempted_at") - timedelta(minutes=14))
        self.client.post(self.url, {"username": "gv1", "password": PASSWORD})
        self.assertFalse(logged_in(self.client))

    def test_lock_expires_after_15_minutes(self):
        self.fail(5)
        LoginAttempt.objects.update(attempted_at=F("attempted_at") - timedelta(minutes=16))
        self.client.post(self.url, {"username": "gv1", "password": PASSWORD})
        self.assertTrue(logged_in(self.client))

    def test_failures_spread_over_more_than_10_minutes_do_not_lock(self):
        self.fail(5)
        for i, a in enumerate(LoginAttempt.objects.order_by("id")):
            a.attempted_at = a.attempted_at - timedelta(minutes=3 * (5 - i))
            a.save()
        self.client.post(self.url, {"username": "gv1", "password": PASSWORD})
        self.assertTrue(logged_in(self.client))

    def test_a_successful_login_resets_the_count(self):
        self.fail(4)
        self.client.post(self.url, {"username": "gv1", "password": PASSWORD})
        self.client.post(self.url.replace("login", "logout"))
        self.fail(4)
        self.client.post(self.url, {"username": "gv1", "password": PASSWORD})
        self.assertTrue(logged_in(self.client))

    def test_unknown_username_is_throttled_the_same_way(self):
        self.fail(5, username="khongco")
        r = self.client.post(self.url, {"username": "khongco", "password": "x"})
        self.assertIn("15 minutes", r.context["error"])


class SessionSettingsTests(TestCase):
    def test_settings(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 1800)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)  # 30 minutes of INACTIVITY
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")

    def test_session_cookie_flags(self):
        make_user("gv1", Role.TEACHER)
        self.client.post(reverse("login"), {"username": "gv1", "password": PASSWORD})
        cookie = self.client.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")

    def test_server_side_session_expires_in_30_minutes(self):
        make_user("gv1", Role.TEACHER)
        self.client.post(reverse("login"), {"username": "gv1", "password": PASSWORD})
        self.assertEqual(self.client.session.get_expiry_age(), 1800)

    def test_expired_session_is_rejected(self):
        u = make_user("gv1", Role.TEACHER)
        self.client.force_login(u)
        Session.objects.update(expire_date=F("expire_date") - timedelta(minutes=31))
        r = self.client.get(reverse("home"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])

    def test_password_not_shown_in_login_error_page(self):
        make_user("gv1", Role.TEACHER)
        r = self.client.post(reverse("login"), {"username": "gv1", "password": "secret-guess"})
        self.assertNotContains(r, "secret-guess")
