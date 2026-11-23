from django.urls import path

from . import views_attendance

urlpatterns = [
    path("summary/", views_attendance.admin_dashboard_view, name="admin_dashboard"),
    path("summary/excel/", views_attendance.export_summary_excel, name="export_summary_excel"),
    path("summary/pdf/", views_attendance.export_summary_pdf, name="export_summary_pdf"),
    path("sessions/<int:pk>/open/", views_attendance.session_open_view, name="session_open"),
    path("sessions/<int:pk>/take/", views_attendance.take_attendance_view, name="take_attendance"),
    path("sessions/<int:pk>/records/", views_attendance.session_records_view, name="session_records"),
    path("classrooms/<str:pk>/report/", views_attendance.classroom_attendance_report, name="classroom_attendance_report"),
    path("classrooms/<str:pk>/report/csv/", views_attendance.export_attendance_csv, name="export_attendance_csv"),
    path("classrooms/<str:pk>/report/excel/", views_attendance.export_attendance_excel, name="export_attendance_excel"),
    path("classrooms/<str:pk>/report/pdf/", views_attendance.export_attendance_pdf, name="export_attendance_pdf"),
]
