from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Sum

from core.models import AppendOnlyRecord


class SalesOrder(models.Model):
    customer = models.ForeignKey("masters.Customer", on_delete=models.PROTECT)
    salesman = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, default="SUBMITTED", choices=[
        (status, status.title()) for status in ("SUBMITTED", "APPROVED", "REJECTED", "CANCELLED")
    ])
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def workflow_status(self):
        if self.status == "APPROVED" and hasattr(self, "invoice"):
            return "Dispatched" if self.invoice.dispatched_at else "Invoiced"
        return self.get_status_display()


class SalesOrderLine(models.Model):
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey("masters.Product", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)


class InvoiceSequence(models.Model):
    year = models.CharField(max_length=7, unique=True)
    number = models.PositiveIntegerField(default=0)


class Invoice(AppendOnlyRecord):
    order = models.OneToOneField(SalesOrder, on_delete=models.PROTECT)
    number = models.CharField(max_length=40, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    customer_snapshot = models.JSONField()
    issuer_snapshot = models.JSONField(default=dict, blank=True)
    taxable = models.DecimalField(max_digits=16, decimal_places=2)
    cgst = models.DecimalField(max_digits=16, decimal_places=2)
    sgst = models.DecimalField(max_digits=16, decimal_places=2)
    igst = models.DecimalField(max_digits=16, decimal_places=2)
    total = models.DecimalField(max_digits=16, decimal_places=2)
    dispatched_at = models.DateTimeField(null=True, blank=True)

    @property
    def outstanding(self):
        if hasattr(self, "credit_note"):
            return Decimal("0")
        return self.total - (self.payments.aggregate(amount=Sum("amount"))["amount"] or Decimal("0"))


class InvoiceLine(AppendOnlyRecord):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="lines")
    item = models.ForeignKey("masters.Item", on_delete=models.PROTECT)
    description = models.CharField(max_length=160)
    hsn = models.CharField(max_length=12)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2)
    taxable = models.DecimalField(max_digits=16, decimal_places=2)
    cgst = models.DecimalField(max_digits=16, decimal_places=2)
    sgst = models.DecimalField(max_digits=16, decimal_places=2)
    igst = models.DecimalField(max_digits=16, decimal_places=2)


class CreditNote(AppendOnlyRecord):
    invoice = models.OneToOneField(Invoice, on_delete=models.PROTECT, related_name="credit_note")
    number = models.CharField(max_length=40, unique=True)
    reason = models.CharField(max_length=250)
    issued_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class Payment(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    reference = models.CharField(max_length=80, unique=True)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    received_at = models.DateTimeField(auto_now_add=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
