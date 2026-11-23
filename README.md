# Student Attendance System

A web-based Student Attendance Management System built for academic institutions to digitize classroom attendance tracking, automate absence-rate calculations and threshold warnings, and generate exportable attendance reports.

**Target Users:**
- **Admin:** Manages user accounts, courses, classrooms, teacher assignments, student enrollments, class sessions, system-wide absence warning thresholds, and institution-wide attendance analytics.
- **Teacher:** Opens scheduled sessions, records and finalizes student attendance, updates attendance records for closed sessions when needed, and reviews or exports classroom attendance reports.
- **Student:** Views assigned classrooms, class schedules, personal attendance history, absence rates, and absence-warning notifications.

---

## Table of Contents

- [Key Features](#key-features)
- [Tech Stack & Architecture](#tech-stack--architecture)
  - [Technology Stack](#technology-stack)
  - [Directory Structure](#directory-structure)
  - [Data Model (ERD / Class Diagram)](#data-model-erd--class-diagram)
  - [Application Routes](#application-routes)
  - [Authorization & Data Scoping](#authorization--data-scoping)
- [Prerequisites](#prerequisites)
- [Installation & Usage](#installation--usage)
  - [1. Clone the Repository](#1-clone-the-repository)
  - [2. Configure Environment Variables](#2-configure-environment-variables)
  - [3. Start the Application with Docker Compose](#3-start-the-application-with-docker-compose)
  - [4. Seed Demo Data or Create an Admin Account](#4-seed-demo-data-or-create-an-admin-account)
  - [5. Common Docker Commands](#5-common-docker-commands)
  - [6. Running Tests](#6-running-tests)
  - [7. Troubleshooting](#7-troubleshooting)
- [Environment Variables](#environment-variables)
- [Contributing & License](#contributing--license)

---

## Key Features

### Common, Authentication & Security
- **Session-Based Authentication:** Secure login (`/login/`) and POST-only logout (`/logout/`).
- **Password Protection:** Passwords are stored exclusively as salted PBKDF2 hashes (`PBKDF2PasswordHasher`) with minimum 8-character and standard Django password validators.
- **Brute-Force Protection:** 5 consecutive failed login attempts for the same username within 10 minutes trigger a 15-minute lockout for that username (`accounts/bruteforce.py`).
- **Immediate Account Lock Enforcement:** Locking a user account immediately invalidates active access (`UserAccount.is_active` reflects `AccountStatus.ACTIVE`).
- **Session & Cookie Hardening:** 30-minute sliding inactivity timeout (`SESSION_SAVE_EVERY_REQUEST = True`), `HttpOnly` session cookies, `SameSite=Lax`, `X-Frame-Options: DENY`, `SECURE_CONTENT_TYPE_NOSNIFF = True`, and optional HTTPS cookie flags via `DJANGO_HTTPS`.

### Admin
- **User Account Management:** Create, view, search (by name, username, or student ID), edit, lock, and unlock accounts (`/users/`). Roles and student IDs are immutable after creation.
- **Course Management:** Full CRUD for courses (`/courses/`), including transactional course-code updates and deletion protection (`PROTECT`) when classrooms exist.
- **Classroom Management:** Create, update, and delete classrooms (`/classrooms/`), assign or change teachers, and add or remove enrolled students (removing a student deletes only the enrollment while preserving historical attendance records). Classrooms with existing attendance records cannot be deleted.
- **Session Scheduling:** Create, edit, and cancel class sessions (`Scheduled` -> `Cancelled`), with uniqueness enforcement per `(classroom, date, start_time)`.
- **Global Absence Threshold:** Configure the system-wide absence warning threshold percentage (`/settings/threshold/`, default `20.00%`, valid range `0`–`100%`).
- **System-Wide Attendance Dashboard:** View institution-wide attendance metrics, weekly trends, classrooms requiring attention, and per-classroom summaries (`/attendance/summary/`).

### Teacher
- **Scoped Classrooms & Sessions:** Access only classrooms and sessions assigned to the logged-in teacher (out-of-scope access returns `403 Forbidden`).
- **Session Attendance Workflow:** Open `Scheduled` sessions (`Scheduled` -> `Open`), mark student statuses (`Present`, `Late`, `Absent`), save progress, and close sessions (`Open` -> `Closed`).
- **Post-Close Corrections:** View and edit attendance statuses for `Closed` sessions (`/attendance/sessions/<id>/records/`), automatically recalculating absence rates.

### Student
- **Scoped Access:** View only enrolled classrooms and their sessions.
- **Personal Attendance Report:** Inspect session-by-session attendance status, computed attendance rate, absence rate, and absence-threshold warning indicators per classroom.

### Reporting & Export
- **Classroom Attendance Reports:** Per-classroom attendance statistics (`/attendance/classrooms/<id>/report/`) with warning highlights for students whose absence rate meets or exceeds the configured threshold.
- **Export Formats:**
  - **Admin Summary:** Export to Excel (`.xlsx`) via `/attendance/summary/excel/` and PDF (`.pdf`) via `/attendance/summary/pdf/`.
  - **Classroom Report:** Export to Excel (`.xlsx`) via `/attendance/classrooms/<id>/report/excel/`, PDF (`.pdf`) via `/attendance/classrooms/<id>/report/pdf/`, and CSV (`.csv`) via `/attendance/classrooms/<id>/report/csv/`.

---

## Tech Stack & Architecture

### Technology Stack

| Layer | Technology | Version (from repo) |
| --- | --- | --- |
| Language | Python | 3.12 (`python:3.12-slim`) |
| Web Framework | Django (MVT / MVC) | 6.1.2 |
| API Toolkit | Django REST Framework | 3.18.3 |
| Database | PostgreSQL | 16.5 (`postgres:16.5`) |
| DB Driver | `psycopg` / `psycopg-binary` | 3.3.6 |
| Excel Export | `openpyxl` | 3.1.5 |
| PDF Export | `reportlab` | 4.4.1 |
| Env Loading | `python-dotenv` | 1.2.4 |
| Containerization | Docker & Docker Compose | Compose v2 |

Django follows the MVT/MVC architecture: **Model** (`models.py`), **View / Controller** (`views.py`, `forms.py`, `services.py`), and **Template** (`source/templates/`).

### Directory Structure

```text
Attendance_Student_System/
├── docker-compose.yml              # Defines `db` (PostgreSQL 16.5) and `web` (Django) services
├── .env.example                    # Environment variable template (copy to `.env`)
├── .env                            # Local secrets and config (not committed)
├── pytest.ini                      # Pytest & pytest-django configuration
├── Testing_Document_Group01.xlsx   # 230 test cases in Testing Document template
├── README.md
└── source/
    ├── Dockerfile                  # Python 3.12-slim container image
    ├── requirements.txt            # Pinned Python dependencies
    ├── manage.py                   # Django CLI entry point
    ├── config/                     # Project configuration
    │   ├── settings.py             # Reads configuration from `.env`
    │   ├── urls.py                 # Root URL router
    │   ├── asgi.py
    │   └── wsgi.py
    ├── accounts/                   # Users, auth, RBAC, brute-force protection
    │   ├── models.py               # UserAccount, Teacher, Student, LoginAttempt
    │   ├── views.py                # Login/logout, user CRUD, lock/unlock
    │   ├── forms.py
    │   ├── services.py             # Account use cases & session termination
    │   ├── permissions.py          # Role decorators & mixins
    │   ├── bruteforce.py           # 5 fails / 10 min -> 15 min lockout
    │   ├── utils.py
    │   └── tests.py
    ├── courses/                    # Course management
    │   ├── models.py               # Course
    │   ├── views.py
    │   ├── forms.py
    │   └── urls.py
    ├── classrooms/                 # Classrooms, enrollments, sessions
    │   ├── models.py               # Classroom, Enrollment, AttendanceSession
    │   ├── views.py
    │   ├── forms.py
    │   ├── access.py               # Role-based data scoping (Teacher/Student)
    │   └── urls.py
    ├── attendance/                 # Attendance recording, statistics, exports, settings
    │   ├── models.py               # AttendanceRecord, AttendanceStatistics, Setting
    │   ├── services.py             # Open/close session, rate calculations, summaries
    │   ├── views_attendance.py     # Dashboard, take attendance, reports, Excel/PDF/CSV exports
    │   ├── views_settings.py       # Absence warning threshold settings
    │   ├── forms.py
    │   ├── templatetags/
    │   ├── management/commands/
    │   │   └── seed_demo.py        # Baseline & reference performance dataset seeder
    │   └── tests.py
    ├── templates/                  # Server-rendered HTML templates
    │   ├── base.html
    │   ├── home.html, form.html, confirm.html, 403.html, 404.html
    │   ├── accounts/               # login, user_list, user_detail
    │   ├── courses/                # course_list, course_detail
    │   ├── classrooms/             # classroom_list, classroom_detail, session_list, session_detail
    │   ├── attendance/             # admin_dashboard, take_attendance, session_records, classroom_report, student_report
    │   └── components/             # Reusable UI partials (badges, chips, modal, pagination, warning_banner)
    └── tests/                      # Modular 230-TC pytest suite (mapped 1-to-1 with Testing_Document_Group01.xlsx)
```

### Data Model (ERD / Class Diagram)

| ERD Entity | Django Model | Primary Key | Key Constraints & Relationships |
| --- | --- | --- | --- |
| `UserAccount` | `accounts.UserAccount` | `user_id` (`AutoField`) | Unique `username`; immutable `role` (`ADMIN`, `TEACHER`, `STUDENT`); `status` (`ACTIVE`, `LOCKED`) |
| `Teacher` | `accounts.Teacher` | `teacher_id` (`CharField`, e.g., `T0001`) | 1-to-1 with `UserAccount` (`role=TEACHER`, `on_delete=PROTECT`) |
| `Student` | `accounts.Student` | `student_id` (`CharField`, admin-supplied) | 1-to-1 with `UserAccount` (`role=STUDENT`, `on_delete=PROTECT`); immutable `student_id`; optional `phone_number` (9–10 digits) and `gender` |
| `Course` | `courses.Course` | `code` (`CharField`, max 20) | Cannot be deleted while classrooms exist (`PROTECT`) |
| `Classroom` | `classrooms.Classroom` | `class_id` (`CharField`, e.g., `CL0001`) | Belongs to 1 `Course` (`PROTECT`), at most 1 `Teacher` (`SET_NULL`); unique `(course, name)`; cannot be deleted if attendance records exist |
| `Enrollment` | `classrooms.Enrollment` | Composite `(classroom, student)` | Prevents duplicate student enrollment; `classroom` `CASCADE`, `student` `PROTECT` |
| `AttendanceSession` | `classrooms.AttendanceSession` | `session_id` (`AutoField`) | Unique `(classroom, date, start_time)`; status transitions: `Scheduled -> Open -> Closed` or `Scheduled -> Cancelled` |
| `AttendanceRecord` | `attendance.AttendanceRecord` | Composite `(session, student)` | At most 1 record per student per session; `PROTECT` on both foreign keys; status in `PRESENT`, `LATE`, `ABSENT` |

**Supporting Tables (outside the core ERD):**
- `accounts.LoginAttempt` — Tracks login attempts per username for brute-force lockout protection.
- `attendance.Setting` — Single-row configuration table (`pk=1`) storing `absence_threshold` (default `20.00%`, constrained to `0`–`100`).

**Intentional Design Notes vs. ERD:**
- `email` is stored on `UserAccount` so every role has an email address; `Student.full_name`, `Student.email`, `Teacher.full_name`, and `Teacher.email` are read-only properties delegating to `UserAccount` to avoid duplication.
- `password` stores Django's salted PBKDF2 string (`pbkdf2_sha256$<iterations>$<salt>$<hash>`); `UserAccount.salt` is exposed as a read-only property extracted from this string.
- `AttendanceStatistics` is a Python `@dataclass` computed dynamically from `AttendanceRecord` rather than a database table, allowing per-classroom absence and attendance rates to stay always consistent.
- Database columns follow Django's `snake_case` convention (`class_id`, `start_time`, etc.) instead of `camelCase`.

### Application Routes

| URL Path | Description | Allowed Roles |
| --- | --- | --- |
| `/`, `/login/`, `/logout/` | Home dashboard, login, and POST-only logout | All authenticated (login is public) |
| `/users/` (+ `new/`, `<id>/`, `<id>/edit/`, `<id>/lock/`, `<id>/unlock/`) | User CRUD, search, lock/unlock | Admin |
| `/courses/` (+ `new/`, `<code>/`, `<code>/edit/`, `<code>/delete/`) | Course CRUD | Admin |
| `/classrooms/`, `/classrooms/<id>/` | List and inspect classrooms (scoped by role) | All |
| `/classrooms/new/`, `<id>/edit/`, `<id>/delete/`, `<id>/teacher/`, `<id>/students/add/`, `<id>/students/<student_id>/remove/` | Classroom CRUD, teacher assignment, student enrollment management | Admin |
| `/classrooms/sessions/`, `/classrooms/sessions/<id>/` | List and inspect sessions (scoped by role) | All |
| `/classrooms/<id>/sessions/new/`, `/classrooms/sessions/<id>/edit/`, `/classrooms/sessions/<id>/cancel/` | Create, edit, and cancel `Scheduled` sessions | Admin |
| `/attendance/sessions/<id>/open/` | Open a `Scheduled` session (`POST`) | Admin, assigned Teacher |
| `/attendance/sessions/<id>/take/` | Mark attendance and save or close an `Open` session | Admin, assigned Teacher |
| `/attendance/sessions/<id>/records/` | View session records and edit statuses of a `Closed` session | Admin, assigned Teacher |
| `/attendance/classrooms/<id>/report/` | Classroom attendance report (or personal report for Student) | All (scoped) |
| `/attendance/classrooms/<id>/report/excel/`, `.../pdf/`, `.../csv/` | Export classroom attendance report | Admin, assigned Teacher |
| `/attendance/summary/`, `.../excel/`, `.../pdf/` | System-wide attendance dashboard and Excel/PDF exports | Admin |
| `/settings/threshold/` | Configure global absence warning threshold | Admin |
| `/admin/` | Django administration site (maintenance) | Admin (`is_staff`) |

### Authorization & Data Scoping
- **Role Guards (`source/accounts/permissions.py`):** `@admin_required`, `@teacher_required`, `@student_required`, `@admin_or_teacher_required`, `@role_required(...)`, and `RoleRequiredMixin`.
- **Data Scoping (`source/classrooms/access.py`):** `@classroom_scoped`, `@session_scoped`, `classrooms_for(user)`, `sessions_for(user)`, and `assert_own_student(...)`. Any Teacher or Student requesting an out-of-scope or non-existent classroom/session receives `403 Forbidden`.

---

## Prerequisites

- **Docker Desktop** (with Docker Compose v2) — required to run the containerized Django + PostgreSQL stack.
- **Git** — required to clone the repository.
- **Python 3.12+** — optional, required only if running Django commands or tests directly on your host machine outside Docker.

---

## Installation & Usage

### 1. Clone the Repository

```bash
git clone https://github.com/huynhtu30082006-alt/Attendance_Student_System.git
cd Attendance_Student_System
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env`:

```bash
# Linux / macOS
cp .env.example .env

# Windows (PowerShell / CMD)
copy .env.example .env
```

Edit `.env` and update at least these two values:
- `DB_PASSWORD`: Any strong password for your local PostgreSQL instance.
- `DJANGO_SECRET_KEY`: A random 50+ character string. Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Keep the remaining defaults in `.env` unless you need custom host/port settings.

### 3. Start the Application with Docker Compose

```bash
docker compose up --build
```

The `web` service waits for PostgreSQL (`db`) to pass its health check, automatically runs `python manage.py migrate`, and starts the development server at `http://localhost:8000/`.

### 4. Seed Demo Data or Create an Admin Account

Open a second terminal while the containers are running.

**Option A — Seed Baseline Demo Data (`seed_demo`):**

```bash
# Seed baseline data (3 courses, 3 classrooms, 1 admin, 3 teachers, 20 students)
docker compose exec web python manage.py seed_demo

# Wipe existing business/seed data and rebuild cleanly
docker compose exec web python manage.py seed_demo --reset

# Rebuild with the large reference dataset for performance testing
# (100 students, 10 teachers, 20 courses, 50 classrooms including PERF.100x60 with 100 students x 60 sessions)
docker compose exec web python manage.py seed_demo --reset --reference
```

**Seeded Demo Credentials** (password for all seeded accounts: **`Attend@2026`**):

| Role | Username(s) | Notes |
| --- | --- | --- |
| Admin | `admin` | Superuser & staff account (`admin@attendance.edu.vn`) |
| Teacher | `gv1`, `gv2`, `gv3` (up to `gv10` with `--reference`) | Assigned to `CS101.L01`, `CS102.L01`, `CS103.L01` |
| Student | `sv1` .. `sv20` (up to `sv100` with `--reference`) | `sv3` is configured to exceed the 20% absence warning threshold in `CS101.L01` |

> Note: `--reset` deletes all business data and seeded accounts (`admin`, `gv1..gv10`, `sv1..sv100`), while preserving any manually created user accounts.

**Option B — Create a Manual Superuser Account:**

```bash
docker compose exec web python manage.py createsuperuser
```

Follow the prompts to enter `username`, `full_name`, `email`, and `password`, then sign in at `http://localhost:8000/login/` (or `http://localhost:8000/admin/`).

### 5. Common Docker Commands

```bash
# Stop containers (preserves database volume)
docker compose down

# Stop containers AND delete the PostgreSQL volume (clean slate)
docker compose down -v

# Rebuild and start after pulling new changes
git pull origin develop
docker compose up --build
```

### 6. Running Tests

Ensure the PostgreSQL service (`db`) is running, then run the Django test suite inside the `web` container:

```bash
docker compose exec web python manage.py test accounts courses classrooms attendance
```

Or run locally from the `source/` directory (with Python 3.12+ and dependencies installed, and `.env` configured with `DB_HOST=localhost` and `DB_PORT=5433`):

```bash
cd source
python manage.py test accounts courses classrooms attendance
```

If running the full 230-test-case `pytest` suite (`source/tests/`, mapped 1-to-1 with `Testing_Document_Group01.xlsx`; ensure `pytest` and `pytest-django` are installed):

```bash
pytest -v
```

### 7. Troubleshooting

| Issue / Error | Cause & Resolution |
| --- | --- |
| `KeyError: 'DJANGO_SECRET_KEY'` | `DJANGO_SECRET_KEY` is missing from `.env`. Copy `.env.example` to `.env` and set a secret key. |
| `InconsistentMigrationHistory` or missing table errors after pulling schema changes | Local PostgreSQL volume contains stale migrations. Run `docker compose down -v` followed by `docker compose up --build`, then re-seed or run `createsuperuser`. |
| `password authentication failed` | `DB_PASSWORD` in `.env` was changed after the PostgreSQL volume was initialized. Run `docker compose down -v` and restart. |
| Port `5433` or `8000` already in use | Stop the conflicting local process, or change the host-side port mapping in `docker-compose.yml`. |
| `docker compose` command fails to connect to daemon | Docker Desktop is not running. Start Docker Desktop and wait until it reports "running". |
| `403 Forbidden` page in browser | The logged-in user does not have permission for that resource or route (e.g., a Teacher accessing `/users/` or another teacher's classroom). |

---

## Environment Variables

All variables are loaded from `.env` at the repository root via `python-dotenv` (`source/config/settings.py`) and passed into containers via `docker-compose.yml`.

| Variable | Required | Default | Description | Sample Value |
| --- | --- | --- | --- | --- |
| `DB_NAME` | Yes | — | PostgreSQL database name | `attendance_db` |
| `DB_USER` | Yes | — | PostgreSQL username | `attendance_user` |
| `DB_PASSWORD` | Yes | — | PostgreSQL password | `your_password_here` |
| `DB_HOST` | Yes | — | Database host (`localhost` for local runs; overridden to `db` in `docker-compose.yml`) | `localhost` |
| `DB_PORT` | Yes | — | Database port (`5433` on host; overridden to `5432` inside `docker-compose.yml`) | `5433` |
| `DJANGO_SECRET_KEY` | Yes | — | Django cryptographic secret key (app fails to start if unset) | `change-me-to-a-long-random-string` |
| `DJANGO_DEBUG` | No | `False` | Enables Django debug mode when set to `True` | `True` |
| `DJANGO_ALLOWED_HOSTS` | No | `localhost,127.0.0.1` | Comma-separated list of allowed host/domain names | `localhost,127.0.0.1` |
| `DJANGO_HTTPS` | No | `False` | When `True`, sets `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` to `True` (use only behind HTTPS) | `False` |

---

## Contributing & License

### Git Workflow & Contribution Guidelines
- **Branching Model:**
  - `main`: Production/release branch — do **not** push directly.
  - `develop`: Integration branch.
  - `feature/<name>-<module>`: Create a dedicated branch for each feature or fix.
- **Pull Requests:** Open a Pull Request targeting `develop` and require at least 1 reviewer approval before merging.
- **Commit Hygiene:** Write clear, descriptive commit messages. Never commit `.env`, `venv/`, or `db.sqlite3` — verify with `git status` before committing.
- **Database Migrations:**
  - Always commit migration files alongside model changes.
  - Only run `python manage.py makemigrations` when you modify `models.py`, and coordinate with the team to avoid migration conflicts.
  - After pulling new commits, running `docker compose up --build` applies committed migrations automatically.
- **Frontend Templates:** Keep template filenames, context variable names, and URL names (defined in each app's `urls.py`) intact when modifying files under `source/templates/`.

### License

`[To be added]`
