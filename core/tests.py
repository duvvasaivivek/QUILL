from django.test import Client, SimpleTestCase, override_settings


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
