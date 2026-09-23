"""The three scheduled jobs. Each takes its collaborators as arguments so tests can pass fakes.

Blocking network calls (Todoist, Google, Canvas) run in a worker thread via
`asyncio.to_thread` so Telegram polling never stalls.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from .brief import format_brief
from .chat_ops import ChatOps
from .db import Store
from .reminders import format_nudges, plan_nudges
from .sync import Report, format_report

Send = Callable[[str], Awaitable[None]]
log = logging.getLogger(__name__)


async def run_nudges_job(ops: ChatOps, store: Store, *, send: Send, now: datetime | None = None,
                         scan_interval: timedelta = timedelta(minutes=10)) -> None:
    now = now or ops.now()

    offline_since = None
    last = store.kv_get("last_scan")
    if last:
        last_dt = datetime.fromisoformat(last)
        if now - last_dt > scan_interval * 3:
            offline_since = last_dt   # we missed at least two scans: say so in any late nudge

    tasks = await asyncio.to_thread(ops.due_tasks)
    nudges = plan_nudges(tasks, now=now, tz=ops.tz, sent=store.sent_nudges(), snoozes=store.snoozes())
    if nudges:
        await send(format_nudges(nudges, now=now, tz=ops.tz, offline_since=offline_since))
        for n in nudges:
            store.mark_nudge(n.key, at=now)
            if n.kind == "snooze":
                store.clear_snooze(n.task.task_id)
    store.kv_set("last_scan", now.isoformat(timespec="seconds"))


OVERDUE_WINDOW = timedelta(days=7)   # older overdue items are noise; they're still in Todoist


async def run_brief_job(ops: ChatOps, *, send: Send, now: datetime | None = None) -> None:
    now = now or ops.now()
    local = now.astimezone(ops.tz)
    today = local.date()
    start_of_today = local.replace(hour=0, minute=0, second=0, microsecond=0)

    events = []
    if ops.calendar is not None:
        try:
            events = await asyncio.to_thread(ops.calendar.events_for_day, ops.calendar_names, today, ops.tz)
        except Exception as e:
            log.warning("brief: calendar unavailable (%s: %s); sending tasks only", type(e).__name__, e)
    tasks = await asyncio.to_thread(ops.all_due_tasks)   # the brief covers every dated task (Faith's choice)

    def day_of(t):
        return t.due_at.astimezone(ops.tz).date()

    await send(format_brief(
        now=now, tz=ops.tz, events=events,
        due_today=[t for t in tasks if day_of(t) == today],
        due_tomorrow=[t for t in tasks if day_of(t) == today + timedelta(days=1)],
        overdue=[t for t in tasks if start_of_today - OVERDUE_WINDOW <= t.due_at < start_of_today],
    ))


async def run_sync_job(*, run: Callable[[], Report], send: Send) -> None:
    report = await asyncio.to_thread(run)
    if report.changed or report.errors:
        await send(format_report(report))
