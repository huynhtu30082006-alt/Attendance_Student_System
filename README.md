# Student Attendance System

Hệ thống điểm danh sinh viên – môn Software Engineering, nhóm 1.
Công nghệ: Python 3.12, Django 6.1 (MVC), PostgreSQL 16, Docker Compose.

---

## 1. Chạy dự án (làm 1 lần khi mới clone)

**Bước 1. Tạo file `.env`** (file này chứa mật khẩu nên **không có trong repo**, mỗi người tự tạo):

```powershell
copy .env.example .env
```

Mở `.env` copy content của `.env.example` vào và sửa 2 chỗ t:

- `DB_PASSWORD=` đặt mật khẩu bất kỳ (chỉ dùng trên máy bạn).
- `DJANGO_SECRET_KEY=` dán một chuỗi ngẫu nhiên. Tạo bằng lệnh:
  `python -c "import secrets; print(secrets.token_urlsafe(50))"`
  (nếu máy không có Python, gõ đại một chuỗi dài 50 ký tự trở lên).

Các dòng còn lại giữ nguyên.

**Bước 2. Chạy hệ thống:**

```powershell
docker compose up --build
```

Lần đầu mất vài phút vì phải tải image. Khi thấy dòng
`Starting development server at http://0.0.0.0:8000/` là xong. Hệ thống tự chạy migration.

**Bước 3. Tạo tài khoản Admin** (mở terminal thứ hai, để terminal cũ chạy tiếp):

```powershell
docker compose exec web python manage.py createsuperuser
```

Nhập username, họ tên, email, mật khẩu do bạn tự đặt. Sau đó mở http://localhost:8000/login/ để đăng nhập,
hoặc http://localhost:8000/admin/ để vào trang quản trị Django.

**Sau khi pull bản viết lại theo ERD:** migration đã được tạo lại từ đầu, nên phải xóa database cũ một lần:
`docker compose down -v` rồi `docker compose up --build`, sau đó tạo lại Admin bằng `createsuperuser`.

**Dừng hệ thống:** bấm `Ctrl+C`, hoặc `docker compose down`. Dữ liệu vẫn được giữ.
Muốn xóa sạch dữ liệu để làm lại từ đầu: `docker compose down -v`.

### Lần sau chỉ cần

```powershell
git pull origin develop
docker compose up --build
```

---

## 2. Cấu trúc thư mục

```
Attendance_System/
├── docker-compose.yml        # chạy 2 service: db (PostgreSQL) và web (Django)
├── .env.example              # mẫu biến môi trường (copy thành .env)
├── .env                      # của riêng mỗi người, KHÔNG commit
├── README.md
└── source/
    ├── Dockerfile
    ├── requirements.txt      # danh sách thư viện Python (chỉ giữ 1 file này)
    ├── manage.py
    ├── config/               # cấu hình project
    │   ├── settings.py       # đọc cấu hình từ .env
    │   └── urls.py           # gom đường dẫn của các app
    ├── templates/            # giao diện HTML (nhóm Frontend làm việc ở đây)
    │   ├── base.html         # layout chung
    │   ├── form.html, confirm.html, home.html, 403.html
    │   ├── accounts/  courses/  classrooms/
    ├── accounts/             # người dùng, đăng nhập, phân quyền
    │   ├── models.py         # UserAccount, Teacher, Student, LoginAttempt
    │   ├── views.py          # đăng nhập/đăng xuất, CRUD tài khoản
    │   ├── forms.py
    │   ├── permissions.py    # decorator phân quyền theo vai trò
    │   ├── services.py       # use case tài khoản (tạo / sửa / khóa / mở khóa, kết thúc session)
│   ├── bruteforce.py     # chống brute-force
    │   └── tests_*.py
    ├── courses/              # Course (khóa học)
    ├── classrooms/           # Classroom, Enrollment, AttendanceSession
    │   └── access.py         # giới hạn dữ liệu theo vai trò (Teacher/Student)
    └── attendance/           # AttendanceRecord, Setting (ngưỡng cảnh báo)
```

Kiến trúc MVC của Django: **Model** = `models.py`, **View/Controller** = `views.py` + `forms.py`,
**Template** = thư mục `templates/`.

### Mô hình dữ liệu (khớp ERD / Class Diagram)

| Bảng ERD | Model Django | Khóa chính | Ràng buộc chính |
| --- | --- | --- | --- |
| UserAccount | `accounts.UserAccount` | `user_id` (INT) | `username` unique; `role` không đổi được; `status` Active/Locked |
| Teacher | `accounts.Teacher` | `teacher_id` (tự sinh T0001...) | 1-1 với UserAccount (role Teacher) |
| Student | `accounts.Student` | `student_id` (admin nhập) | 1-1 với UserAccount (role Student); `phone_number`, `gender`; không đổi được |
| Course | `courses.Course` | `code` | không xóa được khi còn lớp (`PROTECT`) |
| Classroom | `classrooms.Classroom` | `class_id` (tự sinh CL0001...) | 1 course, tối đa 1 teacher; không xóa được khi đã có điểm danh |
| Enrollment | `classrooms.Enrollment` | khóa kép (`classroom`, `student`) | không ghi danh trùng |
| AttendanceSession | `classrooms.AttendanceSession` | `session_id` (INT) | unique (classroom, date, start_time); Scheduled → Open → Closed hoặc Cancelled |
| AttendanceRecord | `attendance.AttendanceRecord` | khóa kép (`session`, `student`) | 1 bản ghi / sinh viên / buổi; `PROTECT` cả hai FK |

Bảng phụ không có trong ERD: `LoginAttempt` (chống brute-force), `Setting` (ngưỡng cảnh báo, 1 dòng, mặc định 20%).

**Khác biệt có chủ đích so với ERD** (nói rõ để báo cáo khớp):

- `email` nằm ở `UserAccount` (FR-04 yêu cầu mọi tài khoản đều có email); `Student.full_name`/`Student.email` đọc từ tài khoản, không lưu trùng.
- `password`: Django lưu chuỗi băm PBKDF2 dạng `pbkdf2_sha256$vòng_lặp$salt$hash` (dài hơn VARCHAR(20)); `salt` là thuộc tính chỉ đọc lấy từ chuỗi này.
- `AttendanceStatistics` **không** tạo bảng: Class Diagram ghi "computed from" AttendanceRecord, và khóa `studentId` đơn lẻ không lưu được tỷ lệ theo từng lớp (FR-24). BE2 tính trực tiếp từ AttendanceRecord.
- Tên cột theo chuẩn snake_case của Django (`class_id`, `start_time`...), không dùng camelCase của ERD.

### Các đường dẫn hiện có

| Đường dẫn | Chức năng | Ai dùng |
| --- | --- | --- |
| `/login/`, `/logout/` | Đăng nhập, đăng xuất (logout bằng POST) | tất cả |
| `/users/` (+ `new/`, `<id>/`, `edit/`, `lock/`, `unlock/`) | Quản lý tài khoản, tìm theo tên / username / mã SV, khóa / mở khóa | Admin |
| `/courses/` (+ `new/`, `<mã>/`, `edit/`, `delete/`) | Quản lý khóa học | Admin |
| `/classrooms/` , `/classrooms/<id>/` | Danh sách / chi tiết lớp (mỗi vai trò chỉ thấy lớp của mình) | tất cả |
| `/classrooms/new/`, `<id>/edit/`, `delete/`, `teacher/`, `students/add/`, `students/<mã SV>/remove/` | CRUD lớp, gán GV, thêm / xóa SV | Admin |
| `/classrooms/<id>/sessions/new/`, `/classrooms/sessions/<id>/edit/`, `cancel/` | Tạo / sửa / hủy buổi học | Admin |
| `/classrooms/sessions/`, `/classrooms/sessions/<id>/` | Danh sách / chi tiết buổi học (theo phạm vi từng vai trò) | tất cả |
| `/settings/threshold/` | Cấu hình ngưỡng cảnh báo vắng | Admin |
| `/admin/` | Trang quản trị Django (chỉ để bảo trì) | Admin |

### Phân quyền (dành cho BE2 / FE dùng lại)

- Theo vai trò: `@admin_required`, `@teacher_required`, `@student_required`, `@role_required(...)`, `RoleRequiredMixin` trong `accounts/permissions.py`.
- Theo dữ liệu: `@classroom_scoped`, `@session_scoped`, `classrooms_for(user)`, `sessions_for(user)`, `assert_own_student(...)` trong `classrooms/access.py`. Teacher / Student truy cập ngoài phạm vi (kể cả ID không tồn tại) đều nhận 403.

---

## 3. Tiến độ (cập nhật khi xong)

Backend 1 (BE1):

- [x] Repo, Docker Compose, models + migration (viết lại theo ERD)
- [x] Đăng nhập / đăng xuất, khóa tài khoản chặn đăng nhập ngay
- [x] Phân quyền theo vai trò, giới hạn dữ liệu Teacher/Student
- [x] CRUD tài khoản (đổi tên đăng nhập, họ tên, email, mật khẩu; không đổi role / mã SV), tìm kiếm
- [x] CRUD khóa học (đổi được mã, chặn xóa khi còn lớp)
- [x] CRUD lớp (chặn xóa khi có điểm danh), gán giáo viên, thêm/xóa sinh viên (giữ điểm danh)
- [x] CRUD buổi học (chống trùng ngày giờ, chỉ sửa/hủy khi Scheduled)
- [x] Chống brute-force (5 lần / 10 phút → khóa 15 phút), session 30 phút, cookie HttpOnly/SameSite
- [x] Cấu hình ngưỡng cảnh báo (mặc định 20%)

Chưa làm: mở/đóng buổi điểm danh, ghi điểm danh, tính tỷ lệ vắng, báo cáo, export Excel/PDF (BE2);
giao diện hoàn chỉnh (Frontend). Các template hiện tại chỉ là bản tạm để chạy thử.

---

## 4. Quy ước làm việc nhóm

- `main`: bản nộp, không push trực tiếp. `develop`: tích hợp. Mỗi việc một nhánh `feature/<tên>-<module>`.
- Mở Pull Request vào `develop`, ít nhất 1 người review trước khi merge.
- Commit rõ nghĩa, ví dụ: `BE1 task: add Enrollment model`.
- **Không commit** `.env`, `venv/`, `db.sqlite3`. Trước khi commit chạy `git status` để kiểm tra.
- **File migration được commit** cùng code. Người khác `git pull` rồi chạy lại là có sẵn, **không cần** chạy
  `makemigrations`. Chỉ chạy lệnh đó khi bạn sửa `models.py`, và báo cả nhóm vì dễ xung đột.
- Nhóm Frontend: sửa giao diện trong `source/templates/`, giữ nguyên tên template, tên biến và tên URL
  (tên URL nằm trong các file `urls.py`).

---

## 5. Lỗi thường gặp

| Thông báo | Nguyên nhân và cách sửa |
| --- | --- |
| `KeyError: 'DJANGO_SECRET_KEY'` | Chưa thêm `DJANGO_SECRET_KEY` vào `.env`. |
| `InconsistentMigrationHistory` / lỗi bảng không tồn tại sau khi pull bản ERD | Database còn dữ liệu cũ. Chạy `docker compose down -v` rồi `docker compose up --build`. |
| `password authentication failed` | Đổi `DB_PASSWORD` sau khi database đã tạo. Chạy `docker compose down -v`. |
| Cổng 5433 hoặc 8000 đã bị dùng | Tắt chương trình đang dùng cổng đó, hoặc đổi số cổng bên trái trong `docker-compose.yml`. |
| `docker compose` không chạy được | Chưa mở Docker Desktop. Mở lên, đợi nó báo "running" rồi thử lại. |
| Trang web báo 403 | Tài khoản không đủ quyền với trang đó (ví dụ Teacher vào `/users/`). |
