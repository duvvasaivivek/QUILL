from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from inventory.models import StockMovement, stock_balance
from masters.models import Item
from sales.models import Invoice, InvoiceLine, InvoiceSequence, Payment, SalesOrder


def money(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def check_stock(lines):
    needed = {}
    for line in lines:
        item = line.product.item if hasattr(line, "product") else line.item
        needed[item.pk] = (item, needed.get(item.pk, (item, Decimal("0")))[1] + line.quantity)
    list(Item.objects.select_for_update().filter(pk__in=needed).order_by("pk"))
    for item, quantity in needed.values():
        available, _ = stock_balance(item)
        if quantity > available:
            raise ValidationError(f"{item.name}: shortage of {quantity - available} (available {available}).")


@transaction.atomic
def approve_order(order, user):
    order = SalesOrder.objects.select_for_update().select_related("customer").get(pk=order.pk)
    if order.status != "SUBMITTED":
        raise ValidationError("Only submitted orders can be approved.")
    lines = list(order.lines.select_related("product__item"))
    if not lines or any(x.quantity <= 0 or x.unit_price < 0 for x in lines):
        raise ValidationError("Order requires valid lines with positive quantities.")
    check_stock(lines)
    today = timezone.localdate()
    start = today.year if today.month >= 4 else today.year - 1
    year = f"{start}-{str(start + 1)[-2:]}"
    sequence, _ = InvoiceSequence.objects.get_or_create(year=year)
    sequence = InvoiceSequence.objects.select_for_update().get(pk=sequence.pk)
    sequence.number += 1
    sequence.save()
    customer = order.customer
    invoice = Invoice.objects.create(order=order, number=f"QUILL/{year}/{sequence.number:05d}",
        customer_snapshot={"name": customer.name, "address": customer.address, "gstin": customer.gstin, "state_code": customer.state_code},
        taxable=0, cgst=0, sgst=0, igst=0, total=0)
    for line in lines:
        item = line.product.item
        taxable = money(line.quantity * line.unit_price)
        local = customer.state_code == "33"
        half = money(taxable * item.gst_rate / 200) if local else Decimal("0")
        igst = Decimal("0") if local else money(taxable * item.gst_rate / 100)
        InvoiceLine.objects.create(invoice=invoice, item=item, description=item.name, hsn=item.hsn_code,
            quantity=line.quantity, unit_price=line.unit_price, gst_rate=item.gst_rate,
            taxable=taxable, cgst=half, sgst=half, igst=igst)
        invoice.taxable += taxable
        invoice.cgst += half
        invoice.sgst += half
        invoice.igst += igst
    invoice.total = invoice.taxable + invoice.cgst + invoice.sgst + invoice.igst
    invoice.save()
    order.status = "APPROVED"
    order.save(update_fields=("status",))
    return invoice


@transaction.atomic
def dispatch_invoice(invoice, user):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.dispatched_at:
        raise ValidationError("Invoice has already been dispatched.")
    lines = list(invoice.lines.select_related("item__base_unit"))
    check_stock(lines)
    for line in lines:
        qty, value = stock_balance(line.item)
        cost = value / qty
        StockMovement.objects.create(item=line.item, item_category=line.item.category, quantity=-line.quantity,
            unit=line.item.base_unit, movement_type="DISPATCH", source_reference=invoice.number,
            unit_cost=cost, value=-(cost * line.quantity), created_by=user)
    invoice.dispatched_at = timezone.now()
    invoice.save(update_fields=("dispatched_at",))


@transaction.atomic
def record_payment(invoice, user, amount, reference):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if amount <= 0 or amount > invoice.outstanding:
        raise ValidationError("Payment must be positive and no greater than outstanding.")
    return Payment.objects.create(invoice=invoice, amount=amount, reference=reference, received_by=user)
