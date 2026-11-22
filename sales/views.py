from decimal import Decimal
from io import BytesIO
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from masters.models import Customer, Product
from sales.models import Invoice, SalesOrder, SalesOrderLine
from sales.services import approve_order, dispatch_invoice, record_payment


class OrderForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=Customer.objects.filter(is_active=True))


class LineForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.filter(is_active=True))
    quantity = forms.DecimalField(min_value=Decimal("0.001"), max_digits=14, decimal_places=3)


LineSet = forms.formset_factory(LineForm, extra=4)


class PaymentForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=16, decimal_places=2)
    reference = forms.CharField(max_length=80)


def manager(user):
    return user.is_superuser or user.has_perm("sales.change_salesorder")


@login_required
def orders(request):
    if not (manager(request.user) or request.user.has_perm("sales.add_salesorder")):
        raise PermissionDenied
    form, lines = OrderForm(request.POST or None), LineSet(request.POST or None)
    if request.method == "POST" and form.is_valid() and lines.is_valid():
        entries = [x.cleaned_data for x in lines if x.cleaned_data]
        if entries:
            with transaction.atomic():
                order = SalesOrder.objects.create(customer=form.cleaned_data["customer"], salesman=request.user)
                for entry in entries:
                    SalesOrderLine.objects.create(order=order, product=entry["product"], quantity=entry["quantity"], unit_price=entry["product"].selling_price)
            return redirect("sales_order", order_id=order.pk)
        form.add_error(None, "Add at least one product.")
    records = SalesOrder.objects.select_related("customer", "salesman").order_by("-pk")
    if not manager(request.user):
        records = records.filter(salesman=request.user)
    totals = Invoice.objects.filter(order__in=records).values("customer_snapshot__name").annotate(sales=Sum("total"))
    return render(request, "sales/orders.html", {"form": form, "lines": lines, "orders": records, "customer_sales": totals})


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(SalesOrder, pk=order_id)
    if not manager(request.user) and order.salesman_id != request.user.pk:
        raise PermissionDenied
    error = None
    payment_form = PaymentForm(request.POST if request.POST.get("action") == "pay" else None)
    if request.method == "POST":
        if not manager(request.user):
            raise PermissionDenied
        try:
            action = request.POST.get("action")
            if action == "approve":
                approve_order(order, request.user)
            elif action == "reject":
                with transaction.atomic():
                    locked = SalesOrder.objects.select_for_update().get(pk=order.pk)
                    if locked.status != "SUBMITTED":
                        raise ValidationError("Only submitted orders may be rejected.")
                    locked.status = "REJECTED"
                    locked.save()
            elif action == "dispatch":
                dispatch_invoice(order.invoice, request.user)
            elif action == "edit":
                with transaction.atomic():
                    locked = SalesOrder.objects.select_for_update().get(pk=order.pk)
                    if locked.status != "SUBMITTED":
                        raise ValidationError("Only submitted orders can be edited.")
                    for line in locked.lines.all():
                        try:
                            quantity = Decimal(request.POST.get(f"quantity_{line.pk}", str(line.quantity)))
                        except Exception:
                            raise ValidationError("Enter a valid quantity.")
                        if not quantity.is_finite() or quantity <= 0:
                            raise ValidationError("Quantity must be positive.")
                        line.quantity = quantity
                        line.save()
            elif action == "pay" and payment_form.is_valid():
                record_payment(order.invoice, request.user, **payment_form.cleaned_data)
            return redirect("sales_order", order_id=order.pk)
        except ValidationError as exc:
            error = "; ".join(exc.messages)
    return render(request, "sales/detail.html", {"order": order, "can_manage": manager(request.user), "error": error, "payment_form": payment_form})


@login_required
def invoice_pdf(request, invoice_id):
    from reportlab.pdfgen import canvas
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    if not manager(request.user) and invoice.order.salesman_id != request.user.pk:
        raise PermissionDenied
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 800
    def write(value):
        nonlocal y
        if y < 60:
            pdf.showPage()
            y = 800
        pdf.drawString(40, y, str(value))
        y -= 22
    write(f"QUILL - GST Invoice {invoice.number}")
    write(invoice.issued_at.strftime("%d-%m-%Y"))
    for key, value in invoice.customer_snapshot.items():
        write(f"{key}: {value}")
    for line in invoice.lines.all():
        write(f"{line.description} | HSN {line.hsn} | {line.quantity} x INR {line.unit_price} | GST {line.gst_rate}%")
    write(f"Taxable INR {invoice.taxable}")
    write(f"CGST {invoice.cgst}  SGST {invoice.sgst}  IGST {invoice.igst}")
    write(f"Total INR {invoice.total} | Outstanding INR {invoice.outstanding}")
    pdf.save()
    return HttpResponse(buffer.getvalue(), content_type="application/pdf")
