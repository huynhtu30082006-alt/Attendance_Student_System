from django import forms

from .models import COURSE_CODE_VALIDATOR, Course


class CourseForm(forms.Form):
    """Plain form on purpose: the code is the primary key, and a ModelForm cannot check the uniqueness
    of a primary key that is being changed."""

    code = forms.CharField(max_length=20, label="Course code", validators=[COURSE_CODE_VALIDATOR])
    name = forms.CharField(max_length=50, label="Course name")

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None:
            kwargs.setdefault("initial", {"code": instance.code, "name": instance.name})
        super().__init__(*args, **kwargs)

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        taken = Course.objects.filter(code__iexact=code)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise forms.ValidationError("A course with this code already exists.")
        return code

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("This field is required.")
        return name

    def save(self):
        code, name = self.cleaned_data["code"], self.cleaned_data["name"]
        if self.instance is None:
            return Course.objects.create(code=code, name=name)
        return self.instance.update_info(code, name)
