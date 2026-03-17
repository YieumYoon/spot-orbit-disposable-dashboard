from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import DashboardConfig
from .models import (
    AnomalySnapshot,
    DashboardPayload,
    RecentAnomaly,
    RecentEvent,
    RecentRun,
    RobotStatus,
    StatusCount,
    SummaryMetrics,
    TimeBucket,
    TrendSeries,
)


STATUS_MAP = {
    "SUCCESS": "success",
    "FAILURE": "failure",
    "ERROR": "error",
    "STOPPED": "stopped",
    "RUNNING": "running",
    "PAUSED": "paused",
    "UNKNOWN": "unknown",
    "NONE": "unknown",
}

STATUS_LABELS = {
    "success": "Success",
    "failure": "Failure",
    "error": "Error",
    "stopped": "Stopped",
    "running": "Running",
    "paused": "Paused",
    "unknown": "Unknown",
}

ACTIVE_STATUSES = {"RUNNING", "PAUSED"}
FALLBACK_MISSION_NAME = "Unnamed mission"
FALLBACK_ISSUE_TITLE = "Untitled issue"
RANGE_DEFINITIONS = {
    "24h": {"window": timedelta(hours=24), "step": timedelta(hours=1), "label_format": "%-I %p"},
    "7d": {"window": timedelta(days=7), "step": timedelta(days=1), "label_format": "%b %-d"},
    "30d": {"window": timedelta(days=30), "step": timedelta(days=1), "label_format": "%b %-d"},
}


def _parse_timestamp(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    value = raw_value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _zoneinfo(timezone_name: str) -> tzinfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _bucket_floor(value: datetime, range_key: str) -> datetime:
    if range_key == "24h":
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _bucket_label(value: datetime, timezone_name: str, range_key: str) -> str:
    local_value = value.astimezone(_zoneinfo(timezone_name))
    if range_key == "24h":
        hour = local_value.strftime("%I").lstrip("0") or "0"
        return f"{hour} {local_value.strftime('%p')}"
    return f"{local_value.strftime('%b')} {local_value.day}"


def _build_buckets(
    timestamps: Iterable[datetime],
    start_at: datetime,
    end_at: datetime,
    range_key: str,
    timezone_name: str,
) -> list[TimeBucket]:
    step = RANGE_DEFINITIONS[range_key]["step"]
    buckets: dict[datetime, int] = {}
    cursor = _bucket_floor(start_at, range_key)
    final_bucket = _bucket_floor(end_at - timedelta(microseconds=1), range_key)
    while cursor <= final_bucket:
        buckets[cursor] = 0
        cursor += step

    for timestamp in timestamps:
        if start_at <= timestamp < end_at:
            bucket_key = _bucket_floor(timestamp, range_key)
            if bucket_key in buckets:
                buckets[bucket_key] += 1

    return [
        TimeBucket(bucketStart=_to_iso(bucket_start) or "", label=_bucket_label(bucket_start, timezone_name, range_key), count=count)
        for bucket_start, count in sorted(buckets.items())
    ]


def _normalize_status(raw_status: str | None) -> str:
    if not raw_status:
        return "unknown"
    return STATUS_MAP.get(raw_status.upper(), "unknown")


def _activity_time_for_run(run: dict[str, Any]) -> datetime | None:
    return _parse_timestamp(run.get("endTime")) or _parse_timestamp(run.get("startTime"))


def _event_time(event: dict[str, Any]) -> datetime | None:
    return _parse_timestamp(event.get("time")) or _parse_timestamp(event.get("createdAt"))


def _capture_time(capture: dict[str, Any]) -> datetime | None:
    return _parse_timestamp(capture.get("createdAt")) or _parse_timestamp(capture.get("time"))


def _recently_active(last_activity: datetime | None, now_utc: datetime) -> bool:
    if last_activity is None:
        return False
    return now_utc - last_activity <= timedelta(hours=24)


def _derive_robot_status(
    runs: list[dict[str, Any]],
    events: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    now_utc: datetime,
) -> RobotStatus:
    latest_run = max(
        runs,
        key=lambda item: _activity_time_for_run(item) or datetime.min.replace(tzinfo=timezone.utc),
        default=None,
    )
    latest_activity = max(
        [timestamp for timestamp in (
            *(_activity_time_for_run(run) for run in runs),
            *(_event_time(event) for event in events),
            *(_capture_time(capture) for capture in captures),
        ) if timestamp is not None],
        default=None,
    )

    if latest_run and (latest_run.get("missionStatus") or "").upper() in ACTIVE_STATUSES:
        mission_name = latest_run.get("missionName") or FALLBACK_MISSION_NAME
        detail = f"Currently running: {mission_name}"
        return RobotStatus(label="Active", detail=detail, lastActivityAt=_to_iso(latest_activity))

    if _recently_active(latest_activity, now_utc):
        detail = "Orbit recorded activity in the last 24 hours."
        return RobotStatus(label="Recently Active", detail=detail, lastActivityAt=_to_iso(latest_activity))

    if latest_activity is not None:
        detail = "Orbit has older activity on record, but none in the last 24 hours."
        return RobotStatus(label="Idle", detail=detail, lastActivityAt=_to_iso(latest_activity))

    return RobotStatus(
        label="Unknown",
        detail="Orbit has not recorded any runs, run activity, or captures yet.",
        lastActivityAt=None,
    )


def _range_window(now_utc: datetime, range_key: str) -> tuple[datetime, datetime]:
    window = RANGE_DEFINITIONS[range_key]["window"]
    return now_utc - window, now_utc


def _sort_desc(items: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: key_fn(item) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


def build_dashboard_payload(
    snapshot: dict[str, Any],
    config: DashboardConfig,
    range_key: str,
) -> DashboardPayload:
    if range_key not in RANGE_DEFINITIONS:
        raise ValueError(f"Unsupported range '{range_key}'")

    now_utc = datetime.fromtimestamp(snapshot["systemTime"]["msSinceEpoch"] / 1000, tz=timezone.utc)
    window_start, window_end = _range_window(now_utc, range_key)

    runs = snapshot["runs"].get("resources", [])
    events = snapshot["runEvents"].get("resources", [])
    captures = snapshot["runCaptures"].get("resources", [])
    anomalies = snapshot["anomalies"].get("resources", [])
    open_anomalies = snapshot["openAnomalies"].get("resources", [])
    warnings = list(snapshot.get("warnings", []))

    ranged_runs = [run for run in runs if (_parse_timestamp(run.get("startTime")) or now_utc) >= window_start and (_parse_timestamp(run.get("startTime")) or now_utc) < window_end]
    ranged_events = [event for event in events if (_event_time(event) or now_utc) >= window_start and (_event_time(event) or now_utc) < window_end]
    ranged_captures = [capture for capture in captures if (_capture_time(capture) or now_utc) >= window_start and (_capture_time(capture) or now_utc) < window_end]
    new_anomalies = [anomaly for anomaly in anomalies if (_parse_timestamp(anomaly.get("createdAt")) or now_utc) >= window_start and (_parse_timestamp(anomaly.get("createdAt")) or now_utc) < window_end]
    closed_in_range = [
        anomaly
        for anomaly in anomalies
        if (anomaly.get("status") or "").lower() == "closed"
        and (
            _parse_timestamp(anomaly.get("statusModifiedAt"))
            or datetime.min.replace(tzinfo=timezone.utc)
        ) >= window_start
        and (
            _parse_timestamp(anomaly.get("statusModifiedAt"))
            or datetime.min.replace(tzinfo=timezone.utc)
        ) < window_end
    ]

    latest_activity = max(
        [timestamp for timestamp in (
            *(_activity_time_for_run(run) for run in runs),
            *(_event_time(event) for event in events),
            *(_capture_time(capture) for capture in captures),
        ) if timestamp is not None],
        default=None,
    )

    status_counts = Counter(_normalize_status(run.get("missionStatus")) for run in ranged_runs)
    trend_statuses = [
        StatusCount(status=status, label=STATUS_LABELS[status], count=status_counts.get(status, 0))
        for status in STATUS_LABELS
    ]

    recent_runs = [
        RecentRun(
            uuid=str(run.get("uuid") or ""),
            missionName=run.get("missionName") or FALLBACK_MISSION_NAME,
            startTime=_to_iso(_parse_timestamp(run.get("startTime"))),
            endTime=_to_iso(_parse_timestamp(run.get("endTime"))),
            status=_normalize_status(run.get("missionStatus")),
            statusLabel=STATUS_LABELS[_normalize_status(run.get("missionStatus"))],
            actionCount=int(run.get("actionCount") or 0),
        )
        for run in _sort_desc(ranged_runs, _activity_time_for_run)[:10]
    ]

    recent_events = [
        RecentEvent(
            uuid=str(event.get("uuid") or ""),
            runUuid=event.get("runUuid"),
            missionName=event.get("missionName"),
            actionName=event.get("actionName"),
            eventType=event.get("eventType"),
            time=_to_iso(_event_time(event)),
            captureCount=len(event.get("dataCaptures") or []),
            error=event.get("error"),
        )
        for event in _sort_desc(ranged_events, _event_time)[:10]
    ]

    recent_anomalies = [
        RecentAnomaly(
            uuid=str(anomaly.get("uuid") or ""),
            title=anomaly.get("title") or anomaly.get("name") or FALLBACK_ISSUE_TITLE,
            status=(anomaly.get("status") or "unknown").lower(),
            severity=anomaly.get("severity"),
            createdAt=_to_iso(_parse_timestamp(anomaly.get("createdAt"))),
            time=_to_iso(_parse_timestamp(anomaly.get("time"))),
            source=anomaly.get("source"),
        )
        for anomaly in _sort_desc(anomalies, lambda item: _parse_timestamp(item.get("createdAt")) or _parse_timestamp(item.get("time")))[:5]
    ]

    payload = DashboardPayload(
        generatedAt=_to_iso(now_utc) or "",
        range=range_key,
        summary=SummaryMetrics(
            robotStatus=_derive_robot_status(runs, events, captures, now_utc),
            lastActivityAt=_to_iso(latest_activity),
            runs=len(ranged_runs),
            successfulRuns=sum(1 for run in ranged_runs if (run.get("missionStatus") or "").upper() == "SUCCESS"),
            dataCaptures=len(ranged_captures),
            openAnomalies=len(open_anomalies),
        ),
        trends=TrendSeries(
            runsByBucket=_build_buckets(
                (_parse_timestamp(run.get("startTime")) for run in ranged_runs if _parse_timestamp(run.get("startTime"))),
                window_start,
                window_end,
                range_key,
                config.timezone,
            ),
            capturesByBucket=_build_buckets(
                (_capture_time(capture) for capture in ranged_captures if _capture_time(capture)),
                window_start,
                window_end,
                range_key,
                config.timezone,
            ),
            eventsByBucket=_build_buckets(
                (_event_time(event) for event in ranged_events if _event_time(event)),
                window_start,
                window_end,
                range_key,
                config.timezone,
            ),
            missionStatusMix=trend_statuses,
        ),
        recentRuns=recent_runs,
        recentEvents=recent_events,
        anomalies=AnomalySnapshot(
            openCount=len(open_anomalies),
            closedInRange=len(closed_in_range),
            newInRange=len(new_anomalies),
            recent=recent_anomalies,
        ),
        warnings=warnings,
    )

    return payload
