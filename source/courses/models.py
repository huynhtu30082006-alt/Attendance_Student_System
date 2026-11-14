from django.core.validators import RegexValidator
from django.db import transaction
from django.db import models

COURSE_CODE_VALIDATOR = RegexValidator(
    r"^[A-Za-z0-9_-]+$", "Use only letters, digits, '-' and '_' (no spaces)."
)


class Course(models.Model):
    """ERD: Course(courseCode PK VARCHAR(20), courseName VARCHAR(50))."""

    code = models.CharField(max_length=20, primary_key=True, validators=[COURSE_CODE_VALIDATOR])
    name = models.CharField(max_length=50)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def has_classrooms(self):  # class diagram: Course.hasClassrooms()
        return self.classrooms.exists()

    @transaction.atomic
    def update_info(self, code, name):
        """Use case 'Update Course' lets the Admin edit the code. The code is the primary key, so a new
        code is applied by creating the new row, moving the classrooms to it and removing the old row;
        everything happens in one transaction (all or nothing)."""
        if code == self.code:
            self.name = name
            self.save(update_fields=["name"])
            return self
        new = Course.objects.create(code=code, name=name)  # IntegrityError if the code is taken
        self.classrooms.update(course=new)
        Course.objects.filter(pk=self.pk).delete()
        return new
