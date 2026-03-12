from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.config import DashboardConfig
from app.orbit_client import DashboardService, LiveOrbitSource


class _FakeResponse:
    def __init__(self, payload: dict | None = None, *, ok: bool = True, text: str = "") -> None:
        self._payload = payload or {}
        self.ok = ok
        self.text = text

    def json(self) -> dict:
        return self._payload


class _FakeOrbitClient:
    system_time_ms = int(datetime(2026, 3, 12, 12, tzinfo=timezone.utc).timestamp() * 1000)
    runs: list[dict] = []
    run_events: list[dict] = []
    run_captures: list[dict] = []
    anomalies: list[dict] = []
    open_anomalies: list[dict] = []
    instances: list["_FakeOrbitClient"] = []

    def __init__(self, hostname: str, verify: bool | str, cert: str | None) -> None:
        self.hostname = hostname
        self.verify = verify
        self.cert = cert
        self.calls: list[dict[str, int | str | None]] = []
        type(self).instances.append(self)

    @classmethod
    def reset(
        cls,
        *,
        runs: list[dict],
        run_events: list[dict],
        run_captures: list[dict],
        anomalies: list[dict],
        open_anomalies: list[dict],
    ) -> None:
        cls.runs = runs
        cls.run_events = run_events
        cls.run_captures = run_captures
        cls.anomalies = anomalies
        cls.open_anomalies = open_anomalies
        cls.instances = []

    def authenticate_with_api_token(self, token: str) -> _FakeResponse:
        return _FakeResponse(ok=bool(token), text="ok")

    def get_system_time(self) -> _FakeResponse:
        return _FakeResponse({"msSinceEpoch": self.system_time_ms})

    def _paged(self, name: str, resources: list[dict], params: dict) -> _FakeResponse:
        limit = int(params["limit"])
        offset = int(params.get("offset", 0))
        self.calls.append(
            {"name": name, "offset": offset, "limit": limit, "status": params.get("status")}
        )
        return _FakeResponse(
            {
                "resources": resources[offset:offset + limit],
                "limit": limit,
                "offset": offset,
                "total": len(resources),
            }
        )

    def get_runs(self, params: dict) -> _FakeResponse:
        return self._paged("runs", type(self).runs, params)

    def get_run_events(self, params: dict) -> _FakeResponse:
        return self._paged("run_events", type(self).run_events, params)

    def get_run_captures(self, params: dict) -> _FakeResponse:
        return self._paged("run_captures", type(self).run_captures, params)

    def get_anomalies(self, params: dict) -> _FakeResponse:
        resources = type(self).open_anomalies if params.get("status") == "open" else type(self).anomalies
        name = "open_anomalies" if params.get("status") == "open" else "anomalies"
        return self._paged(name, resources, params)


def _iso(days_ago: int, *, minutes_offset: int = 0) -> str:
    base = datetime(2026, 3, 12, 12, tzinfo=timezone.utc)
    stamp = base - timedelta(days=days_ago, minutes=minutes_offset)
    return stamp.isoformat().replace("+00:00", "Z")


def _config() -> DashboardConfig:
    return DashboardConfig(
        orbit_host="orbit.local",
        orbit_api_token="token",
        orbit_verify_tls=True,
        orbit_cert_path=None,
        timezone="UTC",
        dashboard_refresh_seconds=60,
        dashboard_cache_ttl_seconds=30,
        dashboard_bind_host="127.0.0.1",
        dashboard_port=8080,
        fixture_mode=False,
        fixture_dir=Path("fixtures/orbit"),
        default_range="7d",
        orbit_item_limit=2,
    )


class OrbitClientTestCase(unittest.TestCase):
    @patch("app.orbit_client._import_bosdyn_client", return_value=_FakeOrbitClient)
    def test_dashboard_service_fetches_all_pages(self, _mock_client_factory) -> None:
        _FakeOrbitClient.reset(
            runs=[
                {
                    "uuid": f"run-{index}",
                    "missionName": f"Mission {index}",
                    "missionStatus": "SUCCESS",
                    "startTime": _iso(index, minutes_offset=index + 1),
                }
                for index in range(5)
            ],
            run_events=[
                {
                    "uuid": f"event-{index}",
                    "missionName": "Mission",
                    "actionName": f"Action {index}",
                    "eventType": "ACTION",
                    "createdAt": _iso(index, minutes_offset=index + 1),
                }
                for index in range(5)
            ],
            run_captures=[
                {"uuid": f"capture-{index}", "createdAt": _iso(index, minutes_offset=index + 1)}
                for index in range(6)
            ],
            anomalies=[
                {
                    "uuid": f"anomaly-{index}",
                    "title": f"Anomaly {index}",
                    "status": "open" if index < 2 else "closed",
                    "createdAt": _iso(index, minutes_offset=index + 1),
                    "time": _iso(index, minutes_offset=index + 1),
                    "statusModifiedAt": _iso(index, minutes_offset=index + 1),
                }
                for index in range(4)
            ],
            open_anomalies=[
                {
                    "uuid": f"open-{index}",
                    "title": f"Open {index}",
                    "status": "open",
                    "createdAt": _iso(index, minutes_offset=index + 1),
                    "time": _iso(index, minutes_offset=index + 1),
                }
                for index in range(3)
            ],
        )

        payload = DashboardService(_config()).get_dashboard("7d")
        client = _FakeOrbitClient.instances[-1]

        self.assertEqual(payload["summary"]["runs"], 5)
        self.assertEqual(payload["summary"]["successfulRuns"], 5)
        self.assertEqual(payload["summary"]["dataCaptures"], 6)
        self.assertEqual(payload["summary"]["openAnomalies"], 3)
        self.assertEqual(sum(item["count"] for item in payload["trends"]["eventsByBucket"]), 5)
        self.assertEqual(sum(item["count"] for item in payload["trends"]["capturesByBucket"]), 6)
        self.assertFalse(payload["warnings"])
        self.assertEqual(
            [call["offset"] for call in client.calls if call["name"] == "run_events"],
            [0, 2, 4],
        )
        self.assertEqual(
            [call["offset"] for call in client.calls if call["name"] == "run_captures"],
            [0, 2, 4],
        )

    def test_fetch_paginated_warns_when_total_exceeds_loaded_resources(self) -> None:
        source = LiveOrbitSource(_config())
        warnings: list[str] = []
        pages = {
            0: {"resources": [{"uuid": "event-1"}, {"uuid": "event-2"}], "limit": 2, "offset": 0, "total": 5},
            2: {"resources": [], "limit": 2, "offset": 2, "total": 5},
        }

        def fetch_page(*, params: dict) -> _FakeResponse:
            return _FakeResponse(pages[params["offset"]])

        payload = source._fetch_paginated(fetch_page, {}, "run events", warnings)

        self.assertEqual(len(payload["resources"]), 2)
        self.assertEqual(warnings, ["run events results incomplete: loaded 2 of 5."])


if __name__ == "__main__":
    unittest.main()
