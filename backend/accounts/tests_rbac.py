import datetime

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.views import View

from classrooms.access import (
    assert_own_student, classrooms_for, get_classroom_or_403, sessions_for,
)
from classrooms.models import AttendanceSession, Classroom, Enrollment
from courses.models import Course

from .factories import make_user
from .models import Role
from .permissions import RoleRequiredMixin, role_required


def make_world():
    """2 teachers, 3 students, 2 classrooms: A (gv1: sv1, sv2) and B (gv2: sv3)."""
    w = type("World", (), {})()
    w.admin = make_user("ad1", Role.ADMIN)
    w.t1, w.t2 = make_user("gv1", Role.TEACHER), make_user("gv2", Role.TEACHER)
    w.sv1, w.sv2, w.sv3 = make_user("sv1"), make_user("sv2"), make_user("sv3")
    course = Course.objects.create(code="SE101", name="SE")
    w.a = Classroom.objects.create(class_id="CL0001", name="A", course=course,
                                   teacher=w.t1.teacher_profile)
    w.b = Classroom.objects.create(class_id="CL0002", name="B", course=course,
                                   teacher=w.t2.teacher_profile)
    for sv in (w.sv1, w.sv2):
        Enrollment.objects.create(classroom=w.a, student=sv.student_profile)
    Enrollment.objects.create(classroom=w.b, student=w.sv3.student_profile)
    mk = lambda room: AttendanceSession.objects.create(
        classroom=room, date=datetime.date(2026, 11, 9), start_time=datetime.time(8, 0), room="P1")
    w.sa, w.sb = mk(w.a), mk(w.b)
    return w


class RoleLayerTests(TestCase):
    """FR-03 layer 1: role."""

    def setUp(self):
        self.w = make_world()

    def test_anonymous_is_redirected_to_login_on_every_protected_url(self):
        urls = [reverse(n) for n in ("home", "user_list", "user_create", "course_list",
                                     "classroom_list", "classroom_create", "session_list",
                                     "threshold_settings")]
        urls += [reverse("classroom_detail", args=["CL0001"]),
                 reverse("session_detail", args=[self.w.sa.pk]),
                 reverse("user_detail", args=[self.w.t1.pk])]
        for url in urls:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn(reverse("login"), r["Location"], url)

    def test_teacher_and_student_get_403_on_every_admin_function(self):
        admin_urls = [
            reverse("user_list"), reverse("user_create"),
            reverse("user_detail", args=[self.w.t1.pk]),
            reverse("user_update", args=[self.w.t1.pk]),
            reverse("user_lock", args=[self.w.t1.pk]),
            reverse("user_unlock", args=[self.w.t1.pk]),
            reverse("course_list"), reverse("course_create"),
            reverse("course_detail", args=["SE101"]), reverse("course_update", args=["SE101"]),
            reverse("course_delete", args=["SE101"]),
            reverse("classroom_create"),
            reverse("classroom_update", args=["CL0001"]), reverse("classroom_delete", args=["CL0001"]),
            reverse("classroom_assign_teacher", args=["CL0001"]),
            reverse("classroom_add_students", args=["CL0001"]),
            reverse("classroom_remove_student", args=["CL0001", "SID-sv1"]),
            reverse("session_create", args=["CL0001"]),
            reverse("session_update", args=[self.w.sa.pk]),
            reverse("session_cancel", args=[self.w.sa.pk]),
            reverse("threshold_settings"),
        ]
        for user in (self.w.t1, self.w.sv1):
            self.client.force_login(user)
            for url in admin_urls:
                self.assertEqual(self.client.get(url).status_code, 403, (user.role, url))
                self.assertEqual(self.client.post(url, {}).status_code, 403, (user.role, url))

    def test_forbidden_post_changes_nothing(self):
        self.client.force_login(self.w.t1)
        self.client.post(reverse("user_lock", args=[self.w.sv1.pk]))
        self.client.post(reverse("classroom_delete", args=["CL0001"]))
        self.w.sv1.refresh_from_db()
        self.assertTrue(self.w.sv1.is_active)
        self.assertTrue(Classroom.objects.filter(pk="CL0001").exists())

    def test_403_page_reveals_no_data(self):
        self.client.force_login(self.w.sv1)
        r = self.client.get(reverse("user_detail", args=[self.w.t1.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertNotContains(r, "gv1", status_code=403)
        self.assertNotContains(r, "gv1@example.com", status_code=403)

    def test_admin_is_allowed(self):
        self.client.force_login(self.w.admin)
        for name in ("user_list", "course_list", "classroom_list", "threshold_settings"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_decorator_and_mixin_for_other_apps(self):
        rf = RequestFactory()

        @role_required(Role.TEACHER)
        def view(request):
            return HttpResponse("ok")

        class V(RoleRequiredMixin, View):
            allowed_roles = (Role.TEACHER,)

            def get(self, request):
                return HttpResponse("ok")

        for u, code in ((self.w.t1, 200), (self.w.sv1, 403), (self.w.admin, 403)):
            req = rf.get("/"); req.user = u
            if code == 200:
                self.assertEqual(view(req).status_code, 200)
                self.assertEqual(V.as_view()(req).status_code, 200)
            else:
                with self.assertRaises(PermissionDenied):
                    view(req)
                with self.assertRaises(PermissionDenied):
                    V.as_view()(req)


class DataScopeTests(TestCase):
    """FR-03 layer 2 / NFR Data Privacy: a Teacher and a Student reach only their own data."""

    def setUp(self):
        self.w = make_world()

    def test_scoped_querysets(self):
        w = self.w
        self.assertEqual(set(classrooms_for(w.admin)), {w.a, w.b})
        self.assertEqual(set(classrooms_for(w.t1)), {w.a})
        self.assertEqual(set(classrooms_for(w.t2)), {w.b})
        self.assertEqual(set(classrooms_for(w.sv1)), {w.a})
        self.assertEqual(set(classrooms_for(w.sv3)), {w.b})
        self.assertEqual(set(sessions_for(w.t1)), {w.sa})
        self.assertEqual(set(sessions_for(w.sv3)), {w.sb})

    def test_lists_only_show_own_classrooms(self):
        for user, own, other in ((self.w.t1, "A", "B"), (self.w.sv3, "B", "A")):
            self.client.force_login(user)
            r = self.client.get(reverse("classroom_list"))
            names = [c.name for c in r.context["classrooms"]]
            self.assertEqual(names, [own])
            self.assertNotContains(r, f">{other}</a>")

    def test_changing_the_id_in_the_url_is_denied(self):
        urls = [reverse("classroom_detail", args=["CL0002"]),
                reverse("session_detail", args=[self.w.sb.pk])]
        for user in (self.w.t1, self.w.sv1):
            self.client.force_login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403, (user.username, url))

    def test_non_admin_gets_403_even_for_ids_that_do_not_exist(self):
        """No difference between 'forbidden' and 'does not exist': nothing can be probed."""
        for user in (self.w.t1, self.w.sv1):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("classroom_detail", args=["CL9999"])).status_code, 403)
            self.assertEqual(self.client.get(reverse("session_detail", args=[99999])).status_code, 403)

    def test_admin_gets_404_for_missing_ids(self):
        self.client.force_login(self.w.admin)
        self.assertEqual(self.client.get(reverse("classroom_detail", args=["CL9999"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("session_detail", args=[99999])).status_code, 404)

    def test_own_classroom_is_visible(self):
        for user in (self.w.t1, self.w.sv1):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("classroom_detail", args=["CL0001"])).status_code, 200)
            self.assertEqual(self.client.get(reverse("session_detail", args=[self.w.sa.pk])).status_code, 200)

    def test_student_does_not_see_classmates_but_teacher_does(self):
        self.client.force_login(self.w.sv1)
        r = self.client.get(reverse("classroom_detail", args=["CL0001"]))
        self.assertIsNone(r.context["enrollments"])
        self.assertNotContains(r, "SID-sv2")
        self.client.force_login(self.w.t1)
        r = self.client.get(reverse("classroom_detail", args=["CL0001"]))
        self.assertContains(r, "SID-sv2")

    def test_replaced_teacher_loses_access_and_new_teacher_gains_it(self):
        self.client.force_login(self.w.admin)
        self.client.post(reverse("classroom_assign_teacher", args=["CL0001"]),
                         {"teacher": self.w.t2.teacher_profile.pk})
        self.client.force_login(self.w.t1)
        self.assertEqual(self.client.get(reverse("classroom_detail", args=["CL0001"])).status_code, 403)
        self.client.force_login(self.w.t2)
        self.assertEqual(self.client.get(reverse("classroom_detail", args=["CL0001"])).status_code, 200)

    def test_removed_student_loses_access(self):
        self.client.force_login(self.w.admin)
        self.client.post(reverse("classroom_remove_student", args=["CL0001", "SID-sv1"]))
        self.client.force_login(self.w.sv1)
        self.assertEqual(self.client.get(reverse("classroom_detail", args=["CL0001"])).status_code, 403)

    def test_helpers(self):
        self.assertEqual(get_classroom_or_403(self.w.t1, "CL0001"), self.w.a)
        with self.assertRaises(PermissionDenied):
            get_classroom_or_403(self.w.t1, "CL0002")
        assert_own_student(self.w.sv1, "SID-sv1")
        with self.assertRaises(PermissionDenied):
            assert_own_student(self.w.sv1, "SID-sv2")
        assert_own_student(self.w.t1, "SID-sv2")  # Teachers are limited by classroom, not here
