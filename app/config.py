from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


RANGE_OPTIONS = ("24h", "7d", "30d")


def _load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()

        key, separator, value = line.partition("=")
        if not separator:
            continue

        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def _env_flag(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DashboardConfig:
    orbit_host: str | None
    orbit_api_token: str | None
    orbit_verify_tls: bool | str
    orbit_cert_path: str | None
    timezone: str
    dashboard_refresh_seconds: int
    dashboard_cache_ttl_seconds: int
    dashboard_bind_host: str
    dashboard_port: int
    fixture_mode: bool
    fixture_dir: Path
    default_range: str
    orbit_item_limit: int


def load_config() -> DashboardConfig:
    repo_root = Path(__file__).resolve().parents[1]
    env_file = Path(os.getenv("DASHBOARD_ENV_FILE", str(repo_root / ".env")))
    _load_dotenv(env_file)

    verify_value = os.getenv("ORBIT_VERIFY_TLS", "true").strip()
    if verify_value.lower() in {"true", "false"}:
        verify_setting: bool | str = verify_value.lower() == "true"
    else:
        verify_setting = verify_value

    default_range = os.getenv("DASHBOARD_DEFAULT_RANGE", "7d")
    if default_range not in RANGE_OPTIONS:
        default_range = "7d"

    return DashboardConfig(
        orbit_host=os.getenv("ORBIT_HOST"),
        orbit_api_token=os.getenv("ORBIT_API_TOKEN"),
        orbit_verify_tls=verify_setting,
        orbit_cert_path=os.getenv("ORBIT_CERT_PATH"),
        timezone=os.getenv("TIMEZONE", "UTC"),
        dashboard_refresh_seconds=max(int(os.getenv("DASHBOARD_REFRESH_SECONDS", "60")), 15),
        dashboard_cache_ttl_seconds=max(
            int(os.getenv("DASHBOARD_CACHE_TTL_SECONDS", "30")),
            5,
        ),
        dashboard_bind_host=os.getenv("DASHBOARD_BIND_HOST", "0.0.0.0"),
        dashboard_port=int(os.getenv("DASHBOARD_PORT", "8080")),
        fixture_mode=_env_flag("ORBIT_USE_FIXTURES", False),
        fixture_dir=Path(os.getenv("ORBIT_FIXTURE_DIR", "fixtures/orbit")),
        default_range=default_range,
        orbit_item_limit=max(int(os.getenv("ORBIT_ITEM_LIMIT", "500")), 20),
    )
