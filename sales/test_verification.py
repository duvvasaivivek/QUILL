from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import Role, provision_role_groups
from core.models import AuditEvent
from inventory.models import MovementType, StockMovement
from masters.models import Customer, PriceList, PriceListItem, Product
from sales.models import Invoice, SalesOrder
from sales.services import approve_order, dispatch_invoice, stock_requirements, submit_order


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class OrderVerificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        provision_role_groups()
        cls.admin = User.objects.create_user(username="verification-admin")
        cls.salesman = User.objects.create_user(username="verification-sales")
        cls.admin.groups.add(Group.objects.get(name=Role.ADMIN.value))
        cls.salesman.groups.add(Group.objects.get(name=Role.SALESMAN.value))
        call_command("seed_benchmark_reports", username=cls.admin.username, opening_only=True, stdout=StringIO())
        cls.product = Product.objects.get()
        cls.customer = Customer.objects.get(code="RETAILER-A")

    def test_order_uses_active_pricing_and_admin_override_is_snapshotted(self):
        today = timezone.localdate()
        for name, customer, starts, ends, price in [
            ("General current", None, today, None, 55),
            ("Customer current", self.customer, today - timedelta(days=1), today, 48),
            ("Customer future", self.customer, today + timedelta(days=1), None, 23),
            ("Customer expired", self.customer, today - timedelta(days=3), today - timedelta(days=1), 31),
        ]:
            price_list = PriceList.objects.create(name=name, customer=customer, effective_from=starts, effective_to=ends)
            PriceListItem.objects.create(price_list=price_list, product=self.product, unit_price=price)

        self.client.force_login(self.salesman)
        response = self.client.post(reverse("sales_orders"), {
            "customer": self.customer.pk, "form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 0,
            "form-0-product": self.product.pk, "form-0-quantity": "10",
        })
        self.assertEqual(response.status_code, 302)
        order = SalesOrder.objects.get()
        line = order.lines.get()
        self.assertEqual(line.unit_price, 48)
        edit_data = {"action": "edit", f"unit_price_{line.pk}": "50.00"}
        url = reverse("sales_order", args=[order.pk])
        self.assertEqual(self.client.post(url, edit_data).status_code, 403)

        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), "Stock before approval")
        self.assertEqual(self.client.post(url, edit_data).status_code, 302)
        event = AuditEvent.objects.get(action="edited")
        self.assertEqual(event.details["lines"][0]["unit_price"], {"from": "48.00", "to": "50.00"})
        self.assertEqual(self.client.post(url, {"action": "approve"}).status_code, 302)
        invoice = Invoice.objects.get(order=order)
        self.assertEqual(invoice.lines.get().unit_price, 50)
        self.assertEqual((invoice.cgst, invoice.sgst, invoice.igst), (Decimal("12.50"), Decimal("12.50"), 0))
        self.assertEqual(invoice.issuer_snapshot["state_code"], invoice.customer_snapshot["state_code"])
        response = self.client.get(reverse("invoice_pdf", args=[invoice.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_duplicate_products_share_one_stock_lookup_and_approval_rechecks_availability(self):
        order = submit_order(self.customer, self.salesman, [(self.product, 20), (self.product, 20)])
        lines = list(order.lines.select_related("product__item"))
        with self.assertNumQueries(1):
            review = stock_requirements(lines)
        self.assertEqual((review[0].required, review[0].available, review[0].shortage), (40, 50, 0))
        other_order = submit_order(self.customer, self.salesman, [(self.product, 5), (self.product, 10)])
        dispatch_invoice(approve_order(other_order, self.admin), self.admin)
        self.assertEqual(StockMovement.objects.filter(movement_type=MovementType.DISPATCH).count(), 1)
        with self.assertRaisesMessage(ValidationError, "shortage of 5"):
            approve_order(order, self.admin)
        self.assertFalse(Invoice.objects.filter(order=order).exists())
