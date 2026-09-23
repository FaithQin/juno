"""The 7:00 am brief. Deterministic: no model call, so it is cheap and never hallucinates.

Data stays as data (course codes and event titles keep their case); only
juno's own words are lowercase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .reminders import DueTask


@dataclass(frozen=True)
class Event:
    title: str
    start: datetime             # aware; for all-day events, local midnight
    end: datetime | None
    location: str | None
    all_day: bool
    calendar: str


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


def _due_line(t: DueTask, tz: ZoneInfo) -> str:
    return f"  - {_time(t.due_at, tz)} · {t.content}"


def format_brief(*, now: datetime, tz: ZoneInfo, events: list[Event], due_today: list[DueTask],
                 due_tomorrow: list[DueTask], overdue: list[DueTask]) -> str:
    local_now = now.astimezone(tz)
    lines = [f"morning. {local_now.strftime('%a %b %-d').lower()}", "today"]

    ordered = sorted(events, key=lambda e: (not e.all_day, e.start))
    lines.extend(_event_line(e, tz) for e in ordered) if ordered else lines.append("  no events")

    if due_today:
        lines.append("due today")
        lines.extend(_due_line(t, tz) for t in sorted(due_today, key=lambda t: t.due_at))
    if due_tomorrow:
        lines.append("due tomorrow")
        lines.extend(_due_line(t, tz) for t in sorted(due_tomorrow, key=lambda t: t.due_at))
    if not due_today and not due_tomorrow:
        lines.append("nothing due today or tomorrow")
    if overdue:
        lines.append("overdue")
        lines.extend(f"  - {t.content} ({t.due_at.astimezone(tz).strftime('%a').lower()})"
                     for t in sorted(overdue, key=lambda t: t.due_at))
    return "\n".join(lines)
