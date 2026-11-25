from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.roles import Role, provision_role_groups
from core.models import AuditEvent
from inventory.models import StockMovement, stock_balance
from masters.models import BOM, Item, Unit
from production.models import ProductionRun
from production.services import post_production_run, reverse_production_run


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class ProductionAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        provision_role_groups()
        users = get_user_model().objects
        cls.supervisor = users.create_user(username="floor", is_staff=True)
        cls.supervisor.groups.add(Group.objects.get(name=Role.PRODUCTION_SUPERVISOR.value))
        cls.admin_user = users.create_user(username="factory", is_staff=True)
        cls.admin_user.groups.add(Group.objects.get(name=Role.ADMIN.value))
        cls.auditor = users.create_user(username="auditor", is_staff=True)
        cls.auditor.groups.add(Group.objects.get(name=Role.AUDITOR.value))
        call_command("seed_benchmark_reports", username="factory", opening_only=True)
        cls.bom = BOM.objects.get()
        flour_line = cls.bom.lines.get(item__sku="RM-FLOUR")
        flour_line.quantity = Decimal("40000")
        flour_line.unit = Unit.objects.get(code="g")
        flour_line.save()

    def test_supervisor_creates_and_edits_bom_snapshot_in_admin(self):
        self.client.force_login(self.supervisor)
        response = self.client.post(reverse("admin:production_productionrun_add"), {
            "reference": "FLOOR-1", "bom": self.bom.pk, "planned_output": "100",
            "good_output": "94", "wastage": "6", "allocated_overhead": "200",
            "variance_tolerance_percent": "3", "_save": "Save",
            "consumptions-TOTAL_FORMS": 0, "consumptions-INITIAL_FORMS": 0,
        })
        self.assertEqual(response.status_code, 302, response.context["errors"] if response.context else "")
        run = ProductionRun.objects.get(reference="FLOOR-1")
        self.assertEqual(run.consumptions.get(item__sku="RM-FLOUR").expected_quantity, 20)
        self.assertEqual(run.consumptions.count(), 5)
        self.assertFalse(self.supervisor.has_perm("production.add_productionreversal"))

        lines = list(run.consumptions.all())
        payload = {
            "good_output": "93", "wastage": "7", "allocated_overhead": "200",
            "variance_tolerance_percent": "3", "_save": "Save",
            "consumptions-TOTAL_FORMS": len(lines), "consumptions-INITIAL_FORMS": len(lines),
        }
        for number, line in enumerate(lines):
            payload[f"consumptions-{number}-id"] = line.pk
            payload[f"consumptions-{number}-actual_quantity"] = "5.5" if line.item.sku == "RM-OIL" else str(line.actual_quantity)
        response = self.client.post(reverse("admin:production_productionrun_change", args=(run.pk,)), payload)
        self.assertEqual(response.status_code, 302, response.context["errors"] if response.context else "")
        self.assertEqual(AuditEvent.objects.get(action="draft_edited").details["changes"]["good_output"]["to"], "93")
        self.assertEqual(AuditEvent.objects.get(action="consumption_edited").details["actual"], "5.5")

        posted = post_production_run(run, self.supervisor)
        self.assertEqual(posted.yield_variance_percent, -7)
        self.assertEqual(posted.consumptions.get(item__sku="RM-OIL").variance_percent, 10)
        self.assertTrue(posted.has_variance_alert)

        self.client.force_login(self.auditor)
        self.assertEqual(self.client.get(reverse("admin:core_auditevent_changelist")).status_code, 200)
        self.assertEqual(self.client.post(reverse("admin:production_productionrun_add")).status_code, 403)

        flour = Item.objects.get(sku="RM-FLOUR")
        self.assertEqual(stock_balance(flour)[0], 80)
        reversal = reverse_production_run(posted, self.admin_user, "Batch recorded under wrong date")
        self.assertEqual(stock_balance(flour)[0], 100)
        reversed_entries = StockMovement.objects.filter(source_reference=reversal.reference).select_related("reverses")
        self.assertEqual(reversed_entries.count(), 6)
        for entry in reversed_entries:
            self.assertEqual(entry.quantity, -entry.reverses.quantity)
            self.assertEqual(entry.value, -entry.reverses.value)
        with self.assertRaises(ValidationError):
            reverse_production_run(posted, self.admin_user, "Duplicate")
