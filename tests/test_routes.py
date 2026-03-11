from __future__ import annotations

import os
import unittest
from pathlib import Path

from app import create_app


class RoutesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = os.environ.copy()
        repo_root = Path(__file__).resolve().parents[1]
        os.environ["ORBIT_USE_FIXTURES"] = "true"
        os.environ["ORBIT_FIXTURE_DIR"] = str(repo_root / "fixtures/orbit")
        os.environ["TIMEZONE"] = "America/Indiana/Indianapolis"
        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_index_renders(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Spot Orbit Activity Dashboard", response.data)

    def test_dashboard_payload_uses_requested_range(self) -> None:
        response = self.client.get("/api/dashboard?range=7d")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["range"], "7d")
        self.assertEqual(payload["summary"]["robotStatus"]["label"], "Active")

    def test_invalid_range_is_rejected(self) -> None:
        response = self.client.get("/api/dashboard?range=90d")
        self.assertEqual(response.status_code, 400)

    def test_healthz_returns_hosting_data(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["fixtureMode"])
        self.assertEqual(payload["status"], "ok")


if __name__ == "__main__":
    unittest.main()
