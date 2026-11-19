from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class QuillUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Operational details", {"fields": ("phone_number",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Operational details", {"fields": ("phone_number",)}),)
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "is_active")
