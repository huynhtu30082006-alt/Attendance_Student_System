"""Course management tests (TC53, TC59–TC71).

Covers viewing courses list/detail, creating, updating, deleting courses,
validation rules, cancel flows, and empty states.
"""
import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from courses.models import Course
from tests.factories import ClassroomFactory, CourseFactory, UserFactory


def _messages_text(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


@pytest.mark.django_db
def test_tc53_view_courses_list_and_detail(admin_client):
    """TC53: View Courses list and detail shows code, name, and belonging classrooms."""
    course = CourseFactory.create(code="SE101", name="Software Engineering")
    teacher = UserFactory.teacher(full_name="Dr. Ada Lovelace")
    c1 = ClassroomFactory.create(name="SE101-A", course=course, teacher=teacher)
    c2 = ClassroomFactory.create(name="SE101-B", course=course, teacher=None)

    list_resp = admin_client.get(reverse("course_list"))
    assert list_resp.status_code == 200
    list_html = list_resp.content.decode()
    assert "SE101" in list_html
    assert "Software Engineering" in list_html
    assert reverse("course_detail", args=[course.pk]) in list_html

    detail_resp = admin_client.get(reverse("course_detail", args=[course.pk]))
    assert detail_resp.status_code == 200
    detail_html = detail_resp.content.decode()
    assert "SE101" in detail_html
    assert "Software Engineering" in detail_html
    assert c1.name in detail_html
    assert "Dr. Ada Lovelace" in detail_html
    assert c2.name in detail_html
    assert "Not assigned" in detail_html


@pytest.mark.django_db
def test_tc59_create_course_uppercase(admin_client):
    """TC59: Create course normalizes code to uppercase and redirects to detail."""
    resp = admin_client.post(
        reverse("course_create"),
        {"code": "cs101", "name": "Intro to Computer Science"},
        follow=True,
    )

    assert resp.status_code == 200
    assert resp.redirect_chain == [(reverse("course_detail", args=["CS101"]), 302)]
    assert "Course created." in _messages_text(resp)

    course = Course.objects.get(pk="CS101")
    assert course.code == "CS101"
    assert course.name == "Intro to Computer Science"


@pytest.mark.django_db
def test_tc60_create_course_duplicate_code_fails(admin_client):
    """TC60: Creating a course with an existing code (case-insensitive) fails."""
    CourseFactory.create(code="CS101", name="Existing Course")

    resp = admin_client.post(
        reverse("course_create"),
        {"code": "cs101", "name": "Duplicate Course"},
    )

    assert resp.status_code == 200
    assert "A course with this code already exists." in resp.content.decode()
    assert Course.objects.count() == 1
    assert Course.objects.get(pk="CS101").name == "Existing Course"


@pytest.mark.django_db
def test_tc61_create_course_invalid_code_characters_fails(admin_client):
    """TC61: Creating a course with invalid code characters (e.g. space) fails."""
    resp = admin_client.post(
        reverse("course_create"),
        {"code": "CS 101", "name": "Invalid Code Course"},
    )

    assert resp.status_code == 200
    assert "Use only letters, digits" in resp.content.decode()
    assert Course.objects.count() == 0


@pytest.mark.django_db
def test_tc62_create_course_cancel_saves_nothing(admin_client):
    """TC62: Cancel on Create Course returns to list without saving anything."""
    get_resp = admin_client.get(reverse("course_create"))
    assert get_resp.status_code == 200
    html = get_resp.content.decode()
    cancel_url = reverse("course_list")
    assert f'href="{cancel_url}"' in html
    assert "Cancel" in html

    list_resp = admin_client.get(cancel_url)
    assert list_resp.status_code == 200
    assert Course.objects.count() == 0


@pytest.mark.django_db
def test_tc63_update_course_name(admin_client):
    """TC63: Updating a course name persists the change and redirects to detail."""
    course = CourseFactory.create(code="CS201", name="Data Structures")

    resp = admin_client.post(
        reverse("course_update", args=[course.pk]),
        {"code": "CS201", "name": "Algorithms and Data Structures"},
        follow=True,
    )

    assert resp.status_code == 200
    assert resp.redirect_chain == [(reverse("course_detail", args=["CS201"]), 302)]
    assert "Course updated." in _messages_text(resp)

    course.refresh_from_db()
    assert course.name == "Algorithms and Data Structures"


@pytest.mark.django_db
def test_tc64_update_course_duplicate_code_fails(admin_client):
    """TC64: Updating a course to another existing course's code fails."""
    c1 = CourseFactory.create(code="CS201", name="Course One")
    c2 = CourseFactory.create(code="CS202", name="Course Two")

    resp = admin_client.post(
        reverse("course_update", args=[c1.pk]),
        {"code": "cs202", "name": "Course One Renamed"},
    )

    assert resp.status_code == 200
    assert "A course with this code already exists." in resp.content.decode()
    c1.refresh_from_db()
    c2.refresh_from_db()
    assert c1.code == "CS201"
    assert c1.name == "Course One"
    assert c2.code == "CS202"
    assert c2.name == "Course Two"


@pytest.mark.django_db
def test_tc65_update_course_blank_name_fails(admin_client):
    """TC65: Updating a course with a blank/whitespace name fails."""
    course = CourseFactory.create(code="CS203", name="Operating Systems")

    resp = admin_client.post(
        reverse("course_update", args=[course.pk]),
        {"code": "CS203", "name": "   "},
    )

    assert resp.status_code == 200
    assert "This field is required." in resp.content.decode()
    course.refresh_from_db()
    assert course.name == "Operating Systems"


@pytest.mark.django_db
def test_tc66_update_course_cancel_keeps_unchanged(admin_client):
    """TC66: Cancel on Update Course leaves the course unchanged."""
    course = CourseFactory.create(code="CS204", name="Computer Networks")

    get_resp = admin_client.get(reverse("course_update", args=[course.pk]))
    assert get_resp.status_code == 200
    html = get_resp.content.decode()
    cancel_url = reverse("course_list")
    assert f'href="{cancel_url}"' in html
    assert "Cancel" in html

    admin_client.get(cancel_url)
    course.refresh_from_db()
    assert course.code == "CS204"
    assert course.name == "Computer Networks"


@pytest.mark.django_db
def test_tc67_delete_course_without_classrooms(admin_client):
    """TC67: Deleting a course with no classrooms shows confirmation and deletes it."""
    course = CourseFactory.create(code="CS301", name="Compilers")
    delete_url = reverse("course_delete", args=[course.pk])

    confirm_resp = admin_client.get(delete_url)
    assert confirm_resp.status_code == 200
    confirm_html = confirm_resp.content.decode()
    assert f"Delete course {course.code} - {course.name}?" in confirm_html

    post_resp = admin_client.post(delete_url, follow=True)
    assert post_resp.status_code == 200
    assert post_resp.redirect_chain == [(reverse("course_list"), 302)]
    assert "Course deleted." in _messages_text(post_resp)
    assert not Course.objects.filter(pk=course.pk).exists()


@pytest.mark.django_db
def test_tc68_cannot_delete_course_with_classrooms(admin_client):
    """TC68: Deleting a course that still has classrooms is blocked with an error message."""
    course = CourseFactory.create(code="CS302", name="Databases")
    ClassroomFactory.create(name="DB-01", course=course)
    delete_url = reverse("course_delete", args=[course.pk])
    detail_url = reverse("course_detail", args=[course.pk])

    get_resp = admin_client.get(delete_url, follow=True)
    assert get_resp.status_code == 200
    assert get_resp.redirect_chain == [(detail_url, 302)]
    assert "This course still has classrooms and cannot be deleted." in _messages_text(get_resp)

    post_resp = admin_client.post(delete_url, follow=True)
    assert post_resp.status_code == 200
    assert post_resp.redirect_chain == [(detail_url, 302)]
    assert "This course still has classrooms and cannot be deleted." in _messages_text(post_resp)
    assert Course.objects.filter(pk=course.pk).exists()


@pytest.mark.django_db
def test_tc69_delete_course_cancel_keeps_course(admin_client):
    """TC69: Cancelling at Delete Course confirmation keeps the course intact."""
    course = CourseFactory.create(code="CS303", name="AI Foundations")
    delete_url = reverse("course_delete", args=[course.pk])
    detail_url = reverse("course_detail", args=[course.pk])

    confirm_resp = admin_client.get(delete_url)
    assert confirm_resp.status_code == 200
    assert f'href="{detail_url}"' in confirm_resp.content.decode()

    back_resp = admin_client.get(detail_url)
    assert back_resp.status_code == 200
    assert Course.objects.filter(pk=course.pk).exists()


@pytest.mark.django_db
def test_tc70_view_course_detail_no_classrooms(admin_client):
    """TC70: Viewing a course detail with no classrooms displays empty-state message."""
    course = CourseFactory.create(code="CS304", name="Empty Course")

    resp = admin_client.get(reverse("course_detail", args=[course.pk]))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "CS304" in html
    assert "Empty Course" in html
    assert "This course has no classroom." in html


@pytest.mark.django_db
def test_tc71_view_courses_list_empty(admin_client):
    """TC71: Viewing Courses list when no course exists displays empty-state message."""
    assert Course.objects.count() == 0

    resp = admin_client.get(reverse("course_list"))
    assert resp.status_code == 200
    assert "There is no course to display." in resp.content.decode()
