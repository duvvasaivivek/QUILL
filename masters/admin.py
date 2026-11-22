from django.contrib import admin

from .models import BOM, BOMLine, Customer, Item, PriceList, PriceListItem, Product, Supplier, Unit


class BOMLineInline(admin.TabularInline):
    model = BOMLine
    extra = 0


class PriceListItemInline(admin.TabularInline):
    model = PriceListItem
    extra = 0


@admin.register(BOM)
class BOMAdmin(admin.ModelAdmin):
    list_display = ("product", "version", "expected_output_quantity", "is_active")
    list_filter = ("is_active",)
    inlines = (BOMLineInline,)


@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin):
    list_display = ("name", "customer", "effective_from", "effective_to", "is_active")
    list_filter = ("is_active",)
    inlines = (PriceListItemInline,)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "conversion_to_base", "is_base_unit")
    list_filter = ("category", "is_base_unit")
    search_fields = ("code", "name")


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "base_unit", "hsn_code", "gst_rate", "reorder_point", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("sku", "name")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("item", "pack_size", "pack_size_unit", "selling_price", "is_active")
    list_filter = ("is_active",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "customer_type", "state_name", "gstin", "is_active")
    list_filter = ("customer_type", "state_name", "is_active")
    search_fields = ("code", "name", "gstin")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "state_name", "gstin", "is_active")
    list_filter = ("state_name", "is_active")
    search_fields = ("code", "name", "gstin")
