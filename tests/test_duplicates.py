"""Duplicate tasks in Todoist: found after every sync and on demand, proposed, removed only on a yes.

The pair that prompted this: the Canvas sync made "MATSCI 88Q: Pre-lab 1" and the Gradescope sync
made "MATSCI 88Q: Pre-lab 1 (Gradescope)" for the same assignment.
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from assistant.db import Store
from assistant.duplicates import DuplicateCheck, find_duplicates, normalize_title
from fakes import FakeDue, FakeTask, FakeTodoist

pytestmark = pytest.mark.anyio
TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 24, 17, 0, tzinfo=timezone.utc)
COURSES = ["ENGR 40M", "CS 106B", "CME 102", "MATSCI 88Q", "EE 310", "EE 100"]


def utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def made(day):
    return datetime(2026, 9, day, 12, 0, tzinfo=timezone.utc)


PRE_GS = FakeTask("G1", "MATSCI 88Q: Pre-lab 1 (Gradescope)", FakeDue(utc(2026, 9, 28, 19, 0)), 1, None, project_id="P-MATSCI",
                  created_at=made(23), description="https://www.gradescope.com/courses/1/assignments/11")
PRE_CV = FakeTask("C1", "MATSCI 88Q: Pre-lab 1", FakeDue(utc(2026, 9, 28, 19, 0)), 1, None, project_id="P-MATSCI",
                  created_at=made(24), description="https://canvas.stanford.edu/courses/232193/assignments/900")
POST_GS = FakeTask("G2", "MATSCI 88Q: Post-lab 1 (Gradescope)", FakeDue(utc(2026, 10, 3, 6, 59)), 1, None, project_id="P-MATSCI",
                   created_at=made(23), description="https://www.gradescope.com/courses/1/assignments/12")
POST_CV = FakeTask("C2", "MATSCI 88Q: Post-lab 1", FakeDue(utc(2026, 10, 3, 6, 59)), 1, None, project_id="P-MATSCI",
                   created_at=made(24), description="https://canvas.stanford.edu/courses/232193/assignments/901")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def link_all(store):
    store.link("gradescope", 11, 1, "G1", adopted=False, name="Pre-lab 1", due_at=None, submitted=False)
    store.link("assignment", 900, 232193, "C1", adopted=False, name="Pre-lab 1", due_at=None, submitted=False)
    store.link("gradescope", 12, 1, "G2", adopted=False, name="Post-lab 1", due_at=None, submitted=False)
    store.link("assignment", 901, 232193, "C2", adopted=False, name="Post-lab 1", due_at=None, submitted=False)


def test_normalize_title_ignores_course_prefix_source_suffix_case_and_punctuation():
    assert normalize_title("MATSCI 88Q: Pre-lab 1 (Gradescope)", courses=COURSES) == "prelab1"
    assert normalize_title("MATSCI 88Q: Pre-lab 1", courses=COURSES) == "prelab1"
    assert normalize_title("  cs106b: Assignment 1 (Paperless) ", courses=COURSES) == "assignment1"
    assert normalize_title("Send the lab emails", courses=COURSES) == "sendthelabemails"


def test_find_duplicates_groups_same_title_in_one_project_and_keeps_the_canvas_linked_task(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    link_all(store)
    elsewhere = FakeTask("X1", "MATSCI 88Q: Pre-lab 1", project_id="P-OTHER")                       # same title, other project
    weekly = [FakeTask("W1", "Weekly reading", FakeDue(date(2026, 9, 21)), project_id="P-CLUB"),   # a week apart: recurring, not a copy
              FakeTask("W2", "Weekly reading", FakeDue(date(2026, 9, 28)), project_id="P-CLUB")]
    groups = find_duplicates([PRE_GS, PRE_CV, elsewhere, *weekly], links=store.links(), courses=COURSES)
    assert [(g.keep.id, [t.id for t in g.extras]) for g in groups] == [("C1", ["G1"])]             # canvas-linked wins, though newer


def test_find_duplicates_prefers_the_older_task_otherwise_and_also_matches_on_shared_links():
    older = FakeTask("A", "Read chapter 3", FakeDue(date(2026, 9, 30)), project_id="P", created_at=made(20))
    newer = FakeTask("B", "read chapter 3!", FakeDue(date(2026, 9, 30)), project_id="P", created_at=made(22))
    l1 = FakeTask("L1", "Lab 0 prelab", project_id="P", created_at=made(20), description="https://www.gradescope.com/courses/1/assignments/5")
    l2 = FakeTask("L2", "ENGR 40M: Lab 0 prelab (Gradescope), redo", project_id="P", created_at=made(21),
                  description="see https://www.gradescope.com/courses/1/assignments/5")
    groups = find_duplicates([newer, older, l2, l1], links={}, courses=COURSES)
    assert sorted((g.keep.id, [t.id for t in g.extras]) for g in groups) == [("A", ["B"]), ("L1", ["L2"])]


class Outbox:
    def __init__(self):
        self.sent: list[str] = []

    async def __call__(self, text):
        self.sent.append(text)


def make_check(tmp_path, tasks):
    store = Store(tmp_path / "t.sqlite3")
    todoist = FakeTodoist(tasks, projects=[("CLASSES", "Classes", None), ("P-MATSCI", "MATSCI 88Q", "CLASSES")])
    out = Outbox()
    check = DuplicateCheck(todoist=todoist, store=store, courses=COURSES, tz=TZ, send=out, now=lambda: NOW)
    return check, store, todoist, out


async def test_check_proposes_once_then_deletes_copies_on_yes_and_repoints_their_links(tmp_path):
    check, store, todoist, out = make_check(tmp_path, [PRE_GS, PRE_CV, POST_GS, POST_CV])
    link_all(store)
    await check.run()
    await check.run()                                                            # still unanswered: asked once
    assert len(out.sent) == 1
    text = out.sent[0]
    assert text.splitlines()[0] == "todoist: 2 pairs look like duplicates."
    assert "- MATSCI 88Q: Pre-lab 1 (Gradescope) looks like a copy of MATSCI 88Q: Pre-lab 1 (both due mon sep 28 12:00pm)" in text
    assert text.endswith("reply yes to delete the copies (undoable), or no to keep them all")
    assert todoist.deleted == []

    reply = await check.approve(store.pending_job()["payload"], True)
    assert reply == "deleted 2 copies: MATSCI 88Q: Post-lab 1 (Gradescope), MATSCI 88Q: Pre-lab 1 (Gradescope). undo brings the last one back"
    assert sorted(todoist.deleted) == ["G1", "G2"]
    assert store.links()[("gradescope", 11)].task_id == "C1"                     # gradescope submissions now tick the kept task
    assert store.links()[("gradescope", 12)].task_id == "C2"
    last = store.last_undoable()
    assert last.kind == "delete_task" and last.payload["snapshot"]["content"] == "MATSCI 88Q: Pre-lab 1 (Gradescope)"
    assert last.payload["snapshot"]["project_id"] == "P-MATSCI"
    store.kv_delete("pending_job")
    assert await check.run() is None and len(out.sent) == 1                       # nothing left to find


async def test_no_keeps_them_and_only_a_new_pair_is_asked_about_later(tmp_path):
    check, store, todoist, out = make_check(tmp_path, [PRE_GS, PRE_CV])
    await check.run()
    assert await check.approve(store.pending_job()["payload"], False) == "ok, keeping them. i won't ask about those again"
    store.kv_delete("pending_job")                                               # chat clears it before calling the handler
    assert await check.run() is None and len(out.sent) == 1
    todoist.add_task(content="Buy a lab notebook", project_id="P-MATSCI", section_id=None)
    todoist.add_task(content="buy a lab notebook", project_id="P-MATSCI", section_id=None)
    await check.run()
    assert len(out.sent) == 2
    assert out.sent[1].splitlines()[0] == "todoist: 1 pair looks like duplicates."
    assert "lab notebook" in out.sent[1] and "Pre-lab" not in out.sent[1]


async def test_quiet_run_answers_chat_and_waits_behind_another_proposal(tmp_path):
    check, store, todoist, out = make_check(tmp_path, [PRE_CV])
    assert await check.run(quiet=True) == "todoist: no duplicate tasks"
    check2, store2, todoist2, out2 = make_check(tmp_path / "b", [PRE_GS, PRE_CV])
    store2.propose_job("outlook_new", {"digest": "x"}, "outlook: 1 meeting?", at=NOW)
    assert await check2.run() is None and out2.sent == []
    assert await check2.run(quiet=True) == "todoist: 1 pair looks like duplicates, once you've answered the outlook proposal"
    store2.kv_delete("pending_job")
    text = await check2.run(quiet=True)
    assert text.startswith("todoist: 1 pair looks like duplicates.") and out2.sent == []
    assert store2.pending_job()["kind"] == "duplicates"
