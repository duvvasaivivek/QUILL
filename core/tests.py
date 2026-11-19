from django.test import Client, SimpleTestCase


class HealthEndpointTests(SimpleTestCase):
    def setUp(self) -> None:
        self.client = Client()

    def test_health_endpoint_returns_ok(self) -> None:
        response = self.client.get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "quill"})
