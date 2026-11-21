"""Top-level URL routing for QUILL."""

from django.contrib import admin
from django.urls import path

from core import views
from inventory import views as inventory_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("stock/", inventory_views.stock_summary, name="stock_summary"),
    path("stock/<int:item_id>/", inventory_views.item_ledger, name="item_ledger"),
]
