from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "full_name", "role", "student_id", "status")
    list_filter = ("role", "status")
    search_fields = ("username", "full_name", "student_id")
    ordering = ("username",)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Thông tin", {"fields": ("full_name", "email", "role", "student_id", "status")}),
        ("Quyền", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "full_name", "email", "role", "student_id",
                       "password1", "password2"),
        }),
    )
