import csv
from dataclasses import dataclass
from io import BytesIO
from itertools import islice

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import F, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_safe

from core.workspace import report_access as access
from inventory.models import StockMovement
from masters.models import Customer, Item
from production.models import ProductionRun, RunStatus
from sales.models import Invoice, Payment, SalesOrder
from . import data


@dataclass(frozen=True)
class Report:
    title: str
    columns: tuple
    rows: object
    customer: bool = False
    item_label: str = ""
    as_of: bool = False
    note: str = ""


REPORTS = {
    "sales": Report("Sales register", ("Date", "Document", "Customer", "SKU", "Product", "Quantity", "Unit price",
                    "Taxable", "GST", "Total"), data.sales_rows, customer=True, item_label="Product"),
    "sales-summary": Report("Sales by customer and product", ("Customer code", "Customer", "SKU", "Quantity",
                            "Taxable", "GST", "Total"), data.sales_summary_rows, customer=True, item_label="Product"),
    "gst": Report("GST outward supplies", ("State code", "GST registration", "HSN", "GST %", "Taxable", "CGST", "SGST", "IGST", "Total"),
                  data.gst_rows, customer=True, item_label="Product",
                  note="Grouped by place of supply, customer GST registration, HSN, and tax rate."),
    "purchases": Report("Purchase register", ("Date", "Receipt", "Supplier code", "Supplier", "SKU", "Item", "Quantity",
                        "Unit", "Unit cost", "Value"), data.purchase_rows, item_label="Item"),
    "stock": Report("Stock summary", ("SKU", "Item", "Category", "Unit", "Opening", "Inward", "Outward", "Closing",
                    "Closing value"), data.stock_rows, item_label="Item",
                    note="Opening includes movements before the start date. Closing includes movements through the end date."),
    "ledger": Report("Stock ledger", ("Date", "SKU", "Item", "Movement", "Reference", "Signed quantity", "Unit",
                     "Unit cost", "Signed value", "Posted by"), data.ledger_rows, item_label="Item"),
    "production": Report("Production planned vs actual", ("Date", "Run", "Product SKU", "Planned", "Good output", "Waste",
                         "Yield variance %", "Status"), data.production_rows, item_label="Product"),
    "consumption": Report("Production material usage", ("Date", "Run", "Material SKU", "Material", "Unit", "Planned",
                           "Actual", "Damaged packaging", "Variance %"), data.consumption_rows, item_label="Product"),
    "variance": Report("Production variance alerts", ("Date", "Run", "Measure", "SKU", "Expected", "Actual",
                       "Variance %", "Tolerance %"), data.variance_rows, item_label="Product",
                       note="Only variances above the run's tolerance are shown."),
    "payments": Report("Payments received", ("Date", "Payment reference", "Invoice", "Customer", "Amount", "Received by"),
                       data.payment_rows, customer=True),
    "ageing": Report("Outstanding and ageing", ("Invoice", "Customer", "Invoice date", "Age in days", "Age band",
                     "Invoiced", "Paid", "Outstanding"), data.ageing_rows, customer=True, as_of=True,
                     note="Age is measured from the invoice date. Payments through the selected date reduce the balance."),
    "customer-ageing": Report("Receivables by customer", ("Customer code", "Customer", *data.AGE_BANDS, "Outstanding"),
                              data.customer_ageing_rows, customer=True, as_of=True,
                              note="Age bands use the invoice date. Balances include payments through the selected date."),
    "costing": Report("Production cost per unit", ("Date", "Run", "Product SKU", "Good output", "Materials", "Overhead",
                      "Total cost", "Cost per good unit"), data.cost_rows, item_label="Product"),
    "margin": Report("Dispatched sales margin", ("Date", "Document", "Customer", "SKU", "Quantity",
                     "Revenue before GST", "Dispatch cost", "Gross margin", "Margin %"), data.margin_rows,
                     customer=True, item_label="Product",
                     note="Margin uses the stock ledger cost at dispatch. A missing ledger cost leaves the margin blank."),
}


class ReportFilter(forms.Form):
    start = forms.DateField(label="From", input_formats=("%Y-%m-%d",), widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Through", input_formats=("%Y-%m-%d",), widget=forms.DateInput(attrs={"type": "date"}))
    customer = forms.ModelChoiceField(queryset=Customer.objects.all(), required=False)
    item = forms.ModelChoiceField(queryset=Item.objects.all(), required=False)

    def __init__(self, query, report, today):
        dates = {"start": today.replace(day=1).isoformat(), "end": today.isoformat()}
        dates.update(query.dict())
        super().__init__(dates)
        if report.as_of:
            del self.fields["start"]
            self.fields["end"].label = "As of"
        if not report.customer:
            del self.fields["customer"]
        if report.item_label:
            self.fields["item"].label = report.item_label
            if report.item_label == "Product":
                self.fields["item"].queryset = Item.objects.filter(product__isnull=False)
        else:
            del self.fields["item"]
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select" if isinstance(field, forms.ModelChoiceField) else "form-control"

    def clean(self):
        values = super().clean()
        if values.get("start") and values.get("end") and values["start"] > values["end"]:
            self.add_error("end", "The end date must be on or after the start date.")
        return values


def export_report(key, report, period, export):
    if export == "csv":
        response = HttpResponse("\ufeff", content_type="text/csv; charset=utf-8")
        writer = csv.writer(response)
        writer.writerow(report.columns)
        for row in report.rows(period):
            writer.writerow([
                "'" + cell if isinstance(cell, str) and cell.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
                else cell for cell in row
            ])
    elif export == "xlsx":
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell

        book = Workbook(write_only=True)
        sheet = book.create_sheet(report.title[:31])
        sheet.freeze_panes = "A2"
        sheet.append(report.columns)
        for row in report.rows(period):
            cells = []
            for value in row:
                cell = WriteOnlyCell(sheet, value=value)
                if isinstance(value, str):
                    cell.data_type = "s"
                cells.append(cell)
            sheet.append(cells)
        stream = BytesIO()
        book.save(stream)
        response = HttpResponse(stream.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        from .pdf import report_pdf

        response = HttpResponse(report_pdf(report, period), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="quill-{key}-{period.end}.{export}"'
    return response


@login_required
@require_safe
def report_index(request):
    if not access(request)["can_view_reports"]:
        raise PermissionDenied
    key = request.GET.get("report", "sales")
    selected = REPORTS.get(key)
    export = request.GET.get("format")
    if not selected or export not in (None, "csv", "xlsx", "pdf"):
        return HttpResponse("Unknown report or export format.", status=400)
    today = timezone.localdate()
    form = ReportFilter(request.GET, selected, today)
    rows = []
    has_more = False
    valid = form.is_valid()
    filters = request.GET.copy()
    for param in ("page", "format"):
        filters.pop(param, None)
    filters["report"] = key
    try:
        page = max(int(request.GET.get("page", "1")), 1)
    except ValueError:
        return HttpResponse("Invalid page.", status=400)
    if valid:
        values = form.cleaned_data
        period = data.Period(values.get("start", values["end"]), values["end"], values.get("customer"), values.get("item"))
        if export:
            return export_report(key, selected, period, export)
        if page > 1_000_000:
            return HttpResponse("Invalid page.", status=400)
        per_page = 50
        row_iterator = selected.rows(period)
        try:
            rows = list(islice(row_iterator, (page - 1) * per_page, page * per_page + 1))
        finally:
            row_iterator.close()
        has_more = len(rows) > per_page
        rows = rows[:per_page]
    return render(request, "reports/index.html", {
        "reports": REPORTS, "key": key, "report": selected, "form": form, "rows": rows,
        "filters": filters.urlencode(), "page": page, "previous": page - 1, "next_page": page + 1,
        "has_more": has_more, "valid": valid,
    }, status=400 if export and not valid else 200)


@login_required
@require_safe
def dashboard(request):
    if not access(request)["can_view_dashboard"]:
        raise PermissionDenied
    today = timezone.localdate()
    period = data.Period(today, today)
    orders = SalesOrder.objects.filter(**period.between("created_at"))
    critical = data.stock_balances(period).filter(is_active=True, closing__lte=F("reorder_point"))
    runs = ProductionRun.objects.filter(status=RunStatus.POSTED, **period.through("posted_at"))
    runs = runs.exclude(**period.through("reversal__created_at")).select_related("bom__product__item")
    movements = StockMovement.objects.order_by("-created_at", "-pk")[:6]
    invoices = Invoice.objects.order_by("-issued_at", "-pk")[:6]
    payments = Payment.objects.order_by("-received_at", "-pk")[:6]
    activity = [(row.created_at, row.get_movement_type_display(), row.source_reference) for row in movements]
    activity += [(row.issued_at, "Invoice issued", row.number) for row in invoices]
    activity += [(row.received_at, "Payment received", row.reference) for row in payments]
    return render(request, "reports/dashboard.html", {
        "today": today, "order_count": orders.count(), "submitted_count": orders.filter(status="SUBMITTED").count(),
        "receivables": data.receivables(period).aggregate(total=Sum("balance", default=data.ZERO))["total"],
        "critical_count": critical.count(), "critical": critical.order_by("closing", "sku")[:8],
        "alerts": runs.filter(has_variance_alert=True)[:6],
        "recent_costs": runs.filter(cost_per_good_unit__isnull=False)[:6],
        "activity": sorted(activity, key=lambda event: event[0], reverse=True)[:6],
    })
