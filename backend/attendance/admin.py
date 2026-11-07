from django.contrib import admin

from .models import AttendanceRecord, Setting

admin.site.register(AttendanceRecord)
admin.site.register(Setting)
