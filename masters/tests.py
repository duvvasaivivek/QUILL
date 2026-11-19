from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from masters.models import BOM, BOMLine, Item, ItemCategory, Product, Unit, UnitCategory


class MasterDataValidationTests(TestCase):
    def setUp(self) -> None:
        self.kilogram = Unit.objects.create(
            code="kg",
            name="Kilogram",
            category=UnitCategory.MASS,
            conversion_to_base=Decimal("1"),
            is_base_unit=True,
        )
        self.litre = Unit.objects.create(
            code="L",
            name="Litre",
            category=UnitCategory.VOLUME,
            conversion_to_base=Decimal("1"),
            is_base_unit=True,
        )
        self.packet = Unit.objects.create(
            code="packet",
            name="Packet",
            category=UnitCategory.COUNT,
            conversion_to_base=Decimal("1"),
            is_base_unit=True,
        )
        self.flour = Item.objects.create(
            sku="RM-FLOUR",
            name="Flour",
            category=ItemCategory.RAW_MATERIAL,
            base_unit=self.kilogram,
        )
        finished_item = Item.objects.create(
            sku="FG-MURUKKU-200G",
            name="Murukku 200 g",
            category=ItemCategory.FINISHED_GOOD,
            base_unit=self.packet,
            gst_rate=Decimal("5"),
        )
        self.product = Product.objects.create(
            item=finished_item,
            pack_size=Decimal("0.2"),
            pack_size_unit=self.kilogram,
            selling_price=Decimal("50"),
        )

    def test_bom_line_rejects_an_incompatible_unit(self) -> None:
        bom = BOM.objects.create(product=self.product, expected_output_quantity=Decimal("200"))
        line = BOMLine(bom=bom, item=self.flour, quantity=Decimal("40"), unit=self.litre)

        with self.assertRaises(ValidationError):
            line.full_clean()

    def test_a_second_base_unit_in_the_same_category_is_rejected(self) -> None:
        gram = Unit(
            code="g",
            name="Gram",
            category=UnitCategory.MASS,
            conversion_to_base=Decimal("0.001"),
            is_base_unit=True,
        )

        with self.assertRaises(ValidationError):
            gram.full_clean()
