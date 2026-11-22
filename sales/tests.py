from decimal import Decimal
from django.test import TestCase
from django.core.management import call_command
from django.core.exceptions import ValidationError
from accounts.models import User
from masters.models import Customer, Product
from inventory.models import StockMovement, stock_balance
from sales.models import SalesOrder, SalesOrderLine
from sales.services import approve_order, dispatch_invoice, record_payment


class SalesBenchmarkTests(TestCase):
    def test_invoice_dispatch_payment_and_shortage(self):
        call_command("seed_benchmark_masters", verbosity=0)
        user = User.objects.create_user(username="admin")
        product = Product.objects.get(item__sku="FG-MURUKKU-200G")
        StockMovement.objects.create(item=product.item, item_category="FG", quantity=238,
            unit=product.item.base_unit, movement_type="OPENING", source_reference="OPEN", unit_cost=20, value=4760, created_by=user)
        order = SalesOrder.objects.create(customer=Customer.objects.get(code="RETAILER-A"), salesman=user)
        SalesOrderLine.objects.create(order=order, product=product, quantity=150, unit_price=50)
        invoice = approve_order(order, user)
        self.assertEqual(invoice.total, Decimal("7875"))
        self.assertEqual(invoice.cgst, Decimal("187.50"))
        self.client.force_login(user)
        response = self.client.get(f"/invoices/{invoice.pk}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        dispatch_invoice(invoice, user)
        self.assertEqual(stock_balance(product.item)[0], Decimal("88"))
        record_payment(invoice, user, Decimal("4000"), "PAY-1")
        self.assertEqual(invoice.outstanding, Decimal("3875"))
        with self.assertRaises(ValidationError):
            dispatch_invoice(invoice, user)
        other = SalesOrder.objects.create(customer=Customer.objects.get(code="DISTRIBUTOR-B"), salesman=user)
        SalesOrderLine.objects.create(order=other, product=product, quantity=120, unit_price=50)
        with self.assertRaisesMessage(ValidationError, "32"):
            approve_order(other, user)
