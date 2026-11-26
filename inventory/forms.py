from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils.functional import cached_property

from inventory.models import DocumentStatus, OpeningBalance, OpeningBalanceLine, PurchaseReceipt, PurchaseReceiptLine
from inventory.services import line_value
from masters.models import Item, ItemCategory, Supplier


class ItemChoice(forms.ModelChoiceField):
    def label_from_instance(self, item):
        return f"{item.sku} · {item.name} ({item.base_unit.code})"


class DocumentLineForm(forms.ModelForm):
    item = ItemChoice(queryset=Item.objects.select_related("base_unit"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self._meta.model is PurchaseReceiptLine:
            self.fields["item"].queryset = self.fields["item"].queryset.exclude(category=ItemCategory.FINISHED_GOOD)

    def clean(self):
        cleaned = super().clean()
        quantity, cost = cleaned.get("quantity"), cleaned.get("unit_cost")
        if quantity is not None and cost is not None:
            line_value(quantity, cost)
        return cleaned


class DocumentLines(BaseInlineFormSet):
    @cached_property
    def item_choices(self):
        return list(self.form().fields["item"].choices)

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["item"].choices = lambda: self.item_choices

    def clean(self):
        submitted = [form.instance.pk for form in self.initial_forms]
        existing = {line.pk for line in self.get_queryset()}
        if len(submitted) != len(existing) or set(submitted) != existing:
            raise ValidationError("The draft lines changed. Reload the document before editing it again.")
        super().clean()

    def save_draft(self):
        # Clear removed and reselected rows first so item swaps respect the unique constraint.
        for form in self.initial_forms:
            if form.cleaned_data.get("DELETE") or "item" in form.changed_data:
                form.instance.delete()
        for form in self.forms:
            if form.has_changed() and not form.cleaned_data.get("DELETE"):
                form.instance.document = self.instance
                form.save()


DOCUMENT_FORMS = {}
for document, line, fields in (
    (PurchaseReceipt, PurchaseReceiptLine, ("reference", "supplier")),
    (OpeningBalance, OpeningBalanceLine, ("reference",)),
):
    DOCUMENT_FORMS[document] = (
        forms.modelform_factory(document, fields=fields),
        inlineformset_factory(document, line, form=DocumentLineForm, formset=DocumentLines,
                              fields=("item", "quantity", "unit_cost"), extra=0, min_num=1, validate_min=True),
    )


def date_field(label):
    return forms.DateField(label=label, required=False, widget=forms.DateInput(attrs={"type": "date"}))


class ReceiptFilter(forms.Form):
    reference = forms.CharField(required=False, max_length=40, label="Reference")
    supplier = forms.ModelChoiceField(required=False, queryset=Supplier.objects.all())
    status = forms.ChoiceField(required=False, choices=[("", "All statuses"), *DocumentStatus.choices, ("REVERSED", "Reversed")])
    start = date_field("From date")
    end = date_field("Through date")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start") and cleaned.get("end") and cleaned["start"] > cleaned["end"]:
            raise ValidationError("The through date must be on or after the from date.")
        return cleaned


class StockFilter(forms.Form):
    category = forms.ChoiceField(required=False, choices=[("", "All categories"), *ItemCategory.choices])
    item = ItemChoice(required=False, queryset=Item.objects.select_related("base_unit"))
    end = date_field("Stock as of")


class ReceiptCorrectionForm(forms.Form):
    reason = forms.CharField(max_length=250, widget=forms.Textarea(attrs={"rows": 2}))
