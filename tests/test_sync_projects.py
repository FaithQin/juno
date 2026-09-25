"""Canvas sync with one Todoist sub-project per course under Classes (decided 2026-09-24).

Reads span Classes plus every course sub-project; new tasks go to the course's sub-project;
updates never move a task; a task the orchestrator moves keeps its id, links and state.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from assistant.canvas_client import CanvasItem
from assistant.config import Course, CoursesConfig
from assistant.db import Store
from assistant.sync import Complete, Create, DueUpdate, Join, Plan, Progress, apply_plan
from fakes import FakeDue, FakeTask, FakeTodoist

TZ = ZoneInfo("America/Los_Angeles")
FRI = datetime(2026, 9, 26, 6, 59, tzinfo=timezone.utc)
EE = Course(code="EE 100", canvas_id=232825, project_id="P-EE")
CME = Course(code="CME 102", canvas_id=232579)                        # legacy: no project_id


def item(canvas_id, name, *, course=EE, due=FRI, submitted=False, group=None):
    gid, gname = group or (None, None)
    return CanvasItem(
        kind="assignment", canvas_id=canvas_id, course_id=course.canvas_id, name=name, due_at=due,
        html_url=f"https://canvas.stanford.edu/courses/{course.canvas_id}/assignments/{canvas_id}",
        submission_types=("online_upload",), external_url=None, group_id=gid, group_name=gname,
        submitted=submitted, published=True,
    )


def store_at(tmp_path: Path) -> Store:
    return Store(tmp_path / "t.sqlite3")


# --- apply_plan: where creates land -------------------------------------------------------

def test_create_for_a_course_with_a_project_goes_into_its_sub_project_with_no_section(tmp_path):
    todoist = FakeTodoist()
    it = item(1, "Lab 1")
    plan = Plan(creates=[Create("assignment:1", [it], EE, "EE 100: Lab 1", "File upload", FRI)])
    report = apply_plan(plan, todoist=todoist, store=store_at(tmp_path), project_id="CLASSES",
                        sections={}, tz=TZ, dry_run=False)
    assert report.errors == []
    (t,) = todoist.tasks("P-EE")
    assert (t.content, t.project_id, t.section_id) == ("EE 100: Lab 1", "P-EE", None)
    assert todoist.tasks("CLASSES") == [] and todoist.sections_created == []   # no legacy section, ever


def test_create_for_a_legacy_course_keeps_the_section_in_classes(tmp_path):
    todoist = FakeTodoist()
    sections: dict = {}
    for n in (1, 2):
        it = item(n, f"Pset {n}", course=CME)
        plan = Plan(creates=[Create(f"assignment:{n}", [it], CME, f"CME 102: Pset {n}", "File upload", FRI)])
        apply_plan(plan, todoist=todoist, store=store_at(tmp_path), project_id="CLASSES", sections=sections,
                   tz=TZ, dry_run=False)
    assert [(t.project_id, t.section_id) for t in todoist.tasks("CLASSES")] == [("CLASSES", "S-CME 102")] * 2
    assert todoist.sections_created == [("CLASSES", "CME 102")]            # created once, then reused


# --- apply_plan: updates never move a task --------------------------------------------------

def test_join_due_update_complete_and_progress_leave_every_task_where_it_is(tmp_path):
    desc = "Canvas items due Fri:\n- [Lab 1](https://canvas.stanford.edu/courses/232825/assignments/1)\n- [Lab 2](https://canvas.stanford.edu/courses/232825/assignments/2)"
    in_project = FakeTask("TP", "EE 100 labs", FakeDue(FRI), description=desc, project_id="P-EE")
    in_section = FakeTask("TS", "EE 100: Form", FakeDue(FRI), section_id="S-EE")            # not moved yet
    done_later = FakeTask("TD", "EE 100: Reading", FakeDue(FRI), project_id="P-EE")
    todoist = FakeTodoist([in_project, in_section, done_later])
    later = FRI + timedelta(days=2)
    l1, l2, l3 = item(1, "Lab 1", submitted=True), item(2, "Lab 2"), item(3, "Lab 3")
    plan = Plan(
        joins=[Join("TP", l3, EE), Join("TS", item(4, "Form part 2"), EE)],
        due_updates=[DueUpdate("TP", [l1, l2], EE, FRI, later), DueUpdate("TS", [item(5, "Form")], EE, FRI, later)],
        progress=[Progress("TP", [l1, l2], EE, 1, 2, [l1])],
        completes=[Complete("TD", [item(6, "Reading", submitted=True)], EE)],
    )
    report = apply_plan(plan, todoist=todoist, store=store_at(tmp_path), project_id="CLASSES", sections={},
                        tz=TZ, dry_run=False)
    assert report.errors == []
    assert "✅ [Lab 1]" in todoist.get_task("TP").description and "[Lab 3]" in todoist.get_task("TP").description
    assert todoist.get_task("TP").due.date == later and todoist.get_task("TD").is_completed
    assert [(t.id, t.project_id, t.section_id) for t in (in_project, in_section, done_later)] == [
        ("TP", "P-EE", None), ("TS", "CLASSES", "S-EE"), ("TD", "P-EE", None)]
    assert todoist.sections_created == []


# --- run_sync: reading Classes plus every course sub-project --------------------------------

from assistant.sync import run_sync  # noqa: E402
from fakes import FakeCanvas  # noqa: E402

CS = {"code": "CS 106B", "canvas_id": None, "project_id": "P-CS"}
PROJECT_CFG = CoursesConfig.model_validate({
    "todoist": {"project_id": "CLASSES"},
    "courses": [{"code": "EE 100", "canvas_id": 232825, "project_id": "P-EE"}, CS],
})
LEGACY_CFG = CoursesConfig.model_validate({
    "todoist": {"project_id": "CLASSES"}, "courses": [{"code": "EE 100", "canvas_id": 232825}],
})


def settings_at(tmp_path):
    return SimpleNamespace(tz=TZ, complete_when_submitted=True, include_undated=False, batch_min_size=2,
                           db_path=tmp_path / "t.sqlite3", canvas_url="", canvas_token="", todoist_token="")


def link(store, canvas_id, task_id, *, name, due=FRI):
    store.link("assignment", canvas_id, 232825, task_id, adopted=False, name=name,
               due_at=due.astimezone(timezone.utc).isoformat(timespec="seconds"), submitted=False)


def remember(store, task_id, content, *, completed=False):
    store.upsert_task(task_id, batch_key=None, managed=True, content=content, description="", due_at=None,
                      completed=completed)


def sync(tmp_path, cfg, todoist, items, *, dry_run=False, verbose=False):
    store = Store(tmp_path / "t.sqlite3")
    return run_sync(settings_at(tmp_path), cfg, todoist=todoist, canvas=FakeCanvas(items), store=store,
                    dry_run=dry_run, verbose=verbose), store


def test_mid_migration_tasks_in_a_section_and_in_the_sub_project_are_both_active(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    t1 = FakeTask("T1", "EE 100: Lab 1", FakeDue(FRI), section_id="S-EE")          # not moved yet
    t2 = FakeTask("T2", "EE 100: Lab 2", FakeDue(FRI), project_id="P-EE")          # already moved
    for n, t in ((1, t1), (2, t2)):
        link(store, n, t.id, name=f"Lab {n}")
        remember(store, t.id, t.content)
    todoist = FakeTodoist([t1, t2], sections={"CLASSES": {"EE 100": "S-EE"}})
    report, store = sync(tmp_path, PROJECT_CFG, todoist, [item(1, "Lab 1"), item(2, "Lab 2")])
    assert report.errors == [] and report.created == []
    assert {tid: row.completed for tid, row in store.tasks().items()} == {"T1": False, "T2": False}
    assert {k: v.task_id for k, v in store.links().items()} == {("assignment", 1): "T1", ("assignment", 2): "T2"}
    assert todoist.sections_created == []


def test_a_task_moved_into_its_sub_project_stays_active_and_is_still_ticked_on_submit(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    t1 = FakeTask("T1", "EE 100: Lab 1", FakeDue(FRI), section_id="S-EE")          # synced before the migration
    link(store, 1, "T1", name="Lab 1")
    remember(store, "T1", t1.content)
    todoist = FakeTodoist([t1])
    report, _ = sync(tmp_path, PROJECT_CFG, todoist, [item(1, "Lab 1")])
    assert report.created == []
    todoist.move("T1", project_id="P-EE")                                            # the orchestrator's move
    report, store = sync(tmp_path, PROJECT_CFG, todoist, [item(1, "Lab 1")])
    assert report.created == [] and store.tasks()["T1"].completed is False
    assert store.links()[("assignment", 1)].task_id == "T1"
    report, store = sync(tmp_path, PROJECT_CFG, todoist, [item(1, "Lab 1", submitted=True)])
    assert report.completed == ["EE 100: Lab 1"] and todoist.get_task("T1").is_completed
    assert [t.id for t in todoist.all_tasks()] == [] and len(store.tasks()) == 1    # never duplicated


def test_a_hand_made_linked_task_in_a_sub_project_is_adopted_not_duplicated(tmp_path):
    form = FakeTask("T9", "EE 100: Form", FakeDue(FRI), project_id="P-EE",
                    description="https://canvas.stanford.edu/courses/232825/assignments/1")
    todoist = FakeTodoist([form])
    report, store = sync(tmp_path, PROJECT_CFG, todoist, [item(1, "Form")])
    assert report.created == [] and store.links()[("assignment", 1)].task_id == "T9"
    assert [t.id for t in todoist.all_tasks()] == ["T9"]


def test_new_canvas_items_are_created_in_the_course_sub_project(tmp_path):
    todoist = FakeTodoist([FakeTask("TG", "Add/drop deadline", FakeDue(FRI))])      # general, Classes root
    report, store = sync(tmp_path, PROJECT_CFG, todoist, [item(1, "Lab 1")])
    assert report.created == ["EE 100: Lab 1 (due Sep 25 11:59pm)"]
    assert [(t.content, t.section_id) for t in todoist.tasks("P-EE")] == [("EE 100: Lab 1", None)]
    assert [t.id for t in todoist.tasks("CLASSES")] == ["TG"] and todoist.sections_created == []
    assert store.tasks()["TG"].completed is False


def test_the_cs106b_sub_project_is_read_even_though_it_has_no_canvas_id(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    remember(store, "TC", "CS 106B: Assignment 1 (Paperless)")
    todoist = FakeTodoist([FakeTask("TC", "CS 106B: Assignment 1 (Paperless)", project_id="P-CS")])
    report, store = sync(tmp_path, PROJECT_CFG, todoist, [])
    assert store.tasks()["TC"].completed is False


def test_tasks_that_leave_every_class_project_are_treated_as_done_like_before(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    for tid in ("TDONE", "TDEL", "TAWAY", "TSTAY"):
        remember(store, tid, tid)
    done = FakeTask("TDONE", "done", project_id="P-EE", is_completed=True)
    away = FakeTask("TAWAY", "moved to her inbox", project_id="INBOX")
    stay = FakeTask("TSTAY", "still in the CS sub-project", project_id="P-CS")
    todoist = FakeTodoist([done, away, stay])                                         # TDEL was deleted
    _, store = sync(tmp_path, PROJECT_CFG, todoist, [])
    assert {tid: row.completed for tid, row in store.tasks().items()} == {
        "TDONE": True, "TDEL": True, "TAWAY": True, "TSTAY": False}


def test_a_task_juno_ticked_and_faith_reopened_is_not_ticked_again(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    t1 = FakeTask("T1", "EE 100: Lab 1", FakeDue(FRI), project_id="P-EE")          # she unticked it to revise
    store.link("assignment", 1, 232825, "T1", adopted=False, name="Lab 1",
               due_at=FRI.isoformat(timespec="seconds"), submitted=True)
    remember(store, "T1", t1.content, completed=True)
    todoist = FakeTodoist([t1])
    report, store = sync(tmp_path, PROJECT_CFG, todoist, [item(1, "Lab 1", submitted=True)])
    assert report.completed == [] and not todoist.get_task("T1").is_completed
    assert store.tasks()["T1"].completed is True


def test_legacy_config_reads_classes_only_and_files_into_the_section(tmp_path):
    todoist = FakeTodoist(sections={"CLASSES": {"EE 100": "S-EE"}})
    report, store = sync(tmp_path, LEGACY_CFG, todoist, [item(1, "Lab 1")])
    assert [(t.project_id, t.section_id) for t in todoist.tasks("CLASSES")] == [("CLASSES", "S-EE")]
    assert todoist.sections_created == []                                             # found, not re-made


def test_verbose_names_the_parent_and_the_sub_projects_read(tmp_path, capsys):
    todoist = FakeTodoist([FakeTask("TG", "Add/drop deadline")])
    sync(tmp_path, PROJECT_CFG, todoist, [], verbose=True)
    assert "todoist: 'Classes' (CLASSES) + 2 course sub-projects, 0 legacy sections, 1 active tasks" in capsys.readouterr().out


def test_a_reopened_task_with_mixed_links_is_not_ticked_again(tmp_path):
    """Review finding (2026-09-24): a task linked to a submitted Canvas item *and* an unsubmitted
    Gradescope item, ticked by juno, then reopened by Faith. Main keeps completed rows completed;
    re-opening the row here would make the next sync tick it again, every time she reopens it."""
    store = Store(tmp_path / "t.sqlite3")
    t1 = FakeTask("T1", "EE 100: Lab 1", FakeDue(FRI), project_id="P-EE")          # she reopened it
    store.link("assignment", 1, 232825, "T1", adopted=False, name="Lab 1",
               due_at=FRI.isoformat(timespec="seconds"), submitted=True)
    store.link("gradescope", 77, 999, "T1", adopted=True, name="Lab 1", due_at=None, submitted=False)
    remember(store, "T1", t1.content, completed=True)
    todoist = FakeTodoist([t1])
    report, store = sync(tmp_path, PROJECT_CFG, todoist, [item(1, "Lab 1", submitted=True)])
    assert report.completed == [] and not todoist.get_task("T1").is_completed
    assert store.tasks()["T1"].completed is True


def test_a_gradescope_made_twin_is_adopted_by_the_canvas_sync_instead_of_a_second_task(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    twin = FakeTask("G1", "EE 100: Lab 1 (Gradescope)", FakeDue(FRI), project_id="P-EE",
                    description="https://www.gradescope.com/courses/9/assignments/5")
    store.link("gradescope", 5, 9, "G1", adopted=False, name="Lab 1", due_at=None, submitted=False)
    remember(store, "G1", twin.content)
    todoist = FakeTodoist([twin])
    report, store = sync(tmp_path, PROJECT_CFG, todoist, [item(1, "Lab 1")])
    assert report.created == [] and report.adopted == ["Lab 1 → EE 100: Lab 1 (Gradescope)"]
    assert store.links()[("assignment", 1)].task_id == "G1"
    assert [t.content for t in todoist.all_tasks()] == ["EE 100: Lab 1 (Gradescope)"]
    report, _ = sync(tmp_path, PROJECT_CFG, todoist, [item(1, "Lab 1")])
    assert report.adopted == [] and not report.changed                                # linked now: quiet
