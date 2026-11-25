from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Sum

from masters.models import Item, ItemCategory, Supplier


class DocumentStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    POSTED = "POSTED", "Posted"


class NoBulkMutationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Bulk updates bypass inventory validation.")

    def delete(self):
        raise ValidationError("Bulk deletes bypass inventory validation.")


class PostedDocument(models.Model):
    objects = NoBulkMutationQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk, status=DocumentStatus.POSTED).exists():
            raise ValidationError("Posted documents are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == DocumentStatus.POSTED:
            raise ValidationError("Posted documents are immutable.")
        return super().delete(*args, **kwargs)


class OpeningBalance(PostedDocument):
    reference = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=6, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)

    def __str__(self):
        return self.reference


class OpeningBalanceLine(models.Model):
    objects = NoBulkMutationQuerySet.as_manager()
    document = models.ForeignKey(OpeningBalance, on_delete=models.PROTECT, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=16, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=16, decimal_places=4)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("document", "item"), name="unique_opening_item")]

    def clean(self):
        if self.document_id and OpeningBalance.objects.get(pk=self.document_id).status != DocumentStatus.DRAFT:
            raise ValidationError("Posted opening balances cannot be edited.")
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be positive."})
        if self.unit_cost is not None and self.unit_cost < 0:
            raise ValidationError({"unit_cost": "Unit cost cannot be negative."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.pk and OpeningBalanceLine.objects.get(pk=self.pk).document_id != self.document_id:
            raise ValidationError("An opening line cannot move to another document.")
        OpeningBalance.objects.select_for_update().get(pk=self.document_id)
        self.full_clean()
        return super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        OpeningBalance.objects.select_for_update().get(pk=self.document_id)
        if OpeningBalance.objects.get(pk=self.document_id).status != DocumentStatus.DRAFT:
            raise ValidationError("Posted opening balances cannot be deleted.")
        return super().delete(*args, **kwargs)


class PurchaseReceipt(PostedDocument):
    reference = models.CharField(max_length=40, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    status = models.CharField(max_length=6, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)

    def __str__(self):
        return self.reference


class PurchaseReceiptLine(models.Model):
    objects = NoBulkMutationQuerySet.as_manager()
    document = models.ForeignKey(PurchaseReceipt, on_delete=models.PROTECT, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=16, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=16, decimal_places=4)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("document", "item"), name="unique_receipt_item")]

    def clean(self):
        if self.document_id and PurchaseReceipt.objects.get(pk=self.document_id).status != DocumentStatus.DRAFT:
            raise ValidationError("Posted receipts cannot be edited.")
        if self.item_id and self.item.category == ItemCategory.FINISHED_GOOD:
            raise ValidationError({"item": "Purchase receipts accept raw and packaging materials only."})
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be positive."})
        if self.unit_cost is not None and self.unit_cost < 0:
            raise ValidationError({"unit_cost": "Unit cost cannot be negative."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.pk and PurchaseReceiptLine.objects.get(pk=self.pk).document_id != self.document_id:
            raise ValidationError("A receipt line cannot move to another document.")
        PurchaseReceipt.objects.select_for_update().get(pk=self.document_id)
        self.full_clean()
        return super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        PurchaseReceipt.objects.select_for_update().get(pk=self.document_id)
        if PurchaseReceipt.objects.get(pk=self.document_id).status != DocumentStatus.DRAFT:
            raise ValidationError("Posted receipts cannot be deleted.")
        return super().delete(*args, **kwargs)


class MovementType(models.TextChoices):
    OPENING = "OPENING", "Opening"
    PURCHASE = "PURCHASE", "Purchase"
    PRODUCTION_ISSUE = "PRODUCTION_ISSUE", "Production issue"
    PRODUCTION_OUTPUT = "PRODUCTION_OUTPUT", "Production output"
    DISPATCH = "DISPATCH", "Dispatch"
    RETURN = "RETURN", "Return"
    ADJUSTMENT = "ADJUSTMENT", "Adjustment"


class StockMovement(models.Model):
    objects = NoBulkMutationQuerySet.as_manager()
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="stock_movements")
    item_category = models.CharField(max_length=8, choices=ItemCategory.choices)
    quantity = models.DecimalField(max_digits=16, decimal_places=3)
    unit = models.ForeignKey("masters.Unit", on_delete=models.PROTECT)
    movement_type = models.CharField(max_length=20, choices=MovementType.choices)
    source_reference = models.CharField(max_length=40)
    opening_line = models.OneToOneField(OpeningBalanceLine, on_delete=models.PROTECT, null=True, blank=True)
    receipt_line = models.OneToOneField(PurchaseReceiptLine, on_delete=models.PROTECT, null=True, blank=True)
    reverses = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversal")
    unit_cost = models.DecimalField(max_digits=16, decimal_places=4)
    value = models.DecimalField(max_digits=20, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ("created_at", "pk")
        indexes = [models.Index(fields=("item", "created_at"))]
        constraints = [
            models.CheckConstraint(condition=~models.Q(quantity=0), name="stock_nonzero_quantity"),
            models.UniqueConstraint(fields=("item",), condition=models.Q(movement_type=MovementType.OPENING), name="one_opening_per_item"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Stock movements are immutable.")
        if self.unit_id != self.item.base_unit_id or self.item_category != self.item.category:
            raise ValidationError("Movement unit and category must match the item.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Stock movements are immutable.")

    def __str__(self):
        return f"{self.source_reference}: {self.item.sku} {self.quantity}"


def stock_balance(item):
    totals = StockMovement.objects.filter(item=item).aggregate(quantity=Sum("quantity"), value=Sum("value"))
    return totals["quantity"] or Decimal("0"), totals["value"] or Decimal("0")
