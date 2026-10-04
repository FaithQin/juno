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


def test_only_words_she_wrote_count_as_notes():
    from assistant.duplicates import hand_written

    assert hand_written("For Lab 1 (Tue Sep 29). No late pre-labs.")
    assert not hand_written("External tool on [Canvas](https://canvas.stanford.edu/courses/232193/assignments/828789)")
    assert not hand_written("https://www.gradescope.com/courses/1/assignments/11")
    assert not hand_written("[Handout](https://canvas.stanford.edu/courses/1/files/2)")
    assert not hand_written("Canvas quizzes due Fri 11:59pm:\n- [2 SI Prefixes](https://x/1)\n- [3. KCL](https://x/2)")
    assert not hand_written("")


def test_normalize_title_ignores_course_prefix_source_suffix_case_and_punctuation():
    assert normalize_title("MATSCI 88Q: Pre-lab 1 (Gradescope)", courses=COURSES) == "prelab1"
    assert normalize_title("MATSCI 88Q: Pre-lab 1", courses=COURSES) == "prelab1"
    assert normalize_title("  cs106b: Assignment 1 (Paperless) ", courses=COURSES) == "assignment1"
    assert normalize_title("Send the lab emails", courses=COURSES) == "sendthelabemails"


def test_assignment_named_is_the_assignment_however_it_is_worded_and_nothing_more():
    from assistant.duplicates import assignment_named

    prelab = ((("1",), frozenset({"pre", "lab"})))
    assert assignment_named("ENGR 40M: Lab 1 prelab (Gradescope)", courses=COURSES) == prelab
    assert assignment_named("Prelab 1", courses=COURSES) == prelab
    assert assignment_named("EE 160A: HW1 (due Fri Oct 9, week 3)", courses=COURSES) == (("1",), frozenset({"pset"}))
    assert assignment_named("CME 102 Pset1: work block (Tue night)", courses=COURSES) is None    # a step towards Pset1
    assert assignment_named("Breakfast", courses=COURSES) is None                               # no number, no guess


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
    l1 = FakeTask("L1", "Lab 0 prelab", FakeDue(date(2026, 9, 21)), project_id="P", created_at=made(20),
                  description="https://www.gradescope.com/courses/1/assignments/5")
    l2 = FakeTask("L2", "ENGR 40M: Lab 0 prelab (Gradescope)", FakeDue(date(2026, 9, 28)), project_id="P", created_at=made(21),
                  description="see https://www.gradescope.com/courses/1/assignments/5")   # a week apart: only the link joins them
    groups = find_duplicates([newer, older, l2, l1], links={}, courses=COURSES)
    assert sorted((g.keep.id, [t.id for t in g.extras]) for g in groups) == [("A", ["B"]), ("L1", ["L2"])]


# --- the 2026-09-28 false positives -------------------------------------------------------------

def test_a_daily_habit_one_day_apart_at_the_same_time_is_a_series_not_a_copy():
    tue = FakeTask("B1", "Breakfast", FakeDue(datetime(2026, 9, 29, 8, 15)), project_id="P-LIFE", created_at=made(27))
    wed = FakeTask("B2", "Breakfast", FakeDue(datetime(2026, 9, 30, 8, 15)), project_id="P-LIFE", created_at=made(27))
    assert find_duplicates([tue, wed], links={}, courses=COURSES) == []
    # still copies: a day apart at different times (11:59pm vs 12:00am drift), or one without a time
    late = FakeTask("Q1", "Pset 2", FakeDue(datetime(2026, 10, 1, 23, 59)), project_id="P", created_at=made(20))
    early = FakeTask("Q2", "Pset 2", FakeDue(datetime(2026, 10, 2, 0, 0)), project_id="P", created_at=made(21))
    dateonly = FakeTask("Q3", "Pset 2", FakeDue(date(2026, 10, 2)), project_id="P", created_at=made(22))
    groups = find_duplicates([late, early, dateonly], links={}, courses=COURSES)
    assert [(g.keep.id, [t.id for t in g.extras]) for g in groups] == [("Q1", ["Q2", "Q3"])]


def test_her_work_blocks_that_carry_the_assignment_link_are_not_copies_of_the_assignment(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    store.link("gradescope", 77, 5, "GS", adopted=False, name="Pset1", due_at=None, submitted=False)
    link = "[Pset1](https://www.gradescope.com/courses/5/assignments/77)"
    pset = FakeTask("GS", "CME 102: Pset1 (Gradescope)", FakeDue(utc(2026, 10, 2, 6, 59)), project_id="P-CME",
                    created_at=made(23), description=f"Gradescope assignment on {link}")
    blocks = [FakeTask("W1", "CME 102 Pset1: work block (Tue night)", FakeDue(datetime(2026, 9, 29, 20, 0)), project_id="P-CME",
                       created_at=made(27), description=link),
              FakeTask("W2", "CME 102 Pset1: work block (Wed AM)", FakeDue(datetime(2026, 9, 30, 9, 0)), project_id="P-CME",
                       created_at=made(27), description=link),
              FakeTask("W3", "CME 102 Pset1: finish + submit", FakeDue(datetime(2026, 10, 1, 19, 0)), project_id="P-CME",
                       created_at=made(27), description=f"submit at {link}")]
    assert find_duplicates([pset, *blocks], links=store.links(), courses=COURSES) == []


def test_her_own_task_for_the_same_assignment_under_a_reworded_name_is_a_copy(tmp_path):
    """The two pairs in her Todoist on 2026-10-03: the same link, the same work, worded differently."""
    store = Store(tmp_path / "t.sqlite3")
    store.link("gradescope", 8769171, 1395437, "GS", adopted=False, name="Prelab 1", due_at=None, submitted=False)
    prelab = "[Gradescope](https://www.gradescope.com/courses/1395437/assignments/8769171)"
    hw = "https://www.gradescope.com/courses/1/assignments/8743688"
    tasks = [FakeTask("GS", "ENGR 40M: Prelab 1 (Gradescope)", FakeDue(utc(2026, 10, 6, 1, 0)), project_id="P-ENGR",
                      created_at=made(30), description=f"Gradescope assignment on {prelab}"),
             FakeTask("HERS", "ENGR 40M: Lab 1 prelab (Gradescope)", FakeDue(datetime(2026, 10, 4, 11, 0)), project_id="P-ENGR",
                      created_at=made(24), description=f"Due Mon Oct 5, 6:00 PM. No late prelabs. {prelab}"),
             FakeTask("HW", "EE 160A: HW1 (Gradescope)", FakeDue(datetime(2026, 10, 9, 23, 59)), project_id="P-EE160",
                      created_at=made(25), description=f"Aim to submit Thu Oct 8. {hw}"),
             FakeTask("HW2", "EE 160A: HW1 (due Fri Oct 9, week 3)", project_id="P-EE160",
                      created_at=made(30), description=f"Don't start before Tue. {hw}")]
    groups = find_duplicates(tasks, links=store.links(), courses=COURSES)
    assert [(g.keep.id, [t.id for t in g.extras]) for g in groups] == [("HW", ["HW2"]), ("GS", ["HERS"])]


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


async def test_a_question_about_tasks_that_are_gone_withdraws_itself_and_frees_the_queue(tmp_path):
    a = FakeTask("A", "Read chapter 3", FakeDue(date(2026, 9, 30)), project_id="P-MATSCI", created_at=made(20))
    b = FakeTask("B", "read chapter 3!", FakeDue(date(2026, 9, 30)), project_id="P-MATSCI", created_at=made(22))
    check, store, todoist, out = make_check(tmp_path, [a, b])
    await check.run()
    assert store.pending_job()["kind"] == "duplicates"
    todoist.complete_task("A")                                                   # she ticked one, deleted the other
    todoist.delete_task("B")
    assert await check.run() == "todoist: no need to answer my duplicates question, it's out of date (nothing was deleted)"
    assert out.sent[-1] == "todoist: no need to answer my duplicates question, it's out of date (nothing was deleted)"
    assert store.pending_job() is None
    assert store.proposal_slot("outlook_new", "d1") == "free"                    # the next job's question can go out
    assert await check.run() is None and len(out.sent) == 2                       # said once
    assert await check.run(quiet=True) == "todoist: no duplicate tasks"


# --- the MATSCI 88Q triples: hand-made, Gradescope-made, Canvas-made (2026-09-24 audit) --------

HAND_NOTES = "For Lab 1 (Tue Sep 29, EVGR C kitchen). No late pre-labs."
GS_DESC = "Gradescope assignment on [Gradescope](https://www.gradescope.com/courses/1399426/assignments/8676496)"


def triple():
    """Fresh each time: FakeTodoist edits the very objects it is given."""
    hand = FakeTask("H", "MATSCI 88Q: Pre-lab 1 (Gradescope)", FakeDue(datetime(2026, 9, 28, 12, 0)), 1, None,
                    project_id="P-MATSCI", created_at=made(23), description=HAND_NOTES)
    gs = FakeTask("G", "MATSCI 88Q: Lab 1: Pre Lab (Gradescope)", FakeDue(utc(2026, 9, 28, 19, 0)), 1, None,
                  project_id="P-MATSCI", created_at=made(24), description=GS_DESC)
    cv = FakeTask("C", "MATSCI 88Q: Pre-lab 1", FakeDue(utc(2026, 9, 28, 19, 0)), 1, None, project_id="P-MATSCI",
                  created_at=made(24), description="External tool on [Canvas](https://canvas.stanford.edu/courses/232193/assignments/828789)")
    return [hand, gs, cv]


TWINS = {8676496: 828789}


def link_triple(store):
    store.link("gradescope", 8676496, 1399426, "G", adopted=False, name="Lab 1: Pre Lab", due_at=None, submitted=False)
    store.link("assignment", 828789, 232193, "C", adopted=False, name="Pre-lab 1", due_at=None, submitted=False)


def test_a_canvas_twin_of_a_gradescope_assignment_is_the_same_task_and_gradescope_is_kept(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    link_triple(store)
    groups = find_duplicates(triple(), links=store.links(), courses=COURSES, twins=TWINS)
    assert [(g.keep.id, [t.id for t in g.extras]) for g in groups] == [("G", ["C", "H"])]
    assert [(g.keep.id, [t.id for t in g.extras]) for g in find_duplicates(triple(), links=store.links(), courses=COURSES)] == [
        ("C", ["H"])]                                                           # without the twin map: the old pair only


async def test_yes_keeps_the_gradescope_task_moves_her_notes_onto_it_and_repoints_canvas(tmp_path):
    check, store, todoist, out = make_check(tmp_path, triple())
    link_triple(store)
    store.kv_set("gradescope_twins", '{"8676496": 828789}')
    await check.run()
    text = out.sent[0]
    assert text.splitlines()[0] == "todoist: 1 pair looks like duplicates."
    assert "- MATSCI 88Q: Pre-lab 1 looks like a copy of MATSCI 88Q: Lab 1: Pre Lab (Gradescope) (both due mon sep 28 12:00pm)" in text
    assert ("- MATSCI 88Q: Pre-lab 1 (Gradescope) looks like a copy of MATSCI 88Q: Lab 1: Pre Lab (Gradescope) "
            "(both due mon sep 28 12:00pm; your notes move over)") in text
    reply = await check.approve(store.pending_job()["payload"], True)
    assert reply == ("deleted 2 copies: MATSCI 88Q: Pre-lab 1, MATSCI 88Q: Pre-lab 1 (Gradescope). "
                     "your notes are on MATSCI 88Q: Lab 1: Pre Lab (Gradescope) now. undo brings the last one back")
    assert sorted(todoist.deleted) == ["C", "H"]
    kept = todoist.get_task("G")
    assert kept.description == GS_DESC + "\n\n" + HAND_NOTES
    assert store.links()[("assignment", 828789)].task_id == "G"
    kinds = []
    while (a := store.last_undoable()) is not None:
        kinds.append(a.kind)
        store.mark_undone(a.id)
    assert kinds == ["delete_task", "delete_task", "edit_task"]                 # undo: copies back first, then the notes edit
