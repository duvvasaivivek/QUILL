from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from inventory.models import OpeningBalance, OpeningBalanceLine, PurchaseReceipt, PurchaseReceiptLine, StockMovement, DocumentStatus
from inventory.services import post_document


class DraftLineInline(admin.TabularInline):
    extra = 1

    def has_add_permission(self, request, obj=None):
        return bool((obj is None or obj.status == DocumentStatus.DRAFT) and super().has_add_permission(request, obj))

    def has_change_permission(self, request, obj=None):
        return bool(obj and obj.status == DocumentStatus.DRAFT and super().has_change_permission(request, obj))

    def has_delete_permission(self, request, obj=None):
        return bool(obj and obj.status == DocumentStatus.DRAFT and super().has_delete_permission(request, obj))


class DocumentAdmin(admin.ModelAdmin):
    list_display = ("reference", "status", "posted_at", "posted_by")
    readonly_fields = ("status", "posted_at", "posted_by")
    actions = ("post_selected",)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return (*fields, "reference") if obj and obj.status == DocumentStatus.POSTED else fields

    def has_delete_permission(self, request, obj=None):
        return bool((obj is None or obj.status == DocumentStatus.DRAFT) and super().has_delete_permission(request, obj))

    @admin.action(description="Post selected draft documents", permissions=("change",))
    def post_selected(self, request, queryset):
        for document in queryset:
            try:
                post_document(document, request.user)
            except ValidationError as error:
                self.message_user(request, f"{document}: {error}", messages.ERROR)
            else:
                self.message_user(request, f"Posted {document}.", messages.SUCCESS)


class OpeningLineInline(DraftLineInline):
    model = OpeningBalanceLine


class ReceiptLineInline(DraftLineInline):
    model = PurchaseReceiptLine


@admin.register(OpeningBalance)
class OpeningBalanceAdmin(DocumentAdmin):
    inlines = (OpeningLineInline,)


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(DocumentAdmin):
    list_display = ("reference", "supplier", "status", "posted_at", "posted_by")
    inlines = (ReceiptLineInline,)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return (*fields, "supplier") if obj and obj.status == DocumentStatus.POSTED else fields


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "item", "movement_type", "quantity", "unit", "unit_cost", "value", "source_reference", "created_by")
    list_filter = ("movement_type", "item__category")
    search_fields = ("item__sku", "source_reference")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
