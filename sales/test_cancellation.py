from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role, provision_role_groups
from core.models import AuditEvent
from inventory.models import stock_balance
from masters.models import Customer, Product
from reports.data import Period, gst_rows, margin_rows, receivables, sales_rows
from sales.models import SalesOrder, SalesOrderLine
from sales.services import approve_order, cancel_invoice, dispatch_invoice, record_payment


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class InvoiceCancellationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        provision_role_groups()
        users = get_user_model().objects
        cls.admin_user = users.create_user(username="factory-admin")
        cls.admin_user.groups.add(Group.objects.get(name=Role.ADMIN.value))
        cls.seller = users.create_user(username="seller")
        cls.seller.groups.add(Group.objects.get(name=Role.SALESMAN.value))
        call_command("seed_benchmark_reports", username="factory-admin", opening_only=True)
        cls.order = SalesOrder.objects.create(customer=Customer.objects.get(code="DISTRIBUTOR-B"), salesman=cls.seller)
        cls.product = Product.objects.get()
        SalesOrderLine.objects.create(order=cls.order, product=cls.product, quantity=20, unit_price=50)

    def test_admin_cancellation_credits_interstate_tax_and_returns_stock(self):
        invoice = approve_order(self.order, self.admin_user)
        self.assertEqual((invoice.cgst, invoice.sgst, invoice.igst), (0, 0, 50))
        dispatch_invoice(invoice, self.admin_user)
        self.assertEqual(stock_balance(self.product.item)[0], 30)

        url = reverse("sales_order", args=(self.order.pk,))
        payload = {"action": "cancel", "reason": "Full order returned", "goods_returned": "on"}
        self.client.force_login(self.seller)
        self.assertEqual(self.client.post(url, payload).status_code, 403)
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.outstanding, 0)
        self.assertEqual(stock_balance(self.product.item)[0], 50)
        self.assertTrue(AuditEvent.objects.filter(reference=invoice.number, actor=self.admin_user, action="cancelled").exists())
        self.assertEqual(self.client.get(reverse("credit_note_pdf", args=(invoice.pk,))).status_code, 200)

        today = timezone.localdate()
        period = Period(today, today)
        self.assertEqual([row[-1] for row in sales_rows(period)], [Decimal("1050"), Decimal("-1050")])
        self.assertEqual(next(iter(gst_rows(period)))[-1], 0)
        self.assertEqual(sum(row[-2] for row in margin_rows(period)), 0)
        self.assertFalse(receivables(period).exists())
        with self.assertRaises(ValidationError):
            invoice.save()
        with self.assertRaises(ValidationError):
            cancel_invoice(invoice, self.admin_user, "Duplicate")

    def test_paid_invoice_cannot_be_cancelled(self):
        invoice = approve_order(self.order, self.admin_user)
        record_payment(invoice, self.admin_user, Decimal("100"), "TEST-PAY")
        with self.assertRaisesMessage(ValidationError, "require a refund"):
            cancel_invoice(invoice, self.admin_user, "Wrong sale")
