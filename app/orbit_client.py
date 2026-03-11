from __future__ import annotations

import copy
import json
import logging
import sys
import time
from pathlib import Path
from threading import Lock
from typing import Any

from .config import DashboardConfig
from .transform import build_dashboard_payload


LOGGER = logging.getLogger(__name__)


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


class FixtureOrbitSource:
    def __init__(self, config: DashboardConfig) -> None:
        self._config = config

    def _load_json(self, file_name: str) -> dict[str, Any]:
        file_path = self._config.fixture_dir / file_name
        with file_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def fetch_snapshot(self, range_key: str) -> dict[str, Any]:
        warnings = ["Fixture mode is enabled. Live Orbit data is not being used."]
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

    def _check_limit(self, payload: dict[str, Any], resource_name: str, warnings: list[str]) -> None:
        total = payload.get("total")
        limit = payload.get("limit")
        if isinstance(total, int) and isinstance(limit, int) and total > limit:
            warnings.append(f"{resource_name} results truncated at {limit} of {total}.")

    def fetch_snapshot(self, range_key: str) -> dict[str, Any]:
        client = self._get_client()
        warnings: list[str] = []
        system_time = client.get_system_time().json()

        now_utc_ms = int(system_time["msSinceEpoch"])
        window_minutes = {"24h": 24 * 60, "7d": 7 * 24 * 60, "30d": 30 * 24 * 60}[range_key]
        window_start_ms = now_utc_ms - (window_minutes * 60 * 1000)

        start_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(window_start_ms / 1000))
        end_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_utc_ms / 1000))
        limit = self._config.orbit_item_limit

        runs = client.get_runs(
            params={
                "startTime": start_iso,
                "endTime": end_iso,
                "limit": limit,
                "orderBy": "newest",
            }
        ).json()
        run_events = client.get_run_events(
            params={
                "startTime": start_iso,
                "endTime": end_iso,
                "limit": limit,
                "orderBy": "-created_at",
            }
        ).json()
        run_captures = client.get_run_captures(
            params={
                "startCreatedAt": start_iso,
                "endCreatedAt": end_iso,
                "limit": limit,
                "orderBy": "-created_at",
            }
        ).json()
        anomalies = client.get_anomalies(
            params={
                "startTime": start_iso,
                "endTime": end_iso,
                "limit": limit,
                "orderBy": "-time",
            }
        ).json()
        open_anomalies = client.get_anomalies(
            params={
                "status": "open",
                "limit": limit,
                "orderBy": "-time",
            }
        ).json()

        self._check_limit(runs, "runs", warnings)
        self._check_limit(run_events, "run events", warnings)
        self._check_limit(run_captures, "run captures", warnings)
        self._check_limit(anomalies, "anomalies", warnings)
        self._check_limit(open_anomalies, "open anomalies", warnings)

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
