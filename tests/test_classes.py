"""Faith's class changes. 2026-10-03: EE 160A is a graded class; EE 227 (CS 227A), EE 260A and AA 274A
are audits; MATSCI 88Q and EE 310 were dropped. juno knows all of them, syncs and nudges only graded
ones, and says so once when Canvas or Todoist shows a class it doesn't know.

2026-10-06: auditing is over ("im done auditing lectures"), so the three audits moved to the dropped
list as ended audits, and EE 160A got its Canvas site (231155, shared with AA 174A and CS 137A)."""

import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from assistant.config import CoursesConfig, load_courses
from assistant.course_watch import CourseWatch, find_changes
from assistant.db import Store
from fakes import FakeDue, FakeTask
from test_chat_ops import make_ops

TZ = ZoneInfo("America/Los_Angeles")
REPO_COURSES = Path(__file__).resolve().parents[1] / "courses.yaml"
CFG = CoursesConfig.model_validate({
    "todoist": {"project_id": "CLASSES"},
    "courses": [
        {"code": "ENGR 40M", "canvas_id": 231533, "project_id": "P-ENGR"},
        {"code": "EE 160A", "project_id": "P-160A"},
        {"code": "EE 227", "aliases": ["CS 227A"], "audit": True, "project_id": "P-227"},
        {"code": "AA 274A", "aliases": ["AA 174A"], "audit": True},
    ],
    "dropped": [{"code": "MATSCI 88Q", "dropped_on": "2026-09-30"}, {"code": "EE 310", "dropped_on": "2026-10-02"}],
})


def test_courses_config_knows_graded_audited_and_dropped_classes():
    assert [c.code for c in CFG.graded()] == ["ENGR 40M", "EE 160A"]
    assert [c.code for c in CFG.audits()] == ["EE 227", "AA 274A"]
    assert CFG.alias_map() == {"CS 227A": "EE 227", "AA 174A": "AA 274A"}
    assert [(d.code, d.dropped_on) for d in CFG.dropped] == [("MATSCI 88Q", date(2026, 9, 30)), ("EE 310", date(2026, 10, 2))]
    audit_on_canvas = CoursesConfig.model_validate({"courses": [{"code": "EE 227", "canvas_id": 231675, "audit": True}]})
    assert audit_on_canvas.by_canvas_id() == {}                                     # audits never sync from Canvas


def test_the_repo_courses_yaml_matches_her_classes():
    """Her graded load on 2026-10-06, 20 units: CS 106B, CME 102, ENGR 40M, EE 100, EE 160A. No audits."""
    cfg = load_courses(REPO_COURSES)
    assert [c.code for c in cfg.courses] == ["ENGR 40M", "CME 102", "EE 100", "CS 106B", "EE 160A"]
    assert cfg.audits() == []
    assert cfg.alias_map() == {"AA 174A": "EE 160A", "CS 137A": "EE 160A"}           # one Canvas site, three codes
    assert [(d.code, d.audit) for d in cfg.dropped] == [("MATSCI 88Q", False), ("EE 310", False),
                                                        ("EE 227", True), ("EE 260A", True), ("AA 274A", True)]
    assert {d.dropped_on for d in cfg.dropped if d.audit} == {date(2026, 10, 6)}
    assert cfg.course_projects()["EE 160A"] == "6hg9Mmh6R7Q68H7M"
    assert set(cfg.by_canvas_id()) == {231533, 232579, 232825, 231155}               # EE 160A's assignments sync now
    assert cfg.by_canvas_id()[231155].code == "EE 160A"
    assert set(cfg.calendar_courses()) == {231533, 232579, 232825}                   # its 55 Canvas events wait for her say


def ops_for_classes(tmp_path, tasks=()):
    from assistant.app import course_kwargs

    ops, store, todoist = make_ops(tmp_path, list(tasks))
    kw = course_kwargs(CFG)
    ops.courses, ops.audit_codes, ops.course_aliases, ops.dropped = kw["courses"], set(kw["audits"]), kw["aliases"], kw["dropped"]
    return ops, store, todoist


def test_the_context_tells_graded_audited_and_dropped_classes_apart(tmp_path):
    ops, *_ = ops_for_classes(tmp_path)
    ctx = ops.context_block().splitlines()
    assert "courses: ENGR 40M, EE 160A" in ctx
    assert "auditing (not graded; no nudges or synced assignments): EE 227 (also CS 227A), AA 274A (also AA 174A)" in ctx
    assert "dropped: MATSCI 88Q (sep 30), EE 310 (oct 2)" in ctx


def test_an_alias_names_its_course_and_audits_get_no_nudges(tmp_path):
    hw = FakeTask("H", "EE 227: HW1 (Gradescope)", FakeDue(datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)), project_id="P-227")
    lab = FakeTask("L", "ENGR 40M: Lab 1", FakeDue(datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)), project_id="P-ENGR")
    ops, store, todoist = ops_for_classes(tmp_path, [hw, lab])
    ops.project_by_course = {"ENGR 40M": "P-ENGR", "EE 160A": "P-160A", "EE 227": "P-227"}
    ops.course_by_project = {v: k for k, v in ops.project_by_course.items()}
    ops.class_project_ids = ["CLASSES", "P-ENGR", "P-160A", "P-227"]
    assert ops.tasks_overview("all", course="cs 227a").splitlines() == ["ee 227:", "- wed sep 23 5:00pm EE 227: HW1 (Gradescope)"]
    assert [t.content for t in ops.due_tasks()] == ["EE 227: HW1 (Gradescope)", "ENGR 40M: Lab 1"]
    assert [t.content for t in ops.nudge_tasks()] == ["ENGR 40M: Lab 1"]
    assert ops.add_task("reading", course="aa 174a").startswith("added: AA 274A: reading")


async def test_the_gradescope_sync_skips_audited_courses(tmp_path):
    from test_gradescope_job import FakeBrowser, Outbox
    from assistant.gradescope_sync import GradescopeSync
    from fakes import FakeTodoist

    cfg = CoursesConfig.model_validate({"courses": [{"code": "CME 102", "canvas_id": 232579, "audit": True}]})
    browser = FakeBrowser()
    job = GradescopeSync(browser=browser, todoist=FakeTodoist([]), store=Store(tmp_path / "t.sqlite3"), courses_cfg=cfg,
                         project_id="CLASSES", sections={}, tz=TZ, send=Outbox(), now=lambda: datetime(2026, 9, 24, 17, tzinfo=timezone.utc))
    job.store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    assert browser.opened == ["https://www.gradescope.com/"]                       # the dashboard only; no course page read


@pytest.fixture
def anyio_backend():
    return "asyncio"


pytestmark = pytest.mark.anyio

CANVAS_NOW = [
    (231533, "F26-ENGR-40M-01", "An Intro to Making: What is EE"),
    (231705, "F26-AA-274A-01/AA-174A-01", "Principles of Robot Autonomy I"),
    (231155, "F26-AA-174A-01", "Principles of Robot Autonomy I"),
    (231675, "F26-EE-227-01/CS-227A-01", "Robot Perception"),
    (211733, "Understanding the Fundamental Standard and Honor Code for Undergraduates 2025-2026", "Honor Code"),
]
PROJECTS = [SimpleNamespace(id="CLASSES", name="Classes", parent_id=None), SimpleNamespace(id="P-ENGR", name="ENGR 40M", parent_id="CLASSES"),
            SimpleNamespace(id="P-160A", name="EE 160A", parent_id="CLASSES"), SimpleNamespace(id="P-227", name="EE 227", parent_id="CLASSES"),
            SimpleNamespace(id="P-MAT", name="MATSCI 88Q", parent_id="CLASSES"), SimpleNamespace(id="P-X", name="Clubs", parent_id=None)]


def test_find_changes_is_quiet_when_juno_knows_every_class():
    assert find_changes(canvas_courses=CANVAS_NOW, projects=PROJECTS, courses_cfg=CFG, parent_id="CLASSES") == []


def test_find_changes_spots_new_classes_and_a_dropped_one():
    canvas = [c for c in CANVAS_NOW if c[0] != 231533] + [(240001, "F26-PHYSICS-43-01", "Electricity and Magnetism")]
    projects = PROJECTS + [SimpleNamespace(id="P-NEW", name="EE 101A", parent_id="CLASSES")]
    assert find_changes(canvas_courses=canvas, projects=projects, courses_cfg=CFG, parent_id="CLASSES") == [
        ("canvas:240001", "canvas lists PHYSICS 43 (Electricity and Magnetism), which juno doesn't know as a class"),
        ("todoist:P-NEW", "todoist has a project 'EE 101A' under Classes that juno doesn't know as a class"),
        ("gone:ENGR 40M", "canvas no longer lists ENGR 40M; if you dropped it, juno should stop syncing it"),
    ]


async def test_the_class_check_texts_each_change_once(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    sent = []

    async def send(text):
        sent.append(text)

    box = {"canvas": CANVAS_NOW + [(240001, "F26-PHYSICS-43-01", "Electricity and Magnetism")]}
    watch = CourseWatch(fetch_canvas=lambda: box["canvas"], fetch_projects=lambda: PROJECTS, courses_cfg=CFG,
                        parent_id="CLASSES", store=store, send=send)
    await watch.run()
    await watch.run()
    assert sent == ["class check:\n- canvas lists PHYSICS 43 (Electricity and Magnetism), which juno doesn't know as a class\n"
                    "juno's class list lives in courses.yaml; ask claude code to change it"]
    box["canvas"] = CANVAS_NOW                                                        # gone again: forgotten, so a return is news
    await watch.run()
    assert json.loads(store.kv_get("course_watch_seen")) == []


# --- 2026-10-06: audits ended, EE 160A on Canvas --------------------------------------------------

ENDED = CoursesConfig.model_validate({
    "todoist": {"project_id": "CLASSES"},
    "courses": [{"code": "ENGR 40M", "canvas_id": 231533, "project_id": "P-ENGR"},
                {"code": "EE 160A", "canvas_id": 231155, "aliases": ["AA 174A", "CS 137A"], "canvas_events": False, "project_id": "P-160A"}],
    "dropped": [{"code": "MATSCI 88Q", "dropped_on": "2026-09-30"},
                {"code": "EE 227", "aliases": ["CS 227A"], "dropped_on": "2026-10-06", "audit": True},
                {"code": "AA 274A", "dropped_on": "2026-10-06", "audit": True}],
})


def test_ended_audits_are_history_not_classes():
    assert [c.code for c in ENDED.courses] == ["ENGR 40M", "EE 160A"] and ENDED.audits() == []
    assert [(d.code, d.audit, d.aliases) for d in ENDED.dropped] == [
        ("MATSCI 88Q", False, []), ("EE 227", True, ["CS 227A"]), ("AA 274A", True, [])]
    assert set(ENDED.by_canvas_id()) == {231533, 231155} and set(ENDED.calendar_courses()) == {231533}


def test_the_context_says_she_stopped_auditing_rather_than_dropped(tmp_path):
    from assistant.app import course_kwargs

    ops, *_ = make_ops(tmp_path, [])
    kw = course_kwargs(ENDED)
    ops.courses, ops.audit_codes, ops.course_aliases = kw["courses"], set(kw["audits"]), kw["aliases"]
    ops.dropped, ops.ended_audits = kw["dropped"], kw["ended_audits"]
    ctx = ops.context_block().splitlines()
    assert "courses: ENGR 40M, EE 160A (also AA 174A, CS 137A)" in ctx              # cross-listed codes of a graded class
    assert not any(line.startswith("auditing") for line in ctx)
    assert "dropped: MATSCI 88Q (sep 30)" in ctx
    assert "stopped auditing (no more audits): EE 227 / CS 227A (oct 6), AA 274A (oct 6)" in ctx


def test_the_class_check_knows_a_canvas_site_by_its_id_whatever_code_canvas_shows():
    """Canvas names the shared Robot Autonomy site after its first listing, cut short: "F26-AA-174A-01..."."""
    canvas = [(231533, "F26-ENGR-40M-01", "An Intro to Making: What is EE"), (231155, "F26-AA-174A-01...", "Principles of Robot Autonomy I")]
    no_alias = CoursesConfig.model_validate({"courses": [{"code": "ENGR 40M", "canvas_id": 231533}, {"code": "EE 160A", "canvas_id": 231155}]})
    assert find_changes(canvas_courses=canvas, projects=[], courses_cfg=no_alias, parent_id="CLASSES") == []
    gone_audit = [(231675, "F26-EE-227-01/CS-227A-01", "Robot Perception")]           # an ended audit's site, if it lingers
    assert find_changes(canvas_courses=canvas + gone_audit, projects=[], courses_cfg=ENDED, parent_id="CLASSES") == []


def test_ed_finds_a_class_under_its_cross_listed_code(tmp_path):
    """Ed lists EE 160A's forum as "AA 174A 01" (course 106110)."""
    from assistant.ed import EdCourse

    class Ed:
        def courses(self):
            return [EdCourse(106894, "AA 274A 01", "Principles of Robot Autonomy I", "active", "2026", "Autumn"),
                    EdCourse(106110, "AA 174A 01", "Principles of Robot Autonomy I", "active", "2026", "Autumn")]

        def threads(self, course_id, *, limit=30, sort="new"):
            assert course_id == 106110
            return []

    ops, *_ = make_ops(tmp_path, [])
    ops.courses, ops.course_aliases, ops.ed = ["EE 160A"], {"AA 174A": "EE 160A", "CS 137A": "EE 160A"}, Ed()
    assert ops.ed_announcements("ee 160a") == "no announcements or pinned posts in EE 160A right now"
    assert ops.ed_announcements("cs 137a") == "no announcements or pinned posts in EE 160A right now"
