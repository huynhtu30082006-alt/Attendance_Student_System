"""Optional, only to make the test run faster: `python manage.py test --settings=config.test_settings`.
Uses a cheap password hasher (the real settings use PBKDF2, which is deliberately slow)."""
from .settings import *  # noqa: F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
