from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("courses/", include("courses.urls")),
    path("classrooms/", include("classrooms.urls")),
    path("settings/", include("attendance.urls")),
]
