import os
from getpass import getpass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, CommandError, call_command
from django.db import transaction

from accounts.roles import Role


ACCOUNTS = (
    ("demo_admin", Role.ADMIN, True),
    ("demo_sales_a", Role.SALESMAN, False),
    ("demo_sales_b", Role.SALESMAN, False),
    ("demo_production", Role.PRODUCTION_SUPERVISOR, True),
    ("demo_auditor", Role.AUDITOR, True),
    ("demo_owner", Role.OWNER, False),
)


class Command(BaseCommand):
    help = "Create six role-based logins and populate a local demo database."

    def add_arguments(self, parser):
        parser.add_argument("--opening-only", action="store_true", help="Prepare a hands-on benchmark from opening stock.")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo accounts can only be created with DJANGO_DEBUG=true.")
        password = os.environ.get("QUILL_DEMO_PASSWORD") or getpass("Password for the new local demo accounts: ")
        if len(password) < 12:
            raise CommandError("Use a demo password of at least 12 characters.")
        self.setup(password, opening_only=options["opening_only"])

    @transaction.atomic
    def setup(self, password, *, opening_only):
        call_command("provision_roles", stdout=self.stdout)
        model = get_user_model()
        for name, role, staff in ACCOUNTS:
            group = Group.objects.get(name=role.value)
            user = model.objects.filter(username=name).first()
            if user is not None:
                if user.is_superuser or user.is_staff != staff or not user.is_active or set(user.groups.all()) != {group}:
                    raise CommandError(f"Account {name} conflicts with the demo account setup.")
                continue
            user = model(username=name, is_staff=staff)
            try:
                validate_password(password, user)
            except ValidationError as error:
                raise CommandError("; ".join(error.messages)) from error
            user.set_password(password)
            user.save()
            user.groups.add(group)

        call_command("seed_benchmark_reports", username="demo_admin", salesmen=["demo_sales_a", "demo_sales_b"],
                     supervisor="demo_production", opening_only=opening_only, stdout=self.stdout)
        self.stdout.write("Demo logins: " + ", ".join(name for name, _, _ in ACCOUNTS))
