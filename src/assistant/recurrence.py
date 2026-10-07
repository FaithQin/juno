"""Repeat rules for the events juno adds (Faith, 2026-10-06: "fix that" after juno said it couldn't).

Google takes a repeating event as one event plus an RFC 5545 rule, e.g. `RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=…`.
The model never writes that rule: it passes plain fields (repeat="weekly", days=["mon", "wed"],
until="2026-11-19") and this module checks them and builds the rule, so a typo can't become a
calendar full of wrong events.

Every repeat ends. Without an end date or a count it stops at the end of the quarter the first
occurrence falls in (her choice; the dates are `calendar.quarter_ends` in assistant.yaml), and if
juno doesn't know that quarter it asks instead of repeating forever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

FREQS = {"daily": ("DAILY", "day"), "weekly": ("WEEKLY", "week"), "monthly": ("MONTHLY", "month"), "yearly": ("YEARLY", "year")}
ORDER = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]               # index = date.weekday()
WORDS = {"MO": "mon", "TU": "tue", "WE": "wed", "TH": "thu", "FR": "fri", "SA": "sat", "SU": "sun"}
NAMES = {"mo": "MO", "mon": "MO", "monday": "MO", "tu": "TU", "tue": "TU", "tues": "TU", "tuesday": "TU",
         "we": "WE", "wed": "WE", "weds": "WE", "wednesday": "WE", "th": "TH", "thu": "TH", "thur": "TH",
         "thurs": "TH", "thursday": "TH", "fr": "FR", "fri": "FR", "friday": "FR", "sa": "SA", "sat": "SA",
         "saturday": "SA", "su": "SU", "sun": "SU", "sunday": "SU"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ASK_END = "how long should it repeat? give an end date (until) or a number of times (count)"


@dataclass(frozen=True)
class Repeat:
    freq: str                     # "WEEKLY"
    unit: str                     # "week", for the words
    every: int
    days: tuple[str, ...]         # ("MO", "WE"), weekly only
    until: date | None            # the last day it may happen, inclusive
    count: int | None
    quarter_end: bool = False     # until was filled in from the quarter's end


def plan(*, repeat: str, every: int | None, days, until: str | None, count: int | None) -> Repeat | str:
    """Check her repeat. A string is what to tell her instead."""
    key = (repeat or "").strip().lower()
    if key not in FREQS:
        return "error: repeat must be daily, weekly, monthly or yearly"
    freq, unit = FREQS[key]
    every = 1 if every is None else int(every)
    if every < 1:
        return "error: every must be 1 or more"
    codes: tuple[str, ...] = ()
    if days:
        if freq != "WEEKLY":
            return "error: days only go with a weekly repeat"
        raw = days.split(",") if isinstance(days, str) else list(days)
        found = [NAMES.get(str(d).strip().lower().rstrip(".")) for d in raw if str(d).strip()]
        if not found or None in found:
            return "error: days must be weekdays like mon, tue, wed"
        codes = tuple(sorted(set(found), key=ORDER.index))
    if until and count:
        return "error: give an end date (until) or a number of times (count), not both"
    if count is not None and int(count) < 1:
        return "error: count must be 1 or more"
    last = None
    if until:
        if not DATE_RE.match(until.strip()):
            return "error: until must be an ISO date like 2026-12-11"
        last = date.fromisoformat(until.strip())
    return Repeat(freq, unit, every, codes, last, int(count) if count else None)


def first_on(start: date, days: tuple[str, ...]) -> date:
    """The first date on or after `start` that falls on one of the days (Google would otherwise
    count the start itself as an occurrence even when it isn't one of them)."""
    if not days:
        return start
    d = start
    while ORDER[d.weekday()] not in days:
        d += timedelta(days=1)
    return d


def finish(rep: Repeat, first: date, quarter_ends: list[date]) -> Repeat | str:
    """Fill in the end of the quarter when she gave no end; refuse an end before the first one."""
    if rep.until is None and rep.count is None:
        end = next((q for q in sorted(quarter_ends) if q >= first), None)
        if end is None:
            return ASK_END
        rep = Repeat(rep.freq, rep.unit, rep.every, rep.days, end, None, quarter_end=True)
    if rep.until is not None and rep.until < first:
        return f"error: until is before the first one ({first.strftime('%a %b %-d').lower()})"
    return rep


def rrule(rep: Repeat, *, all_day: bool, tz: ZoneInfo) -> str:
    parts = [f"FREQ={rep.freq}"]
    if rep.every > 1:
        parts.append(f"INTERVAL={rep.every}")
    if rep.days:
        parts.append("BYDAY=" + ",".join(rep.days))
    if rep.until is not None:
        if all_day:
            parts.append(f"UNTIL={rep.until.strftime('%Y%m%d')}")
        else:   # a timed event's UNTIL is a UTC instant: the end of that day where she is
            last = datetime.combine(rep.until, time(23, 59, 59), tzinfo=tz).astimezone(timezone.utc)
            parts.append(f"UNTIL={last.strftime('%Y%m%dT%H%M%SZ')}")
    elif rep.count is not None:
        parts.append(f"COUNT={rep.count}")
    return "RRULE:" + ";".join(parts)


def describe(rep: Repeat) -> str:
    """'every 2 weeks on mon, wed, 6 times' / 'every week until fri dec 11, the end of the quarter'."""
    words = f"every {rep.unit}" if rep.every == 1 else f"every {rep.every} {rep.unit}s"
    if rep.days:
        words += " on " + ", ".join(WORDS[d] for d in rep.days)
    if rep.until is not None:
        words += f" until {rep.until.strftime('%a %b %-d').lower()}"
        if rep.quarter_end:
            words += ", the end of the quarter"
    elif rep.count is not None:
        words += f", {rep.count} times"
    return words
