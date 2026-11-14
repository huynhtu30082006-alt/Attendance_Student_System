"""Helpers for tests."""
from .models import Role
from .services import create_account

PASSWORD = "Passw0rd!x"


def make_user(username, role=Role.STUDENT, **kwargs):
    if role == Role.STUDENT:
        kwargs.setdefault("student_id", f"SID-{username}")
    kwargs.setdefault("full_name", username.title())
    kwargs.setdefault("email", f"{username}@example.com")
    return create_account(username=username, password=PASSWORD, role=role, **kwargs)
