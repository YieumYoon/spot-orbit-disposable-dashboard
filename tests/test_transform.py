from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError

from app.config import DashboardConfig
from app.transform import _bucket_label
from app.transform import build_dashboard_payload


def _load_snapshot() -> dict:
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures/orbit"
    anomalies = json.loads((fixture_dir / "anomalies.json").read_text(encoding="utf-8"))
    return {
        "systemTime": json.loads((fixture_dir / "system_time.json").read_text(encoding="utf-8")),
        "runs": json.loads((fixture_dir / "runs.json").read_text(encoding="utf-8")),
        "runEvents": json.loads((fixture_dir / "run_events.json").read_text(encoding="utf-8")),
        "runCaptures": json.loads((fixture_dir / "run_captures.json").read_text(encoding="utf-8")),
        "anomalies": anomalies,
        "openAnomalies": {
            "resources": [item for item in anomalies["resources"] if item["status"] == "open"]
        },
        "warnings": ["Fixture mode is enabled."],
    }


def _config() -> DashboardConfig:
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures/orbit"
    return DashboardConfig(
        orbit_host=None,
        orbit_api_token=None,
        orbit_verify_tls=True,
        orbit_cert_path=None,
        timezone="America/Indiana/Indianapolis",
        dashboard_refresh_seconds=60,
        dashboard_cache_ttl_seconds=30,
        dashboard_bind_host="0.0.0.0",
        dashboard_port=8080,
        fixture_mode=True,
        fixture_dir=fixture_dir,
        default_range="7d",
        orbit_item_limit=500,
    )


class TransformTestCase(unittest.TestCase):
    def test_build_payload_for_7d_range(self) -> None:
        payload = build_dashboard_payload(_load_snapshot(), _config(), "7d")
        result = payload.to_dict()
        self.assertEqual(result["summary"]["runs"], 4)
        self.assertEqual(result["summary"]["successfulRuns"], 2)
        self.assertEqual(result["summary"]["openAnomalies"], 2)
        self.assertEqual(result["summary"]["robotStatus"]["label"], "Active")
        self.assertEqual(result["anomalies"]["newInRange"], 3)

    def test_build_payload_for_24h_range(self) -> None:
        payload = build_dashboard_payload(_load_snapshot(), _config(), "24h")
        result = payload.to_dict()
        self.assertEqual(result["range"], "24h")
        self.assertEqual(len(result["trends"]["runsByBucket"]), 24)
        self.assertEqual(result["summary"]["runs"], 2)

    def test_unknown_range_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_dashboard_payload(_load_snapshot(), _config(), "90d")

    def test_bucket_label_falls_back_to_builtin_utc_when_zoneinfo_is_unavailable(self) -> None:
        with patch("app.transform.ZoneInfo", side_effect=ZoneInfoNotFoundError("missing")):
            label = _bucket_label(datetime(2024, 2, 14, 15, tzinfo=timezone.utc), "UTC", "24h")
            self.assertEqual(label, "3 PM")


if __name__ == "__main__":
    unittest.main()
