"""Seed demo data command for development and testing.

Populates the database with:
- 1 Admin account (admin / 1)
- 10 Teachers (gv1..gv10 / 1)
- 100 Students (sv1..sv100 / 1, student_id SV001..SV100)
- 20 Courses
- 50 Classrooms with assigned teachers and enrolled students
- Scheduled, Open, and Closed sessions with attendance records
"""
import datetime
import random
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import AccountStatus, Role, Student, Teacher, UserAccount
from classrooms.models import AttendanceSession, Classroom, Enrollment, SessionStatus
from courses.models import Course
from attendance.models import AttendanceRecord, AttendanceStatus, Setting

PASSWORD = "1"


class Command(BaseCommand):
    help = "Seeds the database with comprehensive demo data."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding demo data..."))

        with transaction.atomic():
            # 1. Setting threshold
            Setting.objects.update_or_create(
                pk=1, defaults={"absence_threshold": Decimal("20.00")}
            )

            # 2. Admin account
            admin_user, _ = UserAccount.objects.get_or_create(
                username="admin",
                defaults={
                    "full_name": "System Administrator",
                    "email": "admin@university.edu.vn",
                    "role": Role.ADMIN,
                    "status": AccountStatus.ACTIVE,
                    "is_staff": True,
                    "is_superuser": True,
                }
            )
            admin_user.set_password(PASSWORD)
            admin_user.save()

            # 3. 10 Teachers
            teachers = []
            for i in range(1, 11):
                username = f"gv{i}"
                user, _ = UserAccount.objects.get_or_create(
                    username=username,
                    defaults={
                        "full_name": f"Teacher {i}",
                        "email": f"gv{i}@university.edu.vn",
                        "role": Role.TEACHER,
                        "status": AccountStatus.ACTIVE,
                    }
                )
                user.set_password(PASSWORD)
                user.save()
                
                teacher, _ = Teacher.objects.get_or_create(
                    teacher_id=f"GV{i:03d}",
                    user=user,
                )
                teachers.append(teacher)

            # 4. 100 Students
            students = []
            for i in range(1, 101):
                username = f"sv{i}"
                student_id = f"SV{i:03d}"
                user, _ = UserAccount.objects.get_or_create(
                    username=username,
                    defaults={
                        "full_name": f"Student {i}",
                        "email": f"sv{i}@student.university.edu.vn",
                        "role": Role.STUDENT,
                        "status": AccountStatus.ACTIVE,
                    }
                )
                user.set_password(PASSWORD)
                user.save()

                student, _ = Student.objects.get_or_create(
                    student_id=student_id,
                    user=user,
                    defaults={
                        "gender": "MALE" if i % 2 == 0 else "FEMALE",
                        "phone_number": f"098{i:07d}"[:10],
                    }
                )
                students.append(student)

            # 5. 20 Courses
            course_data = [
                ("CS101", "Introduction to Programming", 3),
                ("CS102", "Data Structures & Algorithms", 4),
                ("CS103", "Database Systems", 3),
                ("CS104", "Computer Networks", 3),
                ("CS105", "Operating Systems", 3),
                ("CS106", "Software Engineering", 4),
                ("CS107", "Web Application Development", 3),
                ("CS108", "Mobile Application Development", 3),
                ("CS109", "Artificial Intelligence", 3),
                ("CS110", "Machine Learning", 4),
                ("CS111", "Information Security", 3),
                ("CS112", "Cloud Computing", 3),
                ("CS113", "Distributed Systems", 3),
                ("CS114", "Human-Computer Interaction", 3),
                ("CS115", "Computer Architecture", 3),
                ("CS116", "Compiler Design", 3),
                ("CS117", "Data Science Fundamentals", 3),
                ("CS118", "Internet of Things", 3),
                ("CS119", "DevOps & CI/CD", 3),
                ("CS120", "Capstone Project", 4),
            ]
            courses = []
            for code, name, _credits in course_data:
                c, _ = Course.objects.get_or_create(
                    code=code, defaults={"name": name}
                )
                courses.append(c)

            # 6. 50 Classrooms
            classrooms = []
            for i in range(1, 51):
                class_id = f"CL{i:04d}"
                course = courses[(i - 1) % len(courses)]
                teacher = teachers[(i - 1) % len(teachers)]
                name = f"L{((i - 1) % 3) + 1:02d}"

                cr, _ = Classroom.objects.get_or_create(
                    class_id=class_id,
                    defaults={
                        "name": name,
                        "course": course,
                        "teacher": teacher,
                    }
                )
                classrooms.append(cr)

                # Enroll 20-30 students per classroom
                selected_students = students[((i - 1) * 7) % 70 : (((i - 1) * 7) % 70) + 25]
                for s in selected_students:
                    Enrollment.objects.get_or_create(classroom=cr, student=s)

                # Create 3 sessions: 1 Closed (with attendance), 1 Open, 1 Scheduled
                today = timezone.localdate()
                times = [datetime.time(7, 30), datetime.time(9, 30), datetime.time(13, 30)]

                # Closed session (past)
                s_closed, _ = AttendanceSession.objects.get_or_create(
                    classroom=cr,
                    date=today - datetime.timedelta(days=7),
                    start_time=times[0],
                    defaults={"room": f"A{100 + i}", "status": SessionStatus.CLOSED}
                )
                for s in selected_students:
                    rand_val = random.random()
                    status = AttendanceStatus.PRESENT
                    if rand_val < 0.15:
                        status = AttendanceStatus.ABSENT
                    elif rand_val < 0.25:
                        status = AttendanceStatus.LATE
                    AttendanceRecord.objects.get_or_create(
                        session=s_closed, student=s, defaults={"status": status}
                    )

                # Open session (today)
                AttendanceSession.objects.get_or_create(
                    classroom=cr,
                    date=today,
                    start_time=times[1],
                    defaults={"room": f"B{100 + i}", "status": SessionStatus.OPEN}
                )

                # Scheduled session (future)
                AttendanceSession.objects.get_or_create(
                    classroom=cr,
                    date=today + datetime.timedelta(days=7),
                    start_time=times[2],
                    defaults={"room": f"C{100 + i}", "status": SessionStatus.SCHEDULED}
                )

        self.stdout.write(self.style.SUCCESS(
            "Successfully seeded:\n"
            "- 1 Admin (admin / 1)\n"
            "- 10 Teachers (gv1..gv10 / 1)\n"
            "- 100 Students (sv1..sv100 / 1)\n"
            "- 20 Courses\n"
            "- 50 Classrooms\n"
            "- 150 Sessions with demo attendance records."
        ))
