from django import forms
from django.core.exceptions import ValidationError

from accounts.models import AccountStatus, Student, Teacher

from .models import AttendanceSession, Classroom


class ClassroomForm(forms.ModelForm):
    class Meta:
        model = Classroom
        fields = ["name", "course"]
        labels = {"name": "Classroom name"}

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise ValidationError("This field is required.")
        return name


class _TeacherChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.teacher_id} - {obj.full_name}"


class _StudentChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        locked = " (locked account)" if obj.user.is_locked else ""
        return f"{obj.student_id} - {obj.full_name}{locked}"


class AssignTeacherForm(forms.Form):
    # Only active Teacher accounts can be assigned (use case 17)
    teacher = _TeacherChoice(queryset=Teacher.objects.none(), label="Teacher")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["teacher"].queryset = (
            Teacher.objects.select_related("user")
            .filter(user__status=AccountStatus.ACTIVE).order_by("user__full_name"))


class AddStudentsForm(forms.Form):
    students = _StudentChoice(queryset=Student.objects.none(),
                              widget=forms.CheckboxSelectMultiple, label="Students")

    def __init__(self, *args, classroom, **kwargs):
        super().__init__(*args, **kwargs)
        # Only Students who are not enrolled yet are offered, so a duplicate enrollment is rejected
        # even when the request is crafted by hand.
        self.fields["students"].queryset = (
            Student.objects.select_related("user").exclude(enrollments__classroom=classroom)
            .order_by("student_id"))


class SessionForm(forms.ModelForm):
    class Meta:
        model = AttendanceSession
        fields = ["date", "start_time", "room"]
        labels = {"start_time": "Time"}
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def __init__(self, *args, classroom, **kwargs):
        super().__init__(*args, **kwargs)
        self.classroom = classroom

    def clean_room(self):
        room = self.cleaned_data["room"].strip()
        if not room:
            raise ValidationError("This field is required.")
        return room

    def clean(self):
        cleaned = super().clean()
        date, start = cleaned.get("date"), cleaned.get("start_time")
        if date and start:
            clash = AttendanceSession.objects.filter(
                classroom=self.classroom, date=date, start_time=start)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise ValidationError("This classroom already has a session at this date and time.")
        return cleaned
