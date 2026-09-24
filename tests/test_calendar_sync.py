"""Canvas calendar events → Google Calendar: matching against hand-made events, first-run proposal, then sync."""

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from assistant.brief import Event
from assistant.calendar_sync import CalendarSync, CanvasEvent, canvas_events_from_api, match_existing
from assistant.config import CoursesConfig
from assistant.db import Store
from fakes import FakeCalendar

pytestmark = pytest.mark.anyio
TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 23, 17, 0, tzinfo=timezone.utc)
EE310 = CoursesConfig.model_validate({"courses": [{"code": "EE 310", "canvas_id": 230601}, {"code": "CS 106B"}]})


@pytest.fixture
def anyio_backend():
    return "asyncio"


def cev(i, day, h, m=0, title="SystemX: Ubiquitous Sensing, Computing and Communication Seminar", course=230601, end_h=None):
    start = datetime(2026, 9, day, h, m, tzinfo=TZ)
    end = datetime(2026, 9, day, end_h, 0, tzinfo=TZ) if end_h else start + timedelta(hours=1)
    return CanvasEvent(i, course, title, start, end, "Zoom Online Meeting", "weekly seminar", f"https://canvas.stanford.edu/calendar?event_id={i}")


def gev(title, day, h, m=0, end_h=None, end_m=0, cal="Stanford", canvas_id=None):
    start = datetime(2026, 9, day, h, m, tzinfo=TZ)
    end = datetime(2026, 9, day, end_h, end_m, tzinfo=TZ) if end_h else start + timedelta(hours=1)
    return Event(title, start, end, "Blume 108", False, cal, canvas_id=canvas_id)


def test_canvas_events_from_api_objects():
    objs = [SimpleNamespace(id=884165, title="SystemX Seminar", start_at="2026-09-24T23:30:00Z", end_at="2026-09-25T00:30:00Z",
                            location_name="Zoom", description="<p>hi</p>", html_url="https://canvas.stanford.edu/calendar?event_id=884165",
                            context_code="course_230601", hidden=False),
            SimpleNamespace(id=1, title="all day thing", start_at="2026-09-24", end_at=None, context_code="course_230601")]
    evs = canvas_events_from_api(objs)
    assert len(evs) == 1                                                    # date-only / no time: skipped for now
    e = evs[0]
    assert (e.id, e.course_id, e.title, e.location) == (884165, 230601, "SystemX Seminar", "Zoom")
    assert e.start == datetime(2026, 9, 24, 16, 30, tzinfo=TZ) and e.end == datetime(2026, 9, 24, 17, 30, tzinfo=TZ)
    assert e.description == "hi"


def test_match_existing_by_course_code_or_title_within_an_hour():
    seminar = cev(884165, 24, 16, 30)
    mine = [gev("EE 310", 24, 16, 30, 17, 50), gev("CS 106B", 24, 16, 30), gev("EE 310", 17, 16, 30, 17, 50)]
    m = match_existing(seminar, "EE 310", mine, tz=TZ)
    assert m is mine[0]                                                     # same day, overlapping, course code in title
    assert match_existing(seminar, "EE 310", [gev("SystemX seminar (zoom)", 24, 16, 0)], tz=TZ) is not None   # title words
    assert match_existing(seminar, "EE 310", [gev("EE 310", 24, 9, 0)], tz=TZ) is None                     # too far apart
    assert match_existing(seminar, "EE 310", [gev("EE 310", 24, 16, 30, canvas_id=999)], tz=TZ) is None    # already linked elsewhere


class Outbox:
    def __init__(self):
        self.sent: list[str] = []

    async def __call__(self, text):
        self.sent.append(text)


def make_sync(tmp_path, canvas_events, gcal_events):
    store = Store(tmp_path / "t.sqlite3")
    cal = FakeCalendar({date(2026, 9, 24): gcal_events})
    out = Outbox()
    box = {"events": canvas_events}
    sync = CalendarSync(fetch_events=lambda start, end: box["events"], calendar=cal, store=store, courses_cfg=EE310,
                        target_calendar="Stanford", tz=TZ, send=out, now=lambda: NOW)
    return sync, store, cal, out, box


async def test_first_run_proposes_then_links_and_creates_on_yes(tmp_path):
    canvas = [cev(884165, 24, 16, 30), cev(884166, 25, 10, 0, title="EE 310 review session")]
    sync, store, cal, out, _ = make_sync(tmp_path, canvas, [gev("EE 310", 24, 16, 30, 17, 50)])
    await sync.run()
    assert len(out.sent) == 1
    text = out.sent[0]
    assert text.startswith("canvas calendar: 2 events for your courses.")
    assert "looks like an event you already have:\n- SystemX: Ubiquitous Sensing, Computing and Communication Seminar (thu sep 24 4:30pm) → EE 310" in text
    assert "new (i'd add to Stanford):\n- EE 310 review session, fri sep 25 10:00–11:00am" in text
    assert len(cal.events) == 1                                             # nothing written yet

    payload = json.loads(store.kv_get("pending_job"))["payload"]
    assert await sync.approve(payload, True) == "linked 1 existing event, added 1"
    assert store.links()[("canvas_event", 884165)].task_id == "ev1"
    created = next(e for e in cal.events.values() if e.title == "EE 310 review session")
    assert created.calendar_id == "cal-stanford" and created.start == datetime(2026, 9, 25, 10, 0, tzinfo=TZ)
    assert store.links()[("canvas_event", 884166)].task_id == created.id

    await sync.run()                                                        # idempotent
    assert len(out.sent) == 1 and len(cal.events) == 2


async def test_after_first_run_new_and_moved_events_are_applied_and_texted(tmp_path):
    sync, store, cal, out, box = make_sync(tmp_path, [cev(884165, 24, 16, 30)], [])
    store.kv_set("calendar_first_run_done", "1")
    await sync.run()
    assert [e.title for e in cal.events.values()] == ["SystemX: Ubiquitous Sensing, Computing and Communication Seminar"]
    assert out.sent[-1] == "canvas calendar\nadded 1:\n  - SystemX: Ubiquitous Sensing, Computing and Communication Seminar (thu sep 24 4:30–5:30pm)"
    box["events"] = [cev(884165, 24, 17, 0)]                                # canvas moved it half an hour later
    await sync.run()
    assert next(iter(cal.events.values())).start == datetime(2026, 9, 24, 17, 0, tzinfo=TZ)
    assert out.sent[-1] == "canvas calendar\nmoved 1:\n  - SystemX: Ubiquitous Sensing, Computing and Communication Seminar → thu sep 24 5:00–6:00pm"
    await sync.run()
    assert len(out.sent) == 2


async def test_declined_first_run_is_not_repeated_until_canvas_changes(tmp_path):
    sync, store, cal, out, box = make_sync(tmp_path, [cev(884165, 24, 16, 30)], [])
    await sync.run()
    payload = json.loads(store.kv_get("pending_job"))["payload"]
    assert await sync.approve(payload, False) == "ok, skipped. i'll only ask again if canvas adds events"
    await sync.run()
    assert len(out.sent) == 1 and cal.events == {}
    box["events"].append(cev(884166, 25, 10, 0))
    await sync.run()
    assert len(out.sent) == 2


async def test_unanswered_proposal_is_asked_once_until_canvas_changes(tmp_path):
    sync, store, cal, out, box = make_sync(tmp_path, [cev(884165, 24, 16, 30)], [])
    await sync.run()
    await sync.run()                                                        # still unanswered: don't nag every hour
    assert len(out.sent) == 1
    job = store.pending_job()
    assert job["question"] == out.sent[0] and job["asked_at"] == NOW.isoformat(timespec="seconds")
    box["events"].append(cev(884166, 25, 10, 0, title="EE 310 review session"))   # canvas added one: a new question
    await sync.run()
    assert len(out.sent) == 2 and "EE 310 review session" in out.sent[1]
