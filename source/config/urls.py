from django.contrib import admin
from django.urls import include, path

from attendance import views_settings

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("courses/", include("courses.urls")),
    path("classrooms/", include("classrooms.urls")),
    path("attendance/", include("attendance.urls")),
    path("settings/threshold/", views_settings.threshold_settings, name="threshold_settings"),
]
