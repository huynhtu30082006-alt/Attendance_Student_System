from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Student, Teacher, UserAccount


@admin.register(UserAccount)
class UserAccountAdmin(BaseUserAdmin):
    """Read / maintenance view only. Accounts are created in the application (/users/new/) so that the
    Teacher / Student profile is always created together with the account."""

    list_display = ("username", "full_name", "role", "status")
    list_filter = ("role", "status")
    search_fields = ("username", "full_name", "student_profile__student_id")
    ordering = ("username",)
    readonly_fields = ("role",)  # the role cannot be changed (FR-05)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Information", {"fields": ("full_name", "email", "role", "status")}),
        ("Permissions", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
    )

    def has_add_permission(self, request):
        return False


admin.site.register(Teacher)
admin.site.register(Student)
