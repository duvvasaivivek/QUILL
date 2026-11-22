from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from masters.models import BOM, Item


class RunStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    POSTED = "POSTED", "Posted"


class ProductionRun(models.Model):
    reference = models.CharField(max_length=40, unique=True)
    bom = models.ForeignKey(BOM, on_delete=models.PROTECT)
    status = models.CharField(max_length=6, choices=RunStatus.choices, default=RunStatus.DRAFT)
    planned_output = models.DecimalField(max_digits=14, decimal_places=3)
    good_output = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    wastage = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    allocated_overhead = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    variance_tolerance_percent = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("3"))
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    material_cost = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    total_cost = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_per_good_unit = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    yield_variance_percent = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    has_variance_alert = models.BooleanField(default=False)

    class Meta:
        ordering = ("-posted_at", "reference")

    def clean(self):
        if self.planned_output is not None and self.planned_output <= 0:
            raise ValidationError({"planned_output": "Planned output must be positive."})
        if self.good_output is not None and self.good_output < 0:
            raise ValidationError({"good_output": "Good output cannot be negative."})
        if self.wastage is not None and self.wastage < 0:
            raise ValidationError({"wastage": "Wastage cannot be negative."})
        if self.allocated_overhead is not None and self.allocated_overhead < 0:
            raise ValidationError({"allocated_overhead": "Overhead cannot be negative."})
        if self.variance_tolerance_percent is not None and self.variance_tolerance_percent < 0:
            raise ValidationError({"variance_tolerance_percent": "Tolerance cannot be negative."})

    def save(self, *args, **kwargs):
        if self.pk and ProductionRun.objects.filter(pk=self.pk, status=RunStatus.POSTED).exists():
            raise ValidationError("Posted production runs are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.reference


class ProductionConsumption(models.Model):
    run = models.ForeignKey(ProductionRun, on_delete=models.PROTECT, related_name="consumptions")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    # BOM quantities are converted into the item's base unit when snapshotted.
    expected_quantity = models.DecimalField(max_digits=16, decimal_places=3)
    actual_quantity = models.DecimalField(max_digits=16, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal("0"))
    variance_percent = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("run", "item"), name="unique_consumption_per_run_item")]
        ordering = ("item__sku",)

    def clean(self):
        if self.expected_quantity is not None and self.expected_quantity < 0:
            raise ValidationError({"expected_quantity": "Expected consumption cannot be negative."})
        if self.actual_quantity is not None and self.actual_quantity < 0:
            raise ValidationError({"actual_quantity": "Actual consumption cannot be negative."})
        if self.unit_cost is not None and self.unit_cost < 0:
            raise ValidationError({"unit_cost": "Unit cost cannot be negative."})
        if self.run_id and ProductionRun.objects.get(pk=self.run_id).status == RunStatus.POSTED:
            raise ValidationError("Posted production runs are immutable.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.run}: {self.item.sku}"
