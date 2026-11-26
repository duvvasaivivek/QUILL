from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from inventory.forms import DOCUMENT_FORMS, ReceiptCorrectionForm, ReceiptFilter, StockFilter
from inventory.models import DocumentStatus, MovementType, OpeningBalance, PurchaseReceipt, PurchaseReceiptReversal, StockMovement
from inventory.services import line_value, post_document, reverse_purchase_receipt
from masters.models import Item
from production.models import ProductionReversal, ProductionRun
from sales.models import CreditNote, Invoice
from sales.views import manager


def paginate(request, records):
    return Paginator(records, 25).get_page(request.GET.get("page"))


def has_document_permission(user, model, action):
    return user.has_perm(f"inventory.{action}_{model._meta.model_name}")


def can_edit(user, model, *, new=False):
    line = model._meta.get_field("lines").related_model
    actions = ("add",) if new else ("add", "change")
    return has_document_permission(user, model, "add" if new else "change") and all(
        has_document_permission(user, line, action) for action in actions
    )


def document_context(user, model):
    purchase = model is PurchaseReceipt
    return {
        "purchase": purchase,
        "label": "Purchase receipt" if purchase else "Opening balance",
        "list_label": "Purchase receipts" if purchase else "Opening balances",
        "list_url": "purchase_receipts" if purchase else "opening_balances",
        "new_url": "purchase_receipt_new" if purchase else "opening_balance_new",
        "detail_url": "purchase_receipt" if purchase else "opening_balance",
        "edit_url": "purchase_receipt_edit" if purchase else "opening_balance_edit",
        "post_url": "purchase_receipt_post" if purchase else "opening_balance_post",
        "can_create": can_edit(user, model, new=True),
    }


@login_required
@require_http_methods(["GET", "HEAD"])
def document_list(request, model):
    if not has_document_permission(request.user, model, "view"):
        raise PermissionDenied
    documents = model.objects.select_related("posted_by").order_by("-pk")
    filters = None
    if model is PurchaseReceipt:
        documents = documents.select_related("supplier", "reversal").annotate(receipt_date=Coalesce("posted_at", "created_at"))
        filters = ReceiptFilter(request.GET or None)
        if filters.is_valid():
            data = filters.cleaned_data
            for field, value in (
                ("reference__icontains", data["reference"]), ("supplier", data["supplier"]),
                ("receipt_date__date__gte", data["start"]),
                ("receipt_date__date__lte", data["end"]),
            ):
                if value:
                    documents = documents.filter(**{field: value})
            if data["status"] == "REVERSED":
                documents = documents.filter(reversal__isnull=False)
            elif data["status"]:
                documents = documents.filter(status=data["status"], reversal__isnull=True)
    return render(request, "inventory/documents.html", {
        **document_context(request.user, model), "page": paginate(request, documents), "filters": filters,
    })


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def document_edit(request, model, document_id=None):
    new = document_id is None
    if not has_document_permission(request.user, model, "view") or not can_edit(request.user, model, new=new):
        raise PermissionDenied
    context = document_context(request.user, model)
    form_type, lines_type = DOCUMENT_FORMS[model]
    can_remove = has_document_permission(request.user, model._meta.get_field("lines").related_model, "delete")
    data = request.POST if request.method == "POST" else None
    try:
        with transaction.atomic():
            documents = model.objects.select_for_update() if data is not None else model.objects.all()
            document = model() if new else get_object_or_404(documents, pk=document_id)
            if document.status == DocumentStatus.POSTED:
                messages.info(request, "This document is already posted.")
                return redirect(context["detail_url"], document_id=document.pk)
            form = form_type(data, instance=document)
            lines = lines_type(data, instance=document, queryset=document.lines.select_related("item__base_unit") if not new else None)
            if data is not None:
                form_valid, lines_valid = form.is_valid(), lines.is_valid()
                if form_valid and lines_valid:
                    if not can_remove and any(row.cleaned_data.get("DELETE") for row in lines.initial_forms):
                        raise PermissionDenied
                    form.save()
                    lines.save_draft()
                    messages.success(request, "Draft saved.")
                    return redirect(context["detail_url"], document_id=document.pk)
    except ValidationError as error:
        form.add_error(None, error.messages)
    except IntegrityError:
        form.add_error(None, "The reference or a material is already in use. Review the draft and try again.")
    return render(request, "inventory/document_form.html", {
        **context, "form": form, "lines": lines, "new": new, "document_id": document_id, "can_remove": can_remove,
    })


@login_required
@require_http_methods(["GET", "HEAD"])
def document_detail(request, model, document_id):
    if not has_document_permission(request.user, model, "view"):
        raise PermissionDenied
    context = document_context(request.user, model)
    purchase = context["purchase"]
    documents = model.objects.select_related("posted_by")
    if purchase:
        documents = documents.select_related("supplier", "reversal__created_by")
    document = get_object_or_404(documents, pk=document_id)
    draft = document.status == DocumentStatus.DRAFT
    reversal = getattr(document, "reversal", None)
    rows, problems = [], []
    total = Decimal("0")
    lines = list(document.lines.select_related("item__base_unit").order_by("item__sku"))
    if draft and not lines:
        problems.append("Add at least one line before posting.")
    if draft and not purchase:
        conflicts = StockMovement.objects.filter(movement_type=MovementType.OPENING, item_id__in=[line.item_id for line in lines])
        problems.extend(f"Opening balance already exists for {sku}." for sku in conflicts.values_list("item__sku", flat=True).order_by("item__sku"))
    for line in lines:
        try:
            amount = line_value(line.quantity, line.unit_cost)
        except ValidationError as error:
            problems.append(f"{line.item.sku}: {error.messages[0]}")
            amount = None
        else:
            total += amount
        rows.append((line, amount))
    return render(request, "inventory/document_detail.html", {
        **context, "document": document, "draft": draft, "rows": rows, "total": total, "problems": problems,
        "can_edit": draft and can_edit(request.user, model),
        "can_post": draft and not problems and has_document_permission(request.user, model, "change"),
        "reversal": reversal,
        "can_reverse": purchase and not draft and not reversal and request.user.has_perm("inventory.add_purchasereceiptreversal"),
    })


@login_required
@require_POST
def document_post(request, model, document_id):
    if not all(has_document_permission(request.user, model, action) for action in ("view", "change")):
        raise PermissionDenied
    document = get_object_or_404(model, pk=document_id)
    try:
        post_document(document, request.user)
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
    else:
        messages.success(request, f"Posted {document.reference}. Stock updated.")
    return redirect(document_context(request.user, model)["detail_url"], document_id=document.pk)


@login_required
@permission_required(("inventory.view_purchasereceipt", "inventory.add_purchasereceiptreversal"), raise_exception=True)
@require_http_methods(["GET", "HEAD", "POST"])
def purchase_reverse(request, document_id):
    receipt = get_object_or_404(PurchaseReceipt, pk=document_id)
    if receipt.status != DocumentStatus.POSTED or hasattr(receipt, "reversal"):
        messages.error(request, "Only a posted receipt can be reversed, and it can be reversed once.")
        return redirect("purchase_receipt", document_id=document_id)
    form = ReceiptCorrectionForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        try:
            reversal = reverse_purchase_receipt(receipt, request.user, form.cleaned_data["reason"])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f"Recorded {reversal.reference}. Stock updated.")
            return redirect("purchase_receipt", document_id=document_id)
    movements = StockMovement.objects.filter(receipt_line__document=receipt).select_related("item", "unit")
    return render(request, "inventory/purchase_reverse.html", {"document": receipt, "form": form, "movements": movements})


@login_required
@permission_required("production.view_productionreversal", raise_exception=True)
def production_reversal_detail(request, reversal_id):
    reversal = get_object_or_404(ProductionReversal.objects.select_related("run", "created_by"), pk=reversal_id)
    return render(request, "inventory/production_reversal.html", {"reversal": reversal})


@login_required
@permission_required("inventory.view_stockmovement", raise_exception=True)
def stock_summary(request):
    filters = StockFilter(request.GET or None)
    items = Item.objects.order_by("sku")
    period = Q()
    if filters.is_valid():
        data = filters.cleaned_data
        if data["category"]:
            items = items.filter(category=data["category"])
        if data["item"]:
            items = items.filter(pk=data["item"].pk)
        if data["end"]:
            period = Q(stock_movements__created_at__date__lte=data["end"])
    page = paginate(request, items)
    page_item_ids = page.object_list.values("pk")
    page.object_list = Item.objects.filter(pk__in=page_item_ids).select_related("base_unit").annotate(
        stock_quantity=Sum("stock_movements__quantity", filter=period, default=0),
        stock_value=Sum("stock_movements__value", filter=period, default=0),
    ).order_by("sku")
    return render(request, "inventory/stock_summary.html", {"page": page, "filters": filters})


def movement_links(user, movements):
    links = {}
    by_type = {}
    sales_manager = manager(user)
    for movement in movements:
        by_type.setdefault(movement.movement_type, set()).add(movement.source_reference)
        if movement.opening_line_id and user.has_perm("inventory.view_openingbalance"):
            links[movement.pk] = reverse("opening_balance", args=[movement.opening_line.document_id])
        if movement.receipt_line_id and user.has_perm("inventory.view_purchasereceipt"):
            links[movement.pk] = reverse("purchase_receipt", args=[movement.receipt_line.document_id])

    documents = [
        ((MovementType.DISPATCH,), Invoice, "number", "invoice_pdf", False),
        ((MovementType.RETURN,), CreditNote, "number", "credit_note_pdf", False),
    ]
    if user.is_staff and user.has_perm("production.view_productionrun"):
        documents.append(((MovementType.PRODUCTION_ISSUE, MovementType.PRODUCTION_OUTPUT), ProductionRun,
                          "reference", "admin:production_productionrun_change", True))
    if user.has_perm("production.view_productionreversal"):
        documents.append(((MovementType.ADJUSTMENT,), ProductionReversal, "reference", "production_reversal_detail", True))
    if user.has_perm("inventory.view_purchasereceipt"):
        documents.append(((MovementType.ADJUSTMENT,), PurchaseReceiptReversal, "reference", "purchase_receipt", True))

    for types, model, field, route, access_checked in documents:
        references = set().union(*(by_type.get(kind, set()) for kind in types))
        if not references:
            continue
        sources = model.objects.filter(**{f"{field}__in": references})
        if not access_checked and not sales_manager:
            owner_field = "order__salesman" if model is Invoice else "invoice__order__salesman"
            sources = sources.filter(**{owner_field: user})
        id_field = {CreditNote: "invoice_id", PurchaseReceiptReversal: "receipt_id"}.get(model, "pk")
        ids = dict(sources.values_list(field, id_field))
        for movement in movements:
            if movement.movement_type in types and movement.source_reference in ids:
                links[movement.pk] = reverse(route, args=[ids[movement.source_reference]])
                if model is PurchaseReceiptReversal:
                    links[movement.pk] += "#reversal"
    return links


@login_required
@permission_required("inventory.view_stockmovement", raise_exception=True)
def item_ledger(request, item_id):
    item = get_object_or_404(Item.objects.select_related("base_unit"), pk=item_id)
    movements = StockMovement.objects.filter(item=item).select_related(
        "created_by", "opening_line", "receipt_line",
    ).order_by("-created_at", "-pk")
    date_filter = StockFilter({"end": request.GET.get("end", "")})
    if date_filter.is_valid() and (end := date_filter.cleaned_data["end"]):
        movements = movements.filter(created_at__date__lte=end)
    page = paginate(request, movements)
    links = movement_links(request.user, list(page))
    return render(request, "inventory/item_ledger.html", {
        "item": item, "page": page, "date_filter": date_filter["end"],
        "rows": [(movement, links.get(movement.pk)) for movement in page],
    })
