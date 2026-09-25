"""Pure-logic tests for the sync planner. No network."""

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from assistant.canvas_client import CanvasItem
from assistant.config import Course
from assistant.db import ItemLink, TaskRow
from assistant.sync import (
    adopt_links, batch_content, batch_description, fmt_due, links_in, plan_sync,
)

TZ = ZoneInfo("America/Los_Angeles")
ENGR = Course(code="ENGR 40M", canvas_id=231533)
EE100 = Course(code="EE 100", canvas_id=232825)
COURSES = {231533: ENGR, 232825: EE100}
FRI = datetime(2026, 9, 26, 6, 59, tzinfo=timezone.utc)   # Fri Sep 25 11:59pm Pacific


def item(canvas_id, name, *, course=ENGR, due=FRI, group=(10, "Online Quizzes"), submitted=False,
         kind="assignment", published=True, ext=None, types=("online_quiz",)):
    gid, gname = group if group else (None, None)
    return CanvasItem(
        kind=kind, canvas_id=canvas_id, course_id=course.canvas_id, name=name, due_at=due,
        html_url=f"https://canvas.stanford.edu/courses/{course.canvas_id}/{'assignments' if kind == 'assignment' else 'quizzes'}/{canvas_id}",
        submission_types=types, external_url=ext, group_id=gid, group_name=gname,
        submitted=submitted, published=published,
    )


@dataclass
class FakeTask:
    id: str
    content: str
    description: str = ""
    due = None


def test_links_in_finds_assignment_and_quiz_links():
    text = ("- [2 SI Prefixes](https://canvas.stanford.edu/courses/231533/assignments/823749)\n"
            "[Quiz](https://canvas.stanford.edu/courses/231533/quizzes/193063)")
    assert links_in(text) == {("assignment", 823749), ("quiz", 193063)}
    assert links_in(None) == set()


def test_quizzes_same_week_become_one_task_with_checklist():
    items = [item(3, "3. Current + KCL"), item(2, "2 SI Prefixes"), item(4, "4 Voltage + KVL")]
    plan = plan_sync(items, COURSES, {}, {}, tz=TZ)
    assert len(plan.creates) == 1
    c = plan.creates[0]
    assert c.is_batch
    assert c.content == "ENGR 40M quizzes 2–4"
    assert c.description.splitlines()[0] == "Canvas quizzes due Fri 11:59pm:"
    assert [l.split("]")[0] for l in c.description.splitlines()[1:]] == ["- [2 SI Prefixes", "- [3. Current + KCL", "- [4 Voltage + KVL"]
    assert c.due_at == FRI


def test_lone_item_is_a_single_task_named_by_course():
    it = item(818490, "Submit EE Major Declaration Form", course=EE100, group=(5, "Assignments"), types=("online_upload",))
    plan = plan_sync([it], COURSES, {}, {}, tz=TZ)
    assert len(plan.creates) == 1 and not plan.creates[0].is_batch
    assert plan.creates[0].content == "EE 100: Submit EE Major Declaration Form"
    assert plan.creates[0].description == "File upload on [Canvas](https://canvas.stanford.edu/courses/232825/assignments/818490)"


def test_gradescope_linked_assignment_is_labelled():
    it = item(1, "PSET 1", course=EE100, group=(5, "Homework"), types=("external_tool",),
              ext="https://www.gradescope.com/auth/lti/callback")
    plan = plan_sync([it], COURSES, {}, {}, tz=TZ)
    assert plan.creates[0].description.startswith("Gradescope assignment on [Canvas]")


def test_adopts_hand_made_task_and_joins_new_quiz_into_it():
    existing = FakeTask("T1", "ENGR 40M quizzes 2–3",
                        "- [2 SI Prefixes](https://canvas.stanford.edu/courses/231533/assignments/2)\n"
                        "- [3. Current](https://canvas.stanford.edu/courses/231533/assignments/3)")
    items = [item(2, "2 SI Prefixes"), item(3, "3. Current"), item(4, "4 Voltage")]
    links = {l.key: l for l in adopt_links([existing], items, {})}
    assert set(links) == {("assignment", 2), ("assignment", 3)}
    assert all(l.adopted and l.task_id == "T1" for l in links.values())
    assert links[("assignment", 2)].due_at == "2026-09-26T06:59:00+00:00"

    plan = plan_sync(items, COURSES, links, {}, tz=TZ)
    assert plan.creates == []
    assert [(j.task_id, j.item.canvas_id) for j in plan.joins] == [("T1", 4)]
    assert plan.due_updates == []


def test_second_run_is_a_no_op():
    items = [item(2, "2 SI Prefixes"), item(3, "3. Current")]
    links = {
        ("assignment", 2): ItemLink("assignment", 2, 231533, "T1", False, "2 SI Prefixes", "2026-09-26T06:59:00+00:00", False),
        ("assignment", 3): ItemLink("assignment", 3, 231533, "T1", False, "3. Current", "2026-09-26T06:59:00+00:00", False),
    }
    tasks = {"T1": TaskRow("T1", "batch:231533:2026-09-26T06:59:00+00:00:10", True, "x", "y", None, False)}
    plan = plan_sync(items, COURSES, links, tasks, tz=TZ)
    assert plan.is_empty


def test_canvas_due_change_updates_task_once():
    moved = datetime(2026, 9, 29, 6, 59, tzinfo=timezone.utc)
    it = item(818490, "Form", course=EE100, group=(5, "Assignments"), due=moved)
    links = {("assignment", 818490): ItemLink("assignment", 818490, 232825, "T9", True, "Form", "2026-09-26T06:59:00+00:00", False)}
    plan = plan_sync([it], COURSES, links, {}, tz=TZ)
    assert len(plan.due_updates) == 1
    assert plan.due_updates[0].task_id == "T9" and plan.due_updates[0].new == moved


def test_adopted_link_with_unknown_due_never_triggers_update():
    it = item(818490, "Form", course=EE100, group=(5, "Assignments"))
    links = {("assignment", 818490): ItemLink("assignment", 818490, None, "T9", True, None, None, False)}
    plan = plan_sync([it], COURSES, links, {}, tz=TZ)
    assert plan.is_empty


def test_submitted_items_are_not_created_but_linked_ones_complete():
    a = item(1, "Done thing", course=EE100, group=(5, "Assignments"), submitted=True)
    plan = plan_sync([a], COURSES, {}, {}, tz=TZ)
    assert plan.creates == [] and plan.skips[0].reason == "already submitted"

    links = {("assignment", 1): ItemLink("assignment", 1, 232825, "T2", False, "Done thing", "2026-09-26T06:59:00+00:00", False)}
    plan = plan_sync([a], COURSES, links, {}, tz=TZ)
    assert [c.task_id for c in plan.completes] == ["T2"]

    plan = plan_sync([a], COURSES, links, {}, tz=TZ, complete_when_submitted=False)
    assert plan.completes == []


def test_batch_is_not_completed_until_every_member_is_submitted():
    items = [item(2, "2 A", submitted=True), item(3, "3 B", submitted=False)]
    links = {it.key: ItemLink("assignment", it.canvas_id, 231533, "T1", False, it.name, "2026-09-26T06:59:00+00:00", False) for it in items}
    plan = plan_sync(items, COURSES, links, {}, tz=TZ)
    assert plan.completes == []


def test_filters_unpublished_undated_and_unknown_courses():
    other = Course(code="X", canvas_id=1)
    items = [
        item(1, "hidden", published=False),
        item(2, "undated", due=None, group=None),
        item(3, "elsewhere", course=other),
    ]
    plan = plan_sync(items, COURSES, {}, {}, tz=TZ)
    assert sorted(s.reason for s in plan.skips) == ["course not in courses.yaml", "no due date", "unpublished"]
    assert plan.creates == []


def test_fmt_due_is_local_time():
    assert fmt_due(FRI, TZ) == "Fri 11:59pm"
    assert fmt_due(FRI, TZ, with_date=True) == "Sep 25 11:59pm"


def test_links_in_recognises_gradescope_assignment_urls():
    text = "Gradescope assignment on [Gradescope](https://www.gradescope.com/courses/1359455/assignments/8709892)"
    assert links_in(text) == {("gradescope", 8709892)}


def test_gradescope_items_get_the_gradescope_naming_convention():
    cme = Course(code="CME 102", canvas_id=232579)
    it = CanvasItem(kind="gradescope", canvas_id=8709892, course_id=1359455, name="Pset1",
                    due_at=FRI, html_url="https://www.gradescope.com/courses/1359455/assignments/8709892",
                    submission_types=("gradescope",), external_url=None, group_id=None, group_name=None,
                    submitted=False, published=True)
    plan = plan_sync([it], {1359455: cme}, {}, {}, tz=TZ)
    (c,) = plan.creates
    assert c.content == "CME 102: Pset1 (Gradescope)"
    assert c.description == "Gradescope assignment on [Gradescope](https://www.gradescope.com/courses/1359455/assignments/8709892)"


def test_adopt_by_title_matches_hand_made_gradescope_tasks():
    from assistant.sync import adopt_by_title

    cme = Course(code="CME 102", canvas_id=232579)
    t1 = FakeTask("T1", "CME 102: Pset 1 (Gradescope)", "")
    t2 = FakeTask("T2", "CME 102: Find HW due dates on Gradescope", "")
    t3 = FakeTask("T3", "MATSCI 88Q: Pre-lab 1 (Gradescope)", "")
    items = [
        CanvasItem("gradescope", 1, 1359455, "Pset1", FRI, "https://www.gradescope.com/courses/1359455/assignments/1", ("gradescope",), None, None, None, False, True),
        CanvasItem("gradescope", 2, 1359455, "Pset2", FRI, "https://www.gradescope.com/courses/1359455/assignments/2", ("gradescope",), None, None, None, False, True),
    ]
    pairs = adopt_by_title(items, [t1, t2, t3], course_for={1359455: cme}, task_course={"T1": "CME 102", "T2": "CME 102", "T3": "MATSCI 88Q"})
    assert [(it.name, t.id) for it, t in pairs] == [("Pset1", "T1")]     # Pset2 has no counterpart; T2/T3 don't match


# --- partial completion inside a batch (phase 6) ---------------------------------------

def _linked_batch(submitted_flags, known_flags=None):
    """Three quizzes in one task T1; `submitted_flags` is what Canvas says now, `known_flags` what we recorded last time."""
    known_flags = known_flags or [False] * len(submitted_flags)
    items = [item(i + 2, f"{i + 2}. Quiz {i + 2}", submitted=sub) for i, sub in enumerate(submitted_flags)]
    links = {
        it.key: ItemLink("assignment", it.canvas_id, 231533, "T1", False, it.name, "2026-09-26T06:59:00+00:00", known)
        for it, known in zip(items, known_flags)
    }
    tasks = {"T1": TaskRow("T1", "batch:231533:2026-09-26T06:59:00+00:00:10", True, "ENGR 40M quizzes 2–4", "", None, False)}
    return items, links, tasks


def test_one_quiz_submitted_records_progress_but_does_not_complete_the_batch():
    items, links, tasks = _linked_batch([False, True, False])
    plan = plan_sync(items, COURSES, links, tasks, tz=TZ)
    assert plan.completes == []
    (pr,) = plan.progress
    assert pr.task_id == "T1" and pr.done == 1 and pr.total == 3
    assert [it.canvas_id for it in pr.newly_done] == [3]


def test_progress_is_only_reported_when_something_new_was_submitted():
    items, links, tasks = _linked_batch([False, True, False], known_flags=[False, True, False])
    assert plan_sync(items, COURSES, links, tasks, tz=TZ).progress == []
    items, links, tasks = _linked_batch([True, True, True])
    plan = plan_sync(items, COURSES, links, tasks, tz=TZ)
    assert plan.progress == [] and [c.task_id for c in plan.completes] == ["T1"]


def test_apply_marks_done_quizzes_in_the_description():
    from assistant.db import Store
    from assistant.sync import apply_plan, format_report
    from fakes import FakeTask, FakeTodoist

    items, links, tasks = _linked_batch([False, True, False])
    desc = "Canvas quizzes due Fri 11:59pm:\n" + "\n".join(f"- [{it.name}]({it.html_url})" for it in items)
    todoist = FakeTodoist([FakeTask("T1", "ENGR 40M quizzes 2–4", None, 1, "S1", description=desc)])
    plan = plan_sync(items, COURSES, links, tasks, tz=TZ)
    report = apply_plan(plan, todoist=todoist, store=Store(__import__("tempfile").mkdtemp() and __import__("pathlib").Path(__import__("tempfile").mkdtemp()) / "t.sqlite3"),
                        project_id="CLASSES", sections={}, tz=TZ, dry_run=False)
    new_desc = todoist.get_task("T1").description
    assert "- ✅ [3. Quiz 3](" in new_desc and "- [2. Quiz 2](" in new_desc and "- [4. Quiz 4](" in new_desc
    assert report.progress == ["ENGR 40M quizzes 2–4: 1/3 done (3. Quiz 3)"]
    assert "progress 1:" in format_report(report)


def test_adopt_same_title_links_an_item_to_the_task_the_other_sync_made():
    """The Canvas sync and the Gradescope sync each know one side of a Gradescope-linked assignment.
    An exact title match (course code and source suffix stripped) makes them share one task."""
    from assistant.sync import adopt_same_title

    matsci = Course(code="MATSCI 88Q", canvas_id=232193)
    gs_task = FakeTask("G1", "MATSCI 88Q: Pre-lab 1 (Gradescope)", "https://www.gradescope.com/courses/1/assignments/11")
    near = FakeTask("X1", "MATSCI 88Q: Pre-lab 10", "")
    elsewhere = FakeTask("E1", "EE 100: Pre-lab 1", "")
    canvas_item = item(900, "Pre-lab 1", course=matsci, group=(5, "Assignments"), types=("external_tool",),
                       ext="https://www.gradescope.com/courses/1/assignments/11")
    links = {("gradescope", 11): ItemLink("gradescope", 11, 1, "G1", False, "Pre-lab 1", None, False)}
    course_for, task_course = {232193: matsci}, {"G1": "MATSCI 88Q", "X1": "MATSCI 88Q", "E1": "EE 100"}
    new = adopt_same_title([canvas_item], [gs_task, near, elsewhere], links, course_for=course_for, task_course=task_course)
    assert [(l.key, l.task_id, l.adopted, l.due_at) for l in new] == [(("assignment", 900), "G1", True, FRI.isoformat())]
    links[("assignment", 900)] = new[0]
    assert adopt_same_title([canvas_item], [gs_task], links, course_for=course_for, task_course=task_course) == []
