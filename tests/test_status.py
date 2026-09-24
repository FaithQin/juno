"""/status: where juno is running and whether the background jobs are alive."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from assistant.status import describe_runtime

TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)   # wed 11:00am pacific


def test_describe_runtime_mentions_host_container_uptime_and_jobs():
    text = describe_runtime(
        hostname="juno", in_docker=True, version="0.1.0", started_at=NOW - timedelta(hours=2, minutes=3),
        now=NOW, tz=TZ, last_scan=NOW - timedelta(minutes=4), last_sync_at=NOW - timedelta(minutes=30), last_sync_ok=True,
    )
    assert text.splitlines() == [
        "running on juno in docker, v0.1.0, up 2h 3m",
        "last nudge scan 4m ago · last canvas sync 30m ago (ok)",
    ]


def test_describe_runtime_on_a_laptop_with_nothing_run_yet():
    text = describe_runtime(hostname="Faiths-MacBook-Pro", in_docker=False, version="0.1.0",
                            started_at=NOW - timedelta(seconds=40), now=NOW, tz=TZ,
                            last_scan=None, last_sync_at=None, last_sync_ok=None)
    assert text.splitlines() == [
        "running on Faiths-MacBook-Pro (not docker), v0.1.0, up 0m",
        "last nudge scan never · last canvas sync never",
    ]


def test_describe_runtime_shows_todays_model_usage_when_known():
    text = describe_runtime(hostname="juno", in_docker=True, version="0.1.0", started_at=NOW - timedelta(hours=1),
                            now=NOW, tz=TZ, last_scan=None, last_sync_at=None, last_sync_ok=None,
                            usage_today=(41, 1_234_567, 987_654))
    assert text.splitlines()[-1] == "model today: 41 requests, 1.2m tokens in, 80% from cache"
