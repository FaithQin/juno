"""/status: one glance at where juno runs and whether its background jobs are alive."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def _span(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _ago(at: datetime | None, now: datetime) -> str:
    return "never" if at is None else f"{_span(now - at)} ago"


def describe_runtime(*, hostname: str, in_docker: bool, version: str, started_at: datetime, now: datetime,
                     tz: ZoneInfo, last_scan: datetime | None, last_sync_at: datetime | None,
                     last_sync_ok: bool | None) -> str:
    where = "in docker" if in_docker else "(not docker)"
    sync = _ago(last_sync_at, now)
    if last_sync_at is not None:
        sync += " (ok)" if last_sync_ok else " (failed)"
    return "\n".join([
        f"running on {hostname} {where}, v{version}, up {_span(now - started_at)}",
        f"last nudge scan {_ago(last_scan, now)} · last canvas sync {sync}",
    ])
