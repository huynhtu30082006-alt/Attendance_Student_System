from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from accounts.models import AccountStatus, Role, Student, Teacher
from accounts.permissions import admin_required
from accounts.utils import create_with_code, render_confirm
from courses.models import Course

from .access import classroom_scoped, classrooms_for, session_scoped, sessions_for
from .forms import AddStudentsForm, AssignTeacherForm, ClassroomForm, SessionForm
from .models import AttendanceSession, Classroom, Enrollment, SessionStatus

CLASS_PREFIX = "CL"
HAS_RECORDS = "This classroom already has attendance records and cannot be deleted."


# ---------- View (all roles, each limited to their own data: task 2) ----------
@login_required
def classroom_list(request):
    return render(request, "teacher/classroom_list.html", {
        "classrooms": classrooms_for(request.user),  # ordered by course, then name (grouped by course in the page)
        "can_manage": request.user.role == Role.ADMIN,
    })


@classroom_scoped
def classroom_detail(request, classroom):
    is_student = request.user.role == Role.STUDENT
    return render(request, "teacher/classroom_detail.html", {
        "classroom": classroom,
        "can_manage": request.user.role == Role.ADMIN,
        # A Student must not see the other Students (Data Privacy)
        "enrollments": None if is_student else
        classroom.enrollments.select_related("student__user").order_by("student__student_id"),
        "sessions": classroom.sessions.all(),
    })


# ---------- Task 5: classroom CRUD ----------
@admin_required
@require_http_methods(["GET", "POST"])
def classroom_create(request):
    if not Course.objects.exists():
        messages.error(request, "Create a course first: a classroom must belong to a course.")
        return redirect("classroom_list")
    form = ClassroomForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            classroom = create_with_code(
                Classroom, "class_id", CLASS_PREFIX,
                name=form.cleaned_data["name"], course=form.cleaned_data["course"])
        except IntegrityError:
            form.add_error("name", "This course already has a classroom with this name.")
        else:
            messages.success(request, "Classroom created.")
            return redirect("classroom_detail", pk=classroom.pk)
    return render(request, "form.html", {"title": "Create classroom", "form": form,
                                         "cancel_url": "classroom_list"})


@admin_required
@require_http_methods(["GET", "POST"])
def classroom_update(request, pk):
    classroom = get_object_or_404(Classroom, pk=pk)
    form = ClassroomForm(request.POST or None, instance=classroom)  # teacher / students are not edited here
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except IntegrityError:
            form.add_error("name", "This course already has a classroom with this name.")
        else:
            messages.success(request, "Classroom updated.")
            return redirect("classroom_detail", pk=pk)
    return render(request, "form.html", {"title": f"Edit classroom {classroom.name}", "form": form,
                                         "cancel_url": "classroom_list"})


@admin_required
@require_http_methods(["GET", "POST"])
def classroom_delete(request, pk):
    classroom = get_object_or_404(Classroom, pk=pk)
    if classroom.has_attendance_records():  # checked first, before asking for confirmation (use case 16)
        messages.error(request, HAS_RECORDS)
        return redirect("classroom_detail", pk=pk)
    if request.method == "POST":
        try:
            with transaction.atomic():
                # Removes the classroom with its enrollments and its sessions (none has records)
                classroom.delete()
        except ProtectedError:  # a record appeared between the check and the delete
            messages.error(request, HAS_RECORDS)
            return redirect("classroom_detail", pk=pk)
        messages.success(request, "Classroom deleted.")
        return redirect("classroom_list")
    return render_confirm(request, "Delete classroom", f"Delete classroom {classroom}?",
                          reverse("classroom_detail", args=[pk]))


@admin_required
@require_http_methods(["GET", "POST"])
def classroom_assign_teacher(request, pk):
    classroom = get_object_or_404(Classroom, pk=pk)
    if not Teacher.objects.filter(user__status=AccountStatus.ACTIVE).exists():
        messages.error(request, "No active Teacher account exists.")
        return redirect("classroom_detail", pk=pk)
    form = AssignTeacherForm(request.POST or None, initial={"teacher": classroom.teacher_id})
    if request.method == "POST" and form.is_valid():
        teacher = form.cleaned_data["teacher"]
        if teacher.pk == classroom.teacher_id:
            messages.info(request, "This Teacher is already assigned. Nothing changed.")
        else:
            classroom.assign_teacher(teacher)  # replaces the previous Teacher, who loses access at once
            messages.success(request, "Teacher assigned.")
        return redirect("classroom_detail", pk=pk)
    return render(request, "form.html", {"title": f"Assign teacher to {classroom}",
                                         "form": form, "cancel_url": "classroom_list"})


@admin_required
@require_http_methods(["GET", "POST"])
def classroom_add_students(request, pk):
    classroom = get_object_or_404(Classroom, pk=pk)
    form = AddStudentsForm(request.POST or None, classroom=classroom)
    if not form.fields["students"].queryset.exists():
        messages.error(request, "No Student available: every Student is already enrolled.")
        return redirect("classroom_detail", pk=pk)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():  # several Students: all or nothing
                Enrollment.objects.bulk_create(
                    [Enrollment(classroom=classroom, student=s)
                     for s in form.cleaned_data["students"]])
        except IntegrityError:  # someone enrolled one of them a moment ago
            messages.error(request, "Some Students were already enrolled. Nothing was saved.")
            return redirect("classroom_add_students", pk=pk)
        messages.success(request, "Students added to the classroom.")
        return redirect("classroom_detail", pk=pk)
    return render(request, "form.html", {"title": f"Add Students to {classroom}",
                                         "form": form, "cancel_url": "classroom_list"})


@admin_required
@require_http_methods(["GET", "POST"])
def classroom_remove_student(request, pk, student_pk):
    enrollment = get_object_or_404(
        Enrollment.objects.select_related("student__user"), classroom_id=pk, student_id=student_pk)
    back = reverse("classroom_detail", args=[pk])
    if request.method == "POST":
        enrollment.classroom.remove_student(enrollment.student)  # only the enrollment goes
        messages.success(request, "Student removed from the classroom (attendance records kept).")
        return redirect(back)
    return render_confirm(
        request, "Remove Student from classroom",
        f"Remove {enrollment.student.full_name} from the classroom? Attendance records will be kept.",
        back)


# ---------- Task 6: session CRUD ----------
@login_required
def session_list(request):
    sessions = sessions_for(request.user)
    classroom_id = request.GET.get("classroom")
    if classroom_id:
        sessions = sessions.filter(classroom_id=classroom_id)
    return render(request, "classrooms/session_list.html", {
        "sessions": sessions, "can_manage": request.user.role == Role.ADMIN})


@session_scoped
def session_detail(request, session):
    return render(request, "classrooms/session_detail.html", {
        "session": session, "can_manage": request.user.role == Role.ADMIN})


@admin_required
@require_http_methods(["GET", "POST"])
def session_create(request, pk):
    classroom = get_object_or_404(Classroom, pk=pk)
    form = SessionForm(request.POST or None, classroom=classroom)
    if request.method == "POST" and form.is_valid():
        session = form.save(commit=False)
        session.classroom = classroom
        session.status = SessionStatus.SCHEDULED  # a new session is always Scheduled
        try:
            with transaction.atomic():
                session.save()
        except IntegrityError:  # same slot submitted twice at the same moment (database unique constraint)
            form.add_error(None, "This classroom already has a session at this date and time.")
        else:
            messages.success(request, "Session created.")
            return redirect("classroom_detail", pk=pk)
    return render(request, "form.html", {"title": f"Create session for {classroom}",
                                         "form": form, "cancel_url": "classroom_list"})


NOT_SCHEDULED = "Only Scheduled sessions can be edited or cancelled."


@admin_required
@require_http_methods(["GET", "POST"])
def session_update(request, pk):
    with transaction.atomic():
        # Lock the row so that a Teacher opening the session at the same moment cannot slip through
        session = get_object_or_404(
            AttendanceSession.objects.select_for_update().select_related("classroom"), pk=pk)
        if not session.is_scheduled:
            messages.error(request, NOT_SCHEDULED)
            return redirect("classroom_detail", pk=session.classroom_id)
        form = SessionForm(request.POST or None, instance=session, classroom=session.classroom)
        if request.method == "POST" and form.is_valid():
            try:
                with transaction.atomic():
                    form.save()  # status stays Scheduled: the form has no status field
            except IntegrityError:
                form.add_error(None, "This classroom already has a session at this date and time.")
            else:
                messages.success(request, "Session updated.")
                return redirect("classroom_detail", pk=session.classroom_id)
    return render(request, "form.html", {"title": "Edit session", "form": form,
                                         "cancel_url": "classroom_list"})


@admin_required
@require_http_methods(["GET", "POST"])
def session_cancel(request, pk):
    back = None
    with transaction.atomic():
        session = get_object_or_404(
            AttendanceSession.objects.select_for_update().select_related("classroom"), pk=pk)
        back = reverse("classroom_detail", args=[session.classroom_id])
        if not session.is_scheduled:
            messages.error(request, NOT_SCHEDULED)
            return redirect(back)
        if request.method == "POST":
            session.cancel()
            messages.success(request, "Session cancelled.")
            return redirect(back)
    return render_confirm(request, "Cancel session", f"Cancel session {session}?", back)
