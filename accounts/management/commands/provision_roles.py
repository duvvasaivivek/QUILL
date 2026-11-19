from django.core.management.base import BaseCommand

from accounts.roles import provision_role_groups


class Command(BaseCommand):
    help = "Create the QUILL role groups and assign available permissions."

    def handle(self, *args, **options):
        results = provision_role_groups()
        new_groups = [name for name, created in results.items() if created]
        if new_groups:
            self.stdout.write(self.style.SUCCESS(f"Created role groups: {', '.join(new_groups)}"))
        else:
            self.stdout.write("All role groups already exist.")
