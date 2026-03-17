from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.config import DashboardConfig
from app.orbit_client import DashboardService, LiveOrbitSource, _RANGED_ORBIT_ENDPOINTS


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

    def _filtered_resources(
        self,
        resources: list[dict],
        params: dict,
        *,
        start_param: str | None = None,
        end_param: str | None = None,
        time_fields: tuple[str, ...] = (),
    ) -> list[dict]:
        if not start_param and not end_param:
            return resources

        start_at = _parse_iso(params[start_param]) if start_param and params.get(start_param) else None
        end_at = _parse_iso(params[end_param]) if end_param and params.get(end_param) else None
        filtered: list[dict] = []

        for resource in resources:
            resource_time = None
            for field_name in time_fields:
                resource_time = _parse_iso(resource.get(field_name)) if resource.get(field_name) else None
                if resource_time is not None:
                    break

            if resource_time is None:
                continue
            if start_at is not None and resource_time < start_at:
                continue
            if end_at is not None and resource_time >= end_at:
                continue
            filtered.append(resource)

        return filtered

    def _paged(
        self,
        name: str,
        resources: list[dict],
        params: dict,
        *,
        start_param: str | None = None,
        end_param: str | None = None,
        time_fields: tuple[str, ...] = (),
    ) -> _FakeResponse:
        filtered_resources = self._filtered_resources(
            resources,
            params,
            start_param=start_param,
            end_param=end_param,
            time_fields=time_fields,
        )
        limit = int(params["limit"])
        offset = int(params.get("offset", 0))
        self.calls.append(
            {
                "name": name,
                "offset": offset,
                "limit": limit,
                "status": params.get("status"),
                "start": params.get(start_param) if start_param else None,
                "end": params.get(end_param) if end_param else None,
            }
        )
        return _FakeResponse(
            {
                "resources": filtered_resources[offset:offset + limit],
                "limit": limit,
                "offset": offset,
                "total": len(filtered_resources),
            }
        )

    def get_runs(self, params: dict) -> _FakeResponse:
        return self._paged(
            "runs",
            type(self).runs,
            params,
            start_param="startTime",
            end_param="endTime",
            time_fields=("startTime",),
        )

    def get_run_events(self, params: dict) -> _FakeResponse:
        return self._paged(
            "run_events",
            type(self).run_events,
            params,
            start_param="startTime",
            end_param="endTime",
            time_fields=("createdAt",),
        )

    def get_run_captures(self, params: dict) -> _FakeResponse:
        return self._paged(
            "run_captures",
            type(self).run_captures,
            params,
            start_param="startCreatedAt",
            end_param="endCreatedAt",
            time_fields=("createdAt",),
        )

    def get_anomalies(self, params: dict) -> _FakeResponse:
        resources = type(self).open_anomalies if params.get("status") == "open" else type(self).anomalies
        name = "open_anomalies" if params.get("status") == "open" else "anomalies"
        return self._paged(
            name,
            resources,
            params,
            start_param=None if params.get("status") == "open" else "startTime",
            end_param=None if params.get("status") == "open" else "endTime",
            time_fields=("time", "createdAt"),
        )

def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _run(uuid: str, stamp: datetime) -> dict:
    return {
        "uuid": uuid,
        "missionName": f"Mission {uuid}",
        "missionStatus": "SUCCESS",
        "startTime": stamp.isoformat().replace("+00:00", "Z"),
    }


def _event(uuid: str, stamp: datetime) -> dict:
    return {
        "uuid": uuid,
        "missionName": "Mission",
        "actionName": f"Action {uuid}",
        "eventType": "ACTION",
        "createdAt": stamp.isoformat().replace("+00:00", "Z"),
    }


def _capture(uuid: str, stamp: datetime) -> dict:
    return {
        "uuid": uuid,
        "createdAt": stamp.isoformat().replace("+00:00", "Z"),
    }


def _anomaly(uuid: str, stamp: datetime, *, status: str = "open") -> dict:
    return {
        "uuid": uuid,
        "title": f"Anomaly {uuid}",
        "status": status,
        "createdAt": stamp.isoformat().replace("+00:00", "Z"),
        "time": stamp.isoformat().replace("+00:00", "Z"),
        "statusModifiedAt": stamp.isoformat().replace("+00:00", "Z"),
    }


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
    def test_dashboard_service_uses_time_slices_for_ranged_resources(self, _mock_client_factory) -> None:
        base = datetime(2026, 3, 12, 11, tzinfo=timezone.utc)
        _FakeOrbitClient.reset(
            runs=[_run(f"run-{index}", base - timedelta(days=index)) for index in range(5)],
            run_events=[_event(f"event-{index}", base - timedelta(days=index)) for index in range(5)],
            run_captures=[_capture(f"capture-{index}", base - timedelta(days=index)) for index in range(5)],
            anomalies=[
                _anomaly(f"anomaly-{index}", base - timedelta(days=index), status="open" if index < 2 else "closed")
                for index in range(4)
            ],
            open_anomalies=[
                _anomaly(f"open-{index}", base - timedelta(days=index), status="open")
                for index in range(3)
            ],
        )

        payload = DashboardService(_config()).get_dashboard("7d")
        client = _FakeOrbitClient.instances[-1]

        self.assertEqual(payload["summary"]["runs"], 5)
        self.assertEqual(payload["summary"]["successfulRuns"], 5)
        self.assertEqual(payload["summary"]["dataCaptures"], 5)
        self.assertEqual(payload["summary"]["openAnomalies"], 3)
        self.assertEqual(sum(item["count"] for item in payload["trends"]["eventsByBucket"]), 5)
        self.assertEqual(sum(item["count"] for item in payload["trends"]["capturesByBucket"]), 5)
        self.assertFalse(payload["warnings"])
        self.assertTrue(len([call for call in client.calls if call["name"] == "runs"]) > 3)
        self.assertTrue(all(call["offset"] == 0 for call in client.calls if call["name"] == "runs"))
        self.assertEqual(
            sorted(set(call["offset"] for call in client.calls if call["name"] == "run_events")),
            [0],
        )
        self.assertTrue(len([call for call in client.calls if call["name"] == "run_events"]) > 3)
        self.assertTrue(all(call["offset"] == 0 for call in client.calls if call["name"] == "run_captures"))
        self.assertTrue(all(call["offset"] == 0 for call in client.calls if call["name"] == "anomalies"))
        self.assertEqual([call["offset"] for call in client.calls if call["name"] == "open_anomalies"], [0, 2])

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
        self.assertEqual(
            warnings,
            ["Run activity may be incomplete: showing 2 of 5 records from Orbit."],
        )

    def test_fetch_paginated_continues_when_total_indicates_more_results(self) -> None:
        source = LiveOrbitSource(_config())
        warnings: list[str] = []
        pages = {
            0: {
                "resources": [{"uuid": "run-1"}, {"uuid": "run-2"}],
                "limit": 5,
                "offset": 0,
                "total": 5,
            },
            2: {
                "resources": [{"uuid": "run-3"}, {"uuid": "run-4"}],
                "limit": 5,
                "offset": 2,
                "total": 5,
            },
            4: {
                "resources": [{"uuid": "run-5"}],
                "limit": 5,
                "offset": 4,
                "total": 5,
            },
        }

        def fetch_page(*, params: dict) -> _FakeResponse:
            return _FakeResponse(pages[params["offset"]])

        payload = source._fetch_paginated(fetch_page, {}, "runs", warnings)

        self.assertEqual(
            [resource["uuid"] for resource in payload["resources"]],
            ["run-1", "run-2", "run-3", "run-4", "run-5"],
        )
        self.assertFalse(warnings)

    def test_fetch_ranged_resource_retries_incomplete_slice_until_complete(self) -> None:
        source = LiveOrbitSource(_config())
        warnings: list[str] = []
        spec = _RANGED_ORBIT_ENDPOINTS["runs"]
        slice_start = datetime(2026, 3, 12, 10, tzinfo=timezone.utc)
        slice_end = datetime(2026, 3, 12, 12, tzinfo=timezone.utc)
        calls: list[tuple[str, str, int]] = []

        def fetch_page(*, params: dict) -> _FakeResponse:
            start = _parse_iso(params["startTime"])
            end = _parse_iso(params["endTime"])
            offset = params["offset"]
            calls.append((params["startTime"], params["endTime"], offset))

            if end - start > timedelta(hours=1):
                pages = {
                    0: {
                        "resources": [
                            _run("run-1", datetime(2026, 3, 12, 10, 15, tzinfo=timezone.utc)),
                            _run("run-2", datetime(2026, 3, 12, 10, 45, tzinfo=timezone.utc)),
                        ],
                        "limit": 2,
                        "offset": 0,
                        "total": 4,
                    },
                    2: {"resources": [], "limit": 2, "offset": 2, "total": 4},
                }
                return _FakeResponse(pages[offset])

            resources_by_slice = {
                "2026-03-12T10:00:00Z": [
                    _run("run-1", datetime(2026, 3, 12, 10, 15, tzinfo=timezone.utc)),
                    _run("run-2", datetime(2026, 3, 12, 10, 45, tzinfo=timezone.utc)),
                ],
                "2026-03-12T11:00:00Z": [
                    _run("run-3", datetime(2026, 3, 12, 11, 15, tzinfo=timezone.utc)),
                    _run("run-4", datetime(2026, 3, 12, 11, 45, tzinfo=timezone.utc)),
                ],
            }
            resources = resources_by_slice[params["startTime"]]
            return _FakeResponse(
                {
                    "resources": resources[offset:offset + 2],
                    "limit": 2,
                    "offset": offset,
                    "total": len(resources),
                }
            )

        payload = source._fetch_ranged_resource(fetch_page, spec, "24h", slice_start, slice_end, warnings)

        self.assertEqual(
            [resource["uuid"] for resource in payload["resources"]],
            ["run-4", "run-3", "run-2", "run-1"],
        )
        self.assertEqual(payload["total"], 4)
        self.assertFalse(warnings)
        self.assertIn(("2026-03-12T10:00:00Z", "2026-03-12T12:00:00Z", 0), calls)
        self.assertIn(("2026-03-12T10:00:00Z", "2026-03-12T11:00:00Z", 0), calls)
        self.assertIn(("2026-03-12T11:00:00Z", "2026-03-12T12:00:00Z", 0), calls)

    def test_fetch_ranged_resource_refines_day_slice_until_sub_hour_tail(self) -> None:
        source = LiveOrbitSource(_config())
        warnings: list[str] = []
        spec = _RANGED_ORBIT_ENDPOINTS["runs"]
        window_start = datetime(2026, 3, 12, 0, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc)
        calls: list[tuple[str, str, int]] = []

        def fetch_page(*, params: dict) -> _FakeResponse:
            start = _parse_iso(params["startTime"])
            end = _parse_iso(params["endTime"])
            offset = params["offset"]
            calls.append((params["startTime"], params["endTime"], offset))

            if end - start > timedelta(hours=1):
                pages = {
                    0: {
                        "resources": [
                            _run(f"{params['startTime']}-a", start + timedelta(minutes=10)),
                            _run(f"{params['startTime']}-b", start + timedelta(minutes=20)),
                        ],
                        "limit": 2,
                        "offset": 0,
                        "total": 3,
                    },
                    2: {"resources": [], "limit": 2, "offset": 2, "total": 3},
                }
                return _FakeResponse(pages[offset])

            resources = [
                _run(f"{params['startTime']}-a", start + timedelta(minutes=10)),
                _run(f"{params['startTime']}-b", start + timedelta(minutes=20)),
            ]
            return _FakeResponse(
                {
                    "resources": resources[offset:offset + 2],
                    "limit": 2,
                    "offset": offset,
                    "total": len(resources),
                }
            )

        payload = source._fetch_ranged_resource(fetch_page, spec, "7d", window_start, window_end, warnings)

        durations = sorted(
            {
                (_parse_iso(end) - _parse_iso(start)).total_seconds() / 3600
                for start, end, offset in calls
                if offset == 0
            }
        )
        self.assertFalse(warnings)
        self.assertEqual(payload["total"], len(payload["resources"]))
        self.assertIn(0.5, durations)
        self.assertIn(1.0, durations)

    def test_fetch_ranged_resource_splits_one_and_a_half_hour_slice_into_one_hour_and_remainder(self) -> None:
        source = LiveOrbitSource(_config())
        warnings: list[str] = []
        spec = _RANGED_ORBIT_ENDPOINTS["runs"]
        window_start = datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 3, 12, 11, 30, tzinfo=timezone.utc)
        calls: list[tuple[str, str, int]] = []

        def fetch_page(*, params: dict) -> _FakeResponse:
            start = _parse_iso(params["startTime"])
            end = _parse_iso(params["endTime"])
            offset = params["offset"]
            calls.append((params["startTime"], params["endTime"], offset))

            if end - start > timedelta(hours=1):
                pages = {
                    0: {
                        "resources": [
                            _run("run-1", datetime(2026, 3, 12, 10, 10, tzinfo=timezone.utc)),
                            _run("run-2", datetime(2026, 3, 12, 10, 20, tzinfo=timezone.utc)),
                        ],
                        "limit": 2,
                        "offset": 0,
                        "total": 3,
                    },
                    2: {"resources": [], "limit": 2, "offset": 2, "total": 3},
                }
                return _FakeResponse(pages[offset])

            resources_by_slice = {
                "2026-03-12T10:00:00Z": [
                    _run("run-1", datetime(2026, 3, 12, 10, 10, tzinfo=timezone.utc)),
                    _run("run-2", datetime(2026, 3, 12, 10, 40, tzinfo=timezone.utc)),
                ],
                "2026-03-12T11:00:00Z": [
                    _run("run-3", datetime(2026, 3, 12, 11, 10, tzinfo=timezone.utc)),
                    _run("run-4", datetime(2026, 3, 12, 11, 20, tzinfo=timezone.utc)),
                ],
            }
            resources = resources_by_slice[params["startTime"]]
            return _FakeResponse(
                {
                    "resources": resources[offset:offset + 2],
                    "limit": 2,
                    "offset": offset,
                    "total": len(resources),
                }
            )

        payload = source._fetch_ranged_resource(fetch_page, spec, "24h", window_start, window_end, warnings)

        self.assertEqual(
            [resource["uuid"] for resource in payload["resources"]],
            ["run-4", "run-3", "run-2", "run-1"],
        )
        self.assertEqual(payload["total"], 4)
        self.assertFalse(warnings)
        self.assertIn(("2026-03-12T10:00:00Z", "2026-03-12T11:00:00Z", 0), calls)
        self.assertIn(("2026-03-12T11:00:00Z", "2026-03-12T11:30:00Z", 0), calls)

    def test_fetch_ranged_resource_refines_one_hour_slice_down_to_hard_floor(self) -> None:
        source = LiveOrbitSource(_config())
        warnings: list[str] = []
        spec = _RANGED_ORBIT_ENDPOINTS["runs"]
        window_start = datetime(2026, 3, 12, 11, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc)
        calls: list[tuple[str, str, int]] = []

        def fetch_page(*, params: dict) -> _FakeResponse:
            start = _parse_iso(params["startTime"])
            end = _parse_iso(params["endTime"])
            offset = params["offset"]
            calls.append((params["startTime"], params["endTime"], offset))

            if end - start > timedelta(minutes=15):
                pages = {
                    0: {
                        "resources": [
                            _run(f"{params['startTime']}-a", start + timedelta(minutes=1)),
                            _run(f"{params['startTime']}-b", start + timedelta(minutes=2)),
                        ],
                        "limit": 2,
                        "offset": 0,
                        "total": 3,
                    },
                    2: {"resources": [], "limit": 2, "offset": 2, "total": 3},
                }
                return _FakeResponse(pages[offset])

            resources = [
                _run(f"{params['startTime']}-a", start + timedelta(minutes=1)),
                _run(f"{params['startTime']}-b", start + timedelta(minutes=2)),
            ]
            return _FakeResponse(
                {
                    "resources": resources[offset:offset + 2],
                    "limit": 2,
                    "offset": offset,
                    "total": len(resources),
                }
            )

        payload = source._fetch_ranged_resource(fetch_page, spec, "24h", window_start, window_end, warnings)

        self.assertFalse(warnings)
        self.assertEqual(payload["total"], len(payload["resources"]))
        self.assertIn(("2026-03-12T11:00:00Z", "2026-03-12T11:30:00Z", 0), calls)
        self.assertIn(("2026-03-12T11:00:00Z", "2026-03-12T11:15:00Z", 0), calls)

    def test_fetch_ranged_resource_dedupes_adjacent_slices_by_uuid(self) -> None:
        source = LiveOrbitSource(_config())
        warnings: list[str] = []
        spec = _RANGED_ORBIT_ENDPOINTS["runs"]
        window_start = datetime(2026, 3, 10, 12, tzinfo=timezone.utc)
        window_end = datetime(2026, 3, 12, 12, tzinfo=timezone.utc)

        def fetch_page(*, params: dict) -> _FakeResponse:
            resources_by_slice = {
                "2026-03-10T12:00:00Z": [
                    _run("run-a", datetime(2026, 3, 10, 13, tzinfo=timezone.utc)),
                    _run("run-b", datetime(2026, 3, 11, 11, tzinfo=timezone.utc)),
                ],
                "2026-03-11T12:00:00Z": [
                    _run("run-b", datetime(2026, 3, 11, 11, tzinfo=timezone.utc)),
                    _run("run-c", datetime(2026, 3, 12, 11, tzinfo=timezone.utc)),
                ],
            }
            resources = resources_by_slice[params["startTime"]]
            offset = params["offset"]
            return _FakeResponse(
                {
                    "resources": resources[offset:offset + 2],
                    "limit": 2,
                    "offset": offset,
                    "total": len(resources),
                }
            )

        payload = source._fetch_ranged_resource(fetch_page, spec, "7d", window_start, window_end, warnings)

        self.assertEqual(
            [resource["uuid"] for resource in payload["resources"]],
            ["run-c", "run-b", "run-a"],
        )
        self.assertEqual(payload["total"], 3)
        self.assertFalse(warnings)

    def test_fetch_ranged_resource_warns_when_minimum_slice_stays_incomplete(self) -> None:
        source = LiveOrbitSource(_config())
        warnings: list[str] = []
        spec = _RANGED_ORBIT_ENDPOINTS["runEvents"]
        window_start = datetime(2026, 3, 12, 11, tzinfo=timezone.utc)
        window_end = datetime(2026, 3, 12, 11, 15, tzinfo=timezone.utc)

        def fetch_page(*, params: dict) -> _FakeResponse:
            pages = {
                0: {
                    "resources": [
                        _event("event-1", datetime(2026, 3, 12, 11, 10, tzinfo=timezone.utc)),
                        _event("event-2", datetime(2026, 3, 12, 11, 20, tzinfo=timezone.utc)),
                    ],
                    "limit": 2,
                    "offset": 0,
                    "total": 3,
                },
                2: {"resources": [], "limit": 2, "offset": 2, "total": 3},
            }
            return _FakeResponse(pages[params["offset"]])

        with self.assertLogs("app.orbit_client", level="WARNING") as captured_logs:
            payload = source._fetch_ranged_resource(fetch_page, spec, "24h", window_start, window_end, warnings)

        self.assertEqual([resource["uuid"] for resource in payload["resources"]], ["event-2", "event-1"])
        self.assertEqual(payload["total"], 3)
        self.assertEqual(
            warnings,
            ["Run activity may be incomplete: showing 2 of 3 records from Orbit."],
        )
        self.assertTrue(
            any(
                "start=2026-03-12T11:00:00Z end=2026-03-12T11:15:00Z loaded=2 total=3 requested_limit=2"
                in message
                for message in captured_logs.output
            )
        )


if __name__ == "__main__":
    unittest.main()
