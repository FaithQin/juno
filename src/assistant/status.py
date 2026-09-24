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


def _count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def describe_runtime(*, hostname: str, in_docker: bool, version: str, started_at: datetime, now: datetime,
                     tz: ZoneInfo, last_scan: datetime | None, last_sync_at: datetime | None,
                     last_sync_ok: bool | None, usage_today: tuple[int, int, int] | None = None) -> str:
    """`usage_today` is (model requests, input tokens, input tokens served from the provider's cache)."""
    where = "in docker" if in_docker else "(not docker)"
    sync = _ago(last_sync_at, now)
    if last_sync_at is not None:
        sync += " (ok)" if last_sync_ok else " (failed)"
    lines = [
        f"running on {hostname} {where}, v{version}, up {_span(now - started_at)}",
        f"last nudge scan {_ago(last_scan, now)} · last canvas sync {sync}",
    ]
    if usage_today is not None:
        requests, tokens_in, cached = usage_today
        pct = round(100 * cached / tokens_in) if tokens_in else 0
        lines.append(f"model today: {requests} requests, {_count(tokens_in)} tokens in, {pct}% from cache")
    return "\n".join(lines)
