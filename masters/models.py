from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class UnitCategory(models.TextChoices):
    MASS = "MASS", "Mass"
    VOLUME = "VOLUME", "Volume"
    COUNT = "COUNT", "Count"


class Unit(models.Model):
    """A unit represented as a factor to its category's base unit."""

    code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=50)
    category = models.CharField(max_length=12, choices=UnitCategory.choices)
    conversion_to_base = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal("1"))
    is_base_unit = models.BooleanField(default=False)

    class Meta:
        ordering = ("category", "code")

    def clean(self) -> None:
        super().clean()
        if self.conversion_to_base <= 0:
            raise ValidationError({"conversion_to_base": "The conversion factor must be positive."})
        if self.is_base_unit and Unit.objects.filter(
            category=self.category, is_base_unit=True
        ).exclude(pk=self.pk).exists():
            raise ValidationError("Only one base unit is allowed for each unit category.")

    def __str__(self) -> str:
        return self.code


class ItemCategory(models.TextChoices):
    RAW_MATERIAL = "RAW", "Raw material"
    PACKAGING = "PACK", "Packaging material"
    FINISHED_GOOD = "FG", "Finished good"


class Item(models.Model):
    sku = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=8, choices=ItemCategory.choices)
    base_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="items")
    hsn_code = models.CharField(max_length=12, blank=True)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    reorder_point = models.DecimalField(
        max_digits=16, decimal_places=3, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Flag this item when stock is at or below this quantity in its base unit.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sku",)

    def clean(self) -> None:
        super().clean()
        if self.gst_rate < 0 or self.gst_rate > 100:
            raise ValidationError({"gst_rate": "GST rate must be between 0 and 100 percent."})

    def __str__(self) -> str:
        return f"{self.sku} - {self.name}"


class Product(models.Model):
    """A sellable product backed by a finished-good inventory item."""

    item = models.OneToOneField(
        Item,
        on_delete=models.PROTECT,
        related_name="product",
        limit_choices_to={"category": ItemCategory.FINISHED_GOOD},
    )
    pack_size = models.DecimalField(max_digits=12, decimal_places=3)
    pack_size_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="product_pack_sizes")
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("item__name",)

    def clean(self) -> None:
        super().clean()
        if self.item_id and self.item.category != ItemCategory.FINISHED_GOOD:
            raise ValidationError({"item": "A product must reference a finished-good item."})
        if self.pack_size <= 0:
            raise ValidationError({"pack_size": "Pack size must be positive."})
        if self.selling_price < 0:
            raise ValidationError({"selling_price": "Selling price cannot be negative."})

    def __str__(self) -> str:
        return self.item.name


class CustomerType(models.TextChoices):
    RETAILER = "RETAILER", "Retailer"
    DISTRIBUTOR = "DISTRIBUTOR", "Distributor"


class Customer(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=160)
    customer_type = models.CharField(max_length=16, choices=CustomerType.choices)
    gstin = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    state_name = models.CharField(max_length=60)
    state_code = models.CharField(max_length=2)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("code",)

    def clean(self) -> None:
        super().clean()
        if len(self.state_code) != 2 or not self.state_code.isdigit():
            raise ValidationError({"state_code": "Use the two-digit GST state code."})
        if self.credit_limit < 0:
            raise ValidationError({"credit_limit": "Credit limit cannot be negative."})

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Supplier(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=160)
    gstin = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    state_name = models.CharField(max_length=60)
    state_code = models.CharField(max_length=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("code",)

    def clean(self) -> None:
        super().clean()
        if len(self.state_code) != 2 or not self.state_code.isdigit():
            raise ValidationError({"state_code": "Use the two-digit GST state code."})

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class PriceList(models.Model):
    name = models.CharField(max_length=100, unique=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="price_lists",
        null=True,
        blank=True,
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-effective_from", "name")

    def clean(self) -> None:
        super().clean()
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "End date cannot be before the effective date."})

    def __str__(self) -> str:
        return self.name


class PriceListItem(models.Model):
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="entries")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="price_entries")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("price_list", "product"), name="unique_price_per_product"),
        ]

    def clean(self) -> None:
        super().clean()
        if self.unit_price < 0:
            raise ValidationError({"unit_price": "Unit price cannot be negative."})

    def __str__(self) -> str:
        return f"{self.price_list}: {self.product}"


class BOM(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="boms")
    version = models.PositiveIntegerField(default=1)
    expected_output_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("product", "version"), name="unique_bom_product_version"),
        ]
        ordering = ("product", "-version")

    def clean(self) -> None:
        super().clean()
        if self.expected_output_quantity <= 0:
            raise ValidationError({"expected_output_quantity": "Expected output must be positive."})

    def __str__(self) -> str:
        return f"{self.product} v{self.version}"


class BOMLine(models.Model):
    bom = models.ForeignKey(BOM, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="bom_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="bom_lines")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("bom", "item"), name="unique_item_per_bom"),
        ]
        ordering = ("item__sku",)

    def clean(self) -> None:
        super().clean()
        if self.quantity <= 0:
            raise ValidationError({"quantity": "BOM quantity must be positive."})
        if self.item_id and self.item.category == ItemCategory.FINISHED_GOOD:
            raise ValidationError({"item": "A BOM line must use raw or packaging material."})
        if self.item_id and self.unit_id and self.item.base_unit.category != self.unit.category:
            raise ValidationError({"unit": "BOM line unit must match the item's unit category."})

    def __str__(self) -> str:
        return f"{self.bom}: {self.item}"
