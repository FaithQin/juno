"""Which hand-made task a new Gradescope assignment plausibly is (asked, never linked silently).

Real titles from Faith's Todoist on 2026-09-24 against the names Gradescope uses.
"""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from assistant.canvas_client import CanvasItem
from assistant.config import Course
from assistant.matching import plausible_matches, same_work, signature
from fakes import FakeDue, FakeTask

TZ = ZoneInfo("America/Los_Angeles")
ENGR = Course(code="ENGR 40M", canvas_id=231533, project_id="P-ENGR")
MATSCI = Course(code="MATSCI 88Q", canvas_id=232193, project_id="P-MAT")
CME = Course(code="CME 102", canvas_id=232579, project_id="P-CME")
EE160 = Course(code="EE 160A", canvas_id=231155, project_id="P-EE160")
COURSE_FOR = {1: ENGR, 2: MATSCI, 3: CME, 4: EE160}
GS_COURSE = {"ENGR 40M": 1, "MATSCI 88Q": 2, "CME 102": 3, "EE 160A": 4}


def local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


def gs(aid, name, due, *, course=ENGR):
    return CanvasItem(kind="gradescope", canvas_id=aid, course_id=GS_COURSE[course.code], name=name,
                      due_at=due.astimezone(timezone.utc), html_url=f"https://www.gradescope.com/courses/1/assignments/{aid}",
                      submission_types=("gradescope",), external_url=None, group_id=None, group_name=None,
                      submitted=False, published=True)


def task(tid, content, due, *, project="P-ENGR", made=20, deadline=None):
    return FakeTask(tid, content, FakeDue(due) if due else None, project_id=project,
                    created_at=datetime(2026, 9, made, 12, 0, tzinfo=timezone.utc),
                    deadline=SimpleNamespace(date=deadline) if deadline else None)


def course_of(tasks):
    by_project = {"P-ENGR": "ENGR 40M", "P-MAT": "MATSCI 88Q", "P-CME": "CME 102", "P-EE160": "EE 160A"}
    return {t.id: by_project[t.project_id] for t in tasks}


def test_pset_spellings_are_the_same_work():
    mine = signature("ENGR 40M: PSET 1 (Gradescope)", "ENGR 40M")
    for name in ("Pset1", "PSET 1", "Problem Set 1", "HW 1", "Homework #1", "PS1"):
        assert same_work(signature(name, "ENGR 40M"), mine), name
    assert not same_work(signature("Pset 2", "ENGR 40M"), mine)
    assert signature("CME 102: Pset6 (Gradescope) (check date)", "CME 102") == signature("Pset6", "CME 102")


def test_lab_keywords_pre_and_post_must_agree():
    pre = signature("MATSCI 88Q: Pre-lab 1 (Gradescope)", "MATSCI 88Q")
    post = signature("MATSCI 88Q: Post-lab 1 (Gradescope)", "MATSCI 88Q")
    assert same_work(signature("Lab 1: Pre Lab", "MATSCI 88Q"), pre)
    assert same_work(signature("Lab 1: Post Lab", "MATSCI 88Q"), post)
    assert not same_work(signature("Lab 1: Pre Lab", "MATSCI 88Q"), post)
    assert not same_work(signature("Lab 2: Pre Lab", "MATSCI 88Q"), pre)
    assert same_work(signature("Lab 2A Prelab", "ENGR 40M"), signature("ENGR 40M: Lab 2A prelab (Gradescope)", "ENGR 40M"))
    assert not same_work(signature("Lab 2A Prelab", "ENGR 40M"), signature("ENGR 40M: Lab 2B prelab (Gradescope)", "ENGR 40M"))


def test_the_course_code_is_not_a_number_to_match_on():
    assert signature("ENGR 40M: PSET 1 (Gradescope)", "ENGR 40M").numbers == ("1",)
    assert signature("MATSCI 88Q: Pre-lab 01", "MATSCI 88Q").numbers == ("1",)


def test_no_number_means_no_guess():
    assert not same_work(signature("Final Project", "MATSCI 88Q"), signature("MATSCI 88Q: Final Project presentation", "MATSCI 88Q"))


def test_plausible_matches_need_same_course_number_keywords_and_a_close_due_date():
    pset1 = task("P1", "ENGR 40M: PSET 1 (Gradescope)", datetime(2026, 10, 2, 23, 59))       # floating, like Todoist
    pset2 = task("P2", "ENGR 40M: PSET 2 (Gradescope)", datetime(2026, 10, 9, 23, 59))
    prelab = task("L1", "ENGR 40M: Lab 1 prelab (Gradescope)", datetime(2026, 10, 5, 18, 0))
    report = task("L2", "ENGR 40M: Lab 1 measurements + questions (Gradescope)", datetime(2026, 10, 12, 18, 0))
    cme = task("C1", "CME 102: Pset1 (Gradescope)", datetime(2026, 10, 1, 23, 59), project="P-CME")
    tasks = [pset1, pset2, prelab, report, cme]
    items = [gs(11, "PSET 1", local(2026, 10, 3, 17, 0)),                  # a day later than her guess: still her task
             gs(12, "Pset 2", local(2026, 10, 14, 23, 59)),                # five days off: not the same deadline
             gs(13, "Lab 1 Prelab", local(2026, 10, 5, 18, 0)),
             gs(14, "Lab 1", local(2026, 10, 12, 18, 0)),
             gs(15, "Pset1", local(2026, 10, 1, 23, 59), course=MATSCI)]   # other course
    pairs = plausible_matches(items, tasks, course_for=COURSE_FOR, task_course=course_of(tasks), tz=TZ)
    assert [(it.canvas_id, t.id) for it, t in pairs] == [(11, "P1"), (13, "L1"), (14, "L2")]


def test_each_task_is_offered_once_to_the_closest_item_and_date_only_tasks_count():
    older = task("A", "MATSCI 88Q: Pre-lab 1 (Gradescope)", date(2026, 9, 28), project="P-MAT", made=20)
    items = [gs(21, "Lab 1: Pre Lab", local(2026, 9, 28, 12, 0), course=MATSCI),
             gs(22, "Lab 1: Pre Lab (resubmission)", local(2026, 9, 29, 12, 0), course=MATSCI)]
    pairs = plausible_matches(items, [older], course_for=COURSE_FOR, task_course=course_of([older]), tz=TZ)
    assert [(it.canvas_id, t.id) for it, t in pairs] == [(21, "A")]


def test_a_task_without_a_due_date_is_not_guessed_at():
    undated = FakeTask("U", "ENGR 40M: PSET 1 (Gradescope)", None, project_id="P-ENGR")
    pairs = plausible_matches([gs(11, "PSET 1", local(2026, 10, 2, 23, 59))], [undated], course_for=COURSE_FOR,
                              task_course=course_of([undated]), tz=TZ, window=timedelta(days=2))
    assert pairs == []


def test_her_todoist_deadline_counts_as_a_due_date():
    """The two misses: a task with a Todoist deadline is planned work, so its due date is when she'll
    do it and the deadline is when it's due. Both times Gradescope's date was her deadline's day."""
    # 2026-10-06: HW2 planned for the syllabus date (Fri Oct 16), the website's date (Mon Oct 19) as
    # its deadline; Gradescope took the website's. 3 days from her plan, so the sync made "Homework 2".
    hw2 = task("6hg9QmV8rPxfr8HM", "EE 160A: HW2 (Gradescope) (check date)", datetime(2026, 10, 16, 23, 59),
               project="P-EE160", deadline=date(2026, 10, 19))
    # 2026-10-03: the Lab 1 prelab was a work block that evening, deadline Mon; Gradescope said Mon 6pm,
    # 2 days 20 minutes after the block, and the sync made "Prelab 1" a minute after she moved it.
    prelab = task("6hcVjWCrxMJ5pjGr", "ENGR 40M: Lab 1 prelab (Gradescope)", datetime(2026, 10, 3, 17, 40),
                  deadline=date(2026, 10, 5))
    tasks = [hw2, prelab]
    items = [gs(8820420, "Homework 2", local(2026, 10, 19, 23, 59), course=EE160),
             gs(8769171, "Prelab 1", local(2026, 10, 5, 18, 0))]
    pairs = plausible_matches(items, tasks, course_for=COURSE_FOR, task_course=course_of(tasks), tz=TZ)
    assert [(it.canvas_id, t.id) for it, t in pairs] == [(8820420, "6hg9QmV8rPxfr8HM"), (8769171, "6hcVjWCrxMJ5pjGr")]


def test_a_deadline_alone_is_a_date_and_far_dates_still_dont_match():
    only_deadline = task("D", "EE 160A: HW3 (Gradescope)", None, project="P-EE160", deadline=date(2026, 10, 30))
    far = task("F", "EE 160A: HW4 Part 1 (Gradescope) (check date)", datetime(2026, 11, 13, 23, 59),
               project="P-EE160", deadline=date(2026, 11, 17))
    tasks = [only_deadline, far]
    items = [gs(1, "Homework 3", local(2026, 10, 30, 23, 59), course=EE160),
             gs(2, "Homework 4 Part 1", local(2026, 11, 20, 23, 59), course=EE160)]   # 3 days past her deadline
    pairs = plausible_matches(items, tasks, course_for=COURSE_FOR, task_course=course_of(tasks), tz=TZ)
    assert [(it.canvas_id, t.id) for it, t in pairs] == [(1, "D")]
