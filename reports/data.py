from dataclasses import dataclass
from collections import defaultdict
from datetime import date
from decimal import Decimal
from heapq import merge

from django.db.models import Case, F, Q, Sum, Value, When
from django.utils import timezone

from inventory.models import DocumentStatus, MovementType, StockMovement
from masters.models import Item
from production.models import ProductionConsumption, ProductionRun, RunStatus
from sales.models import Invoice, InvoiceLine, Payment

ZERO = Decimal("0")


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    customer: object = None
    item: object = None

    def between(self, field):
        return {f"{field}__date__range": (self.start, self.end)}

    def through(self, field):
        return {f"{field}__date__lte": self.end}

    def match(self, queryset, *, customer=None, item=None):
        if customer and self.customer:
            queryset = queryset.filter(**{customer: self.customer.pk})
        if item and self.item:
            queryset = queryset.filter(**{item: self.item.pk})
        return queryset


def day(timestamp):
    return timezone.localtime(timestamp).date()


def invoice_lines(period):
    return period.match(InvoiceLine.objects.all(), customer="invoice__order__customer_id", item="item_id")


def sales_documents(period):
    lines = invoice_lines(period).select_related("invoice__credit_note", "item")
    return (
        (lines.filter(**period.between("invoice__issued_at")), False),
        (lines.filter(**period.between("invoice__credit_note__issued_at")), True),
    )


def sales_entries(lines, credit):
    event_date = "invoice__credit_note__issued_at" if credit else "invoice__issued_at"
    lines = lines.order_by(event_date, "pk")
    for line in lines.iterator():
        invoice = line.invoice
        document = invoice.credit_note if credit else invoice
        sign = -1 if credit else 1
        tax = line.cgst + line.sgst + line.igst
        yield (document.issued_at, (day(document.issued_at), document.number, invoice.customer_snapshot.get("name", ""),
               line.item.sku, line.description, line.quantity * sign, line.unit_price, line.taxable * sign,
               tax * sign, (line.taxable + tax) * sign))


def sales_rows(period):
    for _, row in merge(*(sales_entries(lines, credit) for lines, credit in sales_documents(period)),
                        key=lambda entry: entry[0]):
        yield row


def grouped_sales(period, keys, amounts, *, annotations=None):
    totals = defaultdict(lambda: [ZERO] * len(amounts))
    for lines, credit in sales_documents(period):
        groups = lines.order_by().annotate(**(annotations or {})).values(*keys).annotate(
            **{f"sum_{field}": Sum(field) for field in amounts},
        )
        for row in groups.iterator():
            key = tuple(row[field] if row[field] is not None else "" for field in keys)
            for index, field in enumerate(amounts):
                amount = row[f"sum_{field}"]
                totals[key][index] += -amount if credit else amount
    for key in sorted(totals):
        yield key, totals[key]


def sales_summary_rows(period):
    keys = ("invoice__order__customer__code", "invoice__customer_snapshot__name", "item__sku")
    for key, (quantity, taxable, cgst, sgst, igst) in grouped_sales(
        period, keys, ("quantity", "taxable", "cgst", "sgst", "igst"),
    ):
        tax = cgst + sgst + igst
        yield (*key, quantity, taxable, tax, taxable + tax)


def gst_rows(period):
    registration = Case(
            When(Q(invoice__customer_snapshot__gstin="") | Q(invoice__customer_snapshot__gstin__isnull=True),
                 then=Value("Unregistered")),
            default=Value("Registered"),
    )
    keys = ("invoice__customer_snapshot__state_code", "registration", "hsn", "gst_rate")
    for key, (taxable, cgst, sgst, igst) in grouped_sales(
        period, keys, ("taxable", "cgst", "sgst", "igst"), annotations={"registration": registration},
    ):
        yield (*key, taxable, cgst, sgst, igst, taxable + cgst + sgst + igst)


def purchase_rows(period):
    entries = StockMovement.objects.filter(
        movement_type=MovementType.PURCHASE, receipt_line__document__status=DocumentStatus.POSTED,
        **period.between("created_at"),
    )
    entries = period.match(entries, item="item_id").select_related(
        "receipt_line__document__supplier", "item", "unit",
    )
    for entry in entries.iterator():
        supplier = entry.receipt_line.document.supplier
        yield (day(entry.created_at), entry.source_reference, supplier.code, supplier.name,
               entry.item.sku, entry.item.name, entry.quantity, entry.unit.code, entry.unit_cost, entry.value)


def stock_balances(period):
    movements = "stock_movements"
    earlier = Q(stock_movements__created_at__date__lt=period.start)
    in_period = Q(**period.between("stock_movements__created_at"))
    through = Q(**period.through("stock_movements__created_at"))
    return period.match(Item.objects.all(), item="pk").select_related("base_unit").annotate(
        opening=Sum(f"{movements}__quantity", filter=earlier, default=ZERO),
        inward=Sum(f"{movements}__quantity", filter=in_period & Q(stock_movements__quantity__gt=0), default=ZERO),
        outward=Sum(f"{movements}__quantity", filter=in_period & Q(stock_movements__quantity__lt=0), default=ZERO),
        closing=Sum(f"{movements}__quantity", filter=through, default=ZERO),
        closing_value=Sum(f"{movements}__value", filter=through, default=ZERO),
    )


def stock_rows(period):
    for item in stock_balances(period).iterator():
        yield (item.sku, item.name, item.get_category_display(), item.base_unit.code, item.opening,
               item.inward, -item.outward, item.closing, item.closing_value)


def ledger_rows(period):
    entries = period.match(StockMovement.objects.filter(**period.between("created_at")), item="item_id")
    for entry in entries.select_related("item", "unit", "created_by").iterator():
        yield (day(entry.created_at), entry.item.sku, entry.item.name, entry.get_movement_type_display(),
               entry.source_reference, entry.quantity, entry.unit.code, entry.unit_cost, entry.value,
               entry.created_by.get_username())


def posted_runs(period):
    runs = ProductionRun.objects.filter(status=RunStatus.POSTED, **period.between("posted_at"))
    return period.match(runs, item="bom__product__item_id").select_related("bom__product__item", "reversal")


def production_rows(period):
    for run in posted_runs(period).iterator():
        reversal = getattr(run, "reversal", None)
        status = "Reversed" if reversal and day(reversal.created_at) <= period.end else "Posted"
        yield (day(run.posted_at), run.reference, run.bom.product.item.sku, run.planned_output,
               run.good_output, run.wastage, run.yield_variance_percent, status)


def consumption_rows(period):
    lines = ProductionConsumption.objects.filter(run__in=posted_runs(period))
    lines = lines.select_related("run", "item__base_unit").order_by("run__posted_at", "run_id", "item__sku")
    for line in lines.iterator():
        yield (day(line.run.posted_at), line.run.reference, line.item.sku, line.item.name,
               line.item.base_unit.code, line.expected_quantity, line.actual_quantity, line.damaged_quantity,
               line.variance_percent)


def variance_rows(period):
    runs = posted_runs(period)
    for run in runs.iterator():
        if run.yield_variance_percent is not None and abs(run.yield_variance_percent) > run.variance_tolerance_percent:
            yield (day(run.posted_at), run.reference, "Yield", run.bom.product.item.sku, run.planned_output,
                   run.good_output, run.yield_variance_percent, run.variance_tolerance_percent)
    lines = ProductionConsumption.objects.filter(run__in=runs).filter(
        Q(variance_percent__gt=F("run__variance_tolerance_percent"))
        | Q(variance_percent__lt=-F("run__variance_tolerance_percent"))
    )
    for line in lines.select_related("run", "item").order_by("-run__posted_at", "run_id", "item__sku").iterator():
        run = line.run
        yield (day(run.posted_at), run.reference, "Material consumption", line.item.sku, line.expected_quantity,
               line.actual_quantity, line.variance_percent, run.variance_tolerance_percent)


def payment_rows(period):
    payments = Payment.objects.filter(**period.between("received_at"))
    payments = period.match(payments, customer="invoice__order__customer_id")
    for payment in payments.select_related("invoice", "received_by").order_by("received_at", "pk").iterator():
        yield (day(payment.received_at), payment.reference, payment.invoice.number,
               payment.invoice.customer_snapshot.get("name", ""), payment.amount, payment.received_by.get_username())


def receivables(period):
    invoices = period.match(Invoice.objects.filter(**period.through("issued_at")), customer="order__customer_id")
    invoices = invoices.exclude(**period.through("credit_note__issued_at"))
    return invoices.annotate(
        received=Sum("payments__amount", filter=Q(**period.through("payments__received_at")), default=ZERO),
        balance=F("total") - F("received"),
    ).filter(balance__gt=0)


AGE_BANDS = ("0–30 days", "31–60 days", "61–90 days", "91+ days")


def age_bucket(age):
    for index, limit in enumerate((30, 60, 90)):
        if age <= limit:
            return index
    return 3


def ageing_rows(period):
    for invoice in receivables(period).order_by("issued_at", "pk").iterator():
        issued = day(invoice.issued_at)
        age = (period.end - issued).days
        yield (invoice.number, invoice.customer_snapshot.get("name", ""), issued, age, AGE_BANDS[age_bucket(age)],
               invoice.total, invoice.received, invoice.balance)


def customer_ageing_rows(period):
    invoices = receivables(period).select_related("order__customer").order_by("order__customer__code", "pk")
    totals = {}
    for invoice in invoices.iterator():
        customer = invoice.order.customer
        buckets = totals.setdefault((customer.code, customer.name), [ZERO] * len(AGE_BANDS))
        buckets[age_bucket((period.end - day(invoice.issued_at)).days)] += invoice.balance
    for (code, name), buckets in totals.items():
        yield (code, name, *buckets, sum(buckets, ZERO))


def cost_rows(period):
    for run in posted_runs(period).iterator():
        yield (day(run.posted_at), run.reference, run.bom.product.item.sku, run.good_output,
               run.material_cost, run.allocated_overhead, run.total_cost, run.cost_per_good_unit)


def margin_entries(period, credit):
    field = "credit_note__issued_at" if credit else "dispatched_at"
    invoices = Invoice.objects.filter(dispatched_at__isnull=False, **period.between(field))
    invoices = period.match(invoices, customer="order__customer_id")
    costs = StockMovement.objects.filter(
        movement_type=MovementType.DISPATCH, source_reference__in=invoices.order_by().values("number"),
    )
    costs = period.match(costs, item="item_id").order_by().values("source_reference", "item_id").annotate(cost=Sum("value"))
    by_invoice_item = {(row["source_reference"], row["item_id"]): -row["cost"] for row in costs.iterator()}
    lines = period.match(InvoiceLine.objects.filter(invoice__in=invoices), item="item_id")
    date_field = f"invoice__{field}"
    lines = lines.values("invoice__number", date_field, "invoice__customer_snapshot", "invoice__credit_note__number",
                         "item_id", "item__sku").annotate(quantity=Sum("quantity"), revenue=Sum("taxable"))
    for row in lines.order_by(date_field, "invoice__number", "item__sku").iterator():
        number = row["invoice__number"]
        cost = by_invoice_item.get((number, row["item_id"]))
        revenue = row["revenue"]
        margin = revenue - cost if cost is not None else None
        percent = (margin * 100 / revenue).quantize(Decimal("0.01")) if margin is not None and revenue else None
        sign = -1 if credit else 1
        yield (row[date_field], (day(row[date_field]), row["invoice__credit_note__number"] if credit else number,
               row["invoice__customer_snapshot"].get("name", ""), row["item__sku"], row["quantity"] * sign,
               revenue * sign, cost * sign if cost is not None else None,
               margin * sign if margin is not None else None, percent))


def margin_rows(period):
    for _, row in merge(margin_entries(period, False), margin_entries(period, True), key=lambda entry: entry[0]):
        yield row
