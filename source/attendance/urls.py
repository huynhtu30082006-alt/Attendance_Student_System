from django.urls import path

from . import views_attendance, views_settings

urlpatterns = [
    path("threshold/", views_settings.threshold_settings, name="threshold_settings"),
    path("sessions/<int:pk>/open/", views_attendance.session_open_view, name="session_open"),
    path("sessions/<int:pk>/take/", views_attendance.take_attendance_view, name="take_attendance"),
    path("classrooms/<str:pk>/report/", views_attendance.classroom_attendance_report, name="classroom_attendance_report"),
    path("classrooms/<str:pk>/attendance-history/", views_attendance.student_attendance_history, name="student_attendance_history"),
    path("classrooms/<str:pk>/report/csv/", views_attendance.export_attendance_csv, name="export_attendance_csv"),
]
