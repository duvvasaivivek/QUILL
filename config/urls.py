"""Top-level URL routing for QUILL."""

from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path

from core import views
from inventory import views as inventory_views
from reports import views as report_views
from sales import views as sales_views

urlpatterns = [
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("service-worker.js", views.service_worker, name="service_worker"),
    path("reports/", report_views.report_index, name="reports"),
    path("dashboard/", report_views.dashboard, name="owner_dashboard"),
    path("login/", views.QuillLoginView.as_view(template_name="sales/login.html"), name="login"),
    path("logout/", LogoutView.as_view(next_page="home"), name="logout"),
    path("orders/", sales_views.orders, name="sales_orders"),
    path("orders/<int:order_id>/", sales_views.order_detail, name="sales_order"),
    path("invoices/<int:invoice_id>/pdf/", sales_views.invoice_pdf, name="invoice_pdf"),
    path("invoices/<int:invoice_id>/credit-note/pdf/", sales_views.invoice_pdf, {"credit": True}, name="credit_note_pdf"),
    path("admin/", admin.site.urls),
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("stock/", inventory_views.stock_summary, name="stock_summary"),
    path("stock/<int:item_id>/", inventory_views.item_ledger, name="item_ledger"),
]
