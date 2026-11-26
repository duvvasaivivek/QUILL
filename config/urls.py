"""Top-level URL routing for QUILL."""

from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.urls import path

from core import views
from inventory import views as inventory_views
from inventory.models import OpeningBalance, PurchaseReceipt
from reports import views as report_views
from sales import views as sales_views

urlpatterns = [
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("service-worker.js", views.service_worker, name="service_worker"),
    path("reports/", report_views.report_index, name="reports"),
    path("dashboard/", report_views.dashboard, name="owner_dashboard"),
    path("login/", LoginView.as_view(template_name="sales/login.html"), name="login"),
    path("logout/", views.QuillLogoutView.as_view(), name="logout"),
    path("orders/", sales_views.orders, name="sales_orders"),
    path("orders/<int:order_id>/", sales_views.order_detail, name="sales_order"),
    path("invoices/<int:invoice_id>/pdf/", sales_views.invoice_pdf, name="invoice_pdf"),
    path("invoices/<int:invoice_id>/credit-note/pdf/", sales_views.invoice_pdf, {"credit": True}, name="credit_note_pdf"),
    path("admin/", admin.site.urls),
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("stock/", inventory_views.stock_summary, name="stock_summary"),
    path("stock/<int:item_id>/", inventory_views.item_ledger, name="item_ledger"),
    path("purchases/<int:document_id>/reverse/", inventory_views.purchase_reverse, name="purchase_receipt_reverse"),
    path("production-reversals/<int:reversal_id>/", inventory_views.production_reversal_detail, name="production_reversal_detail"),
]

for prefix, model, route in (
    ("purchases", PurchaseReceipt, "purchase_receipt"),
    ("opening-balances", OpeningBalance, "opening_balance"),
):
    urlpatterns += [
        path(f"{prefix}/", inventory_views.document_list, {"model": model}, name=f"{route}s"),
        path(f"{prefix}/new/", inventory_views.document_edit, {"model": model}, name=f"{route}_new"),
        path(f"{prefix}/<int:document_id>/", inventory_views.document_detail, {"model": model}, name=route),
        path(f"{prefix}/<int:document_id>/edit/", inventory_views.document_edit, {"model": model}, name=f"{route}_edit"),
        path(f"{prefix}/<int:document_id>/post/", inventory_views.document_post, {"model": model}, name=f"{route}_post"),
    ]

handler403 = views.permission_denied
handler404 = views.page_not_found
