Trong backend/config/settings.py, sửa các đoạn sau:

1) Đầu file:
    load_dotenv(BASE_DIR.parent / ".env")          # BỎ override=True

2) Thay SECRET_KEY / DEBUG / ALLOWED_HOSTS:
    SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
    DEBUG = os.getenv("DJANGO_DEBUG", "False") == "True"
    ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

3) INSTALLED_APPS: thay "accounts" bằng
    "accounts",
    "courses",
    "classrooms",
    "attendance",

4) TIME_ZONE = "Asia/Ho_Chi_Minh"
