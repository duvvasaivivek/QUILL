from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from core.models import AuditEvent
from core.workspace import workspace_for
from inventory.models import DocumentStatus, PurchaseReceipt
from production.models import ProductionRun, RunStatus
from reports.data import Period, receivables
from sales.models import Invoice, SalesOrder


class QuillLogoutView(LogoutView):
    next_page = "login"

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.success(request, "You signed out.")
        return response


@never_cache
@login_required
@require_safe
def home(request):
    workspace = workspace_for(request)
    section = workspace.home_type
    if section == "owner":
        return redirect("owner_dashboard")

    today = timezone.localdate()
    headings = {"operations": "Operations", "sales": "Sales workspace", "production": "Production", "audit": "Audit workspace"}
    context = {"section": section, "heading": headings.get(section, "Workspace"), "today": today, "destinations": workspace.links}
    if section == "operations" and workspace.allows("sales.change_salesorder"):
        queue = SalesOrder.objects.filter(status="SUBMITTED")
        invoices = Invoice.objects.filter(credit_note__isnull=True)
        context.update(
            orders=queue.select_related("customer").order_by("created_at", "pk")[:6],
            waiting_count=queue.count(),
            dispatch_count=invoices.filter(dispatched_at__isnull=True).count(),
            collections=receivables(Period(today, today)).select_related("order__customer").order_by("issued_at", "pk")[:4],
        )
    elif section == "sales" and "orders" in workspace.links:
        orders = SalesOrder.objects.filter(salesman=request.user)
        context.update(
            orders=orders.select_related("customer", "invoice").order_by("-created_at", "-pk")[:6],
            order_count=orders.count(),
            waiting_count=orders.filter(status="SUBMITTED").count(),
        )
    elif section == "production":
        if "production" in workspace.links:
            context["draft_runs"] = ProductionRun.objects.filter(status=RunStatus.DRAFT).select_related(
                "bom__product__item",
            ).order_by("-pk")[:6]
        if "purchases" in workspace.links:
            context["draft_receipts"] = PurchaseReceipt.objects.filter(status=DocumentStatus.DRAFT).select_related(
                "supplier",
            ).order_by("-pk")[:6]
    elif section == "audit" and "audit" in workspace.links:
        events = AuditEvent.objects.select_related("actor").order_by("-created_at", "-pk")[:5]
        context["events"] = [(event, event.action.replace("_", " ").capitalize()) for event in events]
    return render(request, "core/home.html", context)


def permission_denied(request, exception):
    return render(request, "core/error.html", {
        "title": "Access denied", "detail": "Your account does not have access to this page or action.",
    }, status=403)


def page_not_found(request, exception):
    return render(request, "core/error.html", {
        "title": "Page not found", "detail": "Check the address or return to your workspace.",
    }, status=404)


def csrf_failure(request, reason=""):
    return render(request, "core/error.html", {
        "title": "Form could not be submitted",
        "detail": "Return to the form and reload the page before trying again.",
    }, status=403)


def health(request):
    """Expose a lightweight probe endpoint for hosting platforms."""
    return JsonResponse({"status": "ok", "service": "quill"})


@require_safe
def manifest(request):
    return JsonResponse({
        "id": "/", "name": "QUILL Inventory and Sales", "short_name": "QUILL",
        "start_url": reverse("home"), "scope": "/", "display": "standalone",
        "background_color": "#f5f7fa", "theme_color": "#ffffff",
        "icons": [
            {"src": staticfiles_storage.url(f"icons/quill-{size}.png"),
             "sizes": f"{size}x{size}", "type": "image/png", "purpose": "any"}
            for size in (192, 512)
        ],
    }, content_type="application/manifest+json")


@require_safe
@never_cache
def service_worker(request):
    return render(request, "core/service-worker.js", content_type="application/javascript")
