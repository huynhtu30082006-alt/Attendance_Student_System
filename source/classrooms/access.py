"""Row-level access (task 2, FR-03, NFR Data Privacy): a Teacher reaches only the classrooms assigned
to them, a Student only the classrooms they are enrolled in and their own data, the Admin everything.
BE2 reuses these helpers for attendance and reports.

    classrooms_for(user) / sessions_for(user)     querysets already limited to what the user may see
    @classroom_scoped / @session_scoped           decorators that load the object from the URL or
                                                  answer 403, then pass it to the view
    assert_own_student(user, student_id)          a Student may only ask for their own student ID

A non-Admin who asks for something outside their scope gets 403 whether or not it exists, so changing an
ID in the URL reveals nothing. The Admin gets 404 for an ID that does not exist."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from accounts.models import Role

from .models import AttendanceSession, Classroom


def classrooms_for(user):
    """Admin: all. Teacher: assigned classrooms. Student: enrolled classrooms."""
    qs = Classroom.objects.select_related("course", "teacher__user")
    if user.role == Role.ADMIN:
        return qs
    if user.role == Role.TEACHER:
        return qs.filter(teacher__user=user)
    if user.role == Role.STUDENT:
        return qs.filter(enrollments__student__user=user)
    return qs.none()


def get_classroom_or_403(user, pk):
    try:
        return classrooms_for(user).get(pk=pk)
    except Classroom.DoesNotExist:
        if user.role == Role.ADMIN:
            get_object_or_404(Classroom, pk=pk)  # raises 404
        raise PermissionDenied


def sessions_for(user):
    return (AttendanceSession.objects.filter(classroom__in=classrooms_for(user))
            .select_related("classroom__course"))


def get_session_or_403(user, pk):
    try:
        return sessions_for(user).get(pk=pk)
    except AttendanceSession.DoesNotExist:
        if user.role == Role.ADMIN:
            get_object_or_404(AttendanceSession, pk=pk)
        raise PermissionDenied


def assert_own_student(user, student_id):
    """A Student may only access their own data (their own student ID)."""
    if user.role == Role.STUDENT and user.student_id != student_id:
        raise PermissionDenied


def _scoped(getter):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, pk, **kwargs):
            obj = getter(request.user, pk)
            return view_func(request, obj, *args, **kwargs)

        return login_required(_wrapped)

    return decorator


classroom_scoped = _scoped(get_classroom_or_403)
session_scoped = _scoped(get_session_or_403)
