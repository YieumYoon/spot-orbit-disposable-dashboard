from __future__ import annotations

import copy
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from .config import DashboardConfig
from .transform import build_dashboard_payload


LOGGER = logging.getLogger(__name__)
_RANGE_WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
_INITIAL_SLICE_WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=1),
    "30d": timedelta(days=1),
}
_MIN_SLICE_WINDOW = timedelta(hours=1)


def _resolve_vendor_path() -> Path:
    return Path(__file__).resolve().parents[1] / "vendor/spot-sdk/python/bosdyn-orbit/src"


def _import_bosdyn_client():
    try:
        from bosdyn.orbit.client import Client

        return Client
    except ModuleNotFoundError:
        vendor_src = _resolve_vendor_path()
        if str(vendor_src) not in sys.path:
            sys.path.append(str(vendor_src))
        from bosdyn.orbit.client import Client

        return Client


def _warning_label(resource_name: str) -> str:
    return {
        "runs": "Runs",
        "run events": "Run activity",
        "run captures": "Captures",
        "anomalies": "Issues",
        "open anomalies": "Open issues",
    }.get(resource_name, resource_name.capitalize())


def _parse_orbit_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_orbit_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unique_messages(messages: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for message in messages:
        if message in seen:
            continue
        seen.add(message)
        unique.append(message)
    return unique


@dataclass(frozen=True)
class PaginatedFetchResult:
    payload: dict[str, Any]
    incomplete: bool
    issues: tuple[str, ...]


@dataclass(frozen=True)
class RangedOrbitEndpointSpec:
    getter_name: str
    resource_name: str
    start_param: str
    end_param: str
    order_by: str
    timestamp_fields: tuple[str, ...]


_RANGED_ORBIT_ENDPOINTS = {
    "runs": RangedOrbitEndpointSpec(
        getter_name="get_runs",
        resource_name="runs",
        start_param="startTime",
        end_param="endTime",
        order_by="newest",
        timestamp_fields=("startTime", "endTime"),
    ),
    "runEvents": RangedOrbitEndpointSpec(
        getter_name="get_run_events",
        resource_name="run events",
        start_param="startTime",
        end_param="endTime",
        order_by="-created_at",
        timestamp_fields=("createdAt",),
    ),
    "runCaptures": RangedOrbitEndpointSpec(
        getter_name="get_run_captures",
        resource_name="run captures",
        start_param="startCreatedAt",
        end_param="endCreatedAt",
        order_by="-created_at",
        timestamp_fields=("createdAt",),
    ),
    "anomalies": RangedOrbitEndpointSpec(
        getter_name="get_anomalies",
        resource_name="anomalies",
        start_param="startTime",
        end_param="endTime",
        order_by="-time",
        timestamp_fields=("time", "createdAt"),
    ),
}


class FixtureOrbitSource:
    def __init__(self, config: DashboardConfig) -> None:
        self._config = config

    def _load_json(self, file_name: str) -> dict[str, Any]:
        file_path = self._config.fixture_dir / file_name
        with file_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def fetch_snapshot(self, range_key: str) -> dict[str, Any]:
        warnings = ["Showing sample data. This dashboard is not using live Orbit data."]
        return {
            "systemTime": self._load_json("system_time.json"),
            "runs": self._load_json("runs.json"),
            "runEvents": self._load_json("run_events.json"),
            "runCaptures": self._load_json("run_captures.json"),
            "anomalies": self._load_json("anomalies.json"),
            "openAnomalies": {
                "resources": [
                    item
                    for item in self._load_json("anomalies.json").get("resources", [])
                    if (item.get("status") or "").lower() == "open"
                ]
            },
            "warnings": warnings,
            "range": range_key,
        }


class LiveOrbitSource:
    def __init__(self, config: DashboardConfig) -> None:
        self._config = config
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._config.orbit_host or not self._config.orbit_api_token:
            raise RuntimeError("ORBIT_HOST and ORBIT_API_TOKEN are required for live Orbit access.")

        client_cls = _import_bosdyn_client()
        client = client_cls(
            hostname=self._config.orbit_host,
            verify=self._config.orbit_verify_tls,
            cert=self._config.orbit_cert_path,
        )
        response = client.authenticate_with_api_token(self._config.orbit_api_token)
        if not response.ok:
            raise RuntimeError(f"Orbit authentication failed: {response.text}")
        self._client = client
        return client

    def _warn_if_incomplete(self, payload: dict[str, Any], resource_name: str, warnings: list[str]) -> None:
        total = payload.get("total")
        loaded = len(payload.get("resources", []))
        if isinstance(total, int) and total > loaded:
            warnings.append(
                f"{_warning_label(resource_name)} may be incomplete: showing {loaded} of {total} records from Orbit."
            )

    def _shortfall(self, payload: dict[str, Any]) -> int:
        total = payload.get("total")
        loaded = len(payload.get("resources", []))
        if isinstance(total, int) and total > loaded:
            return total - loaded
        return 0

    def _fetch_paginated_result(
        self,
        fetch_page: Callable[..., Any],
        params: dict[str, Any],
        resource_name: str,
    ) -> PaginatedFetchResult:
        page_size = self._config.orbit_item_limit
        offset = 0
        combined_resources: list[dict[str, Any]] = []
        last_payload: dict[str, Any] | None = None
        issues: list[str] = []

        while True:
            page_payload = fetch_page(params={**params, "limit": page_size, "offset": offset}).json()
            last_payload = page_payload

            current_offset = page_payload.get("offset", offset)
            if isinstance(current_offset, int) and current_offset != offset:
                issues.append(
                    f"{_warning_label(resource_name)} may be incomplete because Orbit returned an unexpected page at record {offset}."
                )
                break

            page_resources_raw = page_payload.get("resources", [])
            page_resources = page_resources_raw if isinstance(page_resources_raw, list) else []
            combined_resources.extend(page_resources)

            total = page_payload.get("total")
            page_limit = page_payload.get("limit")
            effective_limit = page_limit if isinstance(page_limit, int) and page_limit > 0 else page_size

            if not page_resources:
                break
            if isinstance(total, int):
                if len(combined_resources) >= total:
                    break
            elif len(page_resources) < effective_limit:
                break

            next_offset = offset + len(page_resources)
            if next_offset <= offset:
                issues.append(
                    f"{_warning_label(resource_name)} may be incomplete because Orbit pagination stopped early at record {offset}."
                )
                break
            offset = next_offset

        if last_payload is None:
            payload = {"resources": [], "limit": page_size, "offset": 0, "total": 0}
        else:
            payload = dict(last_payload)
            payload["resources"] = combined_resources
            payload["offset"] = 0
            payload["limit"] = page_size
            payload["total"] = (
                payload.get("total")
                if isinstance(payload.get("total"), int)
                else len(combined_resources)
            )

        return PaginatedFetchResult(
            payload=payload,
            incomplete=bool(issues) or self._shortfall(payload) > 0,
            issues=tuple(issues),
        )

    def _fetch_paginated(
        self,
        fetch_page: Callable[..., Any],
        params: dict[str, Any],
        resource_name: str,
        warnings: list[str],
    ) -> dict[str, Any]:
        result = self._fetch_paginated_result(fetch_page, params, resource_name)
        warnings.extend(result.issues)
        self._warn_if_incomplete(result.payload, resource_name, warnings)
        return result.payload

    def _resource_sort_key(self, resource: dict[str, Any], spec: RangedOrbitEndpointSpec) -> datetime:
        for field_name in spec.timestamp_fields:
            parsed = _parse_orbit_datetime(resource.get(field_name))
            if parsed is not None:
                return parsed
        return datetime.min.replace(tzinfo=timezone.utc)

    def _merge_ranged_results(
        self,
        results: list[PaginatedFetchResult],
        spec: RangedOrbitEndpointSpec,
        warnings: list[str],
    ) -> dict[str, Any]:
        resources: list[dict[str, Any]] = []
        seen_uuids: set[str] = set()
        incomplete_issues: list[str] = []
        missing_records = 0
        any_incomplete = False

        for result in results:
            payload_resources_raw = result.payload.get("resources", [])
            payload_resources = payload_resources_raw if isinstance(payload_resources_raw, list) else []

            if result.incomplete:
                any_incomplete = True
                incomplete_issues.extend(result.issues)
                missing_records += self._shortfall(result.payload)

            for resource in payload_resources:
                if not isinstance(resource, dict):
                    continue
                resource_uuid = resource.get("uuid")
                if isinstance(resource_uuid, str) and resource_uuid:
                    if resource_uuid in seen_uuids:
                        continue
                    seen_uuids.add(resource_uuid)
                resources.append(resource)

        resources.sort(key=lambda resource: self._resource_sort_key(resource, spec), reverse=True)

        payload = {
            "resources": resources,
            "limit": self._config.orbit_item_limit,
            "offset": 0,
            "total": len(resources) + missing_records,
        }

        if any_incomplete:
            if payload["total"] > len(resources):
                self._warn_if_incomplete(payload, spec.resource_name, warnings)
            else:
                warnings.extend(_unique_messages(incomplete_issues))

        return payload

    def _fetch_ranged_slice(
        self,
        fetch_page: Callable[..., Any],
        spec: RangedOrbitEndpointSpec,
        slice_start: datetime,
        slice_end: datetime,
    ) -> PaginatedFetchResult:
        params = {
            spec.start_param: _to_orbit_iso(slice_start),
            spec.end_param: _to_orbit_iso(slice_end),
            "orderBy": spec.order_by,
        }
        return self._fetch_paginated_result(fetch_page, params, spec.resource_name)

    def _fetch_ranged_slice_with_retry(
        self,
        fetch_page: Callable[..., Any],
        spec: RangedOrbitEndpointSpec,
        slice_start: datetime,
        slice_end: datetime,
    ) -> list[PaginatedFetchResult]:
        result = self._fetch_ranged_slice(fetch_page, spec, slice_start, slice_end)
        if not result.incomplete:
            return [result]

        duration = slice_end - slice_start
        half_duration = duration / 2
        if half_duration < _MIN_SLICE_WINDOW:
            LOGGER.warning(
                "Orbit %s remained incomplete at minimum slice window from %s to %s.",
                spec.resource_name,
                _to_orbit_iso(slice_start),
                _to_orbit_iso(slice_end),
            )
            return [result]

        midpoint = slice_start + half_duration
        if midpoint <= slice_start or midpoint >= slice_end:
            LOGGER.warning(
                "Orbit %s could not be split into smaller slices from %s to %s.",
                spec.resource_name,
                _to_orbit_iso(slice_start),
                _to_orbit_iso(slice_end),
            )
            return [result]

        LOGGER.info(
            "Retrying Orbit %s with smaller slices from %s to %s.",
            spec.resource_name,
            _to_orbit_iso(slice_start),
            _to_orbit_iso(slice_end),
        )
        return [
            *self._fetch_ranged_slice_with_retry(fetch_page, spec, slice_start, midpoint),
            *self._fetch_ranged_slice_with_retry(fetch_page, spec, midpoint, slice_end),
        ]

    def _fetch_ranged_resource(
        self,
        fetch_page: Callable[..., Any],
        spec: RangedOrbitEndpointSpec,
        range_key: str,
        window_start: datetime,
        window_end: datetime,
        warnings: list[str],
    ) -> dict[str, Any]:
        slice_width = _INITIAL_SLICE_WINDOWS[range_key]
        results: list[PaginatedFetchResult] = []
        cursor = window_start

        while cursor < window_end:
            slice_end = min(cursor + slice_width, window_end)
            results.extend(self._fetch_ranged_slice_with_retry(fetch_page, spec, cursor, slice_end))
            cursor = slice_end

        return self._merge_ranged_results(results, spec, warnings)

    def fetch_snapshot(self, range_key: str) -> dict[str, Any]:
        client = self._get_client()
        warnings: list[str] = []
        system_time = client.get_system_time().json()

        now_utc = datetime.fromtimestamp(int(system_time["msSinceEpoch"]) / 1000, tz=timezone.utc).replace(microsecond=0)
        window_start = now_utc - _RANGE_WINDOWS[range_key]

        runs = self._fetch_ranged_resource(
            getattr(client, _RANGED_ORBIT_ENDPOINTS["runs"].getter_name),
            _RANGED_ORBIT_ENDPOINTS["runs"],
            range_key,
            window_start,
            now_utc,
            warnings,
        )
        run_events = self._fetch_ranged_resource(
            getattr(client, _RANGED_ORBIT_ENDPOINTS["runEvents"].getter_name),
            _RANGED_ORBIT_ENDPOINTS["runEvents"],
            range_key,
            window_start,
            now_utc,
            warnings,
        )
        run_captures = self._fetch_ranged_resource(
            getattr(client, _RANGED_ORBIT_ENDPOINTS["runCaptures"].getter_name),
            _RANGED_ORBIT_ENDPOINTS["runCaptures"],
            range_key,
            window_start,
            now_utc,
            warnings,
        )
        anomalies = self._fetch_ranged_resource(
            getattr(client, _RANGED_ORBIT_ENDPOINTS["anomalies"].getter_name),
            _RANGED_ORBIT_ENDPOINTS["anomalies"],
            range_key,
            window_start,
            now_utc,
            warnings,
        )
        open_anomalies = self._fetch_paginated(
            client.get_anomalies,
            {
                "status": "open",
                "orderBy": "-time",
            },
            "open anomalies",
            warnings,
        )

        return {
            "systemTime": system_time,
            "runs": runs,
            "runEvents": run_events,
            "runCaptures": run_captures,
            "anomalies": anomalies,
            "openAnomalies": open_anomalies,
            "warnings": warnings,
            "range": range_key,
        }


class DashboardService:
    def __init__(self, config: DashboardConfig) -> None:
        self._config = config
        self._source = FixtureOrbitSource(config) if config.fixture_mode else LiveOrbitSource(config)
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = Lock()

    def get_dashboard(self, range_key: str) -> dict[str, Any]:
        with self._lock:
            cached = self._cache.get(range_key)
            if cached and (time.time() - cached[0]) < self._config.dashboard_cache_ttl_seconds:
                return copy.deepcopy(cached[1])

        snapshot = self._source.fetch_snapshot(range_key)
        payload = build_dashboard_payload(snapshot, self._config, range_key).to_dict()

        with self._lock:
            self._cache[range_key] = (time.time(), payload)

        return copy.deepcopy(payload)

    def health(self) -> dict[str, Any]:
        cache_age = None
        with self._lock:
            if self._cache:
                newest = max(item[0] for item in self._cache.values())
                cache_age = round(time.time() - newest, 1)

        return {
            "status": "ok",
            "fixtureMode": self._config.fixture_mode,
            "orbitConfigured": bool(self._config.orbit_host and self._config.orbit_api_token),
            "cacheAgeSeconds": cache_age,
            "bindHost": self._config.dashboard_bind_host,
            "port": self._config.dashboard_port,
        }
