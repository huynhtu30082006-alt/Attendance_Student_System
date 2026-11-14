from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Gender, Role, Student, UserAccount


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150, label="Username")
    password = forms.CharField(widget=forms.PasswordInput, label="Password")


class _UsernameMixin:
    def _check_username(self, exclude_pk=None):
        username = self.cleaned_data["username"].strip()
        taken = UserAccount.objects.filter(username__iexact=username)
        if exclude_pk is not None:
            taken = taken.exclude(pk=exclude_pk)
        if taken.exists():
            raise forms.ValidationError("This username is already used.")
        return username

    def _check_password(self, password, username):
        try:
            validate_password(password, user=UserAccount(username=username or ""))
        except ValidationError as e:
            raise forms.ValidationError(e.messages)
        return password


class UserCreateForm(_UsernameMixin, forms.Form):
    """FR-04: full name, username, password, email, one role; a Student also has a student ID."""

    username = forms.CharField(max_length=50)
    full_name = forms.CharField(max_length=30)
    email = forms.EmailField(max_length=50)
    role = forms.ChoiceField(choices=Role.choices)
    student_id = forms.CharField(max_length=20, required=False, label="Student ID")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def clean_username(self):
        return self._check_username()

    def clean_full_name(self):
        value = self.cleaned_data["full_name"].strip()
        if not value:
            raise forms.ValidationError("This field is required.")
        return value

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        sid = (cleaned.get("student_id") or "").strip() or None
        if role == Role.STUDENT and not sid:
            self.add_error("student_id", "A Student must have a student ID.")
        elif role and role != Role.STUDENT and sid:
            self.add_error("student_id", "Only a Student can have a student ID.")
        elif sid and Student.objects.filter(student_id__iexact=sid).exists():
            self.add_error("student_id", "This student ID is already used.")
        cleaned["student_id"] = sid

        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        elif p1:
            try:
                self._check_password(p1, cleaned.get("username"))
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return cleaned


class UserUpdateForm(_UsernameMixin, forms.Form):
    """FR-05 / use case 'Update User Account': full name, username, email and password.
    There is deliberately no role and no student ID field. Phone number and gender are the optional
    Student details of the class diagram and are only shown for a Student account."""

    username = forms.CharField(max_length=50)
    full_name = forms.CharField(max_length=30)
    email = forms.EmailField(max_length=50)
    new_password = forms.CharField(
        label="New password", required=False, widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep the current password.",
    )

    def __init__(self, *args, instance, **kwargs):
        self.instance = instance
        initial = {"username": instance.username, "full_name": instance.full_name,
                   "email": instance.email}
        self.is_student = instance.role == Role.STUDENT
        if self.is_student:
            initial.update(phone_number=instance.student_profile.phone_number,
                           gender=instance.student_profile.gender)
        kwargs.setdefault("initial", initial)
        super().__init__(*args, **kwargs)
        if self.is_student:
            self.fields["phone_number"] = forms.RegexField(
                r"^\d{9,10}$", required=False, max_length=10,
                error_messages={"invalid": "Enter 9 or 10 digits."})
            self.fields["gender"] = forms.ChoiceField(
                required=False, choices=[("", "---------")] + list(Gender.choices))

    def clean_username(self):
        return self._check_username(exclude_pk=self.instance.pk)

    def clean_full_name(self):
        value = self.cleaned_data["full_name"].strip()
        if not value:
            raise forms.ValidationError("This field is required.")
        return value

    def clean_new_password(self):
        password = self.cleaned_data.get("new_password")
        if password:
            self._check_password(password, self.cleaned_data.get("username"))
        return password
