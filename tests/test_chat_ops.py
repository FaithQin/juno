"""What juno can *do* from a text, independent of any language model."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from assistant.brief import Event
from assistant.chat_ops import ChatOps
from assistant.db import Store
from fakes import FakeCalendar, FakeDue, FakeTask, FakeTodoist

TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 23, 17, 0, tzinfo=timezone.utc)      # Wed Sep 23, 10:00am Pacific
COURSES = ["ENGR 40M", "CS 106B", "CME 102", "MATSCI 88Q", "EE 310", "EE 100"]
SECTIONS = {"ENGR 40M": "S1", "CS 106B": "S2", "CME 102": "S3"}


def utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def make_ops(tmp_path, tasks=None, events=None):
    store = Store(tmp_path / "t.sqlite3")
    todoist = FakeTodoist(deepcopy(tasks or []))   # fresh copies: tests must not share mutable tasks
    calendar = FakeCalendar(events or {})
    ops = ChatOps(store=store, todoist=todoist, calendar=calendar, tz=TZ, courses=COURSES,
                  sections=SECTIONS, classes_project_id="CLASSES", calendar_names=["Stanford"],
                  now=lambda: NOW)
    return ops, store, todoist


SAMPLE = [
    FakeTask("T1", "ENGR 40M: Sign up for a lab section", FakeDue(utc(2026, 9, 23, 19, 0)), 4, "S1"),   # today 12pm
    FakeTask("T2", "ENGR 40M quizzes 2–8", FakeDue(utc(2026, 9, 26, 6, 59)), 1, "S1"),                   # fri 11:59pm
    FakeTask("T3", "CS 106B: Assignment 1 (Paperless)", FakeDue(utc(2026, 10, 6, 6, 59)), 1, "S2"),      # oct 5
    FakeTask("T4", "CME 102: Find HW due dates", FakeDue(date(2026, 9, 22)), 1, "S3"),                     # yesterday, date only
    FakeTask("T5", "Send the lab emails", FakeDue(utc(2026, 9, 24, 3, 0)), 3, None, project_id="OTHER"),   # p2 elsewhere, today 8pm
]


def test_tasks_overview_today_includes_p2_from_other_projects(tmp_path):
    ops, *_ = make_ops(tmp_path, SAMPLE)
    text = ops.tasks_overview("today")
    assert text.splitlines() == [
        "due today:",
        "- 12:00pm ENGR 40M: Sign up for a lab section [p1]",
        "- 8:00pm Send the lab emails [p2]",
    ]


def test_tasks_overview_week_and_overdue_and_course_filter(tmp_path):
    ops, *_ = make_ops(tmp_path, SAMPLE)
    assert "ENGR 40M quizzes 2–8" in ops.tasks_overview("week")
    assert "Assignment 1" not in ops.tasks_overview("week")
    assert ops.tasks_overview("overdue").splitlines() == ["overdue:", "- tue sep 22 CME 102: Find HW due dates"]
    assert ops.tasks_overview("all", course="cs106b").splitlines() == ["cs 106b:", "- mon oct 5 11:59pm CS 106B: Assignment 1 (Paperless)"]
    assert ops.tasks_overview("today", course="cs106b") == "nothing due today for CS 106B"


def test_schedule_today_and_tomorrow(tmp_path):
    ev = Event("CME 102", datetime(2026, 9, 23, 9, 30, tzinfo=TZ), datetime(2026, 9, 23, 10, 20, tzinfo=TZ), "Oshman Hall", False, "Stanford")
    ops, *_ = make_ops(tmp_path, SAMPLE, {date(2026, 9, 23): [ev]})
    assert ops.schedule("today").splitlines() == ["today (wed sep 23):", "- 9:30–10:20am CME 102 · Oshman Hall"]
    assert ops.schedule("tomorrow") == "nothing on the calendar for thu sep 24"


def test_add_task_infers_course_and_files_it_in_the_right_section(tmp_path):
    ops, store, todoist = make_ops(tmp_path)
    reply = ops.add_task("hw1", due="2026-09-24T23:59", course="cme102")
    assert reply == "added: CME 102: hw1 (thu 11:59pm)"
    (t,) = todoist.tasks("CLASSES")
    assert t.content == "CME 102: hw1" and t.section_id == "S3"
    assert t.due.date == datetime(2026, 9, 24, 23, 59, tzinfo=TZ)
    assert store.last_undoable().kind == "add_task"


def test_add_task_reads_the_course_from_the_title_and_handles_dates(tmp_path):
    ops, _, todoist = make_ops(tmp_path)
    assert ops.add_task("cs106b assignment 0 google form", due="2026-09-28") == "added: CS 106B: assignment 0 google form (mon sep 28)"
    (t,) = todoist.tasks("CLASSES")
    assert t.section_id == "S2" and t.due.date == date(2026, 9, 28)


def test_add_task_without_a_course_asks_instead_of_guessing(tmp_path):
    ops, _, todoist = make_ops(tmp_path)
    reply = ops.add_task("read chapter 3", due="2026-09-28")
    assert reply.startswith("which course is that for?")
    assert todoist.tasks("CLASSES") == []


def test_add_task_rejects_bad_dates(tmp_path):
    ops, *_ = make_ops(tmp_path)
    assert ops.add_task("hw1", due="thursday", course="cme102").startswith("error: due must be")


def test_complete_task_single_multiple_none(tmp_path):
    ops, store, todoist = make_ops(tmp_path, SAMPLE)
    reply = ops.complete_task("engr 40m")
    assert reply.startswith("which one?") and "quizzes 2–8" in reply and "lab section" in reply
    assert ops.complete_task("lab section") == "done: ENGR 40M: Sign up for a lab section"
    assert todoist.get_task("T1").is_completed
    assert ops.complete_task("physics") == "no task matches 'physics'"
    assert store.last_undoable().kind == "complete_task"


def test_reschedule_then_undo_restores_the_old_due(tmp_path):
    ops, store, todoist = make_ops(tmp_path, SAMPLE)
    assert ops.reschedule_task("assignment 1", due="2026-10-07T23:59") == "moved: CS 106B: Assignment 1 (Paperless) → wed 11:59pm"
    assert todoist.get_task("T3").due.date == datetime(2026, 10, 7, 23, 59, tzinfo=TZ)
    assert ops.undo() == "undone: CS 106B: Assignment 1 (Paperless) back to mon 11:59pm"
    assert todoist.get_task("T3").due.date == utc(2026, 10, 6, 6, 59)
    assert ops.undo() == "nothing to undo"


def test_undo_add_deletes_and_undo_complete_reopens(tmp_path):
    ops, _, todoist = make_ops(tmp_path, SAMPLE)
    ops.add_task("hw1", due="2026-09-24T23:59", course="cme102")
    assert ops.undo() == "undone: deleted CME 102: hw1"
    assert todoist.deleted == ["T101"]
    ops.complete_task("lab section")
    assert ops.undo() == "undone: reopened ENGR 40M: Sign up for a lab section"
    assert not todoist.get_task("T1").is_completed


def test_snooze_sets_a_time_and_undo_clears_it(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    assert ops.snooze("quizzes", at="2026-09-25T21:00") == "ok, i'll remind you about ENGR 40M quizzes 2–8 at fri 9:00pm"
    assert store.snoozes() == {"T2": datetime(2026, 9, 25, 21, 0, tzinfo=TZ)}
    assert ops.undo() == "undone: snooze for ENGR 40M quizzes 2–8 cleared"
    assert store.snoozes() == {}


def test_remember_and_forget_show_up_in_context(tmp_path):
    ops, store, _ = make_ops(tmp_path)
    assert ops.remember("ENGR 40M lab is Tuesday 3-6 in Packard 051") == "noted"
    ctx = ops.context_block()
    assert "now: wed sep 23, 10:00am (america/los_angeles)" in ctx
    assert "courses: ENGR 40M, CS 106B, CME 102, MATSCI 88Q, EE 310, EE 100" in ctx
    assert "- ENGR 40M lab is Tuesday 3-6 in Packard 051" in ctx
    assert ops.forget("lab") == "forgot: ENGR 40M lab is Tuesday 3-6 in Packard 051"
    assert ops.forget("lab") == "nothing matches 'lab'"
    assert "- ENGR" not in ops.context_block()


class BrokenCalendar:
    def events_for_day(self, *args):
        raise FileNotFoundError("Google token missing. Run: uv run assistant gcal-auth")


def test_schedule_says_when_the_calendar_is_not_connected(tmp_path):
    ops, *_ = make_ops(tmp_path)
    ops.calendar = BrokenCalendar()
    assert ops.schedule("today") == "calendar isn't connected yet. run: uv run assistant gcal-auth"


def test_edit_task_changes_title_notes_priority_and_undoes(tmp_path):
    ops, store, todoist = make_ops(tmp_path, SAMPLE)
    reply = ops.edit_task("assignment 1", notes="Paperless link: https://paperless.stanford.edu/a1", priority="p2")
    assert reply == "updated: CS 106B: Assignment 1 (Paperless) (notes, priority p2)"
    t = todoist.get_task("T3")
    assert t.description == "Paperless link: https://paperless.stanford.edu/a1" and t.priority == 3
    assert ops.edit_task("assignment 1", title="CS 106B: Assignment 1 (Paperless, late day used)") == \
        "updated: CS 106B: Assignment 1 (Paperless, late day used) (title)"
    assert ops.undo() == "undone: CS 106B: Assignment 1 (Paperless) restored"
    assert todoist.get_task("T3").content == "CS 106B: Assignment 1 (Paperless)"
    assert ops.undo() == "undone: CS 106B: Assignment 1 (Paperless) restored"
    assert todoist.get_task("T3").description == "" and todoist.get_task("T3").priority == 1


def test_edit_task_needs_something_to_change_and_a_single_match(tmp_path):
    ops, *_ = make_ops(tmp_path, SAMPLE)
    assert ops.edit_task("assignment 1") == "nothing to change: give a new title, notes, or priority"
    assert ops.edit_task("engr 40m", notes="x").startswith("which one?")
    assert ops.edit_task("assignment 1", priority="p9") == "error: priority must be p1, p2, p3 or p4"


class FakeEd:
    def __init__(self):
        from assistant.ed import EdCourse, EdThread
        from datetime import datetime, timezone
        self._courses = [EdCourse(70001, "CS 106B", "Programming Abstractions", "active", "2026", "Autumn")]
        self._threads = [EdThread(9001, 12, "announcement", "Section sign-ups open Thursday", "Sign-ups open Thu 12pm.",
                                  "Logistics", True, datetime(2026, 9, 23, 15, 4, 5, tzinfo=timezone.utc),
                                  "https://edstem.org/us/courses/70001/discussion/9001")]

    def courses(self):
        return self._courses

    def threads(self, course_id, *, limit=30, sort="new"):
        assert course_id == 70001
        return self._threads


def test_ed_announcements_by_course(tmp_path):
    ops, *_ = make_ops(tmp_path)
    assert ops.ed_announcements("cs106b") == "ed isn't connected yet (ED_API_TOKEN in .env)"
    ops.ed = FakeEd()
    text = ops.ed_announcements("cs106b")
    assert text.splitlines()[0] == "CS 106B announcements and pinned posts (newest first):"
    assert "Section sign-ups open Thursday" in text
    assert ops.ed_announcements("physics") == "'physics' isn't one of your courses (ENGR 40M, CS 106B, CME 102, MATSCI 88Q, EE 310, EE 100)"
    ops.ed._courses = []
    assert ops.ed_announcements("cs106b") == "i can't find CS 106B on ed"


# --- calendar tools and deletes (phase 6) -----------------------------------------------

from assistant.brief import Event as _Event


def _ev(title, h, m=0, end_h=None, end_m=0, day=23, calendar="Stanford", location=None):
    start = datetime(2026, 9, day, h, m, tzinfo=TZ)
    end = datetime(2026, 9, day, end_h, end_m, tzinfo=TZ) if end_h else start + timedelta(hours=1)
    return _Event(title, start, end, location, False, calendar)


def make_cal_ops(tmp_path, events=()):
    from fakes import FakeCalendar
    ops, store, todoist = make_ops(tmp_path, SAMPLE)
    ops.calendar = FakeCalendar({date(2026, 9, 23): list(events)})
    ops.calendar_names = ["Stanford", "TA", "faithclairvoyant333@gmail.com"]
    return ops, store, ops.calendar


def test_add_event_defaults_to_primary_and_one_hour(tmp_path):
    ops, store, cal = make_cal_ops(tmp_path)
    reply = ops.add_event("Coffee with Nick", start="2026-09-24T09:00", location="Coupa")
    assert reply == "added: Coffee with Nick, thu sep 24 9:00–10:00am at Coupa (personal calendar)"
    (e,) = [e for e in cal.events.values() if e.title == "Coffee with Nick"]
    assert e.calendar_id == "primary" and e.end == datetime(2026, 9, 24, 10, 0, tzinfo=TZ)
    assert ops.undo() == "undone: deleted Coffee with Nick" and cal.deleted == [e.id]


def test_add_event_on_a_named_calendar_with_explicit_end(tmp_path):
    ops, store, cal = make_cal_ops(tmp_path)
    reply = ops.add_event("ENGR 40M OH", start="2026-09-25T15:00", end="2026-09-25T16:00", calendar="TA", location="Packard 175")
    assert reply == "added: ENGR 40M OH, fri sep 25 3:00–4:00pm at Packard 175 (TA)"
    assert ops.add_event("x", start="2026-09-25T15:00", calendar="Nope") == "no calendar called 'Nope' (i know Stanford, TA, faithclairvoyant333@gmail.com)"
    assert ops.add_event("x", start="friday").startswith("error: start must be")


def test_move_and_delete_event_with_undo(tmp_path):
    ops, store, cal = make_cal_ops(tmp_path, [_ev("CS 106B", 12, 30, 13, 20), _ev("CME 102 OH — Yifa Yu", 11, 0, 13, 0, calendar="TA")])
    assert ops.move_event("cme 102 oh", start="2026-09-23T14:00") == "moved: CME 102 OH — Yifa Yu → wed sep 23 2:00–4:00pm"
    moved = next(e for e in cal.events.values() if e.title.startswith("CME 102 OH"))
    assert moved.start == datetime(2026, 9, 23, 14, 0, tzinfo=TZ) and moved.end == datetime(2026, 9, 23, 16, 0, tzinfo=TZ)
    assert ops.undo() == "undone: CME 102 OH — Yifa Yu back to wed sep 23 11:00am–1:00pm"

    assert ops.delete_event("cs 106b") == "deleted: CS 106B (wed sep 23 12:30–1:20pm)"
    assert not any(e.title == "CS 106B" for e in cal.events.values())
    assert ops.undo() == "undone: CS 106B is back on wed sep 23"
    assert any(e.title == "CS 106B" and e.start == datetime(2026, 9, 23, 12, 30, tzinfo=TZ) for e in cal.events.values())
    assert ops.delete_event("physics") == "no event matches 'physics' in the next two weeks"


def test_delete_task_with_undo(tmp_path):
    ops, store, todoist = make_ops(tmp_path, SAMPLE)
    assert ops.delete_task("assignment 1") == "deleted: CS 106B: Assignment 1 (Paperless)"
    assert not any(t.content.startswith("CS 106B: Assignment 1") for t in todoist.tasks("CLASSES"))
    assert ops.undo() == "undone: CS 106B: Assignment 1 (Paperless) is back"
    back = next(t for t in todoist.tasks("CLASSES") if t.content.startswith("CS 106B: Assignment 1"))
    assert back.section_id == "S2" and back.due.date == datetime(2026, 10, 6, 6, 59, tzinfo=timezone.utc)
    assert ops.delete_task("engr 40m").startswith("which one?")


def test_sync_now_runs_the_syncs_and_reports(tmp_path):
    from assistant.sync import Report

    ops, *_ = make_ops(tmp_path, SAMPLE)
    assert ops.sync_now() == "syncs aren't wired up in this context"

    def canvas():
        r = Report(dry_run=False)
        r.progress.append("ENGR 40M quizzes 2–8: 1/7 done (3. Current + KCL)")
        return r

    def gradescope():
        return "gradescope sync\ncompleted 1 (submitted on Gradescope):\n  - CME 102: Pset1 (Gradescope)"

    ops.sync_canvas = canvas
    ops.sync_gradescope = gradescope
    text = ops.sync_now("canvas")
    assert text == "canvas: progress 1:\n  - ENGR 40M quizzes 2–8: 1/7 done (3. Current + KCL)"
    text = ops.sync_now("all")
    assert text.startswith("canvas: progress 1:") and "gradescope sync" in text
