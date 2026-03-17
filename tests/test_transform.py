from __future__ import annotations

import copy
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
        "warnings": ["Showing sample data. This dashboard is not using live Orbit data."],
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
        self.assertEqual(
            result["summary"]["robotStatus"]["detail"],
            "Currently running: Steam Loop Thermal Sweep",
        )
        self.assertEqual(result["anomalies"]["newInRange"], 3)

    def test_robot_status_recently_active_detail_is_plain_english(self) -> None:
        snapshot = _load_snapshot()
        snapshot["runs"]["resources"] = []
        snapshot["runCaptures"]["resources"] = []

        payload = build_dashboard_payload(snapshot, _config(), "7d")
        result = payload.to_dict()

        self.assertEqual(result["summary"]["robotStatus"]["label"], "Recently Active")
        self.assertEqual(
            result["summary"]["robotStatus"]["detail"],
            "Orbit recorded activity in the last 24 hours.",
        )

    def test_robot_status_idle_detail_is_plain_english(self) -> None:
        snapshot = _load_snapshot()
        snapshot["runs"]["resources"] = []
        snapshot["runCaptures"]["resources"] = []
        stale_event = copy.deepcopy(snapshot["runEvents"]["resources"][-1])
        stale_event["time"] = "2026-03-01T10:00:00Z"
        stale_event["createdAt"] = "2026-03-01T10:00:00Z"
        snapshot["runEvents"]["resources"] = [stale_event]

        payload = build_dashboard_payload(snapshot, _config(), "30d")
        result = payload.to_dict()

        self.assertEqual(result["summary"]["robotStatus"]["label"], "Idle")
        self.assertEqual(
            result["summary"]["robotStatus"]["detail"],
            "Orbit has older activity on record, but none in the last 24 hours.",
        )

    def test_robot_status_unknown_detail_when_no_activity_exists(self) -> None:
        snapshot = _load_snapshot()
        snapshot["runs"]["resources"] = []
        snapshot["runEvents"]["resources"] = []
        snapshot["runCaptures"]["resources"] = []

        payload = build_dashboard_payload(snapshot, _config(), "7d")
        result = payload.to_dict()

        self.assertEqual(result["summary"]["robotStatus"]["label"], "Unknown")
        self.assertEqual(
            result["summary"]["robotStatus"]["detail"],
            "Orbit has not recorded any runs, run activity, or captures yet.",
        )

    def test_backend_fallback_copy_is_polished(self) -> None:
        snapshot = _load_snapshot()
        snapshot["runs"]["resources"] = [copy.deepcopy(snapshot["runs"]["resources"][0])]
        snapshot["runs"]["resources"][0]["missionName"] = None
        snapshot["anomalies"]["resources"] = [copy.deepcopy(snapshot["anomalies"]["resources"][0])]
        snapshot["anomalies"]["resources"][0]["title"] = None
        snapshot["anomalies"]["resources"][0]["name"] = None

        payload = build_dashboard_payload(snapshot, _config(), "7d")
        result = payload.to_dict()

        self.assertEqual(result["recentRuns"][0]["missionName"], "Unnamed mission")
        self.assertEqual(result["anomalies"]["recent"][0]["title"], "Untitled issue")

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
