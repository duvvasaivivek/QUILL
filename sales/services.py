from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, Q, Sum, When
from django.utils import timezone
from core.models import record_event
from inventory.models import MovementType, StockMovement
from inventory.services import lock_items, reverse_movements
from masters.models import PriceListItem
from sales.models import CreditNote, Invoice, InvoiceLine, InvoiceSequence, Payment, SalesOrder, SalesOrderLine

ZERO = Decimal("0")
VALUE_PRECISION = Decimal("0.0001")
MAX_INVOICE_TOTAL = Decimal("99999999999999.99")


def money(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def active_prices(customer, product_ids, on_date):
    """Prefer a customer's latest active price, then the latest general price."""
    entries = PriceListItem.objects.filter(
        Q(price_list__customer=customer) | Q(price_list__customer__isnull=True),
        Q(price_list__effective_to__isnull=True) | Q(price_list__effective_to__gte=on_date),
        product_id__in=product_ids, price_list__is_active=True, price_list__effective_from__lte=on_date,
    ).order_by(
        "product_id", Case(When(price_list__customer=customer, then=0), default=1),
        "-price_list__effective_from", "-price_list_id",
    ).values_list("product_id", "unit_price")
    prices = {}
    for product_id, price in entries:
        prices.setdefault(product_id, price)
    return prices


@transaction.atomic
def submit_order(customer, salesman, entries):
    entries = list(entries)
    if not entries:
        raise ValidationError("Add at least one product.")
    if not customer.is_active or any(
        not product.is_active or not product.item.is_active or quantity <= ZERO for product, quantity in entries
    ):
        raise ValidationError("Use an active customer and active products with positive quantities.")
    prices = active_prices(customer, {product.pk for product, _ in entries}, timezone.localdate())
    order = SalesOrder.objects.create(customer=customer, salesman=salesman)
    SalesOrderLine.objects.bulk_create([
        SalesOrderLine(order=order, product=product, quantity=quantity,
                       unit_price=prices.get(product.pk, product.selling_price))
        for product, quantity in entries
    ])
    return order


@dataclass(frozen=True)
class StockRequirement:
    item: object
    required: Decimal
    available: Decimal
    value: Decimal

    @property
    def shortage(self):
        return max(self.required - self.available, ZERO)


def stock_requirements(lines, *, lock=False):
    needed = {}
    for line in lines:
        item = line.product.item if hasattr(line, "product") else line.item
        needed[item.pk] = (item, needed.get(item.pk, (item, ZERO))[1] + line.quantity)
    if lock:
        lock_items(needed)
    totals = {
        item_id: (quantity, value)
        for item_id, quantity, value in StockMovement.objects.filter(item_id__in=needed).order_by()
        .values("item_id").annotate(quantity_total=Sum("quantity"), value_total=Sum("value"))
        .values_list("item_id", "quantity_total", "value_total")
    }
    return [
        StockRequirement(item, quantity, *totals.get(item_id, (ZERO, ZERO)))
        for item_id, (item, quantity) in needed.items()
    ]


def check_stock(lines):
    requirements = stock_requirements(lines, lock=True)
    for row in requirements:
        if row.shortage:
            raise ValidationError(f"{row.item.name}: shortage of {row.shortage} (available {row.available}).")
    return requirements


@transaction.atomic
def approve_order(order, user):
    order = SalesOrder.objects.select_for_update(of=("self",)).select_related("customer").get(pk=order.pk)
    if order.status != "SUBMITTED":
        raise ValidationError("Only submitted orders can be approved.")
    lines = list(order.lines.select_related("product__item"))
    if not lines or any(x.quantity <= 0 or x.unit_price < 0 for x in lines):
        raise ValidationError("Order requires valid lines with positive quantities.")
    check_stock(lines)
    issuer = settings.QUILL_INVOICE_ISSUER
    if not all(issuer.get(key) for key in ("name", "address", "gstin", "state_name", "state_code")):
        raise ValidationError("Configure the factory name, address, GSTIN, state name, and state code before invoicing.")
    if not re.fullmatch(r"[0-9]{2}[A-Z0-9]{13}", issuer["gstin"]) or issuer["gstin"][:2] != issuer["state_code"]:
        raise ValidationError("The factory GSTIN must be 15 characters and start with the factory state code.")
    today = timezone.localdate()
    start = today.year if today.month >= 4 else today.year - 1
    year = f"{start}-{str(start + 1)[-2:]}"
    sequence, _ = InvoiceSequence.objects.get_or_create(year=year)
    sequence = InvoiceSequence.objects.select_for_update().get(pk=sequence.pk)
    sequence.number += 1
    sequence.save()
    customer = order.customer
    invoice_lines = []
    for line in lines:
        item = line.product.item
        taxable = money(line.quantity * line.unit_price)
        local = customer.state_code == issuer["state_code"]
        half = money(taxable * item.gst_rate / 200) if local else Decimal("0")
        igst = Decimal("0") if local else money(taxable * item.gst_rate / 100)
        invoice_lines.append(InvoiceLine(item=item, description=item.name, hsn=item.hsn_code,
            quantity=line.quantity, unit_price=line.unit_price, gst_rate=item.gst_rate,
            taxable=taxable, cgst=half, sgst=half, igst=igst))
    totals = {key: sum(getattr(line, key) for line in invoice_lines) for key in ("taxable", "cgst", "sgst", "igst")}
    invoice_total = sum(totals.values())
    if invoice_total > MAX_INVOICE_TOTAL:
        raise ValidationError("The invoice total is too large. Split this order before approving it.")
    invoice = Invoice.objects.create(
        order=order, number=f"QUILL/{year}/{sequence.number:05d}", total=invoice_total, **totals,
        issuer_snapshot=issuer,
        customer_snapshot={"name": customer.name, "address": customer.address,
                           "gstin": customer.gstin, "state_code": customer.state_code, "state_name": customer.state_name},
    )
    for line in invoice_lines:
        line.invoice = invoice
    InvoiceLine.objects.bulk_create(invoice_lines)
    order.status = "APPROVED"
    order.save(update_fields=("status",))
    record_event(user, invoice, "issued", reference=invoice.number, order_id=order.pk, total=invoice.total)
    return invoice


@transaction.atomic
def dispatch_invoice(invoice, user):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if hasattr(invoice, "credit_note"):
        raise ValidationError("A cancelled invoice cannot be dispatched.")
    if invoice.dispatched_at:
        raise ValidationError("Invoice has already been dispatched.")
    lines = list(invoice.lines.select_related("item__base_unit").order_by("pk"))
    if not lines or any(line.quantity <= ZERO for line in lines):
        raise ValidationError("The invoice must contain positive quantities before dispatch.")
    for row in check_stock(lines):
        cost = row.value / row.available
        value = row.value if row.required == row.available else (cost * row.required).quantize(
            VALUE_PRECISION, rounding=ROUND_HALF_UP,
        )
        StockMovement.objects.create(
            item=row.item, item_category=row.item.category, quantity=-row.required, unit=row.item.base_unit,
            movement_type=MovementType.DISPATCH, source_reference=invoice.number,
            unit_cost=cost.quantize(VALUE_PRECISION, rounding=ROUND_HALF_UP), value=-value, created_by=user,
        )
    Invoice._base_manager.filter(pk=invoice.pk).update(dispatched_at=timezone.now())
    record_event(user, invoice, "dispatched", reference=invoice.number)


@transaction.atomic
def cancel_invoice(invoice, user, reason, *, goods_returned=False):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    reason = reason.strip()
    if not reason or len(reason) > 250:
        raise ValidationError("Enter a cancellation reason of 1 to 250 characters.")
    if hasattr(invoice, "credit_note"):
        raise ValidationError("This invoice has already been cancelled.")
    if invoice.payments.exists():
        raise ValidationError("Invoices with recorded payments require a refund before cancellation.")
    if invoice.dispatched_at and not goods_returned:
        raise ValidationError("Confirm that all dispatched goods have been returned.")
    note = CreditNote.objects.create(invoice=invoice, number=f"CN/{invoice.number}", reason=reason, issued_by=user)
    if invoice.dispatched_at:
        movements = list(StockMovement.objects.filter(
            movement_type=MovementType.DISPATCH, source_reference=invoice.number,
        ).select_related("item", "unit"))
        if not movements:
            raise ValidationError("The invoice has no dispatch movements to reverse.")
        reverse_movements(movements, reference=note.number, movement_type=MovementType.RETURN, user=user)
    SalesOrder.objects.filter(pk=invoice.order_id).update(status="CANCELLED")
    record_event(user, invoice, "cancelled", reference=invoice.number, credit_note=note.number, reason=reason)
    return note


@transaction.atomic
def record_payment(invoice, user, amount, reference):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if amount <= 0 or amount > invoice.outstanding:
        raise ValidationError("Payment must be positive and no greater than outstanding.")
    if Payment.objects.filter(reference=reference).exists():
        raise ValidationError("This payment reference is already in use.")
    payment = Payment.objects.create(invoice=invoice, amount=amount, reference=reference, received_by=user)
    record_event(user, invoice, "payment_recorded", reference=invoice.number, payment=reference, amount=amount)
    return payment
