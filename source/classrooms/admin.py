from django.contrib import admin

from .models import ClassSession, Classroom, Enrollment

admin.site.register(Classroom)
admin.site.register(Enrollment)
admin.site.register(ClassSession)
