from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_safe
from core.models import record_event
from masters.models import Customer, Product
from sales.models import Invoice, SalesOrder, SalesOrderLine
from sales.services import approve_order, cancel_invoice, dispatch_invoice, record_payment, stock_requirements, submit_order


class OrderForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=Customer.objects.filter(is_active=True))


class LineForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.filter(is_active=True, item__is_active=True).select_related("item"))
    quantity = forms.DecimalField(min_value=Decimal("0.001"), max_digits=14, decimal_places=3)


LineSet = forms.formset_factory(LineForm, extra=4, max_num=20, validate_max=True, absolute_max=20)


class OrderLineEditForm(forms.Form):
    unit_price = forms.DecimalField(min_value=Decimal("0"), max_digits=14, decimal_places=2)


class PaymentForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=16, decimal_places=2)
    reference = forms.CharField(max_length=80)


class CancellationForm(forms.Form):
    reason = forms.CharField(max_length=250)
    goods_returned = forms.BooleanField(required=False, label="All dispatched goods have been returned")

    def __init__(self, *args, dispatched=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not dispatched:
            del self.fields["goods_returned"]


def manager(user):
    return user.is_superuser or user.has_perm("sales.change_salesorder")


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def orders(request):
    can_manage = manager(request.user)
    if not (can_manage or request.user.has_perm("sales.add_salesorder")):
        raise PermissionDenied
    form, lines = OrderForm(request.POST or None), LineSet(request.POST or None)
    if request.method == "POST" and form.is_valid() and lines.is_valid():
        entries = [x.cleaned_data for x in lines if x.cleaned_data]
        try:
            order = submit_order(
                form.cleaned_data["customer"], request.user, ((entry["product"], entry["quantity"]) for entry in entries),
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Order submitted.")
            return redirect("sales_order", order_id=order.pk)
    records = SalesOrder.objects.select_related("customer", "invoice").order_by("-pk")
    if not can_manage:
        records = records.filter(salesman=request.user)
    totals = Invoice.objects.filter(order__in=records, credit_note__isnull=True).values("customer_snapshot__name").annotate(sales=Sum("total"))
    page = Paginator(records, 25).get_page(request.GET.get("page"))
    return render(request, "sales/orders.html", {
        "form": form, "lines": lines, "orders": page, "customer_sales": totals,
    })


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def order_detail(request, order_id):
    order = get_object_or_404(SalesOrder.objects.select_related("customer", "invoice__credit_note"), pk=order_id)
    can_manage = manager(request.user)
    if not can_manage and order.salesman_id != request.user.pk:
        raise PermissionDenied
    error = None
    payment_form = PaymentForm(request.POST if request.POST.get("action") == "pay" else None)
    cancellation_form = CancellationForm(
        request.POST if request.POST.get("action") == "cancel" else None,
        dispatched=bool(getattr(getattr(order, "invoice", None), "dispatched_at", None)),
    )
    if request.method == "POST":
        if not can_manage:
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
                    record_event(request.user, locked, "rejected", reference=locked.pk)
            elif action == "edit":
                with transaction.atomic():
                    locked = SalesOrder.objects.select_for_update().get(pk=order.pk)
                    if locked.status != "SUBMITTED":
                        raise ValidationError("Only submitted orders can be edited.")
                    changes = []
                    for line in locked.lines.order_by("pk"):
                        quantity = LineForm.base_fields["quantity"].clean(
                            request.POST.get(f"quantity_{line.pk}", str(line.quantity)),
                        )
                        unit_price = OrderLineEditForm.base_fields["unit_price"].clean(
                            request.POST.get(f"unit_price_{line.pk}", str(line.unit_price)),
                        )
                        updates = {"quantity": quantity, "unit_price": unit_price}
                        delta = {}
                        for field, new_value in updates.items():
                            old_value = getattr(line, field)
                            if old_value != new_value:
                                delta[field] = {"from": old_value, "to": new_value}
                                setattr(line, field, new_value)
                        if delta:
                            line.save(update_fields=tuple(delta))
                            changes.append({"line": line.pk, **delta})
                    if changes:
                        record_event(request.user, locked, "edited", reference=locked.pk, lines=changes)
            elif action in ("dispatch", "pay", "cancel"):
                invoice = get_object_or_404(Invoice, order=order)
                if action == "dispatch":
                    dispatch_invoice(invoice, request.user)
                elif action == "pay" and payment_form.is_valid():
                    record_payment(invoice, request.user, **payment_form.cleaned_data)
                elif action == "cancel":
                    if not request.user.has_perm("sales.add_creditnote"):
                        raise PermissionDenied
                    if cancellation_form.is_valid():
                        cancel_invoice(invoice, request.user, **cancellation_form.cleaned_data)
            else:
                raise ValidationError("Unknown order action.")
            if not payment_form.errors and not cancellation_form.errors:
                messages.success(request, {
                    "approve": "Invoice issued.",
                    "reject": "Order rejected.",
                    "edit": "Order details saved.",
                    "dispatch": "Dispatch recorded.",
                    "pay": "Payment recorded.",
                    "cancel": "Invoice cancelled and credit note issued.",
                }[action])
                return redirect("sales_order", order_id=order.pk)
        except ValidationError as exc:
            error = "; ".join(exc.messages)
    lines = list(order.lines.select_related("product__item__base_unit").order_by("pk"))
    review = stock_requirements(lines) if can_manage and order.status == "SUBMITTED" else []
    return render(request, "sales/detail.html", {
        "order": order, "lines": lines, "can_manage": can_manage, "error": error,
        "stock_review": review, "has_shortage": any(row.shortage for row in review),
        "payment_form": payment_form, "cancellation_form": cancellation_form,
    })


@login_required
@require_safe
def invoice_pdf(request, invoice_id, credit=False):
    from .pdf import render_invoice

    invoice = get_object_or_404(Invoice.objects.select_related("order", "credit_note"), pk=invoice_id)
    if not manager(request.user) and invoice.order.salesman_id != request.user.pk:
        raise PermissionDenied
    note = getattr(invoice, "credit_note", None)
    if credit and note is None:
        return HttpResponse(status=404)
    number = note.number if credit else invoice.number
    filename = "".join(char if char.isascii() and char.isalnum() else "-" for char in number)
    response = HttpResponse(render_invoice(invoice, credit_note=note if credit else None), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    response["Cache-Control"] = "private, no-store"
    return response
