"""Reminder planner: which nudges fire now, and how late ones are worded.

Two nudges per task: "eve" at 8:00pm the day before it's due, and "2h" two
hours before. Plus snoozes the user asks for.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from assistant.reminders import DueTask, format_nudges, plan_nudges

TZ = ZoneInfo("America/Los_Angeles")
DUE = datetime(2026, 9, 26, 6, 59, tzinfo=timezone.utc)      # Fri Sep 25 11:59pm Pacific
EVE = datetime(2026, 9, 24, 20, 0, tzinfo=TZ)                 # Thu Sep 24 8:00pm Pacific


def task(task_id="T1", content="ENGR 40M quizzes 2–8", due=DUE, priority=1, created=None):
    return DueTask(task_id=task_id, content=content, due_at=due, priority=priority, created_at=created)


def plan(tasks, now, sent=None, snoozes=None):
    return plan_nudges(tasks, now=now, tz=TZ, sent=sent or set(), snoozes=snoozes or {})


def test_eve_nudge_fires_at_8pm_the_day_before_once():
    now = EVE + timedelta(minutes=5)
    nudges = plan([task()], now)
    assert [(n.kind, n.task.task_id, n.late) for n in nudges] == [("eve", "T1", False)]
    assert nudges[0].key == "T1:eve" and nudges[0].intended_at == EVE
    assert plan([task()], now, sent={"T1:eve"}) == []


def test_nothing_fires_before_the_window_or_after_due():
    assert plan([task()], EVE - timedelta(hours=1)) == []
    assert plan([task()], DUE + timedelta(minutes=1)) == []


def test_2h_window_suppresses_the_eve_nudge():
    now = DUE - timedelta(hours=1, minutes=30)
    assert [n.kind for n in plan([task()], now)] == ["2h"]


def test_late_nudge_is_flagged_not_skipped():
    now = DUE - timedelta(hours=9)             # Fri 2:59pm; eve nudge was due Thu 8pm
    nudges = plan([task()], now)
    assert [(n.kind, n.late, n.intended_at) for n in nudges] == [("eve", True, EVE)]


def test_task_created_after_the_eve_mark_is_not_late():
    created = datetime(2026, 9, 25, 19, 0, tzinfo=TZ)   # Fri 7pm, due 11:59pm that night
    nudges = plan([task(created=created)], created + timedelta(minutes=5))
    assert [(n.kind, n.late, n.intended_at) for n in nudges] == [("eve", False, created)]


def test_task_created_inside_the_2h_window_is_not_late():
    created = DUE - timedelta(hours=1, minutes=5)
    nudges = plan([task(created=created)], DUE - timedelta(hours=1))
    assert [(n.kind, n.late, n.intended_at) for n in nudges] == [("2h", False, created)]


def test_snooze_fires_at_its_time_once():
    at = DUE - timedelta(hours=5)
    sent = {"T1:eve"}  # a snooze only exists because a nudge already went out
    nudges = plan([task()], at + timedelta(minutes=2), sent=sent, snoozes={"T1": at})
    assert [n.kind for n in nudges] == ["snooze"]
    assert nudges[0].key == f"T1:snooze:{at.isoformat()}"
    assert plan([task()], at - timedelta(minutes=2), sent=sent, snoozes={"T1": at}) == []


def test_format_groups_nudges_and_explains_lateness():
    now = DUE - timedelta(hours=9)
    late = plan([task()], now)
    text = format_nudges(late, now=now, tz=TZ, offline_since=now - timedelta(hours=6))
    assert text.startswith("heads up, i was offline from fri 8:59am to fri 2:59pm, so this is late:")
    assert text.endswith("due today 11:59pm: ENGR 40M quizzes 2–8 (fri 11:59pm)")

    at = DUE - timedelta(hours=1, minutes=55)   # five minutes after the 2h mark: on time
    soon = plan([task()], at)
    assert format_nudges(soon, now=at, tz=TZ, offline_since=None) == \
        "due in 1h: ENGR 40M quizzes 2–8 (fri 11:59pm)"

    at = EVE + timedelta(minutes=5)
    two = plan([task(), task("T2", "CS 106B: Assignment 1")], at)
    assert format_nudges(two, now=at, tz=TZ, offline_since=None).splitlines() == [
        "due tomorrow 11:59pm:",
        "- ENGR 40M quizzes 2–8",
        "- CS 106B: Assignment 1",
    ]


def test_date_only_task_gets_only_the_eve_nudge_without_a_clock_time():
    # "Sep 25" with no time: due_at is local end of day, has_time is False
    t = DueTask("T5", "ENGR 40M: Lab safety training", DUE, has_time=False)
    assert plan([t], EVE + timedelta(minutes=5)) and plan([t], EVE + timedelta(minutes=5))[0].kind == "eve"
    assert plan([t], DUE - timedelta(hours=1), sent={"T5:eve"}) == []   # no 2h nudge once eve went out
    text = format_nudges(plan([t], EVE + timedelta(minutes=5)), now=EVE + timedelta(minutes=5), tz=TZ, offline_since=None)
    assert text == "due tomorrow: ENGR 40M: Lab safety training (fri)"
