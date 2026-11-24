"""Clean Django model factories for isolated, order-independent pytest tests.

Each factory generates unique identifiers via an internal counter so tests can
freely create multiple records without colliding on DB uniqueness constraints.
"""
import datetime
import itertools

from accounts.models import AccountStatus, Gender, Role, Student, Teacher, UserAccount
from attendance.models import AttendanceRecord, AttendanceStatus
from classrooms.models import AttendanceSession, Classroom, Enrollment, SessionStatus
from courses.models import Course

_user_seq = itertools.count(1)
_teacher_seq = itertools.count(1)
_student_seq = itertools.count(1)
_course_seq = itertools.count(1)
_classroom_seq = itertools.count(1)
_session_seq = itertools.count(1)


def _as_teacher(teacher):
    if teacher is None:
        return None
    if isinstance(teacher, Teacher):
        return teacher
    if isinstance(teacher, UserAccount):
        return teacher.teacher_profile
    raise TypeError(f"Expected Teacher or UserAccount, got {type(teacher).__name__}")


def _as_student(student):
    if isinstance(student, Student):
        return student
    if isinstance(student, UserAccount):
        return student.student_profile
    raise TypeError(f"Expected Student or UserAccount, got {type(student).__name__}")


class UserFactory:
    """Factory for UserAccount + matching Teacher / Student profile."""

    DEFAULT_PASSWORD = "Password123!"

    @classmethod
    def create(
        cls,
        *,
        role=Role.STUDENT,
        username=None,
        password=DEFAULT_PASSWORD,
        full_name=None,
        email=None,
        status=AccountStatus.ACTIVE,
        student_id=None,
        teacher_id=None,
        phone_number="",
        gender="",
        is_staff=None,
        is_superuser=None,
    ):
        seq = next(_user_seq)
        prefix = role.lower()
        username = username or f"{prefix}_{seq}"
        full_name = full_name or f"{role.title()} User {seq}"
        email = email or f"{username}@example.com"

        extra = {
            "full_name": full_name,
            "email": email,
            "role": role,
            "status": status,
        }
        if is_staff is not None:
            extra["is_staff"] = is_staff
        if is_superuser is not None:
            extra["is_superuser"] = is_superuser

        user = UserAccount.objects.create_user(
            username=username,
            password=password,
            **extra,
        )
        # Non-persisted helper attribute so login tests can read the plaintext password.
        user.raw_password = password

        if role == Role.TEACHER:
            tid = teacher_id or f"T{next(_teacher_seq):04d}"
            Teacher.objects.create(teacher_id=tid, user=user)
        elif role == Role.STUDENT:
            sid = student_id or f"SV{next(_student_seq):04d}"
            Student.objects.create(
                student_id=sid,
                user=user,
                phone_number=phone_number,
                gender=gender,
            )
        return user

    @classmethod
    def admin(cls, **kwargs):
        kwargs.setdefault("role", Role.ADMIN)
        return cls.create(**kwargs)

    @classmethod
    def teacher(cls, **kwargs):
        kwargs.setdefault("role", Role.TEACHER)
        return cls.create(**kwargs)

    @classmethod
    def student(cls, **kwargs):
        kwargs.setdefault("role", Role.STUDENT)
        return cls.create(**kwargs)

    @classmethod
    def locked(cls, role=Role.STUDENT, **kwargs):
        kwargs["role"] = role
        kwargs["status"] = AccountStatus.LOCKED
        return cls.create(**kwargs)


class CourseFactory:
    """Factory for Course."""

    @classmethod
    def create(cls, *, code=None, name=None):
        seq = next(_course_seq)
        code = code or f"CS{seq:03d}"
        name = name or f"Course {seq}"
        return Course.objects.create(code=code, name=name)


class ClassroomFactory:
    """Factory for Classroom with teacher assignment and student enrolment helpers."""

    @classmethod
    def create(
        cls,
        *,
        name=None,
        course=None,
        teacher=None,
        students=None,
        class_id=None,
    ):
        seq = next(_classroom_seq)
        course = course or CourseFactory.create()
        class_id = class_id or f"CL{seq:04d}"
        name = name or f"Class {seq}"
        teacher_profile = _as_teacher(teacher)

        classroom = Classroom.objects.create(
            class_id=class_id,
            name=name,
            course=course,
            teacher=teacher_profile,
        )
        if students:
            cls.enrol_students(classroom, students)
        return classroom

    @classmethod
    def assign_teacher(cls, classroom, teacher):
        teacher_profile = _as_teacher(teacher)
        classroom.assign_teacher(teacher_profile)
        return classroom

    @classmethod
    def enrol_student(cls, classroom, student):
        student_profile = _as_student(student)
        enrollment, _ = Enrollment.objects.get_or_create(
            classroom=classroom,
            student=student_profile,
        )
        return enrollment

    @classmethod
    def enrol_students(cls, classroom, students):
        return [cls.enrol_student(classroom, s) for s in students]


class SessionFactory:
    """Factory for AttendanceSession across Scheduled, Open, Closed, Cancelled states."""

    BASE_DATE = datetime.date(2026, 11, 1)

    @classmethod
    def create(
        cls,
        *,
        classroom=None,
        date=None,
        start_time=None,
        room=None,
        status=SessionStatus.SCHEDULED,
    ):
        seq = next(_session_seq)
        classroom = classroom or ClassroomFactory.create()
        date = date or (cls.BASE_DATE + datetime.timedelta(days=seq))
        start_time = start_time or datetime.time(8, 0)
        room = room or f"R{seq:03d}"

        return AttendanceSession.objects.create(
            classroom=classroom,
            date=date,
            start_time=start_time,
            room=room,
            status=status,
        )

    @classmethod
    def scheduled(cls, **kwargs):
        kwargs["status"] = SessionStatus.SCHEDULED
        return cls.create(**kwargs)

    @classmethod
    def open(cls, **kwargs):
        kwargs["status"] = SessionStatus.OPEN
        return cls.create(**kwargs)

    @classmethod
    def closed(cls, **kwargs):
        kwargs["status"] = SessionStatus.CLOSED
        return cls.create(**kwargs)

    @classmethod
    def cancelled(cls, **kwargs):
        kwargs["status"] = SessionStatus.CANCELLED
        return cls.create(**kwargs)


class AttendanceFactory:
    """Factory for AttendanceRecord across Present, Late, Absent statuses."""

    @classmethod
    def create(
        cls,
        *,
        session=None,
        student=None,
        status=AttendanceStatus.PRESENT,
        enrol=True,
    ):
        session = session or SessionFactory.open()
        if student is None:
            student_profile = UserFactory.student().student_profile
        else:
            student_profile = _as_student(student)

        if enrol:
            ClassroomFactory.enrol_student(session.classroom, student_profile)

        return AttendanceRecord.objects.create(
            session=session,
            student=student_profile,
            status=status,
        )

    @classmethod
    def present(cls, **kwargs):
        kwargs["status"] = AttendanceStatus.PRESENT
        return cls.create(**kwargs)

    @classmethod
    def late(cls, **kwargs):
        kwargs["status"] = AttendanceStatus.LATE
        return cls.create(**kwargs)

    @classmethod
    def absent(cls, **kwargs):
        kwargs["status"] = AttendanceStatus.ABSENT
        return cls.create(**kwargs)


__all__ = [
    "AccountStatus",
    "AttendanceFactory",
    "AttendanceStatus",
    "ClassroomFactory",
    "CourseFactory",
    "Gender",
    "Role",
    "SessionFactory",
    "SessionStatus",
    "UserFactory",
]
