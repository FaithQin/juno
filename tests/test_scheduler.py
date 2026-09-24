"""The scheduler registers exactly the three jobs, at the configured times."""

from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from assistant.config import AppConfig
from assistant.scheduler import build_scheduler


async def noop():
    return None


def test_build_scheduler_registers_sync_nudges_and_brief():
    cfg = AppConfig.model_validate({"brief": {"time": "07:00"}, "nudges": {"scan_minutes": 10}, "sync": {"every_minutes": 60}})
    sched = build_scheduler(cfg, ZoneInfo("America/Los_Angeles"), sync=noop, nudges=noop, brief=noop)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert set(jobs) == {"sync", "nudges", "brief"}
    assert isinstance(jobs["sync"].trigger, IntervalTrigger) and jobs["sync"].trigger.interval.total_seconds() == 3600
    assert isinstance(jobs["nudges"].trigger, IntervalTrigger) and jobs["nudges"].trigger.interval.total_seconds() == 600
    assert isinstance(jobs["brief"].trigger, CronTrigger)
    assert "hour='7'" in str(jobs["brief"].trigger) and "minute='0'" in str(jobs["brief"].trigger)
    # coalesce / max_instances come from job_defaults and are applied when the scheduler starts


def test_browser_idle_job_is_optional():
    cfg = AppConfig()
    sched = build_scheduler(cfg, ZoneInfo("America/Los_Angeles"), sync=noop, nudges=noop, brief=noop, browser_idle=noop)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert "browser_idle" in jobs and jobs["browser_idle"].trigger.interval.total_seconds() == 300


def test_gradescope_job_runs_every_few_hours():
    cfg = AppConfig.model_validate({"gradescope": {"every_hours": 3}})
    sched = build_scheduler(cfg, ZoneInfo("America/Los_Angeles"), sync=noop, nudges=noop, brief=noop, gradescope=noop)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert jobs["gradescope"].trigger.interval.total_seconds() == 3 * 3600


def test_calendar_job_runs_hourly_by_default():
    cfg = AppConfig()
    sched = build_scheduler(cfg, ZoneInfo("America/Los_Angeles"), sync=noop, nudges=noop, brief=noop, calendar=noop)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert jobs["calendar"].trigger.interval.total_seconds() == 3600
