"""
seed_basic - MINIMAL baseline data for the Student Attendance System.

Idea: the seed only prepares *data to work with*. It does NOT prepare every test scenario.
Scenarios (locked accounts, late joiners, cancelled sessions, brute-force history, XSS names...)
are created by the test itself: pytest fixtures, or the steps written in the test case.

Install (copy this file next to the old seed, the old one can be kept or deleted):
    source/attendance/management/commands/seed_basic.py

Usage:
    docker compose exec web python manage.py seed_basic                # baseline (small)
    docker compose exec web python manage.py seed_basic --reset        # wipe and rebuild
    docker compose exec web python manage.py seed_basic --reset --reference
                                                                       # + reference dataset (performance tests only)

Baseline (default):
    Accounts   admin | gv1..gv3 | sv1..sv20            (password of every account: Attend@2026)
    Courses    CS101, CS102, CS103
    Classrooms CS101.L01 (gv1, sv1..sv15)  4 Closed + 1 Open (nobody recorded yet) + 2 Scheduled
               CS102.L01 (gv2, sv11..sv20) 3 Closed + 1 Scheduled
               CS103.L01 (gv3, sv16..sv20) no sessions yet
    Threshold  20%
    Attendance of Closed sessions follows a fixed formula (no random). sv3 is absent most of the time
    in CS101.L01, so one Student reaches the warning threshold without any special classroom.

--reference (the "reference dataset" of the specification, used only by the performance test cases):
    100 Students, 10 Teachers, 20 Courses, 50 Classrooms, and one classroom "PERF.100x60" with
    100 Students x 60 sessions (59 Closed + 1 Open with nobody recorded).

--reset deletes all business data (courses, classrooms, sessions, enrollments, attendance records)
and the accounts created by this seed. Accounts created manually by the team are NOT deleted.
"""
import datetime as dt
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import AccountStatus, LoginAttempt, Role, Student, Teacher, UserAccount
from accounts.utils import create_with_code
from attendance.models import AttendanceRecord, AttendanceStatus, Setting
from classrooms.models import AttendanceSession, Classroom, Enrollment, SessionStatus
from courses.models import Course

PASSWORD = "Attend@2026"
CLASS_PREFIX = "CL"  # Classroom.class_id = CL0001, CL0002, ... (same helper as the classroom view)

BASE_TEACHERS, BASE_STUDENTS, BASE_COURSES = 3, 20, 3
REF_TEACHERS, REF_STUDENTS, REF_COURSES, REF_CLASSROOMS = 10, 100, 20, 50

P, L, A = AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.ABSENT
SCHEDULED, OPEN, CLOSED = SessionStatus.SCHEDULED, SessionStatus.OPEN, SessionStatus.CLOSED

COURSE_NAMES = [
    "Object-Oriented Programming", "Data Structures and Algorithms", "Software Engineering",
    "Databases", "Operating Systems", "Computer Networks", "Artificial Intelligence",
    "Web Application Development", "Information Security", "Data Mining",
    "Cloud Computing", "Mobile Application Development", "Software Architecture",
    "Introduction to Machine Learning", "IT Project Management", "Database Management Systems",
    "System Analysis and Design", "Advanced Python Programming", "Embedded Systems",
    "Image Processing",
]  # CS101..CS120 (the baseline uses the first 3)

CHRONIC_STUDENT = 3  # sv3: absent in most sessions -> reaches the 20% threshold in the baseline

# Every username this seed can create (used by --reset so that manual accounts are kept)
SEED_USERNAMES = (
    ["admin"] + [f"gv{i}" for i in range(1, REF_TEACHERS + 1)]
    + [f"sv{i}" for i in range(1, REF_STUDENTS + 1)]
)


def status_for(student_no, session_index):
    """Fixed attendance formula (no random): ~10% Absent, ~10% Late, the rest Present."""
    if student_no == CHRONIC_STUDENT:
        return P if session_index % 3 == 2 else A
    k = (student_no * 3 + session_index * 5) % 10
    return A if k == 0 else (L if k == 1 else P)


class Command(BaseCommand):
    help = "Seed minimal baseline data (use --reset to rebuild, --reference for the performance dataset)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete business data and seed accounts, then recreate them.")
        parser.add_argument("--reference", action="store_true",
                            help="Also create the reference dataset (100 students x 60 sessions...) "
                                 "for the performance test cases.")

    # ------------------------------------------------------------------ main
    def handle(self, *args, **opts):
        try:
            validate_password(PASSWORD)
        except DjangoValidationError as e:
            raise CommandError(f"PASSWORD is not valid: {e.messages}")

        has_data = (Course.objects.exists() or Classroom.objects.exists()
                    or AttendanceSession.objects.exists() or AttendanceRecord.objects.exists())
        if has_data and not opts["reset"]:
            raise CommandError("The database already contains data. Run again with --reset:\n"
                               "  python manage.py seed_basic --reset")

        self.reference = opts["reference"]
        self.today = timezone.localdate()
        self.pw_hash = make_password(PASSWORD)  # hashed once (PBKDF2), reused for every account
        self.class_counter = {}

        with transaction.atomic():
            if opts["reset"]:
                self._reset()
            self._seed_setting()
            self._seed_users()
            self._seed_courses()
            self._seed_baseline_classrooms()
            if self.reference:
                self._seed_reference_classrooms()

        self._print_summary()

    # ----------------------------------------------------------------- reset
    def _reset(self):
        self.stdout.write(self.style.WARNING("--reset: deleting old data..."))
        # Order matters because of the PROTECT foreign keys
        AttendanceRecord.objects.all().delete()
        AttendanceSession.objects.all().delete()
        Enrollment.objects.all().delete()
        Classroom.objects.all().delete()
        Course.objects.all().delete()
        LoginAttempt.objects.filter(username__in=SEED_USERNAMES).delete()
        Student.objects.filter(user__username__in=SEED_USERNAMES).delete()
        Teacher.objects.filter(user__username__in=SEED_USERNAMES).delete()
        UserAccount.objects.filter(username__in=SEED_USERNAMES).delete()

    # ------------------------------------------------------------ small data
    def _seed_setting(self):
        setting = Setting.get()
        setting.absence_threshold = Decimal("20.00")
        setting.save()

    def _upsert_user(self, username, role, full_name, **extra):
        domain = "student.edu.vn" if role == Role.STUDENT else "attendance.edu.vn"
        user = UserAccount.objects.filter(username=username).first()
        if user is None:
            user = UserAccount(username=username, role=role)
        elif user.role != role:
            raise CommandError(f"Account '{username}' already exists with another role "
                               "(the role cannot be changed, FR-05). Run again with --reset.")
        user.full_name, user.email = full_name, f"{username}@{domain}"
        user.status, user.password = AccountStatus.ACTIVE, self.pw_hash
        for key, value in extra.items():
            setattr(user, key, value)
        user.save()
        return user

    def _seed_users(self):
        n_teachers = REF_TEACHERS if self.reference else BASE_TEACHERS
        n_students = REF_STUDENTS if self.reference else BASE_STUDENTS
        self._upsert_user("admin", Role.ADMIN, "System Admin", is_staff=True, is_superuser=True)

        self.teachers, self.students = {}, {}
        for i in range(1, n_teachers + 1):
            user = self._upsert_user(f"gv{i}", Role.TEACHER, f"Teacher {i}")
            self.teachers[i], _ = Teacher.objects.get_or_create(
                user=user, defaults={"teacher_id": f"T{i:04d}"})
        for i in range(1, n_students + 1):
            user = self._upsert_user(f"sv{i}", Role.STUDENT, f"Student {i}")
            self.students[i], _ = Student.objects.get_or_create(
                user=user, defaults={"student_id": f"SV{i:03d}"})

    def _seed_courses(self):
        n = REF_COURSES if self.reference else BASE_COURSES
        for i in range(n):
            Course.objects.create(code=f"CS{101 + i}", name=COURSE_NAMES[i])

    # --------------------------------------------------------------- helpers
    def _day(self, offset):
        return self.today + dt.timedelta(days=offset)

    def _classroom(self, course_code, teacher, student_nums, name=None):
        seq = self.class_counter.get(course_code, 0) + 1
        self.class_counter[course_code] = seq
        cls = create_with_code(
            Classroom, "class_id", CLASS_PREFIX,
            course=Course.objects.get(code=course_code),
            name=name or f"{course_code}.L{seq:02d}", teacher=teacher)
        Enrollment.objects.bulk_create(
            [Enrollment(classroom=cls, student=self.students[n]) for n in student_nums])
        return cls

    def _session(self, cls, day_offset, hour, minute, room, status):
        return AttendanceSession.objects.create(
            classroom=cls, date=self._day(day_offset), start_time=dt.time(hour, minute),
            room=room, status=status)

    def _closed_sessions(self, cls, count, step=7):
        """`count` Closed sessions, `step` days apart; the latest one is `step` days ago."""
        return [self._session(cls, -step * (count - i), 7, 30, f"A10{1 + i % 5}", CLOSED)
                for i in range(count)]

    def _records(self, sessions, student_nums):
        AttendanceRecord.objects.bulk_create(
            [AttendanceRecord(session=s, student=self.students[n], status=status_for(n, idx))
             for idx, s in enumerate(sessions) for n in student_nums],
            batch_size=2000)

    # ------------------------------------------------------------- baseline
    def _seed_baseline_classrooms(self):
        # A. One session in every working status: Closed (reports), Open (record/close), Scheduled (edit/cancel)
        nums = list(range(1, 16))
        cls = self._classroom("CS101", self.teachers[1], nums)
        self._records(self._closed_sessions(cls, 4), nums)
        self._session(cls, 0, 9, 30, "B201", OPEN)          # nobody recorded yet
        self._session(cls, 7, 7, 30, "A101", SCHEDULED)
        self._session(cls, 14, 7, 30, "A101", SCHEDULED)

        # B. A second classroom, shares sv11..sv15 with A (a Student with 2 classrooms)
        nums = list(range(11, 21))
        cls = self._classroom("CS102", self.teachers[2], nums)
        self._records(self._closed_sessions(cls, 3), nums)
        self._session(cls, 7, 7, 30, "A102", SCHEDULED)

        # C. A classroom with Students but no sessions yet (Admin creates sessions, can delete it)
        self._classroom("CS103", self.teachers[3], range(16, 21))

    # ------------------------------------------------------------ reference
    def _seed_reference_classrooms(self):
        """Volume only: same simple pattern repeated. Used by the performance test cases."""
        pool = list(range(1, REF_STUDENTS + 1))
        for i in range(REF_CLASSROOMS - 4):  # 3 baseline + 46 generic + 1 performance = 50
            nums = [pool[(i * 7 + k) % len(pool)] for k in range(25)]
            cls = self._classroom(f"CS{101 + i % REF_COURSES}", self.teachers[1 + i % REF_TEACHERS], nums)
            self._records(self._closed_sessions(cls, 3 + i % 6), nums)
            self._session(cls, 7, 7, 30, "A101", SCHEDULED)

        cls = self._classroom("CS101", self.teachers[6], pool, name="PERF.100x60")
        self._records(self._closed_sessions(cls, 59, step=3), pool)
        self._session(cls, 0, 10, 0, "B301", OPEN)  # 100 Students with no status: close it in < 3 s

    # --------------------------------------------------------------- summary
    def _print_summary(self):
        w, count = self.stdout.write, lambda m, **f: m.objects.filter(**f).count()
        w(self.style.SUCCESS("\nSeed completed."))
        w(f"  Accounts  : {count(UserAccount, role=Role.ADMIN)} Admin, "
          f"{count(UserAccount, role=Role.TEACHER)} Teacher, {count(UserAccount, role=Role.STUDENT)} Student "
          f"(password of every account: {PASSWORD})")
        w(f"  Courses   : {Course.objects.count()}  |  Classrooms: {Classroom.objects.count()}  |  "
          f"Enrollments: {Enrollment.objects.count()}")
        w(f"  Sessions  : {AttendanceSession.objects.count()} "
          f"(Scheduled {count(AttendanceSession, status=SCHEDULED)}, Open {count(AttendanceSession, status=OPEN)}, "
          f"Closed {count(AttendanceSession, status=CLOSED)})  |  Records: {AttendanceRecord.objects.count()}")
        w("\n  Baseline classrooms:")
        w("    CS101.L01  gv1  sv1..sv15   4 Closed, 1 Open (nobody recorded), 2 Scheduled; sv3 reaches the warning threshold")
        w("    CS102.L01  gv2  sv11..sv20  3 Closed, 1 Scheduled")
        w("    CS103.L01  gv3  sv16..sv20  no sessions")
        if self.reference:
            w(f"    + reference dataset: {REF_CLASSROOMS} classrooms in total, PERF.100x60 = 100 Students x 60 sessions")
