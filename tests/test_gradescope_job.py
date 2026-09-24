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
