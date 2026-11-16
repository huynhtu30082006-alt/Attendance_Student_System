"""Mock view contexts for previewing the FE3 Django templates."""

from datetime import date, time
from types import SimpleNamespace


def obj(**values):
    return SimpleNamespace(**values)


course = obj(code="CS101", name="Introduction to Computer Science")
teacher = obj(full_name="Nguyen Minh Anh")
student = obj(student_id="SV001", full_name="Tran Thu Ha")
classroom = obj(
    pk="CL0001",
    class_id="CL0001",
    name="CS101-A",
    course=course,
    teacher=teacher,
    enrollments=obj(count=lambda: 2),
)
session = obj(
    pk=1,
    date=date(2026, 11, 16),
    start_time=time(8, 0),
    room="A101",
    status="OPEN",
    is_scheduled=False,
    classroom=classroom,
)

MOCK_CONTEXTS = {
    "teacher_classroom_list": {
        "classrooms": [classroom],
        "can_manage": False,
    },
    "teacher_classroom_detail": {
        "classroom": classroom,
        "can_manage": False,
        "enrollments": [obj(student=student)],
        "sessions": [session],
    },
    "teacher_attendance_session": {
        "session": session,
        "student_rows": [
            {"student": student, "status": "PRESENT", "note": ""},
            {
                "student": obj(student_id="SV002", full_name="Le Quoc Bao"),
                "status": "",
                "note": "",
            },
        ],
        "status_choices": [
            ("PRESENT", "Present"),
            ("LATE", "Late"),
            ("ABSENT", "Absent"),
        ],
    },
    "teacher_classroom_report": {
        "classroom": classroom,
        "report": {
            "threshold": 20,
            "sessions": [session],
            "rows": [
                {
                    "student": student,
                    "session_statuses": ["ABSENT"],
                    "total_sessions": 1,
                    "present_count": 0,
                    "late_count": 0,
                    "absent_count": 1,
                    "absence_rate": 100,
                    "is_warned": True,
                }
            ],
        },
    },
    "student_dashboard": {
        "threshold": 20,
        "classroom_rows": [
            {
                "classroom": classroom,
                "summary": {
                    "total_sessions": 1,
                    "present_count": 0,
                    "late_count": 0,
                    "absent_count": 1,
                    "absence_rate": 100,
                    "is_warned": True,
                },
            }
        ],
    },
    "student_attendance_history": {
        "classroom": classroom,
        "threshold": 20,
        "summary": {
            "student": student,
            "total_sessions": 1,
            "present_count": 0,
            "late_count": 0,
            "absent_count": 1,
            "absence_rate": 100,
            "is_warned": True,
            "records": [
                obj(
                    status="ABSENT",
                    note="",
                    session=session,
                )
            ],
        },
    },
}
