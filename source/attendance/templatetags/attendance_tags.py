"""Template helpers for the attendance screens (FE3).

    {% load attendance_tags %}
    {% student_warning_banner %}          red banner for a Student whose absence rate reached the threshold
    {{ report.rows|warned }}              only the report rows that reached the threshold
"""
from django import template

from accounts.models import Role
from classrooms.access import classrooms_for

from attendance.services import get_student_classroom_summary

register = template.Library()


@register.filter
def warned(rows):
    """Rows of get_classroom_attendance_report() whose is_warned is True."""
    return [r for r in rows if r.get("is_warned")]


@register.inclusion_tag("components/warning_banner.html", takes_context=True)
def student_warning_banner(context):
    """Banner listing every classroom in which the logged-in Student reached the warning threshold.
    Renders nothing for Admin / Teacher or when there is no warning."""
    request = context.get("request")
    user = getattr(request, "user", None)
    warnings = []
    if user is not None and user.is_authenticated and user.role == Role.STUDENT and user.student_id:
        student = user.student_profile
        for classroom in classrooms_for(user):
            summary = get_student_classroom_summary(student, classroom)
            if summary["total_sessions"] and summary["is_warned"]:
                warnings.append({"classroom": classroom, "rate": summary["absence_rate"]})
    return {"warnings": warnings}
