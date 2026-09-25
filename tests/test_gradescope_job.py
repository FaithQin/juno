"""The Gradescope sync job: first run proposes, a yes applies, later runs create-then-text."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from assistant.config import Course, CoursesConfig
from assistant.db import Store
from assistant.gradescope_sync import GradescopeSync
from fakes import FakeTask, FakeTodoist
from test_gradescope import COURSE, DASHBOARD

pytestmark = pytest.mark.anyio
TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 24, 17, 0, tzinfo=timezone.utc)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeBrowser:
    def __init__(self, login=False):
        self.login = login
        self.opened: list[str] = []

    async def html(self, url):
        self.opened.append(url)
        if self.login:
            return "<html>login</html>", True
        if url.endswith("gradescope.com/"):
            return DASHBOARD, False
        if "/courses/1359455" in url:
            return COURSE, False
        return "<html><table id='assignments-student-table'><tbody></tbody></table></html>", False


class Outbox:
    def __init__(self):
        self.sent: list[str] = []

    async def __call__(self, text):
        self.sent.append(text)


def make_job(tmp_path, tasks, browser=None):
    store = Store(tmp_path / "t.sqlite3")
    todoist = FakeTodoist(tasks)
    cfg = CoursesConfig.model_validate({"courses": [{"code": "CME 102", "canvas_id": 232579}, {"code": "CS 106B"}, {"code": "MATSCI 88Q", "canvas_id": 232193}]})
    out = Outbox()
    job = GradescopeSync(browser=browser or FakeBrowser(), todoist=todoist, store=store, courses_cfg=cfg,
                         project_id="CLASSES", sections={"CME 102": "S3", "CS 106B": "S2", "MATSCI 88Q": "S4"},
                         tz=TZ, send=out, now=lambda: NOW)
    return job, store, todoist, out


async def test_first_run_proposes_matches_and_new_items_then_applies_on_yes(tmp_path):
    hand_made = FakeTask("T1", "CME 102: Pset 1 (Gradescope)", None, 1, "S3")
    job, store, todoist, out = make_job(tmp_path, [hand_made])

    await job.run()
    assert len(out.sent) == 1
    text = out.sent[0]
    assert text.startswith("gradescope: i found 1 open assignment across 1 course.")
    assert "looks like a task you already have:\n- Pset1 → CME 102: Pset 1 (Gradescope)" in text
    assert "reply yes to link and add" in text
    assert store.kv_get("pending_job") and "gradescope_first_run" in store.kv_get("pending_job")
    assert [t.content for t in todoist.tasks("CLASSES")] == ["CME 102: Pset 1 (Gradescope)"]   # nothing written yet

    import json
    payload = json.loads(store.kv_get("pending_job"))["payload"]
    reply = await job.approve(payload, True)
    assert reply == "linked 1 existing task, nothing new to add"
    assert ("gradescope", 8709892) in store.links() and store.links()[("gradescope", 8709892)].task_id == "T1"

    await job.run()                                  # second run: linked, nothing changed, no text
    assert len(out.sent) == 1


async def test_after_first_run_new_assignments_are_created_then_texted(tmp_path):
    job, store, todoist, out = make_job(tmp_path, [])
    store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    created = todoist.tasks("CLASSES")
    assert [t.content for t in created] == ["CME 102: Pset1 (Gradescope)"]
    assert created[0].section_id == "S3" and created[0].due.date == datetime(2026, 10, 2, 6, 59, tzinfo=timezone.utc)
    assert out.sent and out.sent[0].startswith("gradescope sync\nadded 1:")
    await job.run()
    assert len(out.sent) == 1                        # idempotent


async def test_declined_proposal_is_not_repeated_until_something_changes(tmp_path):
    job, store, todoist, out = make_job(tmp_path, [])
    await job.run()
    import json
    payload = json.loads(store.kv_get("pending_job"))["payload"]
    assert await job.approve(payload, False) == "ok, skipped. i'll only ask again if gradescope changes"
    await job.run()
    assert len(out.sent) == 1 and todoist.tasks("CLASSES") == []


async def test_expired_login_is_reported_once_a_day(tmp_path):
    job, store, todoist, out = make_job(tmp_path, [], browser=FakeBrowser(login=True))
    await job.run()
    await job.run()
    assert out.sent == ["gradescope logged me out. on your mac: uv run assistant browser-login gradescope, then scripts/deploy.sh"]


async def test_unanswered_proposal_is_asked_once(tmp_path):
    job, store, todoist, out = make_job(tmp_path, [])
    await job.run()
    await job.run()                                  # still unanswered: no repeat
    assert len(out.sent) == 1
    assert store.pending_job()["question"] == out.sent[0]
    assert await job.run(quiet=True) == out.sent[0]  # sync_now still learns what's waiting on her


async def test_waits_while_another_jobs_proposal_is_pending(tmp_path):
    job, store, todoist, out = make_job(tmp_path, [])
    store.propose_job("outlook_new", {"digest": "x"}, "outlook: 1 meeting. yes or no?", at=NOW)
    assert await job.run() is None and out.sent == [] and store.pending_job()["kind"] == "outlook_new"
    assert await job.run(quiet=True) == "gradescope: 1 open assignment to propose, once you've answered the outlook proposal"


# --- per-course Todoist sub-projects (2026-09-24) -------------------------------------------

PROJECT_COURSES = [{"code": "CME 102", "canvas_id": 232579, "project_id": "P-CME"},
                   {"code": "CS 106B", "project_id": "P-CS"},
                   {"code": "MATSCI 88Q", "canvas_id": 232193, "project_id": "P-MAT"}]
PSET2 = COURSE.replace("<tbody>", """<tbody>
<tr><th class="table--primaryLink"><button class="js-submitAssignment" data-assignment-id="8709893" data-assignment-title="Pset2">Pset2</button></th>
  <td class="submissionStatus"><div class="submissionStatus--text">No Submission</div></td>
  <td><time class="submissionTimeChart--dueDate" datetime="2026-10-08 23:59:00 -0700">Oct 08 at 11:59PM</time></td></tr>""", 1)


class GrowingBrowser(FakeBrowser):
    """CME 102 gains a second pset between the first and the second run."""

    def __init__(self):
        super().__init__()
        self.runs = 0

    async def html(self, url):
        if url.endswith("gradescope.com/"):
            self.runs += 1
        if "/courses/1359455" in url and self.runs > 1:
            self.opened.append(url)
            return PSET2, False
        return await super().html(url)


def make_project_job(tmp_path, tasks, *, courses=None, sections=None, browser=None):
    store = Store(tmp_path / "t.sqlite3")
    todoist = FakeTodoist(tasks)
    cfg = CoursesConfig.model_validate({"todoist": {"project_id": "CLASSES"}, "courses": courses or PROJECT_COURSES})
    out = Outbox()
    job = GradescopeSync(browser=browser or FakeBrowser(), todoist=todoist, store=store, courses_cfg=cfg,
                         project_id="CLASSES", sections={"CME 102": "S3"} if sections is None else sections,
                         tz=TZ, send=out, now=lambda: NOW)
    return job, store, todoist, out


async def test_new_gradescope_items_go_into_the_course_sub_project(tmp_path):
    job, store, todoist, out = make_project_job(tmp_path, [])
    store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    (t,) = todoist.tasks("P-CME")
    assert (t.content, t.section_id) == ("CME 102: Pset1 (Gradescope)", None)
    assert todoist.tasks("CLASSES") == [] and todoist.sections_created == []


async def test_first_run_pairs_a_hand_made_task_living_in_the_sub_project(tmp_path):
    hand_made = FakeTask("T1", "CME 102: Pset 1 (Gradescope)", project_id="P-CME")
    job, store, todoist, out = make_project_job(tmp_path, [hand_made])
    await job.run()
    assert "looks like a task you already have:\n- Pset1 → CME 102: Pset 1 (Gradescope)" in out.sent[0]
    assert "new (i'd add" not in out.sent[0]


async def test_first_run_mid_migration_pairs_a_task_still_in_the_old_section(tmp_path):
    not_moved = FakeTask("T1", "CME 102: Pset 1 (Gradescope)", section_id="S3")     # CME has a project; task not moved yet
    job, store, todoist, out = make_project_job(tmp_path, [not_moved])
    await job.run()
    assert "looks like a task you already have:\n- Pset1 → CME 102: Pset 1 (Gradescope)" in out.sent[0]


async def test_a_hand_made_gradescope_link_in_a_sub_project_is_adopted_not_duplicated(tmp_path):
    linked = FakeTask("T1", "pset one", project_id="P-CME",
                      description="https://www.gradescope.com/courses/1359455/assignments/8709892")
    job, store, todoist, out = make_project_job(tmp_path, [linked])
    store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    assert store.links()[("gradescope", 8709892)].task_id == "T1"
    assert [t.id for t in todoist.all_tasks()] == ["T1"] and out.sent == []


async def test_approving_the_first_run_creates_new_items_in_the_sub_project(tmp_path):
    import json

    job, store, todoist, out = make_project_job(tmp_path, [])
    await job.run()
    payload = json.loads(store.kv_get("pending_job"))["payload"]
    assert await job.approve(payload, True) == "linked 0 existing tasks, added 1"
    assert [(t.content, t.project_id, t.section_id) for t in todoist.all_tasks()] == [
        ("CME 102: Pset1 (Gradescope)", "P-CME", None)]
    assert todoist.sections_created == []


async def test_a_legacy_course_section_is_created_once_across_runs(tmp_path):
    legacy = [{"code": "CME 102", "canvas_id": 232579}]
    job, store, todoist, out = make_project_job(tmp_path, [], courses=legacy, sections={}, browser=GrowingBrowser())
    store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    await job.run()                                   # Pset2 appears: must reuse the section made on run 1
    assert [t.content for t in todoist.tasks("CLASSES")] == ["CME 102: Pset1 (Gradescope)", "CME 102: Pset2 (Gradescope)"]
    assert todoist.sections_created == [("CLASSES", "CME 102")]
    assert {t.section_id for t in todoist.tasks("CLASSES")} == {"S-CME 102"}


async def test_an_assignment_the_canvas_sync_already_made_is_adopted_not_twinned(tmp_path):
    canvas_made = FakeTask("T9", "CME 102: Pset1", project_id="P-CME",
                           description="https://canvas.stanford.edu/courses/232579/assignments/77")
    job, store, todoist, out = make_project_job(tmp_path, [canvas_made])
    store.kv_set("gradescope_first_run_done", "1")
    store.link("assignment", 77, 232579, "T9", adopted=False, name="Pset1", due_at=None, submitted=False)
    await job.run()
    assert [t.content for t in todoist.all_tasks()] == ["CME 102: Pset1"]                 # no "(Gradescope)" twin
    assert store.links()[("gradescope", 8709892)].task_id == "T9"
    assert out.sent[0].startswith("gradescope sync\nlinked 1 to tasks you already had:\n  - Pset1 → CME 102: Pset1")
    await job.run()
    assert len(out.sent) == 1


# --- hand-made tasks vs new Gradescope items, and Canvas twins (2026-09-24 audit) -------------

import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from assistant.canvas_client import CanvasItem  # noqa: E402
from assistant.sync import run_sync  # noqa: E402
from fakes import FakeCanvas, FakeDue  # noqa: E402

MAT_GS, CME_GS = 1399426, 1359455


def local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


def row(course, aid, name, due, *, submitted=False):
    if submitted:
        head = f'<a href="/courses/{course}/assignments/{aid}/submissions/1">{name}</a>'
        status = "Submitted"
    else:
        head = f'<button class="js-submitAssignment" data-assignment-id="{aid}">{name}</button>'
        status = "No Submission"
    return (f'<tr><th class="table--primaryLink">{head}</th><td class="submissionStatus">'
            f'<div class="submissionStatus--text">{status}</div></td><td><time class="submissionTimeChart--dueDate" '
            f'datetime="{due.strftime("%Y-%m-%d %H:%M:%S %z")}">x</time></td></tr>')


class PagesBrowser(FakeBrowser):
    """Gradescope with the course pages a test sets (and changes between runs)."""

    def __init__(self, pages):
        super().__init__()
        self.pages = pages

    async def html(self, url):
        self.opened.append(url)
        if url.endswith("gradescope.com/"):
            return DASHBOARD, False
        for course, rows in self.pages.items():
            if url.endswith(f"/courses/{course}"):
                return f"<table id='assignments-student-table'><tbody>{''.join(rows)}</tbody></table>", False
        return "<table id='assignments-student-table'><tbody></tbody></table>", False


PRE_LAB_2 = lambda **kw: row(MAT_GS, 8676500, "Lab 2: Pre Lab", local(2026, 10, 5, 12), **kw)  # noqa: E731


def hand_made_pre_lab_2():
    return FakeTask("H1", "MATSCI 88Q: Pre-lab 2 (Gradescope)", FakeDue(datetime(2026, 10, 5, 12, 0)), project_id="P-MAT",
                    description="For Lab 2 (Tue Oct 6). No late pre-labs.")


async def answer(job, store, approved):
    """What chat does with a yes/no: clear the proposal, then call the job's handler."""
    payload = store.pending_job()["payload"]
    store.kv_delete("pending_job")
    return await job.approve_match(payload, approved)


async def test_a_new_item_that_looks_like_a_hand_made_task_is_asked_about_not_created(tmp_path):
    browser = PagesBrowser({MAT_GS: [PRE_LAB_2()]})
    job, store, todoist, out = make_project_job(tmp_path, [hand_made_pre_lab_2()], browser=browser)
    store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    assert [t.id for t in todoist.all_tasks()] == ["H1"]                       # nothing made while she decides
    assert out.sent == ["gradescope: a new assignment looks like a task you already have:\n"
                        "- Lab 2: Pre Lab → MATSCI 88Q: Pre-lab 2 (Gradescope) (both due mon oct 5 12:00pm)\n"
                        "reply yes to link them (i'll tick it when you submit and follow gradescope's date changes), "
                        "or no to add it as a new task"]
    assert store.pending_job()["kind"] == "gradescope_match"
    assert ("gradescope", 8676500) not in store.links()
    await job.run()
    assert len(out.sent) == 1 and len(todoist.all_tasks()) == 1               # asked once; still waiting


async def test_yes_links_the_hand_made_task_so_submitting_ticks_it(tmp_path):
    browser = PagesBrowser({MAT_GS: [PRE_LAB_2()]})
    job, store, todoist, out = make_project_job(tmp_path, [hand_made_pre_lab_2()], browser=browser)
    store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    assert await answer(job, store, True) == "linked 1: Lab 2: Pre Lab → MATSCI 88Q: Pre-lab 2 (Gradescope)"
    link = store.links()[("gradescope", 8676500)]
    assert (link.task_id, link.adopted) == ("H1", True)
    await job.run()
    assert len(out.sent) == 1 and [t.id for t in todoist.all_tasks()] == ["H1"]
    browser.pages[MAT_GS] = [PRE_LAB_2(submitted=True)]
    await job.run()
    assert todoist.get_task("H1").is_completed
    assert out.sent[-1].startswith("gradescope sync\ncompleted 1")


async def test_yes_says_so_when_the_dates_differ_but_leaves_hers(tmp_path):
    mine = FakeTask("H2", "CME 102: Pset1 (Gradescope)", FakeDue(datetime(2026, 9, 30, 23, 59)), project_id="P-CME")
    job, store, todoist, out = make_project_job(tmp_path, [mine])              # Gradescope: Pset1 due thu oct 1 11:59pm
    store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    assert "- Pset1 → CME 102: Pset1 (Gradescope) (gradescope: thu oct 1 11:59pm, yours: wed sep 30 11:59pm)" in out.sent[0]
    reply = await answer(job, store, True)
    assert reply == ("linked 1: Pset1 → CME 102: Pset1 (Gradescope)\n"
                     "heads up: gradescope has CME 102: Pset1 (Gradescope) due thu oct 1 11:59pm, yours says wed sep 30 11:59pm. i left yours")
    assert todoist.get_task("H2").due.date == datetime(2026, 9, 30, 23, 59)


async def test_an_exact_title_hand_made_task_is_asked_about_too_never_linked_silently(tmp_path):
    mine = FakeTask("H2", "CME 102: Pset1 (Gradescope)", FakeDue(datetime(2026, 10, 1, 23, 59)), project_id="P-CME")
    job, store, todoist, out = make_project_job(tmp_path, [mine])
    store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    assert ("gradescope", 8709892) not in store.links()
    assert out.sent[0].startswith("gradescope: a new assignment looks like a task you already have:")


async def test_no_adds_it_as_its_own_task_and_is_not_asked_again(tmp_path):
    browser = PagesBrowser({MAT_GS: [PRE_LAB_2()]})
    job, store, todoist, out = make_project_job(tmp_path, [hand_made_pre_lab_2()], browser=browser)
    store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    assert await answer(job, store, False) == "ok, added it as a new task: MATSCI 88Q: Lab 2: Pre Lab (Gradescope)"
    assert sorted(t.content for t in todoist.all_tasks()) == ["MATSCI 88Q: Lab 2: Pre Lab (Gradescope)",
                                                              "MATSCI 88Q: Pre-lab 2 (Gradescope)"]
    await job.run()
    assert len(out.sent) == 1 and len(todoist.all_tasks()) == 2 and store.pending_job() is None


async def test_a_match_waits_behind_another_jobs_proposal_without_creating_a_twin(tmp_path):
    browser = PagesBrowser({MAT_GS: [PRE_LAB_2()]})
    job, store, todoist, out = make_project_job(tmp_path, [hand_made_pre_lab_2()], browser=browser)
    store.kv_set("gradescope_first_run_done", "1")
    store.propose_job("outlook_new", {"digest": "x"}, "outlook: 1 meeting. yes or no?", at=NOW)
    assert await job.run() is None and out.sent == [] and len(todoist.all_tasks()) == 1
    assert await job.run(quiet=True) == ("gradescope: 1 new assignment looks like a task you already have; "
                                         "i'll ask once you've answered the outlook proposal")


async def test_an_item_whose_canvas_twin_has_a_task_is_linked_to_it_by_id(tmp_path):
    canvas_made = FakeTask("C1", "MATSCI 88Q: Pre-lab 2", FakeDue(local(2026, 10, 5, 12)), project_id="P-MAT",
                           description="External tool on [Canvas](https://canvas.stanford.edu/courses/232193/assignments/828800)")
    browser = PagesBrowser({MAT_GS: [PRE_LAB_2()]})
    job, store, todoist, out = make_project_job(tmp_path, [canvas_made, hand_made_pre_lab_2()], browser=browser)
    store.kv_set("gradescope_first_run_done", "1")
    store.link("assignment", 828800, 232193, "C1", adopted=False, name="Pre-lab 2", due_at="2026-10-05T19:00:00+00:00",
               submitted=False)
    store.kv_set("gradescope_twins", json.dumps({"8676500": 828800}))
    await job.run()
    assert store.links()[("gradescope", 8676500)].task_id == "C1"
    assert out.sent == ["gradescope sync\nlinked 1 to tasks you already had:\n  - Lab 2: Pre Lab → MATSCI 88Q: Pre-lab 2"]
    assert store.pending_job() is None and len(todoist.all_tasks()) == 2


async def test_a_question_made_moot_by_a_canvas_twin_is_withdrawn(tmp_path):
    browser = PagesBrowser({MAT_GS: [PRE_LAB_2()]})
    job, store, todoist, out = make_project_job(tmp_path, [hand_made_pre_lab_2()], browser=browser)
    store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    assert store.pending_job()["kind"] == "gradescope_match"
    store.link("assignment", 828800, 232193, "H1", adopted=True, name="Pre-lab 2", due_at=None, submitted=False)  # the canvas sync adopted it
    store.kv_set("gradescope_twins", json.dumps({"8676500": 828800}))
    await job.run()
    assert store.links()[("gradescope", 8676500)].task_id == "H1" and store.pending_job() is None
    assert out.sent[-1] == ("gradescope sync\nlinked 1 to tasks you already had:\n  - Lab 2: Pre Lab → MATSCI 88Q: Pre-lab 2 (Gradescope)\n"
                            "notes:\n  - no need to answer my question about Lab 2: Pre Lab, that's sorted")


def settings_at(tmp_path):
    return SimpleNamespace(tz=TZ, complete_when_submitted=True, include_undated=False, batch_min_size=2,
                           db_path=tmp_path / "t.sqlite3", canvas_url="", canvas_token="", todoist_token="")


def canvas_pre_lab_2(**kw):
    return CanvasItem(kind="assignment", canvas_id=828800, course_id=232193, name="Pre-lab 2",
                      due_at=datetime(2026, 10, 5, 19, 0, tzinfo=timezone.utc),
                      html_url="https://canvas.stanford.edu/courses/232193/assignments/828800",
                      submission_types=("external_tool",), external_url="https://lti.int.turnitin.com/launch/gs-proxy",
                      group_id=None, group_name=None, submitted=False, published=True, gradescope_id=8676500, **kw)


async def test_canvas_first_then_gradescope_makes_one_task_with_both_ids(tmp_path):
    job, store, todoist, out = make_project_job(tmp_path, [], browser=PagesBrowser({MAT_GS: [PRE_LAB_2()]}))
    store.kv_set("gradescope_first_run_done", "1")
    report = run_sync(settings_at(tmp_path), job.courses_cfg, todoist=todoist, canvas=FakeCanvas([canvas_pre_lab_2()]), store=store)
    assert report.created == ["MATSCI 88Q: Pre-lab 2 (due Oct 5 12:00pm)"]
    (task,) = todoist.all_tasks()
    await job.run()
    assert [t.id for t in todoist.all_tasks()] == [task.id]
    assert store.links()[("gradescope", 8676500)].task_id == task.id == store.links()[("assignment", 828800)].task_id


async def test_other_jobs_name_the_match_question_when_they_wait_behind_it(tmp_path):
    browser = PagesBrowser({MAT_GS: [PRE_LAB_2()]})
    job, store, todoist, out = make_project_job(tmp_path, [hand_made_pre_lab_2()], browser=browser)
    store.kv_set("gradescope_first_run_done", "1")
    await job.run()
    assert store.proposal_slot("duplicates", "d") == "gradescope match"
