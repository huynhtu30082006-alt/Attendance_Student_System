from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from accounts.permissions import admin_required
from accounts.utils import render_confirm

from .forms import CourseForm
from .models import Course

HAS_CLASSROOMS = "This course still has classrooms and cannot be deleted."


@admin_required
def course_list(request):
    return render(request, "courses/course_list.html", {"courses": Course.objects.all()})


@admin_required
def course_detail(request, pk):
    course = get_object_or_404(Course, pk=pk)
    return render(request, "courses/course_detail.html",
                  {"course": course, "classrooms": course.classrooms.select_related("teacher__user")})


@admin_required
@require_http_methods(["GET", "POST"])
def course_create(request):
    form = CourseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            course = form.save()
        except IntegrityError:  # same code submitted twice at the same moment
            form.add_error("code", "A course with this code already exists.")
        else:
            messages.success(request, "Course created.")
            return redirect("course_detail", pk=course.pk)
    return render(request, "form.html", {"title": "Create course", "form": form,
                                         "cancel_url": "course_list"})


@admin_required
@require_http_methods(["GET", "POST"])
def course_update(request, pk):
    course = get_object_or_404(Course, pk=pk)
    form = CourseForm(request.POST or None, instance=course)
    if request.method == "POST" and form.is_valid():
        try:
            course = form.save()  # may return a different object when the code changed
        except IntegrityError:
            form.add_error("code", "A course with this code already exists.")
        else:
            messages.success(request, "Course updated.")
            return redirect("course_detail", pk=course.pk)
    return render(request, "form.html", {"title": f"Edit course {course.code}",
                                         "form": form, "cancel_url": "course_list"})


@admin_required
@require_http_methods(["GET", "POST"])
def course_delete(request, pk):
    course = get_object_or_404(Course, pk=pk)
    back = reverse("course_detail", args=[pk])
    if course.has_classrooms():  # checked first, before asking for confirmation (use case 13)
        messages.error(request, HAS_CLASSROOMS)
        return redirect("course_detail", pk=pk)
    if request.method == "POST":
        try:
            with transaction.atomic():
                course.delete()
        except ProtectedError:  # a classroom was added between the check and the delete
            messages.error(request, HAS_CLASSROOMS)
            return redirect("course_detail", pk=pk)
        messages.success(request, "Course deleted.")
        return redirect("course_list")
    return render_confirm(request, "Delete course", f"Delete course {course.code} - {course.name}?", back)
