from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from app.config import RANGE_OPTIONS, DashboardConfig, load_config
from app.orbit_client import (
    LiveOrbitSource,
    PaginatedFetchResult,
    RangedOrbitEndpointSpec,
    _RANGE_WINDOWS,
    _to_orbit_iso,
    _warning_label,
)
from app.transform import build_dashboard_payload


RESOURCE_KEYS = (
    "runs",
    "runEvents",
    "runCaptures",
    "anomalies",
    "openAnomalies",
)
RESOURCE_LABEL_NAMES = {
    "runs": "runs",
    "runEvents": "run events",
    "runCaptures": "run captures",
    "anomalies": "anomalies",
    "openAnomalies": "open anomalies",
}


@dataclass(frozen=True)
class IncompleteSliceRecord:
    resource_name: str
    slice_start: str
    slice_end: str
    loaded: int
    total: Any
    requested_limit: int
    issues: tuple[str, ...]


class TracingLiveOrbitSource(LiveOrbitSource):
    def __init__(self, config: DashboardConfig, *, emit_source_logs: bool = False) -> None:
        super().__init__(config)
        self._emit_source_logs = emit_source_logs
        self._final_incomplete_slices: list[IncompleteSliceRecord] = []

    def _log_incomplete_slice(
        self,
        spec: RangedOrbitEndpointSpec,
        slice_start: datetime,
        slice_end: datetime,
        result: PaginatedFetchResult,
    ) -> None:
        self._final_incomplete_slices.append(
            IncompleteSliceRecord(
                resource_name=spec.resource_name,
                slice_start=_to_orbit_iso(slice_start),
                slice_end=_to_orbit_iso(slice_end),
                loaded=len(result.payload.get("resources", [])),
                total=result.payload.get("total"),
                requested_limit=self._config.orbit_item_limit,
                issues=result.issues,
            )
        )
        if self._emit_source_logs:
            super()._log_incomplete_slice(spec, slice_start, slice_end, result)

    def fetch_snapshot_with_trace(
        self,
        range_key: str,
    ) -> tuple[dict[str, Any], tuple[IncompleteSliceRecord, ...]]:
        self._final_incomplete_slices = []
        snapshot = self.fetch_snapshot(range_key)
        return snapshot, tuple(self._final_incomplete_slices)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Troubleshoot range warnings by fetching the live Orbit-backed dashboard data "
            "for 7d/30d and printing final incomplete slice windows."
        )
    )
    parser.add_argument(
        "--ranges",
        nargs="+",
        default=["7d", "30d"],
        choices=RANGE_OPTIONS,
        help="Dashboard ranges to inspect. Defaults to 7d and 30d.",
    )
    parser.add_argument(
        "--emit-source-logs",
        action="store_true",
        help="Also emit the underlying slice warning logs while tracing.",
    )
    return parser.parse_args()


def _format_exception(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _window_bounds(snapshot: dict[str, Any], range_key: str) -> tuple[str, str]:
    now_utc = datetime.fromtimestamp(int(snapshot["systemTime"]["msSinceEpoch"]) / 1000, tz=timezone.utc)
    window_start = now_utc - _RANGE_WINDOWS[range_key]
    return _to_orbit_iso(window_start), _to_orbit_iso(now_utc)


def _loaded_total(payload: dict[str, Any]) -> tuple[int, Any]:
    return len(payload.get("resources", [])), payload.get("total")


def _print_resource_counts(snapshot: dict[str, Any]) -> None:
    print("Resource totals:")
    for resource_key in RESOURCE_KEYS:
        payload = snapshot.get(resource_key, {})
        loaded, total = _loaded_total(payload if isinstance(payload, dict) else {})
        shortfall = total - loaded if isinstance(total, int) else "n/a"
        label = _warning_label(RESOURCE_LABEL_NAMES[resource_key])
        print(f"  - {label}: loaded={loaded} total={total} shortfall={shortfall}")


def _print_warnings(warnings: list[str]) -> None:
    print(f"Dashboard warnings ({len(warnings)}):")
    if not warnings:
        print("  - none")
        return
    for warning in warnings:
        print(f"  - {warning}")


def _print_incomplete_slices(records: tuple[IncompleteSliceRecord, ...]) -> None:
    print(f"Final incomplete slices ({len(records)}):")
    if not records:
        print("  - none")
        return

    for record in records:
        shortfall = record.total - record.loaded if isinstance(record.total, int) else "n/a"
        issue_text = "; ".join(record.issues) if record.issues else "none"
        print(
            "  - "
            f"{_warning_label(record.resource_name)}: "
            f"{record.slice_start} -> {record.slice_end} "
            f"loaded={record.loaded} total={record.total} shortfall={shortfall} "
            f"limit={record.requested_limit} issues={issue_text}"
        )


def main() -> int:
    args = _parse_args()

    try:
        config = load_config()
    except Exception as exc:
        print(f"[FAIL] Load config: {_format_exception(exc)}")
        return 1

    if config.fixture_mode:
        print("[WARN] ORBIT_USE_FIXTURES=true in config; forcing live Orbit mode for this diagnostic.")

    live_config = replace(config, fixture_mode=False)
    if not live_config.orbit_host:
        print("[FAIL] ORBIT_HOST is missing.")
        return 1
    if not live_config.orbit_api_token:
        print("[FAIL] ORBIT_API_TOKEN is missing.")
        return 1

    print(f"Host: {live_config.orbit_host}")
    print(f"Item limit: {live_config.orbit_item_limit}")
    print(f"Timezone: {live_config.timezone}")

    source = TracingLiveOrbitSource(live_config, emit_source_logs=args.emit_source_logs)
    for range_key in args.ranges:
        print()
        print(f"=== Range {range_key} ===")
        try:
            snapshot, incomplete_slices = source.fetch_snapshot_with_trace(range_key)
            payload = build_dashboard_payload(snapshot, live_config, range_key).to_dict()
        except Exception as exc:
            print(f"[FAIL] Fetch {range_key}: {_format_exception(exc)}")
            return 1

        window_start, window_end = _window_bounds(snapshot, range_key)
        print(f"Window: {window_start} -> {window_end}")
        _print_warnings(list(payload.get("warnings", [])))
        _print_resource_counts(snapshot)
        _print_incomplete_slices(incomplete_slices)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
