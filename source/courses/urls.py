from django.urls import path

from . import views

urlpatterns = [
    path("", views.course_list, name="course_list"),
    path("new/", views.course_create, name="course_create"),
    path("<str:pk>/", views.course_detail, name="course_detail"),
    path("<str:pk>/edit/", views.course_update, name="course_update"),
    path("<str:pk>/delete/", views.course_delete, name="course_delete"),
]
