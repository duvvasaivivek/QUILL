from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from inventory.models import OpeningBalance, OpeningBalanceLine, PurchaseReceipt, PurchaseReceiptLine, StockMovement, stock_balance
from inventory.services import average_unit_cost, post_document
from masters.models import Item, ItemCategory, Supplier, Unit, UnitCategory


class PostingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="stock-admin", password="password")
        unit = Unit.objects.create(code="kg", name="Kilogram", category=UnitCategory.MASS, is_base_unit=True)
        self.flour = Item.objects.create(sku="RM-FLOUR", name="Flour", category=ItemCategory.RAW_MATERIAL, base_unit=unit)
        self.supplier = Supplier.objects.create(code="SUP", name="Supplier", state_name="Tamil Nadu", state_code="33")

    def test_opening_and_purchase_benchmark_with_weighted_average(self):
        opening = OpeningBalance.objects.create(reference="OPEN-1")
        OpeningBalanceLine.objects.create(document=opening, item=self.flour, quantity=100, unit_cost=20)
        post_document(opening, self.user)
        receipt = PurchaseReceipt.objects.create(reference="GRN-1", supplier=self.supplier)
        PurchaseReceiptLine.objects.create(document=receipt, item=self.flour, quantity=60, unit_cost=30)
        post_document(receipt, self.user)

        self.assertEqual(stock_balance(self.flour), (Decimal("160"), Decimal("3800")))
        self.assertEqual(average_unit_cost(self.flour), Decimal("23.75"))
        self.assertEqual(StockMovement.objects.count(), 2)
        movement = StockMovement.objects.get(receipt_line__document=receipt)
        self.assertEqual(movement.source_reference, "GRN-1")
        self.assertEqual(movement.unit_id, self.flour.base_unit_id)

        with self.assertRaises(ValidationError):
            post_document(receipt, self.user)
        self.assertEqual(StockMovement.objects.count(), 2)
        with self.assertRaises(ValidationError):
            movement.delete()

    def test_failed_document_rolls_back_every_movement(self):
        opening = OpeningBalance.objects.create(reference="OPEN-1")
        OpeningBalanceLine.objects.create(document=opening, item=self.flour, quantity=100, unit_cost=20)
        post_document(opening, self.user)
        duplicate = OpeningBalance.objects.create(reference="OPEN-2")
        another = Item.objects.create(sku="RM-OTHER", name="Other", category=ItemCategory.RAW_MATERIAL, base_unit=self.flour.base_unit)
        OpeningBalanceLine.objects.create(document=duplicate, item=another, quantity=2, unit_cost=1)
        OpeningBalanceLine.objects.create(document=duplicate, item=self.flour, quantity=1, unit_cost=1)
        with self.assertRaises(ValidationError):
            post_document(duplicate, self.user)
        self.assertEqual(StockMovement.objects.count(), 1)
        duplicate.refresh_from_db()
        self.assertEqual(duplicate.status, "DRAFT")

    def test_posted_line_cannot_change(self):
        opening = OpeningBalance.objects.create(reference="OPEN-1")
        line = OpeningBalanceLine.objects.create(document=opening, item=self.flour, quantity=100, unit_cost=20)
        post_document(opening, self.user)
        line.quantity = 200
        with self.assertRaises(ValidationError):
            line.save()
        opening.reference = "CHANGED"
        with self.assertRaises(ValidationError):
            opening.save()
        with self.assertRaises(ValidationError):
            OpeningBalance.objects.filter(pk=opening.pk).update(reference="CHANGED")
        with self.assertRaises(ValidationError):
            OpeningBalanceLine.objects.filter(pk=line.pk).update(quantity=200)
        with self.assertRaises(ValidationError):
            StockMovement.objects.filter(item=self.flour).update(quantity=200)
        with self.assertRaises(ValidationError):
            StockMovement.objects.filter(item=self.flour).delete()

    def test_second_opening_is_rejected_even_when_current_quantity_is_zero(self):
        opening = OpeningBalance.objects.create(reference="OPEN-1")
        OpeningBalanceLine.objects.create(document=opening, item=self.flour, quantity=100, unit_cost=20)
        post_document(opening, self.user)
        # A later consumption can bring stock back to zero without resetting its history.
        StockMovement.objects.create(item=self.flour, item_category=self.flour.category,
            quantity=-100, unit=self.flour.base_unit, movement_type="PRODUCTION_ISSUE",
            source_reference="RUN-1", unit_cost=20, value=-2000, created_by=self.user)
        second = OpeningBalance.objects.create(reference="OPEN-2")
        OpeningBalanceLine.objects.create(document=second, item=self.flour, quantity=10, unit_cost=30)
        with self.assertRaises(ValidationError):
            post_document(second, self.user)
