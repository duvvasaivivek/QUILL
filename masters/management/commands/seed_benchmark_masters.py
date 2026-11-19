"""Load idempotent master data for the mandatory Murukku benchmark."""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from masters.models import (
    BOM,
    BOMLine,
    Customer,
    CustomerType,
    Item,
    ItemCategory,
    PriceList,
    PriceListItem,
    Product,
    Supplier,
    Unit,
    UnitCategory,
)


class Command(BaseCommand):
    help = "Load the required unit, item, customer, price-list, and BOM master data."

    @transaction.atomic
    def handle(self, *args, **options):
        units = {
            "kg": self._unit("kg", "Kilogram", UnitCategory.MASS, "1", True),
            "g": self._unit("g", "Gram", UnitCategory.MASS, "0.001", False),
            "L": self._unit("L", "Litre", UnitCategory.VOLUME, "1", True),
            "ml": self._unit("ml", "Millilitre", UnitCategory.VOLUME, "0.001", False),
            "piece": self._unit("piece", "Piece", UnitCategory.COUNT, "1", True),
            "packet": self._unit("packet", "Packet", UnitCategory.COUNT, "1", False),
            "carton": self._unit("carton", "Carton of 20 packets", UnitCategory.COUNT, "20", False),
        }

        flour = self._item("RM-FLOUR", "Flour", ItemCategory.RAW_MATERIAL, units["kg"], "0")
        oil = self._item("RM-OIL", "Cooking oil", ItemCategory.RAW_MATERIAL, units["L"], "0")
        spice = self._item("RM-SPICE", "Salt and spice mix", ItemCategory.RAW_MATERIAL, units["kg"], "0")
        pouch = self._item("PK-POUCH-200G", "200 g pouch", ItemCategory.PACKAGING, units["piece"], "0")
        carton = self._item("PK-CARTON-20", "Carton (holds 20 packets)", ItemCategory.PACKAGING, units["piece"], "0")
        finished_good = self._item(
            "FG-MURUKKU-200G",
            "Murukku 200 g",
            ItemCategory.FINISHED_GOOD,
            units["packet"],
            "5",
            hsn_code="19059040",
        )

        product, _ = Product.objects.update_or_create(
            item=finished_good,
            defaults={
                "pack_size": Decimal("200"),
                "pack_size_unit": units["g"],
                "selling_price": Decimal("50"),
                "is_active": True,
            },
        )
        retailer, _ = Customer.objects.update_or_create(
            code="RETAILER-A",
            defaults={
                "name": "Retailer A",
                "customer_type": CustomerType.RETAILER,
                "state_name": "Tamil Nadu",
                "state_code": "33",
                "is_active": True,
            },
        )
        Customer.objects.update_or_create(
            code="DISTRIBUTOR-B",
            defaults={
                "name": "Distributor B",
                "customer_type": CustomerType.DISTRIBUTOR,
                "state_name": "Karnataka",
                "state_code": "29",
                "is_active": True,
            },
        )
        Supplier.objects.update_or_create(
            code="SUPPLIER-RAW",
            defaults={
                "name": "Benchmark Raw Materials Supplier",
                "state_name": "Tamil Nadu",
                "state_code": "33",
                "is_active": True,
            },
        )
        price_list, _ = PriceList.objects.update_or_create(
            name="Benchmark standard price list",
            defaults={"effective_from": date(2026, 1, 1), "is_active": True},
        )
        PriceListItem.objects.update_or_create(
            price_list=price_list,
            product=product,
            defaults={"unit_price": Decimal("50")},
        )
        bom, _ = BOM.objects.update_or_create(
            product=product,
            version=1,
            defaults={"expected_output_quantity": Decimal("200"), "is_active": True},
        )
        for item, quantity, unit in (
            (flour, "40", units["kg"]),
            (oil, "10", units["L"]),
            (spice, "1.2", units["kg"]),
            (pouch, "200", units["piece"]),
            (carton, "10", units["piece"]),
        ):
            BOMLine.objects.update_or_create(
                bom=bom,
                item=item,
                defaults={"quantity": Decimal(quantity), "unit": unit},
            )

        self.stdout.write(self.style.SUCCESS("Loaded benchmark master data for Murukku 200 g."))
        self.stdout.write(f"Default sales customer: {retailer.code}")

    @staticmethod
    def _unit(code, name, category, conversion_to_base, is_base_unit):
        unit, _ = Unit.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "category": category,
                "conversion_to_base": Decimal(conversion_to_base),
                "is_base_unit": is_base_unit,
            },
        )
        return unit

    @staticmethod
    def _item(sku, name, category, base_unit, gst_rate, hsn_code=""):
        item, _ = Item.objects.update_or_create(
            sku=sku,
            defaults={
                "name": name,
                "category": category,
                "base_unit": base_unit,
                "hsn_code": hsn_code,
                "gst_rate": Decimal(gst_rate),
                "is_active": True,
            },
        )
        return item
