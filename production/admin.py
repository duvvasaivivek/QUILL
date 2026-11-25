from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from core.models import record_event

from production.models import ProductionConsumption, ProductionRun, RunStatus
from production.services import post_production_run, reverse_production_run, snapshot_consumption


class RunForm(forms.ModelForm):
    def clean_bom(self):
        bom = self.cleaned_data["bom"]
        if not bom.is_active or not bom.lines.exists() or bom.expected_output_quantity <= 0:
            raise ValidationError("Choose an active BOM with material lines and a positive expected output.")
        return bom


class RunActionsForm(ActionForm):
    reason = forms.CharField(required=False, max_length=250, label="Reversal reason")


class ConsumptionFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        for form in self.forms:
            quantity = form.cleaned_data.get("actual_quantity")
            if quantity is not None and quantity < 0:
                form.add_error("actual_quantity", "Actual consumption cannot be negative.")


class ConsumptionInline(admin.TabularInline):
    model = ProductionConsumption
    extra = 0
    formset = ConsumptionFormSet
    readonly_fields = ("item", "expected_quantity", "unit_cost", "variance_percent")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(obj and obj.status == RunStatus.DRAFT and super().has_change_permission(request, obj))

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductionRun)
class ProductionRunAdmin(admin.ModelAdmin):
    form = RunForm
    action_form = RunActionsForm
    exclude = ("status",)
    list_display = ("reference", "bom", "display_status", "planned_output", "good_output", "yield_variance_percent", "has_variance_alert", "cost_per_good_unit")
    list_select_related = ("bom__product__item", "reversal")
    list_filter = ("status", "has_variance_alert")
    search_fields = ("reference", "bom__product__item__name")
    readonly_fields = ("display_status", "reversal_reference", "posted_at", "posted_by", "material_cost", "total_cost", "cost_per_good_unit", "yield_variance_percent", "has_variance_alert")
    inlines = (ConsumptionInline,)
    actions = ("post_selected", "reverse_selected")

    @admin.display(description="Status")
    def display_status(self, obj):
        return "Reversed" if hasattr(obj, "reversal") else obj.get_status_display()

    @admin.display(description="Reversal")
    def reversal_reference(self, obj):
        if hasattr(obj, "reversal"):
            return f"{obj.reversal.reference}: {obj.reversal.reason}"

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return (*self.readonly_fields, "reference", "bom", "planned_output")
        return self.readonly_fields

    def has_change_permission(self, request, obj=None):
        return (obj is None or obj.status == RunStatus.DRAFT) and super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            if not obj.consumptions.exists():
                snapshot_consumption(obj, request.user)
        elif form.changed_data:
            changes = {field: {"from": form.initial[field], "to": form.cleaned_data[field]} for field in form.changed_data}
            record_event(request.user, obj, "draft_edited", reference=obj.reference, changes=changes)

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        for line_form in formset.forms:
            line = line_form.instance
            changed = set(line_form.changed_data) & {"actual_quantity", "damaged_quantity"}
            if changed:
                record_event(request.user, line.run, "consumption_edited", reference=line.run.reference,
                             item=line.item.sku, previous=line_form.initial["actual_quantity"],
                             actual=line.actual_quantity, previous_damage=line_form.initial.get("damaged_quantity"),
                             damaged=line.damaged_quantity)

    @admin.action(description="Post selected draft production runs", permissions=("change",))
    def post_selected(self, request, queryset):
        for run in queryset:
            try:
                post_production_run(run, request.user)
            except ValidationError as error:
                self.message_user(request, f"{run}: {error}", messages.ERROR)
            else:
                self.message_user(request, f"Posted {run}.", messages.SUCCESS)

    def has_delete_permission(self, request, obj=None):
        return False

    def has_reverse_permission(self, request):
        return request.user.has_perm("production.add_productionreversal")

    @admin.action(description="Reverse selected posted production runs", permissions=("reverse",))
    def reverse_selected(self, request, queryset):
        for run in queryset:
            try:
                reversal = reverse_production_run(run, request.user, request.POST.get("reason", ""))
            except ValidationError as error:
                self.message_user(request, "; ".join(error.messages), messages.ERROR)
            else:
                self.message_user(request, f"Reversed {run} as {reversal.reference}.", messages.SUCCESS)


@admin.register(ProductionConsumption)
class ProductionConsumptionAdmin(admin.ModelAdmin):
    list_display = ("run", "item", "expected_quantity", "actual_quantity", "damaged_quantity", "variance_percent", "unit_cost")
    readonly_fields = ("run", "item", "expected_quantity", "actual_quantity", "damaged_quantity", "variance_percent", "unit_cost")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
