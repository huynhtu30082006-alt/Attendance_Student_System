# Student Attendance System

Hệ thống điểm danh sinh viên (Django + PostgreSQL + Docker). Nhóm 1 – Software Engineering.

## Công nghệ
Python 3.12, Django 6.1 (MVC), PostgreSQL 16, Docker Compose, pytest/Django test.

## Chạy dự án
1. `cp .env.example .env` rồi điền `DB_PASSWORD` và `DJANGO_SECRET_KEY`.
2. `docker compose up --build`
3. Mở http://localhost:8000/admin
4. Tạo admin: `docker compose exec web python manage.py createsuperuser`
5. Chạy test: `docker compose exec web python manage.py test`

Chạy Django ngoài Docker: chỉ bật DB bằng `docker compose up db`, đặt `DB_HOST=localhost`, `DB_PORT=5433` trong `.env`, rồi `cd backend && python manage.py runserver`.

## Cấu trúc
- `backend/accounts` – User, đăng nhập, phân quyền
- `backend/courses` – Course
- `backend/classrooms` – Classroom, Enrollment, ClassSession
- `backend/attendance` – AttendanceRecord, Setting
- `frontend/` – template/static giao diện

## Quy ước Git
- `main`: bản nộp, không push trực tiếp. `develop`: tích hợp. Mỗi việc một nhánh `feature/<tên>-<module>`.
- Mở Pull Request vào `develop`, ít nhất 1 người review trước khi merge.
- Commit rõ nghĩa, ví dụ: `feat(classrooms): add Enrollment model`.
- Model/migration: merge sớm, báo cả nhóm; mỗi lần chỉ một người sửa model cùng app.
- Không commit `.env`, `venv/`, `db.sqlite3`.
