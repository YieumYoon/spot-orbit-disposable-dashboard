from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sys
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import DashboardConfig, load_config
from app.orbit_client import DashboardService, _import_bosdyn_client
from app.transform import build_dashboard_payload


def _print_result(status: str, step: str, detail: str) -> None:
    print(f"[{status}] {step}: {detail}")


def _mask_token(token: str | None) -> str:
    if not token:
        return "<missing>"
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def _format_exception(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    if not text:
        return "<empty>"
    if len(text) > 300:
        return f"{text[:300]}..."
    return str(text)


def _call_json(
    name: str,
    request_fn: Callable[..., Any],
    failures: list[str],
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        response = request_fn(params=params) if params is not None else request_fn()
        payload = response.json()
    except Exception as exc:
        failures.append(name)
        _print_result("FAIL", name, _format_exception(exc))
        return None

    resources = payload.get("resources")
    if isinstance(resources, list):
        detail = f"resources={len(resources)}"
        total = payload.get("total")
        limit = payload.get("limit")
        if total is not None:
            detail += f", total={total}"
        if limit is not None:
            detail += f", limit={limit}"
        _print_result("PASS", name, detail)
    else:
        keys = ", ".join(sorted(payload.keys()))
        _print_result("PASS", name, f"payload keys: {keys}")
    return payload


def _check_timezone(config: DashboardConfig, warnings: list[str]) -> None:
    try:
        ZoneInfo(config.timezone)
        _print_result("PASS", "Timezone lookup", f"{config.timezone} resolved")
    except ZoneInfoNotFoundError:
        warnings.append("timezone")
        _print_result(
            "WARN",
            "Timezone lookup",
            f"{config.timezone} not found. Install tzdata for named timezone support on Windows.",
        )


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    try:
        config = load_config()
    except Exception as exc:
        _print_result("FAIL", "Load config", _format_exception(exc))
        return 1

    _print_result(
        "PASS",
        "Load config",
        (
            f"host={config.orbit_host or '<missing>'}, "
            f"token={_mask_token(config.orbit_api_token)}, "
            f"verify_tls={config.orbit_verify_tls}, "
            f"timezone={config.timezone}, "
            f"fixture_mode={config.fixture_mode}"
        ),
    )

    if config.fixture_mode:
        warnings.append("fixture_mode")
        _print_result(
            "WARN",
            "Fixture mode",
            "ORBIT_USE_FIXTURES=true, so the real /api/dashboard route would use fixtures unless you turn it off.",
        )

    if not config.orbit_host:
        failures.append("orbit_host")
        _print_result("FAIL", "Config value", "ORBIT_HOST is missing")

    if not config.orbit_api_token:
        failures.append("orbit_api_token")
        _print_result("FAIL", "Config value", "ORBIT_API_TOKEN is missing")

    _check_timezone(config, warnings)

    if failures:
        print("\nSummary: fix the failed config items first, then rerun this script.")
        return 1

    try:
        client_cls = _import_bosdyn_client()
        _print_result("PASS", "Import Orbit client", client_cls.__name__)
    except Exception as exc:
        _print_result("FAIL", "Import Orbit client", _format_exception(exc))
        return 1

    try:
        client = client_cls(
            hostname=config.orbit_host,
            verify=config.orbit_verify_tls,
            cert=config.orbit_cert_path,
        )
        _print_result("PASS", "Create Orbit client", f"cert={config.orbit_cert_path or '<none>'}")
    except Exception as exc:
        _print_result("FAIL", "Create Orbit client", _format_exception(exc))
        return 1

    try:
        auth_response = client.authenticate_with_api_token(config.orbit_api_token)
    except Exception as exc:
        _print_result("FAIL", "Authenticate", _format_exception(exc))
        return 1

    if not getattr(auth_response, "ok", False):
        _print_result(
            "FAIL",
            "Authenticate",
            f"status={getattr(auth_response, 'status_code', 'n/a')}, body={_response_text(auth_response)}",
        )
        return 1

    _print_result(
        "PASS",
        "Authenticate",
        f"status={getattr(auth_response, 'status_code', 'n/a')}",
    )

    system_time = _call_json("Get system time", client.get_system_time, failures)
    if system_time is None:
        return 1

    now_utc_ms = int(system_time["msSinceEpoch"])
    end_iso = time_to_iso(now_utc_ms)
    start_iso = time_to_iso(now_utc_ms - int(timedelta(hours=24).total_seconds() * 1000))
    limit = min(config.orbit_item_limit, 5)

    runs = _call_json(
        "Get runs",
        client.get_runs,
        failures,
        params={
            "startTime": start_iso,
            "endTime": end_iso,
            "limit": limit,
            "orderBy": "newest",
        },
    )
    run_events = _call_json(
        "Get run events",
        client.get_run_events,
        failures,
        params={
            "startTime": start_iso,
            "endTime": end_iso,
            "limit": limit,
            "orderBy": "-created_at",
        },
    )
    run_captures = _call_json(
        "Get run captures",
        client.get_run_captures,
        failures,
        params={
            "startCreatedAt": start_iso,
            "endCreatedAt": end_iso,
            "limit": limit,
            "orderBy": "-created_at",
        },
    )
    anomalies = _call_json(
        "Get anomalies",
        client.get_anomalies,
        failures,
        params={
            "startTime": start_iso,
            "endTime": end_iso,
            "limit": limit,
            "orderBy": "-time",
        },
    )
    open_anomalies = _call_json(
        "Get open anomalies",
        client.get_anomalies,
        failures,
        params={
            "status": "open",
            "limit": limit,
            "orderBy": "-time",
        },
    )

    if failures:
        print("\nSummary: one or more Orbit API calls failed before the dashboard transform step.")
        return 1

    snapshot = {
        "systemTime": system_time,
        "runs": runs,
        "runEvents": run_events,
        "runCaptures": run_captures,
        "anomalies": anomalies,
        "openAnomalies": open_anomalies,
        "warnings": [],
    }

    try:
        payload = build_dashboard_payload(snapshot, config, "24h").to_dict()
        _print_result(
            "PASS",
            "Build dashboard payload",
            (
                f"runs={payload['summary']['runs']}, "
                f"captures={payload['summary']['dataCaptures']}, "
                f"open_anomalies={payload['summary']['openAnomalies']}"
            ),
        )
    except Exception as exc:
        _print_result("FAIL", "Build dashboard payload", _format_exception(exc))
        return 1

    try:
        service_config = replace(config, fixture_mode=False, orbit_item_limit=limit)
        payload = DashboardService(service_config).get_dashboard("24h")
        _print_result(
            "PASS",
            "Simulate /api/dashboard",
            f"generatedAt={payload['generatedAt']}, range={payload['range']}",
        )
    except Exception as exc:
        _print_result("FAIL", "Simulate /api/dashboard", _format_exception(exc))
        return 1

    print("\nSummary: live Orbit auth, endpoint calls, transform, and dashboard generation all passed.")
    if warnings:
        print(f"Warnings: {', '.join(warnings)}")
    return 0


def time_to_iso(ms_since_epoch: int) -> str:
    value = datetime.fromtimestamp(ms_since_epoch / 1000, tz=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
