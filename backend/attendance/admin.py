from django.contrib import admin

from .models import Setting

# AttendanceRecord has a composite primary key (not supported by the Django admin site).
admin.site.register(Setting)
