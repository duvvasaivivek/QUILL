import csv
from datetime import timedelta
from decimal import Decimal
from io import BytesIO, StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from sales.models import Payment, SalesOrder
from sales.services import approve_order

from .views import REPORTS


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class BenchmarkReportsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.auditor = users.create_user(username="audit")
        cls.owner = users.create_user(username="owner")
        cls.salesman = users.create_user(username="salesman")
        for user, role in ((cls.auditor, "Auditor"), (cls.owner, "Owner"), (cls.salesman, "Salesman")):
            user.groups.add(Group.objects.get_or_create(name=role)[0])
        call_command("seed_benchmark_reports", username=cls.salesman.username, stdout=StringIO())

    def test_every_report_contains_benchmark_data(self):
        self.client.force_login(self.auditor)
        results = {}
        for key, report in REPORTS.items():
            with self.subTest(report=key):
                response = self.client.get(reverse("reports"), {"report": key})
                self.assertEqual(response.status_code, 200)
                rows = response.context["rows"]
                self.assertTrue(rows)
                self.assertTrue(all(len(row) == len(report.columns) for row in rows))
                results[key] = rows

        self.assertEqual(results["sales"][0][-1], Decimal("7875"))
        self.assertEqual(results["gst"][0][4:], (7500, Decimal("187.50"), Decimal("187.50"), 0, 7875))
        self.assertEqual(results["purchases"][0][-1], Decimal("2700"))
        closing = {row[0]: row[-2] for row in results["stock"]}
        self.assertEqual(closing["RM-FLOUR"], Decimal("120"))
        self.assertEqual(closing["RM-OIL"], Decimal("19.5"))
        self.assertEqual(closing["PK-POUCH-200G"], Decimal("306"))
        self.assertEqual(closing["FG-MURUKKU-200G"], Decimal("88"))
        self.assertEqual(results["production"][0][3:], (200, 188, 12, -6))
        self.assertIn(("RM-OIL", 10, Decimal("10.5"), 5, 3), [row[3:] for row in results["variance"]])
        self.assertEqual(results["ageing"][0][-1], Decimal("3875"))
        self.assertEqual(results["costing"][0][-1], Decimal("31.1436"))
        self.assertGreater(results["margin"][0][-2], 0)
        other = SalesOrder.objects.get(customer__code="DISTRIBUTOR-B")
        with self.assertRaisesMessage(ValidationError, "shortage of 32"):
            approve_order(other, self.salesman)

    def test_exports_share_the_same_filter_and_preserve_amounts(self):
        self.client.force_login(self.auditor)
        retailer = SalesOrder.objects.get(customer__code="RETAILER-A").customer
        url = reverse("reports")
        query = {"report": "sales", "customer": retailer.pk}
        csv_response = self.client.get(url, {**query, "format": "csv"})
        rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 2)
        self.assertEqual(Decimal(rows[1][-1]), Decimal("7875"))

        excel_response = self.client.get(url, {**query, "format": "xlsx"})
        with BytesIO(excel_response.content) as workbook_data:
            workbook = load_workbook(workbook_data, read_only=True)
            self.addCleanup(workbook.close)
            workbook_rows = list(workbook.active.values)
        self.assertEqual(len(workbook_rows), 2)
        self.assertEqual(workbook_rows[1][-1], 7875)

        pdf_response = self.client.get(url, {**query, "format": "pdf"})
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")
        self.assertTrue(pdf_response.content.startswith(b"%PDF"))

    def test_ageing_excludes_payments_after_cutoff(self):
        self.client.force_login(self.auditor)
        payment = Payment.objects.get()
        Payment.objects.filter(pk=payment.pk).update(received_at=payment.received_at + timedelta(days=1))
        response = self.client.get(reverse("reports"), {"report": "ageing", "end": timezone.localdate().isoformat()})
        self.assertEqual(response.context["rows"][0][-2:], (0, 7875))

    def test_role_limits_apply_to_the_dashboard_and_downloads(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("owner_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["receivables"], Decimal("3875"))
        self.assertEqual(response.context["order_count"], 2)
        self.assertEqual(self.client.get(reverse("reports"), {"format": "xlsx"}).status_code, 403)

        for user in (self.auditor, self.salesman):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("owner_dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("reports"), {"format": "csv"}).status_code, 403)
