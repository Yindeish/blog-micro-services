import unittest
from starlette.testclient import TestClient
from services.gateway.main import app


class GatewayTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_gateway_root(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["service"], "api-gateway")
        self.assertEqual(data["status"], "online")
        self.assertIn("services", data)
        self.assertIn("user", data["services"])
        self.assertIn("blog", data["services"])
        self.assertIn("comment", data["services"])
        self.assertIn("payment", data["services"])


if __name__ == "__main__":
    unittest.main()
