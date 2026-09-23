"""Morning brief: deterministic, no LLM."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from assistant.brief import Event, format_brief
from assistant.reminders import DueTask

TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)   # Wed Sep 23, 7:00am Pacific


def ev(title, h, m=0, end_h=None, location=None, all_day=False):
    start = datetime(2026, 9, 23, h, m, tzinfo=TZ)
    end = datetime(2026, 9, 23, end_h, 0, tzinfo=TZ) if end_h else None
    return Event(title=title, start=start, end=end, location=location, all_day=all_day, calendar="Stanford")


def test_brief_lists_events_in_order_with_short_locations():
    events = [
        ev("ENGR 40M", 15, end_h=16, location="William R. Hewlett Teaching Center, Room 201, 370 Jane Stanford Way"),
        ev("CME 102 MATLAB Tutorial (TA Yifa Yu)", 13, location="Wallenberg Hall, 450 Jane Stanford Way #B40"),
        ev("Democracy Day", 0, all_day=True),
    ]
    text = format_brief(now=NOW, tz=TZ, events=events, due_today=[], due_tomorrow=[], overdue=[])
    lines = text.splitlines()
    assert lines[0] == "morning. wed sep 23"
    assert lines[1] == "today"
    assert lines[2] == "  all day · Democracy Day"
    assert lines[3] == "  1:00pm · CME 102 MATLAB Tutorial (TA Yifa Yu) · Wallenberg Hall"
    assert lines[4] == "  3:00–4:00pm · ENGR 40M · William R. Hewlett Teaching Center"
    assert lines[5] == "nothing due today or tomorrow"


def test_brief_lists_due_and_overdue():
    due = DueTask("T1", "ENGR 40M: Sign up for a lab section", datetime(2026, 9, 23, 19, 0, tzinfo=timezone.utc), 4)
    tomorrow = DueTask("T2", "ENGR 40M quizzes 2–8", datetime(2026, 9, 25, 6, 59, tzinfo=timezone.utc), 1)
    over = DueTask("T3", "CME 102: Find HW due dates", datetime(2026, 9, 21, 19, 0, tzinfo=timezone.utc), 1)  # Mon Sep 21 noon Pacific
    text = format_brief(now=NOW, tz=TZ, events=[], due_today=[due], due_tomorrow=[tomorrow], overdue=[over])
    assert text.splitlines() == [
        "morning. wed sep 23",
        "today",
        "  no events",
        "due today",
        "  - 12:00pm · ENGR 40M: Sign up for a lab section",
        "due tomorrow",
        "  - 11:59pm · ENGR 40M quizzes 2–8",
        "overdue",
        "  - CME 102: Find HW due dates (mon)",
    ]
