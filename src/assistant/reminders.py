"""Due-date nudges: 8:00pm the evening before ("eve"), 2 hours before ("2h"), plus snoozes.

Pure planning, like the sync: `plan_nudges()` decides what fires *now* given
what was already sent; the caller sends and records. Rules from DECISIONS.md:
every nudge has an idempotency key so retries never double-send; a nudge that
is late because juno was offline is still sent but says so; a task that didn't
exist yet at the intended time isn't "late"; date-only tasks get the eve nudge
but no 2h nudge, since there is no clock time to count from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

EVE_HOUR = 20
LATE_AFTER = timedelta(minutes=30)


@dataclass(frozen=True)
class DueTask:
    task_id: str
    content: str
    due_at: datetime            # aware; for date-only tasks, local 11:59pm on that date
    priority: int = 1           # Todoist API scale: 1 normal … 4 urgent (p1)
    course: str | None = None
    created_at: datetime | None = None   # a nudge can't be "late" for a task that didn't exist yet
    has_time: bool = True


@dataclass(frozen=True)
class Nudge:
    key: str                    # idempotency key, e.g. "T1:eve"
    task: DueTask
    kind: str                   # "eve" | "2h" | "snooze"
    intended_at: datetime       # when it should have fired
    late: bool


def eve_before(due: datetime, tz: ZoneInfo) -> datetime:
    local = due.astimezone(tz)
    return (local - timedelta(days=1)).replace(hour=EVE_HOUR, minute=0, second=0, microsecond=0)


def plan_nudges(tasks: list[DueTask], *, now: datetime, tz: ZoneInfo, sent: set[str],
                snoozes: dict[str, datetime], late_after: timedelta = LATE_AFTER) -> list[Nudge]:
    out: list[Nudge] = []
    for t in tasks:
        if t.due_at <= now:
            continue  # overdue items belong in the morning brief, not in nudges

        at = snoozes.get(t.task_id)
        if at is not None and at <= now:
            key = f"{t.task_id}:snooze:{at.isoformat()}"
            if key not in sent:
                out.append(Nudge(key, t, "snooze", at, now - at > late_after))

        within_2h = now >= t.due_at - timedelta(hours=2)
        schedule = [("eve", eve_before(t.due_at, tz))]
        if t.has_time:
            schedule.append(("2h", t.due_at - timedelta(hours=2)))

        for kind, intended in schedule:
            if t.created_at is not None and t.created_at > intended:
                intended = t.created_at
            if now < intended:
                continue
            if kind == "eve" and within_2h and t.has_time:
                continue  # the 2h nudge says it better
            key = f"{t.task_id}:{kind}"
            if key in sent:
                continue
            out.append(Nudge(key, t, kind, intended, now - intended > late_after))
    return out


# --------------------------------------------------------------------------
# wording (juno's voice: lowercase, short; task names stay as they are)
# --------------------------------------------------------------------------

def _time(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%-I:%M%p").lower()


def _day_time(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%a %-I:%M%p").lower()


def _due_stamp(t: DueTask, tz: ZoneInfo) -> str:
    return _day_time(t.due_at, tz) if t.has_time else t.due_at.astimezone(tz).strftime("%a").lower()


def _relative(due: datetime, now: datetime) -> str:
    left = due - now
    hours = int(left.total_seconds() // 3600)
    if hours >= 1:
        return f"due in {hours}h"
    minutes = max(1, int(left.total_seconds() // 60))
    return f"due in {minutes}m"


def _header(n: Nudge, now: datetime, tz: ZoneInfo) -> str:
    if n.kind in ("2h", "snooze") and n.task.has_time:
        return _relative(n.task.due_at, now)
    due_local = n.task.due_at.astimezone(tz)
    today = now.astimezone(tz).date()
    day = due_local.date()
    when = "today" if day == today else "tomorrow" if day == today + timedelta(days=1) else due_local.strftime("%a").lower()
    return f"due {when} {_time(n.task.due_at, tz)}" if n.task.has_time else f"due {when}"


def format_nudges(nudges: list[Nudge], *, now: datetime, tz: ZoneInfo, offline_since: datetime | None) -> str:
    if not nudges:
        return ""
    lines: list[str] = []
    late = [n for n in nudges if n.late]
    if late:
        if offline_since is not None:
            lines.append(f"heads up, i was offline from {_day_time(offline_since, tz)} to {_day_time(now, tz)}, so this is late:")
        else:
            lines.append(f"heads up, this should have gone out at {_day_time(late[0].intended_at, tz)}, so this is late:")

    if len(nudges) == 1:
        n = nudges[0]
        lines.append(f"{_header(n, now, tz)}: {n.task.content} ({_due_stamp(n.task, tz)})")
        return "\n".join(lines)

    groups: dict[str, list[Nudge]] = {}
    for n in nudges:
        groups.setdefault(_header(n, now, tz), []).append(n)
    for header, group in groups.items():
        lines.append(f"{header}:")
        lines.extend(f"- {n.task.content}" for n in group)
    return "\n".join(lines)
