from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventory.models import OpeningBalance, OpeningBalanceLine, PurchaseReceipt, PurchaseReceiptLine, StockMovement
from inventory.services import post_document
from masters.models import BOM, Customer, Item, Supplier
from production.services import create_production_run, post_production_run
from sales.models import Payment, SalesOrder
from sales.services import approve_order, dispatch_invoice, record_payment, submit_order


OPENING = {
    "RM-FLOUR": ("100", "42"),
    "RM-OIL": ("30", "140"),
    "RM-SPICE": ("5", "200"),
    "PK-POUCH-200G": ("500", "2.50"),
    "PK-CARTON-20": ("30", "15"),
    "FG-MURUKKU-200G": ("50", "0"),
}
PAYMENT_REFERENCE = "BENCHMARK-REPORT-PAYMENT"


class Command(BaseCommand):
    help = "Post the Murukku reporting benchmark in an empty demo ledger."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Existing demo user who records the transactions.")
        parser.add_argument("--opening-only", action="store_true", help="Stop after posting opening stock.")
        parser.add_argument("--salesmen", nargs=2, metavar="USERNAME", help="Existing users for the two orders.")
        parser.add_argument("--supervisor", help="Existing user who posts the purchase and production run.")

    def handle(self, *args, **options):
        usernames = (options["username"], *(options["salesmen"] or [options["username"]] * 2),
                     options["supervisor"] or options["username"])
        users = get_user_model().objects.filter(username__in=usernames, is_active=True).in_bulk(field_name="username")
        if set(users) != set(usernames):
            raise CommandError("Use the usernames of existing, active demo users.")
        try:
            self.seed(*(users[name] for name in usernames), opening_only=options["opening_only"])
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from error

    @transaction.atomic
    def seed(self, user, salesman_a, salesman_b, supervisor, *, opening_only):
        if Payment.objects.filter(reference=PAYMENT_REFERENCE).exists():
            self.stdout.write("Reporting benchmark is already posted.")
            return
        if opening_only and OpeningBalance.objects.filter(reference="BENCHMARK-REPORT-OPENING", status="POSTED").exists():
            self.stdout.write("Benchmark opening stock is already posted.")
            return
        if StockMovement.objects.exists() or SalesOrder.objects.exists():
            raise CommandError("Use a demo database with an empty stock ledger and no sales orders.")
        call_command("seed_benchmark_masters", stdout=self.stdout)
        items = Item.objects.in_bulk(OPENING, field_name="sku")
        opening = OpeningBalance.objects.create(reference="BENCHMARK-REPORT-OPENING")
        for sku, (qty, cost) in OPENING.items():
            OpeningBalanceLine.objects.create(document=opening, item=items[sku],
                                              quantity=Decimal(qty), unit_cost=Decimal(cost))
        post_document(opening, user)
        if opening_only:
            self.stdout.write(self.style.SUCCESS("Benchmark master data and opening stock are ready."))
            return
        purchase = PurchaseReceipt.objects.create(reference="BENCHMARK-REPORT-PURCHASE",
                                                   supplier=Supplier.objects.get(code="SUPPLIER-RAW"))
        PurchaseReceiptLine.objects.create(document=purchase, item=items["RM-FLOUR"], quantity=60, unit_cost=45)
        post_document(purchase, supervisor)

        bom = BOM.objects.get(product__item=items["FG-MURUKKU-200G"], version=1)
        run = create_production_run(reference="BENCHMARK-REPORT-RUN", bom=bom, planned_output=200,
                                    user=supervisor, allocated_overhead=Decimal("1800"))
        actuals = {"RM-OIL": Decimal("10.5"), "PK-POUCH-200G": Decimal("194"), "PK-CARTON-20": Decimal("9")}
        for line in run.consumptions.select_related("item"):
            if line.item.sku in actuals:
                line.actual_quantity = actuals[line.item.sku]
                if line.item.sku == "PK-POUCH-200G":
                    line.damaged_quantity = Decimal("6")
                line.save(update_fields=("actual_quantity", "damaged_quantity"))
        run.good_output = Decimal("188")
        run.wastage = Decimal("12")
        run.save(update_fields=("good_output", "wastage"))
        post_production_run(run, supervisor)

        def order_for(customer_code, quantity, salesman):
            return submit_order(Customer.objects.get(code=customer_code), salesman, [(bom.product, Decimal(quantity))])

        invoice = approve_order(order_for("RETAILER-A", 150, salesman_a), user)
        dispatch_invoice(invoice, user)
        order_for("DISTRIBUTOR-B", 120, salesman_b)
        record_payment(invoice, user, Decimal("4000"), PAYMENT_REFERENCE)
        self.stdout.write(self.style.SUCCESS(f"Reporting benchmark posted. Retailer invoice: {invoice.number}."))
