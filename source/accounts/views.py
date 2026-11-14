from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from . import services
from .bruteforce import lockout_until, purge_old_attempts, record_attempt
from .forms import LoginForm, UserCreateForm, UserUpdateForm
from .models import Role, UserAccount
from .permissions import admin_required
from .utils import render_confirm

# Never reveal whether the username or the password was wrong (NFR Brute-Force Protection)
GENERIC_LOGIN_ERROR = "Incorrect username or password, or the account is locked."
LOCKOUT_ERROR = "Too many failed login attempts. Please try again in 15 minutes."


# ---------- Task 1: login / logout ----------
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = LoginForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():  # empty fields -> field errors, nothing recorded
        username = form.cleaned_data["username"]
        if lockout_until(username):
            # Rejected without even checking the password; not recorded, so the lock cannot be extended forever
            error = LOCKOUT_ERROR
        else:
            user = authenticate(request, username=username,
                                password=form.cleaned_data["password"])
            record_attempt(username, succeeded=user is not None)
            if user is not None:  # authenticate() already refuses a locked account
                login(request, user)  # new session key (no session fixation)
                purge_old_attempts()
                nxt = request.GET.get("next")
                if nxt and url_has_allowed_host_and_scheme(
                    nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
                ):
                    return redirect(nxt)
                return redirect("home")
            error = GENERIC_LOGIN_ERROR
    return render(request, "accounts/login.html", {"form": form, "error": error})


@require_POST
def logout_view(request):
    logout(request)  # flushes the session on the server, so the old cookie is useless at once
    return redirect("login")


@login_required
def home(request):
    return render(request, "home.html", {"role": request.user.role})


# ---------- Task 3: account CRUD + search (Admin only) ----------
@admin_required
def user_list(request):
    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    users = UserAccount.objects.select_related("student_profile", "teacher_profile").order_by("username")
    if "q" in request.GET and not q:
        messages.error(request, "Please enter a keyword to search.")
    if q:
        users = users.filter(
            Q(full_name__icontains=q) | Q(username__icontains=q)
            | Q(student_profile__student_id__icontains=q)
        )
    if role in Role.values:
        users = users.filter(role=role)
    page = Paginator(users, 20).get_page(request.GET.get("page"))
    return render(request, "accounts/user_list.html",
                  {"page": page, "q": q, "role": role, "roles": Role.choices})


@admin_required
def user_detail(request, pk):
    target = get_object_or_404(
        UserAccount.objects.select_related("student_profile", "teacher_profile"), pk=pk)
    return render(request, "accounts/user_detail.html", {"target": target})


@admin_required
@require_http_methods(["GET", "POST"])
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            user = services.create_account(
                username=d["username"], password=d["password1"], full_name=d["full_name"],
                email=d["email"], role=d["role"], student_id=d["student_id"])
        except IntegrityError:  # two Admins submitting the same username / student ID at once
            form.add_error(None, "The username or the student ID is already used.")
        else:
            messages.success(request, "Account created.")
            return redirect("user_detail", pk=user.pk)
    return render(request, "form.html", {"title": "Create account", "form": form,
                                         "cancel_url": "user_list"})


@admin_required
@require_http_methods(["GET", "POST"])
def user_update(request, pk):
    target = get_object_or_404(UserAccount.objects.select_related("student_profile"), pk=pk)
    form = UserUpdateForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            services.update_account(
                target, username=d["username"], full_name=d["full_name"], email=d["email"],
                password=d.get("new_password"), phone_number=d.get("phone_number"),
                gender=d.get("gender"))
        except IntegrityError:
            form.add_error("username", "This username is already used.")
        else:
            if target.pk == request.user.pk and d.get("new_password"):
                update_session_auth_hash(request, target)  # the Admin who changed own password stays logged in
            messages.success(request, "Account updated.")
            return redirect("user_detail", pk=pk)
    return render(request, "form.html", {"title": f"Edit account {target.username}",
                                         "form": form, "cancel_url": "user_list"})


@admin_required
@require_http_methods(["GET", "POST"])
def user_lock(request, pk):
    target = get_object_or_404(UserAccount, pk=pk)
    back = reverse("user_detail", args=[pk])
    if target.pk == request.user.pk:
        messages.error(request, "You cannot lock your own account.")
        return redirect(back)
    if target.is_locked:
        messages.info(request, "This account is already locked. Nothing changed.")
        return redirect(back)
    if request.method == "POST":
        services.lock_account(target)  # status -> Locked and every session of the user is ended
        messages.success(request, "Account locked. The user has been logged out.")
        return redirect(back)
    return render_confirm(
        request, "Lock account",
        f"Lock account {target.username}? This user will be logged out immediately.", back)


@admin_required
@require_http_methods(["GET", "POST"])
def user_unlock(request, pk):
    target = get_object_or_404(UserAccount, pk=pk)
    back = reverse("user_detail", args=[pk])
    if not target.is_locked:
        messages.info(request, "This account is not locked. Nothing changed.")
        return redirect(back)
    if request.method == "POST":
        services.unlock_account(target)
        messages.success(request, "Account unlocked.")
        return redirect(back)
    return render_confirm(request, "Unlock account", f"Unlock account {target.username}?", back)
