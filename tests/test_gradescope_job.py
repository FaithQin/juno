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
