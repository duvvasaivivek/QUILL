from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "entity", "reference", "action")
    list_filter = ("entity", "action", "created_at")
    search_fields = ("reference", "actor__username")
    list_select_related = ("actor",)
    readonly_fields = ("created_at", "actor", "entity", "object_id", "reference", "action", "details")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
