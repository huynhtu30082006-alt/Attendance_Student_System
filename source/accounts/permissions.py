"""Role-based authorization (task 2, FR-03). Used by every app.

Layer 1 - role: who may use a function at all.
    @admin_required / @teacher_required / @student_required / @role_required(...)   (function views)
    RoleRequiredMixin with allowed_roles = (...)                                    (class-based views)
Layer 2 - data: which rows a Teacher / Student may see. See classrooms/access.py
    (@classroom_scoped, @session_scoped, classrooms_for, sessions_for ...).

Not logged in -> redirect to the login page. Logged in but not allowed -> 403 without any data."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied

from .models import Role


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return login_required(_wrapped)

    return decorator


admin_required = role_required(Role.ADMIN)
teacher_required = role_required(Role.TEACHER)
student_required = role_required(Role.STUDENT)
admin_or_teacher_required = role_required(Role.ADMIN, Role.TEACHER)


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """For class-based views: declare allowed_roles = (Role.ADMIN, ...)."""

    allowed_roles = ()

    def test_func(self):
        return self.request.user.role in self.allowed_roles
