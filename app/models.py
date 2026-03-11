from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RobotStatus:
    label: str
    detail: str
    lastActivityAt: str | None


@dataclass(frozen=True)
class SummaryMetrics:
    robotStatus: RobotStatus
    lastActivityAt: str | None
    runs: int
    successfulRuns: int
    dataCaptures: int
    openAnomalies: int


@dataclass(frozen=True)
class TimeBucket:
    bucketStart: str
    label: str
    count: int


@dataclass(frozen=True)
class StatusCount:
    status: str
    label: str
    count: int


@dataclass(frozen=True)
class TrendSeries:
    runsByBucket: list[TimeBucket]
    capturesByBucket: list[TimeBucket]
    eventsByBucket: list[TimeBucket]
    missionStatusMix: list[StatusCount]


@dataclass(frozen=True)
class RecentRun:
    uuid: str
    missionName: str
    startTime: str | None
    endTime: str | None
    status: str
    statusLabel: str
    actionCount: int


@dataclass(frozen=True)
class RecentEvent:
    uuid: str
    runUuid: str | None
    missionName: str | None
    actionName: str | None
    eventType: str | None
    time: str | None
    captureCount: int
    error: int | None


@dataclass(frozen=True)
class RecentAnomaly:
    uuid: str
    title: str
    status: str
    severity: int | None
    createdAt: str | None
    time: str | None
    source: str | None


@dataclass(frozen=True)
class AnomalySnapshot:
    openCount: int
    closedInRange: int
    newInRange: int
    recent: list[RecentAnomaly]


@dataclass(frozen=True)
class DashboardPayload:
    generatedAt: str
    range: str
    summary: SummaryMetrics
    trends: TrendSeries
    recentRuns: list[RecentRun]
    recentEvents: list[RecentEvent]
    anomalies: AnomalySnapshot
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
