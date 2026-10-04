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
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

EVE_HOUR = 20
LATE_AFTER = timedelta(minutes=30)
HEADS_UP = timedelta(minutes=10)    # planned work: one text this long before it starts (Faith, 2026-10-03)


@dataclass(frozen=True)
class DueTask:
    task_id: str
    content: str
    due_at: datetime            # aware; for date-only tasks, local 11:59pm on that date
    priority: int = 1           # Todoist API scale: 1 normal … 4 urgent (p1)
    course: str | None = None
    created_at: datetime | None = None   # a nudge can't be "late" for a task that didn't exist yet
    has_time: bool = True
    kind: str = "due"           # "due": the date is a deadline. "planned": the date is when she'll do it
    duration_min: int | None = None      # Todoist duration, for planned work
    deadline: date | None = None         # Todoist's deadline field: the real due date of planned work


@dataclass(frozen=True)
class Nudge:
    key: str                    # idempotency key, e.g. "T1:eve"
    task: DueTask
    kind: str                   # "eve" | "2h" | "snooze" | "start" (planned work about to begin)
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

        if t.kind == "planned":    # work time, not a deadline: one heads-up before it starts, nothing else
            if not t.has_time:
                continue
            intended = t.due_at - HEADS_UP
            if t.created_at is not None and t.created_at > intended:
                intended = t.created_at
            key = f"{t.task_id}:start:{t.due_at.isoformat()}"   # per occurrence: recurring blocks keep their id
            if now >= intended and key not in sent:
                out.append(Nudge(key, t, "start", intended, now - intended > late_after))
            continue

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


def duration_words(minutes: int) -> str:
    hours, rest = divmod(int(minutes), 60)
    if not hours:
        return f"{rest}m"
    return f"{hours}h {rest}m" if rest else f"{hours}h"


def deadline_words(d: date, *, today: date) -> str:
    """'today', 'tomorrow', 'thu' within the week, 'oct 20' beyond it, 'was wed sep 30' once passed."""
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    if today < d <= today + timedelta(days=6):
        return d.strftime("%a").lower()
    if d < today:
        return "was " + d.strftime("%a %b %-d").lower()
    return d.strftime("%b %-d").lower()


def planned_tail(t: DueTask, *, today: date, label: bool = False) -> str:
    """' (1h · deadline thu)' for planned work; with `label`, ' (planned · 1h · …)'."""
    bits = ["planned"] if label else []
    if t.duration_min:
        bits.append(duration_words(t.duration_min))
    if t.deadline:
        bits.append(f"deadline {deadline_words(t.deadline, today=today)}")
    return f" ({' · '.join(bits)})" if bits else ""


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
    if n.kind == "start":
        return f"starting {_time(n.task.due_at, tz)}"
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

    today = now.astimezone(tz).date()
    if len(nudges) == 1:
        n = nudges[0]
        if n.kind == "start":
            lines.append(f"{_header(n, now, tz)}: {n.task.content}{planned_tail(n.task, today=today)}")
        else:
            lines.append(f"{_header(n, now, tz)}: {n.task.content} ({_due_stamp(n.task, tz)})")
        return "\n".join(lines)

    groups: dict[str, list[Nudge]] = {}
    for n in nudges:
        groups.setdefault(_header(n, now, tz), []).append(n)
    for header, group in groups.items():
        lines.append(f"{header}:")
        lines.extend(f"- {n.task.content}" + (planned_tail(n.task, today=today) if n.kind == "start" else "") for n in group)
    return "\n".join(lines)
