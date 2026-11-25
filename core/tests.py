from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.roles import Role, provision_role_groups


class HealthEndpointTests(SimpleTestCase):
    def setUp(self) -> None:
        self.client = Client()

    def test_health_endpoint_returns_ok(self) -> None:
        response = self.client.get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "quill"})

    @override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
    def test_pwa_manifest_and_service_worker_are_available_from_the_root(self):
        manifest = self.client.get("/manifest.webmanifest")
        self.assertEqual(manifest["Content-Type"], "application/manifest+json")
        self.assertEqual(manifest.json()["display"], "standalone")
        self.assertEqual({icon["sizes"] for icon in manifest.json()["icons"]}, {"192x192", "512x512"})
        worker = self.client.get("/service-worker.js")
        self.assertEqual(worker["Content-Type"], "application/javascript")
        self.assertIn("no-store", worker["Cache-Control"])
        self.assertContains(worker, "/static/offline.html")


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class WorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        provision_role_groups()
        cls.accounts = {}
        for role in Role:
            user = get_user_model().objects.create_user(
                username=role.name.lower(), is_staff=role in {Role.ADMIN, Role.PRODUCTION_SUPERVISOR, Role.AUDITOR},
            )
            user.groups.add(Group.objects.get(name=role.value))
            cls.accounts[role] = user

    def test_home_works_for_all_five_roles(self):
        for role, heading in (
            (Role.ADMIN, "Operations"), (Role.SALESMAN, "Sales workspace"),
            (Role.PRODUCTION_SUPERVISOR, "Production"), (Role.AUDITOR, "Audit workspace"),
            (Role.OWNER, "Owner dashboard"),
        ):
            with self.subTest(role=role):
                self.client.force_login(self.accounts[role])
                response = self.client.get(reverse("home"), follow=True)
                self.assertContains(response, f"<h1>{heading}</h1>", html=True)
                self.assertContains(response, 'aria-current="page"')
                self.assertContains(response, "Skip to content")

    def test_restricted_navigation_has_matching_server_permissions(self):
        self.client.force_login(self.accounts[Role.SALESMAN])
        home = self.client.get(reverse("home"))
        self.assertNotContains(home, reverse("reports"))
        self.assertNotContains(home, reverse("admin:production_productionrun_changelist"))
        for route in ("reports", "owner_dashboard", "stock_summary"):
            self.assertContains(self.client.get(reverse(route)), "Access denied", status_code=403)
        self.assertEqual(self.client.post(reverse("reports")).status_code, 405)
        self.assertEqual(self.client.post(reverse("admin:production_productionrun_changelist")).status_code, 302)

    def test_protected_navigation_and_sign_out(self):
        self.assertRedirects(self.client.get(reverse("home")), "/login/?next=/", fetch_redirect_response=False)
        self.client.force_login(self.accounts[Role.ADMIN])
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        response = self.client.post(reverse("logout"), follow=True)
        self.assertContains(response, "You signed out.")
        self.assertContains(response, "<h1>Sign in</h1>", html=True)

    def test_session_cannot_be_signed_out_without_a_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.accounts[Role.ADMIN])
        response = client.post(reverse("logout"))
        self.assertContains(response, "Form could not be submitted", status_code=403)
        self.assertContains(client.get(reverse("home")), "Operations")

    @override_settings(DEBUG=False)
    def test_missing_page_uses_the_workspace_error_screen(self):
        response = self.client.get("/missing-workspace-page/")
        self.assertContains(response, "Page not found", status_code=404)
