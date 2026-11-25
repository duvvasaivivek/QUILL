from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from masters.models import Item
from inventory.models import DocumentStatus, MovementType, OpeningBalance, PurchaseReceipt, StockMovement, stock_balance


def lock_items(item_ids):
    """Use one lock order for all ledger posting paths."""
    list(Item.objects.select_for_update().filter(pk__in=item_ids).order_by("pk"))


def reverse_movements(movements, *, reference, movement_type, user):
    """Record the exact opposite of each posted quantity and value within the caller's transaction."""
    lock_items({movement.item_id for movement in movements})
    for movement in movements:
        if movement.quantity > 0:
            quantity, value = stock_balance(movement.item)
            if quantity < movement.quantity or value < movement.value:
                raise ValidationError(f"Not enough stock or stock value to reverse {movement.item.sku}.")
        StockMovement.objects.create(
            item=movement.item, item_category=movement.item_category, unit=movement.unit,
            movement_type=movement_type, source_reference=reference, reverses=movement,
            quantity=-movement.quantity, value=-movement.value, unit_cost=movement.unit_cost, created_by=user,
        )


@transaction.atomic
def post_document(document, user):
    """Post one opening balance or purchase receipt exactly once."""
    if isinstance(document, OpeningBalance):
        model, movement_type, source_field = OpeningBalance, MovementType.OPENING, "opening_line"
    elif isinstance(document, PurchaseReceipt):
        model, movement_type, source_field = PurchaseReceipt, MovementType.PURCHASE, "receipt_line"
    else:
        raise TypeError("Unsupported inventory document")

    document = model.objects.select_for_update().get(pk=document.pk)
    if document.status != DocumentStatus.DRAFT:
        raise ValidationError("Document has already been posted.")
    lines = list(document.lines.select_related("item__base_unit").order_by("item_id"))
    if not lines:
        raise ValidationError("Add at least one line before posting.")

    # Lock item rows in a stable order, serializing valuation across document types.
    lock_items(line.item_id for line in lines)
    for line in lines:
        line.full_clean()
        if movement_type == MovementType.OPENING and StockMovement.objects.filter(item=line.item, movement_type=MovementType.OPENING).exists():
            raise ValidationError(f"Opening balance already exists for {line.item.sku}.")
        value = (line.quantity * line.unit_cost).quantize(Decimal("0.0001"))
        StockMovement.objects.create(
            item=line.item,
            item_category=line.item.category,
            quantity=line.quantity,
            unit=line.item.base_unit,
            movement_type=movement_type,
            source_reference=document.reference,
            unit_cost=line.unit_cost,
            value=value,
            created_by=user,
            **{source_field: line},
        )
    document.status = DocumentStatus.POSTED
    document.posted_at = timezone.now()
    document.posted_by = user
    document.save(update_fields=("status", "posted_at", "posted_by"))
    return document


def average_unit_cost(item):
    quantity, value = stock_balance(item)
    return value / quantity if quantity else Decimal("0")
