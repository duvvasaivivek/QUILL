from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import Role, provision_role_groups
from inventory.models import OpeningBalance, OpeningBalanceLine, PurchaseReceipt, PurchaseReceiptLine, PurchaseReceiptReversal, StockMovement, stock_balance
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


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class InventoryWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        provision_role_groups()
        cls.admin = User.objects.create_user(username="inventory-admin")
        cls.supervisor = User.objects.create_user(username="inventory-supervisor")
        cls.auditor = User.objects.create_user(username="inventory-auditor")
        for user, role in ((cls.admin, Role.ADMIN), (cls.supervisor, Role.PRODUCTION_SUPERVISOR), (cls.auditor, Role.AUDITOR)):
            user.groups.add(Group.objects.get(name=role.value))
        unit = Unit.objects.create(code="kg", name="Kilogram", category=UnitCategory.MASS, is_base_unit=True)
        cls.flour = Item.objects.create(sku="FLOUR", name="Flour", category=ItemCategory.RAW_MATERIAL, base_unit=unit)
        cls.sugar = Item.objects.create(sku="SUGAR", name="Sugar", category=ItemCategory.RAW_MATERIAL, base_unit=unit)
        cls.supplier = Supplier.objects.create(code="SUP", name="Supplier", state_name="Tamil Nadu", state_code="33")

    def draft_data(self, reference, rows, *, initial=0):
        data = {"reference": reference, "supplier": self.supplier.pk, "lines-TOTAL_FORMS": len(rows),
                "lines-INITIAL_FORMS": initial}
        for index, row in enumerate(rows):
            data.update({f"lines-{index}-{name}": value for name, value in row.items()})
        return data

    def test_opening_and_receipt_benchmark_through_workspace(self):
        self.client.force_login(self.admin)
        data = self.draft_data("OPEN-1", [{"item": self.flour.pk, "quantity": "100", "unit_cost": "20"}])
        opening = self.client.post(reverse("opening_balance_new"), data, follow=True)
        self.assertContains(opening, "Stock posting preview")
        self.client.post(reverse("opening_balance_post", args=[OpeningBalance.objects.get().pk]))
        self.assertEqual(stock_balance(self.flour)[0], Decimal("100"))

        self.client.force_login(self.supervisor)
        data = self.draft_data("GRN-1", [{"item": self.flour.pk, "quantity": "60", "unit_cost": "45"}])
        response = self.client.post(reverse("purchase_receipt_new"), data, follow=True)
        self.assertContains(response, "2700.0000")
        receipt = PurchaseReceipt.objects.get()
        url = reverse("purchase_receipt_post", args=[receipt.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertContains(self.client.post(url, follow=True), "Posted by")
        self.assertContains(self.client.post(url, follow=True), "Document has already been posted.")
        self.assertEqual(stock_balance(self.flour), (Decimal("160"), Decimal("4700")))
        self.assertEqual(StockMovement.objects.count(), 2)
        self.assertContains(self.client.get(reverse("item_ledger", args=[self.flour.pk])),
                            reverse("purchase_receipt", args=[receipt.pk]))
        self.assertContains(self.client.get(reverse("purchase_receipts"), {
            "reference": "grn", "supplier": self.supplier.pk, "status": "POSTED", "end": timezone.localdate(),
        }), "GRN-1")
        self.assertContains(self.client.get(reverse("stock_summary"), {"item": self.flour.pk}), "160")
        historical = self.client.get(reverse("stock_summary"), {"item": self.flour.pk, "end": "2000-01-01"})
        self.assertEqual(list(historical.context["page"])[0].stock_quantity, Decimal("0"))
        self.assertRedirects(self.client.get(reverse("purchase_receipt_edit", args=[receipt.pk])),
                             reverse("purchase_receipt", args=[receipt.pk]))

    def test_draft_validation_and_permissions(self):
        self.client.force_login(self.supervisor)
        self.assertEqual(self.client.get(reverse("opening_balance_new")).status_code, 403)
        response = self.client.post(reverse("purchase_receipt_new"), self.draft_data("INVALID", [
            {"item": self.flour.pk, "quantity": "-60", "unit_cost": "45"},
        ]))
        self.assertContains(response, "Quantity must be positive.")
        self.assertContains(response, 'value="-60"')
        self.assertFalse(PurchaseReceipt.objects.exists())

        receipt = PurchaseReceipt.objects.create(reference="DRAFT-1", supplier=self.supplier)
        flour = PurchaseReceiptLine.objects.create(document=receipt, item=self.flour, quantity=5, unit_cost=30)
        sugar = PurchaseReceiptLine.objects.create(document=receipt, item=self.sugar, quantity=10, unit_cost=20)
        edit = reverse("purchase_receipt_edit", args=[receipt.pk])
        response = self.client.post(edit, self.draft_data("DRAFT-1", [
            {"id": flour.pk, "item": self.sugar.pk, "quantity": "5", "unit_cost": "30"},
            {"id": sugar.pk, "item": self.flour.pk, "quantity": "10", "unit_cost": "20"},
        ], initial=2), follow=True)
        self.assertContains(response, "Draft saved.")
        self.assertEqual(receipt.lines.get(item=self.flour).quantity, Decimal("10"))
        self.client.force_login(self.auditor)
        self.assertContains(self.client.get(reverse("purchase_receipt", args=[receipt.pk])), "DRAFT-1")
        self.assertEqual(self.client.post(reverse("purchase_receipt_post", args=[receipt.pk])).status_code, 403)

    def test_receipt_correction_is_authorized_and_traceable(self):
        receipt = PurchaseReceipt.objects.create(reference="GRN-2", supplier=self.supplier)
        PurchaseReceiptLine.objects.create(document=receipt, item=self.flour, quantity=60, unit_cost=45)
        post_document(receipt, self.supervisor)
        reverse_url = reverse("purchase_receipt_reverse", args=[receipt.pk])
        self.client.force_login(self.supervisor)
        self.assertEqual(self.client.post(reverse_url, {"reason": "Wrong delivery"}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse_url), "Stock to remove")
        self.assertContains(self.client.post(reverse_url, {"reason": "Wrong delivery"}, follow=True), "Wrong delivery")
        self.assertEqual(stock_balance(self.flour), (Decimal("0"), Decimal("0")))
        self.assertEqual(receipt.lines.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 2)
        self.assertEqual(StockMovement.objects.get(reverses__isnull=False).reverses.receipt_line.document_id, receipt.pk)
        self.assertContains(self.client.post(reverse_url, {"reason": "Retry"}, follow=True), "it can be reversed once")
        self.assertEqual(PurchaseReceiptReversal.objects.count(), 1)
        self.assertContains(self.client.get(reverse("item_ledger", args=[self.flour.pk])),
                            reverse("purchase_receipt", args=[receipt.pk]) + "#reversal")

    def test_duplicate_items_and_opening_conflicts_preserve_stock(self):
        self.client.force_login(self.admin)
        row = {"item": self.flour.pk, "quantity": "5", "unit_cost": "12"}
        duplicate = self.client.post(reverse("purchase_receipt_new"), self.draft_data("DUP", [row, row]))
        self.assertContains(duplicate, "duplicate")
        self.assertFalse(PurchaseReceipt.objects.exists())

        first = OpeningBalance.objects.create(reference="FIRST")
        OpeningBalanceLine.objects.create(document=first, **{**row, "item": self.flour})
        post_document(first, self.admin)
        second = OpeningBalance.objects.create(reference="SECOND")
        OpeningBalanceLine.objects.create(document=second, **{**row, "item": self.flour})
        self.assertContains(self.client.get(reverse("opening_balance", args=[second.pk])), "Opening balance already exists for FLOUR.")
        self.client.post(reverse("opening_balance_post", args=[second.pk]))
        self.assertEqual(StockMovement.objects.count(), 1)
