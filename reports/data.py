from dataclasses import dataclass
from datetime import date
from decimal import Decimal

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


def sales_rows(period):
    lines = InvoiceLine.objects.filter(**period.between("invoice__issued_at"))
    lines = period.match(lines, customer="invoice__order__customer_id", item="item_id")
    lines = lines.select_related("invoice", "item").order_by("invoice__issued_at", "pk")
    for line in lines.iterator():
        invoice = line.invoice
        tax = line.cgst + line.sgst + line.igst
        yield (day(invoice.issued_at), invoice.number, invoice.customer_snapshot.get("name", ""),
               line.item.sku, line.description, line.quantity, line.unit_price, line.taxable,
               tax, line.taxable + tax)


def sales_summary_rows(period):
    lines = InvoiceLine.objects.filter(**period.between("invoice__issued_at"))
    lines = period.match(lines, customer="invoice__order__customer_id", item="item_id")
    groups = lines.values("invoice__order__customer__code", "invoice__customer_snapshot__name", "item__sku").annotate(
        quantity=Sum("quantity"), taxable=Sum("taxable"), cgst=Sum("cgst"), sgst=Sum("sgst"), igst=Sum("igst"),
    )
    for row in groups.order_by("invoice__order__customer__code", "invoice__customer_snapshot__name", "item__sku").iterator():
        tax = row["cgst"] + row["sgst"] + row["igst"]
        yield (row["invoice__order__customer__code"], row["invoice__customer_snapshot__name"], row["item__sku"],
               row["quantity"], row["taxable"], tax, row["taxable"] + tax)


def gst_rows(period):
    lines = InvoiceLine.objects.filter(**period.between("invoice__issued_at"))
    lines = period.match(lines, customer="invoice__order__customer_id", item="item_id")
    groups = (
        lines.annotate(registration=Case(
            When(Q(invoice__customer_snapshot__gstin="") | Q(invoice__customer_snapshot__gstin__isnull=True),
                 then=Value("Unregistered")),
            default=Value("Registered"),
        )).values("invoice__customer_snapshot__state_code", "registration", "hsn", "gst_rate")
        .annotate(taxable=Sum("taxable"), cgst=Sum("cgst"), sgst=Sum("sgst"), igst=Sum("igst"))
        .order_by("invoice__customer_snapshot__state_code", "registration", "hsn", "gst_rate")
    )
    for row in groups.iterator():
        tax = row["cgst"] + row["sgst"] + row["igst"]
        yield (row["invoice__customer_snapshot__state_code"] or "", row["registration"], row["hsn"], row["gst_rate"],
               row["taxable"], row["cgst"], row["sgst"], row["igst"], row["taxable"] + tax)


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
    return period.match(runs, item="bom__product__item_id").select_related("bom__product__item")


def production_rows(period):
    for run in posted_runs(period).iterator():
        yield (day(run.posted_at), run.reference, run.bom.product.item.sku, run.planned_output,
               run.good_output, run.wastage, run.yield_variance_percent)


def consumption_rows(period):
    lines = ProductionConsumption.objects.filter(run__in=posted_runs(period))
    lines = lines.select_related("run", "item__base_unit").order_by("run__posted_at", "run_id", "item__sku")
    for line in lines.iterator():
        yield (day(line.run.posted_at), line.run.reference, line.item.sku, line.item.name,
               line.item.base_unit.code, line.expected_quantity, line.actual_quantity, line.variance_percent)


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


def margin_rows(period):
    invoices = period.match(
        Invoice.objects.filter(**period.between("dispatched_at")), customer="order__customer_id",
    )
    costs = StockMovement.objects.filter(
        movement_type=MovementType.DISPATCH, source_reference__in=invoices.order_by().values("number"),
    )
    costs = period.match(costs, item="item_id").order_by().values("source_reference", "item_id").annotate(cost=Sum("value"))
    by_invoice_item = {(row["source_reference"], row["item_id"]): -row["cost"] for row in costs.iterator()}
    lines = period.match(InvoiceLine.objects.filter(invoice__in=invoices), item="item_id")
    lines = lines.values("invoice__number", "invoice__dispatched_at", "invoice__customer_snapshot",
                         "item_id", "item__sku").annotate(quantity=Sum("quantity"), revenue=Sum("taxable"))
    for row in lines.order_by("invoice__dispatched_at", "invoice__number", "item__sku").iterator():
        number = row["invoice__number"]
        cost = by_invoice_item.get((number, row["item_id"]))
        revenue = row["revenue"]
        margin = revenue - cost if cost is not None else None
        percent = (margin * 100 / revenue).quantize(Decimal("0.01")) if margin is not None and revenue else None
        yield (day(row["invoice__dispatched_at"]), number, row["invoice__customer_snapshot"].get("name", ""),
               row["item__sku"], row["quantity"], revenue, cost, margin, percent)
