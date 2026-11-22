from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from production.models import ProductionConsumption, ProductionRun, RunStatus
from production.services import post_production_run


class ConsumptionInline(admin.TabularInline):
    model = ProductionConsumption
    extra = 0
    readonly_fields = ("expected_quantity", "unit_cost", "variance_percent")

    def has_add_permission(self, request, obj=None):
        return bool(obj and obj.status == RunStatus.DRAFT and super().has_add_permission(request, obj))

    def has_change_permission(self, request, obj=None):
        return bool(obj and obj.status == RunStatus.DRAFT and super().has_change_permission(request, obj))

    def has_delete_permission(self, request, obj=None):
        return bool(obj and obj.status == RunStatus.DRAFT and super().has_delete_permission(request, obj))


@admin.register(ProductionRun)
class ProductionRunAdmin(admin.ModelAdmin):
    list_display = ("reference", "bom", "status", "planned_output", "good_output", "yield_variance_percent", "has_variance_alert", "cost_per_good_unit")
    list_filter = ("status", "has_variance_alert")
    search_fields = ("reference", "bom__product__item__name")
    readonly_fields = ("status", "posted_at", "posted_by", "material_cost", "total_cost", "cost_per_good_unit", "yield_variance_percent", "has_variance_alert")
    inlines = (ConsumptionInline,)
    actions = ("post_selected",)

    @admin.action(description="Post selected draft production runs")
    def post_selected(self, request, queryset):
        for run in queryset:
            try:
                post_production_run(run, request.user)
            except ValidationError as error:
                self.message_user(request, f"{run}: {error}", messages.ERROR)
            else:
                self.message_user(request, f"Posted {run}.", messages.SUCCESS)

    def has_delete_permission(self, request, obj=None):
        return bool((obj is None or obj.status == RunStatus.DRAFT) and super().has_delete_permission(request, obj))


@admin.register(ProductionConsumption)
class ProductionConsumptionAdmin(admin.ModelAdmin):
    list_display = ("run", "item", "expected_quantity", "actual_quantity", "variance_percent", "unit_cost")
    readonly_fields = ("run", "item", "expected_quantity", "actual_quantity", "variance_percent", "unit_cost")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
