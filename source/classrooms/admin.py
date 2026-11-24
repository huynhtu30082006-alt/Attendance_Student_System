from django.contrib import admin

from .models import AttendanceSession, Classroom

# Enrollment has a composite primary key, which the Django admin site does not support:
# manage enrollments in the application (/classrooms/<id>/students/add/).
admin.site.register(Classroom)
admin.site.register(AttendanceSession)
