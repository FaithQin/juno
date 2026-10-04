"""APScheduler wiring: three jobs on the same asyncio loop as Telegram.

`coalesce=True` and `max_instances=1` mean that if the laptop sleeps through
several scan times, one run happens on wake, not a burst; the reminder
planner then decides what is late.
"""

from __future__ import annotations

from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import AppConfig

Job = Callable[[], Awaitable[None]]


def build_scheduler(cfg: AppConfig, tz: ZoneInfo, *, sync: Job, nudges: Job, brief: Job,
                    browser_idle: Job | None = None, gradescope: Job | None = None,
                    calendar: Job | None = None, outlook: Job | None = None, course_watch: Job | None = None) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=tz, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    sched.add_job(sync, IntervalTrigger(minutes=cfg.sync.every_minutes, timezone=tz), id="sync", name="canvas → todoist")
    sched.add_job(nudges, IntervalTrigger(minutes=cfg.nudges.scan_minutes, timezone=tz), id="nudges", name="due-date nudges")
    hour, minute = cfg.brief.hour_minute
    sched.add_job(brief, CronTrigger(hour=hour, minute=minute, timezone=tz), id="brief", name="morning brief")
    if browser_idle is not None:
        sched.add_job(browser_idle, IntervalTrigger(minutes=5, timezone=tz), id="browser_idle", name="close idle browser page")
    if gradescope is not None:
        sched.add_job(gradescope, IntervalTrigger(hours=cfg.gradescope.every_hours, timezone=tz), id="gradescope", name="gradescope → todoist")
    if calendar is not None:
        sched.add_job(calendar, IntervalTrigger(minutes=cfg.calendar.every_minutes, timezone=tz), id="calendar", name="canvas events → calendar")
    if outlook is not None:
        sched.add_job(outlook, IntervalTrigger(minutes=cfg.outlook.every_minutes, timezone=tz), id="outlook", name="outlook → google calendar")
    if course_watch is not None:
        sched.add_job(course_watch, CronTrigger(hour=9, minute=30, timezone=tz), id="course_watch", name="class check")
    return sched
