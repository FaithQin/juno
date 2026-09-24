"""Scheduled jobs: nudges, morning brief, hourly sync. Each takes its collaborators as arguments."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from assistant.brief import Event
from assistant.jobs import run_brief_job, run_nudges_job, run_sync_job
from assistant.sync import Report
from fakes import FakeDue, FakeTask
from test_chat_ops import SAMPLE, make_ops

pytestmark = pytest.mark.anyio
TZ = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Outbox:
    def __init__(self):
        self.sent: list[str] = []

    async def __call__(self, text):
        self.sent.append(text)


async def test_nudges_job_sends_once_and_records(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    out = Outbox()
    now = datetime(2026, 9, 24, 20, 5, tzinfo=TZ)          # Thu 8:05pm: eve nudge for Fri's quizzes
    await run_nudges_job(ops, store, send=out, now=now, scan_interval=timedelta(minutes=10))
    assert out.sent == ["due tomorrow 11:59pm: ENGR 40M quizzes 2–8 (fri 11:59pm)"]
    assert "T2:eve" in store.sent_nudges()
    assert store.kv_get("last_scan") == now.isoformat(timespec="seconds")
    await run_nudges_job(ops, store, send=out, now=now + timedelta(minutes=10), scan_interval=timedelta(minutes=10))
    assert len(out.sent) == 1


async def test_nudges_job_explains_an_offline_gap(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    out = Outbox()
    now = datetime(2026, 9, 25, 14, 59, tzinfo=TZ)          # Fri 2:59pm; eve nudge was due Thu 8pm
    store.kv_set("last_scan", (now - timedelta(hours=6)).isoformat(timespec="seconds"))
    await run_nudges_job(ops, store, send=out, now=now, scan_interval=timedelta(minutes=10))
    assert out.sent[0].startswith("heads up, i was offline from fri 8:59am to fri 2:59pm")


async def test_brief_job_covers_every_dated_task_and_recent_overdue_only(tmp_path):
    ev = Event("CME 102", datetime(2026, 9, 23, 9, 30, tzinfo=TZ), datetime(2026, 9, 23, 10, 20, tzinfo=TZ), "Oshman Hall", False, "Stanford")
    extra = [
        FakeTask("T6", "Breakfast", FakeDue(datetime(2026, 9, 23, 15, 15, tzinfo=timezone.utc)), 1, None, project_id="OTHER"),  # p4, today 8:15am
        FakeTask("T7", "ancient thing", FakeDue(date(2026, 9, 10)), 1, None, project_id="OTHER"),                            # overdue 13 days
    ]
    ops, store, _ = make_ops(tmp_path, SAMPLE + extra, {date(2026, 9, 23): [ev]})
    out = Outbox()
    await run_brief_job(ops, send=out, now=datetime(2026, 9, 23, 7, 0, tzinfo=TZ))
    text = out.sent[0]
    lines = text.splitlines()
    assert lines[0] == "morning. wed sep 23"
    assert "  9:30–10:20am · CME 102 · Oshman Hall" in lines
    assert "due today" in lines and "  - 12:00pm · ENGR 40M: Sign up for a lab section" in lines
    assert "  - 8:15am · Breakfast" in lines            # every dated task, not just school or p1/p2
    assert "overdue" in lines and "  - CME 102: Find HW due dates (tue)" in lines
    assert "ancient thing" not in text                   # overdue older than 7 days is left to Todoist


async def test_sync_job_texts_only_when_something_changed(tmp_path):
    out = Outbox()

    def quiet():
        return Report(dry_run=False)

    def busy():
        r = Report(dry_run=False)
        r.created.append("EE 310: attendance (due Sep 24 5:30pm)")
        return r

    await run_sync_job(run=quiet, send=out)
    assert out.sent == []
    await run_sync_job(run=busy, send=out)
    assert out.sent == ["sync\nadded 1:\n  - EE 310: attendance (due Sep 24 5:30pm)"]


async def test_brief_job_survives_a_disconnected_calendar(tmp_path):
    from test_chat_ops import BrokenCalendar

    ops, store, _ = make_ops(tmp_path, SAMPLE)
    ops.calendar = BrokenCalendar()
    out = Outbox()
    await run_brief_job(ops, send=out, now=datetime(2026, 9, 23, 7, 0, tzinfo=TZ))
    assert out.sent and out.sent[0].splitlines()[2] == "  no events"


def http_error(status: int):
    import httpx
    req = httpx.Request("GET", "https://api.todoist.com/api/v1/tasks")
    return httpx.HTTPStatusError("boom", request=req, response=httpx.Response(status, request=req))


class Naps:
    def __init__(self):
        self.taken: list[float] = []

    async def __call__(self, seconds):
        self.taken.append(seconds)


async def test_brief_job_rides_out_a_todoist_hiccup(tmp_path):
    ops, store, todoist = make_ops(tmp_path, SAMPLE)
    real, failures = todoist.all_tasks, []

    def flaky():
        if len(failures) < 2:
            failures.append(1)
            raise http_error(503)
        return real()

    todoist.all_tasks = flaky
    out, naps = Outbox(), Naps()
    await run_brief_job(ops, send=out, now=datetime(2026, 9, 23, 7, 0, tzinfo=TZ), sleep=naps)
    assert naps.taken == [5, 20] and out.sent[0].startswith("morning. wed sep 23")


async def test_brief_job_says_so_when_todoist_stays_down(tmp_path):
    ops, store, todoist = make_ops(tmp_path, SAMPLE)

    def down():
        raise http_error(503)

    todoist.all_tasks = down
    out, naps = Outbox(), Naps()
    await run_brief_job(ops, send=out, now=datetime(2026, 9, 23, 7, 0, tzinfo=TZ), sleep=naps)
    assert len(naps.taken) == 5
    assert out.sent == ["no brief this morning: todoist isn't answering (503 Service Unavailable). ask me what's due once it's back"]


async def test_nudges_job_skips_a_scan_quietly_when_todoist_is_down(tmp_path):
    ops, store, todoist = make_ops(tmp_path, SAMPLE)

    def down(project_id):
        raise http_error(502)

    todoist.tasks = down
    out, naps = Outbox(), Naps()
    now = datetime(2026, 9, 24, 20, 5, tzinfo=TZ)
    await run_nudges_job(ops, store, send=out, now=now, sleep=naps)       # no exception, no text
    assert out.sent == [] and naps.taken == [5, 20] and store.kv_get("last_scan") is None
