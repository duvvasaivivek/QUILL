from decimal import Decimal, localcontext

from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator
from django.db import transaction
from django.utils import timezone

from core.models import record_event
from masters.models import Item
from inventory.models import DocumentStatus, MovementType, OpeningBalance, PurchaseReceipt, PurchaseReceiptReversal, StockMovement, stock_balance


def lock_items(item_ids):
    """Use one lock order for all ledger posting paths."""
    list(Item.objects.select_for_update().filter(pk__in=item_ids).order_by("pk"))


def line_value(quantity, unit_cost):
    with localcontext() as context:
        context.prec = 36
        value = (quantity * unit_cost).quantize(Decimal("0.0001"))
    try:
        DecimalValidator(20, 4)(value)
    except ValidationError as error:
        raise ValidationError("Line value exceeds the stock ledger limit.") from error
    return value


def reverse_movements(movements, *, reference, movement_type, user, require_balanced_zero=False):
    """Record the exact opposite of each posted quantity and value within the caller's transaction."""
    lock_items({movement.item_id for movement in movements})
    for movement in movements:
        if movement.quantity > 0:
            quantity, value = stock_balance(movement.item)
            if quantity < movement.quantity or value < movement.value:
                raise ValidationError(f"Not enough stock or stock value to reverse {movement.item.sku}.")
            if require_balanced_zero and quantity == movement.quantity and value != movement.value:
                raise ValidationError(f"Reversing {movement.item.sku} would leave stock value without quantity.")
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
        value = line_value(line.quantity, line.unit_cost)
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


@transaction.atomic
def reverse_purchase_receipt(receipt, user, reason):
    receipt = PurchaseReceipt.objects.select_for_update().get(pk=receipt.pk)
    reason = reason.strip()
    if not reason or len(reason) > 250:
        raise ValidationError("Enter a correction reason of 1 to 250 characters.")
    if receipt.status != DocumentStatus.POSTED or hasattr(receipt, "reversal"):
        raise ValidationError("Only a posted receipt can be reversed, and it can be reversed once.")
    movements = list(StockMovement.objects.filter(receipt_line__document=receipt).select_related("item", "unit"))
    if not movements:
        raise ValidationError("The receipt has no stock movements to reverse.")
    reversal = PurchaseReceiptReversal.objects.create(
        receipt=receipt, reference=f"PUR-REV/{receipt.pk}", reason=reason, created_by=user,
    )
    reverse_movements(movements, reference=reversal.reference, movement_type=MovementType.ADJUSTMENT,
                      user=user, require_balanced_zero=True)
    record_event(user, receipt, "reversed", reference=receipt.reference, reversal=reversal.reference, reason=reason)
    return reversal
