"""The 7:00 am brief. Deterministic: no model call, so it is cheap and never hallucinates.

Data stays as data (course codes and event titles keep their case); only
juno's own words are lowercase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .reminders import DueTask, deadline_words, duration_words


@dataclass(frozen=True)
class Event:
    title: str
    start: datetime             # aware; for all-day events, local midnight
    end: datetime | None
    location: str | None
    all_day: bool
    calendar: str               # display name
    id: str | None = None       # Google event id (when it came from the API)
    calendar_id: str | None = None
    description: str | None = None
    canvas_id: int | None = None   # set when juno created it from a Canvas event
    color_id: str | None = None    # Google's event color id ("1".."11"); None = the calendar's color
    recurring_id: str | None = None   # the series this occurrence belongs to, if it repeats


def short_location(location: str | None) -> str | None:
    if not location:
        return None
    first = location.split(",")[0].strip()
    return first or None


def _time(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%-I:%M%p").lower()


def _span(ev: Event, tz: ZoneInfo) -> str:
    if ev.all_day:
        return "all day"
    if ev.end is None:
        return _time(ev.start, tz)
    start, end = ev.start.astimezone(tz), ev.end.astimezone(tz)
    if start.strftime("%p") == end.strftime("%p"):
        return f"{start.strftime('%-I:%M')}–{_time(ev.end, tz)}"
    return f"{_time(ev.start, tz)}–{_time(ev.end, tz)}"


def _event_line(ev: Event, tz: ZoneInfo) -> str:
    parts = [_span(ev, tz), ev.title]
    loc = short_location(ev.location)
    if loc:
        parts.append(loc)
    return "  " + " · ".join(parts)


def _day(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%a").lower()


def _due_line(t: DueTask, tz: ZoneInfo, audits) -> str:
    tag = " (audit)" if t.course in audits else ""
    if t.kind == "planned":   # planned another day, but its Todoist deadline falls here
        return f"  - deadline · {t.content}{tag} (planned {_day(t.due_at, tz)})"
    return f"  - {_time(t.due_at, tz)} · {t.content}{tag}"


def _planned_line(t: DueTask, tz: ZoneInfo, audits, today) -> str:
    bits = [_time(t.due_at, tz) if t.has_time else "any time"]
    if t.duration_min:
        bits.append(duration_words(t.duration_min))
    tail = f" (deadline {deadline_words(t.deadline, today=today)})" if t.deadline else ""
    tag = " (audit)" if t.course in audits else ""
    return "  - " + " · ".join(bits + [t.content]) + tag + tail


def format_brief(*, now: datetime, tz: ZoneInfo, events: list[Event], due_today: list[DueTask],
                 due_tomorrow: list[DueTask], overdue: list[DueTask], planned_today: list[DueTask] = (),
                 audits=frozenset()) -> str:
    """`due_*` are deadlines (including planned work whose Todoist deadline falls that day);
    `planned_today` is work she scheduled for today, which is not a deadline."""
    local_now = now.astimezone(tz)
    today = local_now.date()
    lines = [f"morning. {local_now.strftime('%a %b %-d').lower()}", "today"]

    ordered = sorted(events, key=lambda e: (not e.all_day, e.start))
    lines.extend(_event_line(e, tz) for e in ordered) if ordered else lines.append("  no events")

    def deadlines_first(t):
        return (t.kind == "planned", t.due_at)

    if due_today:
        lines.append("due today")
        lines.extend(_due_line(t, tz, audits) for t in sorted(due_today, key=deadlines_first))
    if planned_today:
        lines.append("planned today")
        lines.extend(_planned_line(t, tz, audits, today) for t in sorted(planned_today, key=lambda t: (not t.has_time, t.due_at)))
    if due_tomorrow:
        lines.append("due tomorrow")
        lines.extend(_due_line(t, tz, audits) for t in sorted(due_tomorrow, key=deadlines_first))
    if not due_today and not due_tomorrow:
        lines.append("nothing due today or tomorrow")
    if overdue:
        lines.append("overdue")
        for t in sorted(overdue, key=lambda t: t.due_at):
            tag = " (audit)" if t.course in audits else ""
            when = f"planned {_day(t.due_at, tz)}" if t.kind == "planned" else _day(t.due_at, tz)
            lines.append(f"  - {t.content}{tag} ({when})")
    return "\n".join(lines)
