from django.urls import path

from . import views

urlpatterns = [
    path("", views.classroom_list, name="classroom_list"),
    path("new/", views.classroom_create, name="classroom_create"),
    # sessions/... must stay above <str:pk>/ so that "sessions" is never read as a classroom ID
    path("sessions/", views.session_list, name="session_list"),
    path("sessions/<int:pk>/", views.session_detail, name="session_detail"),
    path("sessions/<int:pk>/edit/", views.session_update, name="session_update"),
    path("sessions/<int:pk>/cancel/", views.session_cancel, name="session_cancel"),
    path("<str:pk>/", views.classroom_detail, name="classroom_detail"),
    path("<str:pk>/edit/", views.classroom_update, name="classroom_update"),
    path("<str:pk>/delete/", views.classroom_delete, name="classroom_delete"),
    path("<str:pk>/teacher/", views.classroom_assign_teacher, name="classroom_assign_teacher"),
    path("<str:pk>/students/add/", views.classroom_add_students, name="classroom_add_students"),
    path("<str:pk>/students/<str:student_pk>/remove/",
         views.classroom_remove_student, name="classroom_remove_student"),
    path("<str:pk>/sessions/new/", views.session_create, name="session_create"),
]
