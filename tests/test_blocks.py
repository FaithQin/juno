"""Planned work vs. real deadlines (Faith, 2026-10-03: "differentiate due dates and scheduled work block due").

Her Todoist already says which is which: a task with a duration (e.g. "CME 102 Pset 2: work block",
1h) or with Todoist's own deadline field is *planned* work, and its date is when she'll do it. Tasks
a sync tracks (Canvas, Gradescope) are real deadlines whatever else they carry.
"""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from assistant.brief import format_brief
from assistant.reminders import DueTask, deadline_words, duration_words, format_nudges, plan_nudges
from assistant.tasks import due_task_from
from fakes import FakeDue, FakeTask
from test_chat_ops import make_ops

TZ = ZoneInfo("America/Los_Angeles")
SAT = date(2026, 10, 3)


def at(day, h, m=0):
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


def task(id, content, due, *, minutes=None, deadline=None, project="P-CME"):
    return FakeTask(id, content, FakeDue(due), 1, None, project,
                    duration=SimpleNamespace(amount=minutes, unit="minute") if minutes else None,
                    deadline=SimpleNamespace(date=deadline) if deadline else None)


def test_planned_work_is_told_apart_from_deadlines():
    block = due_task_from(task("B", "CME 102 Pset 2: work block", at(3, 15), minutes=60, deadline=date(2026, 10, 8)), tz=TZ, sections={})
    assert (block.kind, block.duration_min, block.deadline) == ("planned", 60, date(2026, 10, 8))
    habit = due_task_from(task("H", "Get Clear", SAT, minutes=15), tz=TZ, sections={})
    assert (habit.kind, habit.duration_min, habit.has_time) == ("planned", 15, False)
    named = due_task_from(task("N", "CS 106B A1: work block 1 (Sat)", SAT), tz=TZ, sections={})
    assert named.kind == "planned"
    plain = due_task_from(task("D", "EE 100: Reflection", at(3, 23, 59)), tz=TZ, sections={})
    assert plain.kind == "due"
    tracked = due_task_from(task("G", "CME 102: Pset 2 (Gradescope)", at(8, 23, 59), minutes=90), tz=TZ, sections={}, tracked={"G"})
    assert tracked.kind == "due" and tracked.duration_min == 90                       # a sync's assignment is a deadline
    planned_assignment = due_task_from(task("P", "ENGR 40M: Lab 1 prelab (Gradescope)", at(4, 11), minutes=90, deadline=date(2026, 10, 5)),
                                       tz=TZ, sections={}, tracked={"P"})
    assert (planned_assignment.kind, planned_assignment.deadline) == ("planned", date(2026, 10, 5))   # her deadline field wins


def test_words_for_durations_and_deadlines():
    assert [duration_words(m) for m in (15, 60, 90, 120)] == ["15m", "1h", "1h 30m", "2h"]
    assert deadline_words(SAT, today=SAT) == "today" and deadline_words(date(2026, 10, 4), today=SAT) == "tomorrow"
    assert deadline_words(date(2026, 10, 8), today=SAT) == "thu" and deadline_words(date(2026, 10, 20), today=SAT) == "oct 20"
    assert deadline_words(date(2026, 9, 30), today=SAT) == "was wed sep 30"


def block(**kw):
    base = dict(task_id="B", content="CME 102 Pset 2: work block", due_at=at(3, 15), course="CME 102",
                created_at=at(1, 9), kind="planned", duration_min=60, deadline=date(2026, 10, 8))
    base.update(kw)
    return DueTask(**base)


def test_a_planned_block_gets_one_heads_up_ten_minutes_before_and_no_due_nudges():
    b = block()
    assert plan_nudges([b], now=at(2, 20, 5), tz=TZ, sent=set(), snoozes={}) == []          # no "due tomorrow" the night before
    assert plan_nudges([b], now=at(3, 13, 0), tz=TZ, sent=set(), snoozes={}) == []          # no "due in 2h"
    (n,) = plan_nudges([b], now=at(3, 14, 51), tz=TZ, sent=set(), snoozes={})
    assert (n.kind, n.key, n.late) == ("start", "B:start:2026-10-03T15:00:00-07:00", False)
    assert format_nudges([n], now=at(3, 14, 51), tz=TZ, offline_since=None) == "starting 3:00pm: CME 102 Pset 2: work block (1h · deadline thu)"
    assert plan_nudges([b], now=at(3, 14, 55), tz=TZ, sent={n.key}, snoozes={}) == []
    next_week = block(due_at=at(10, 15))                                                       # a recurring block: new date, new key
    assert plan_nudges([next_week], now=at(10, 14, 52), tz=TZ, sent={n.key}, snoozes={})[0].key == "B:start:2026-10-10T15:00:00-07:00"
    assert plan_nudges([block(due_at=datetime.combine(SAT, datetime.min.time(), tzinfo=TZ).replace(hour=23, minute=59), has_time=False)],
                       now=at(3, 23, 50), tz=TZ, sent=set(), snoozes={}) == []                  # no time, no heads-up


def test_the_brief_separates_due_from_planned_and_surfaces_deadlines():
    due = DueTask("D", "EE 100: Reflection", at(3, 23, 59), course="EE 100")
    planned = block()
    habit = DueTask("H", "Get Clear", at(3, 23, 59), kind="planned", duration_min=15, has_time=False)
    writeup = DueTask("W", "Write-up: §1 + §3", at(4, 23, 59), kind="planned", deadline=SAT, has_time=False)
    audit = DueTask("A", "EE 227: HW1 (Gradescope)", at(4, 17), course="EE 227")
    late_due = DueTask("L", "CME 102: Find HW due dates", at(2, 23, 59), course="CME 102", has_time=False)
    late_plan = DueTask("P", "wash clothes", at(2, 23, 59), kind="planned", duration_min=10, has_time=False)
    text = format_brief(now=at(3, 7), tz=TZ, events=[], due_today=[due, writeup], planned_today=[planned, habit],
                        due_tomorrow=[audit], overdue=[late_due, late_plan], audits={"EE 227"})
    assert text.splitlines() == [
        "morning. sat oct 3", "today", "  no events",
        "due today", "  - 11:59pm · EE 100: Reflection", "  - deadline · Write-up: §1 + §3 (planned sun)",
        "planned today", "  - 3:00pm · 1h · CME 102 Pset 2: work block (deadline thu)", "  - any time · 15m · Get Clear",
        "due tomorrow", "  - 5:00pm · EE 227: HW1 (Gradescope) (audit)",
        "overdue", "  - CME 102: Find HW due dates (fri)", "  - wash clothes (planned fri)",
    ]


def test_the_brief_job_sorts_tasks_into_due_planned_and_deadlines(tmp_path):
    import asyncio
    from assistant.jobs import run_brief_job

    tasks = [task("B", "CME 102 Pset 2: work block", at(3, 15), minutes=60, deadline=date(2026, 10, 8)),
             task("W", "Write-up: §1 + §3", date(2026, 10, 4), minutes=30, deadline=SAT, project="OTHER"),
             task("D", "EE 100: Reflection", at(3, 23, 59), project="OTHER")]
    ops, store, _ = make_ops(tmp_path, tasks)
    ops.now = lambda: at(3, 7)
    out = []

    async def send(t):
        out.append(t)

    asyncio.run(run_brief_job(ops, send=send, now=at(3, 7)))
    lines = out[0].splitlines()
    assert lines[lines.index("due today") + 1:lines.index("planned today")] == [
        "  - 11:59pm · EE 100: Reflection", "  - deadline · Write-up: §1 + §3 (planned sun)"]
    assert "  - 3:00pm · 1h · CME 102 Pset 2: work block (deadline thu)" in lines
    assert "due tomorrow" not in lines                                                          # the write-up is due today, not tomorrow


def test_chat_lists_due_and_planned_separately(tmp_path):
    tasks = [task("B", "CME 102 Pset 2: work block", at(3, 15), minutes=60, deadline=date(2026, 10, 8), project="CLASSES"),
             task("D", "CME 102: Quiz 1 corrections", at(3, 23, 59), project="CLASSES")]
    ops, store, _ = make_ops(tmp_path, tasks)
    ops.now = lambda: at(3, 9)
    assert ops.tasks_overview("today").splitlines() == [
        "due today:", "- 11:59pm CME 102: Quiz 1 corrections",
        "planned today (work time, not deadlines):", "- 3:00pm CME 102 Pset 2: work block (1h · deadline thu)"]
    assert ops.tasks_overview("week").splitlines()[1:] == [
        "- sat oct 3 3:00pm CME 102 Pset 2: work block (planned · 1h · deadline thu)", "- sat oct 3 11:59pm CME 102: Quiz 1 corrections"]


def test_add_task_can_schedule_a_work_block_with_a_duration_and_deadline(tmp_path):
    ops, store, todoist = make_ops(tmp_path, [])
    ops.now = lambda: at(3, 9)
    reply = ops.add_task("Pset 2: work block", due="2026-10-04T15:00", course="CME 102", duration=90, deadline="2026-10-08")
    assert reply == "added: CME 102: Pset 2: work block (sun 3:00pm · 1h 30m · deadline thu)"
    (t,) = todoist.all_tasks()
    assert (t.duration.amount, t.duration.unit, t.deadline.date) == (90, "minute", date(2026, 10, 8))
    assert ops.add_task("x", course="CME 102", deadline="next week").startswith("error: deadline must be an ISO date")
