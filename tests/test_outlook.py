"""Outlook meetings → Google Calendar, from a published Outlook calendar link (ICS).

Every new item on the Outlook calendar (invites arrive there as tentative) is proposed over
Telegram; a yes copies it to the Stanford calendar with everything Outlook knows about it.
"""

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from assistant.brief import Event
from assistant.db import Store
from assistant.outlook_sync import OutlookSync, in_window, outlook_body, parse_ics
from fakes import FakeCalendar

pytestmark = pytest.mark.anyio
TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 24, 17, 0, tzinfo=timezone.utc)      # Thu Sep 24, 10:00am Pacific

VTZ = """BEGIN:VTIMEZONE
TZID:Pacific Standard Time
BEGIN:STANDARD
DTSTART:16011104T020000
RRULE:FREQ=YEARLY;BYDAY=1SU;BYMONTH=11
TZOFFSETFROM:-0700
TZOFFSETTO:-0800
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010311T020000
RRULE:FREQ=YEARLY;BYDAY=2SU;BYMONTH=3
TZOFFSETFROM:-0800
TZOFFSETTO:-0700
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VTIMEZONE
TZID:Eastern Standard Time
BEGIN:STANDARD
DTSTART:16011104T020000
RRULE:FREQ=YEARLY;BYDAY=1SU;BYMONTH=11
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010311T020000
RRULE:FREQ=YEARLY;BYDAY=2SU;BYMONTH=3
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
END:DAYLIGHT
END:VTIMEZONE
"""

TIM = """BEGIN:VEVENT
UID:tim-uid
SUMMARY:Faith <> Tim
DTSTART;TZID=Pacific Standard Time:20260925T090000
DTEND;TZID=Pacific Standard Time:20260925T093000
LOCATION:https://meet.google.com/xyz
DESCRIPTION:Intro chat\\nBring questions
STATUS:CONFIRMED
X-MICROSOFT-CDO-BUSYSTATUS:TENTATIVE
END:VEVENT
"""

SSIG = """BEGIN:VEVENT
UID:ssig-uid
SUMMARY:SSIG Weekly Leadership Sync
DTSTART;TZID=Eastern Standard Time:20260930T233000
DTEND;TZID=Eastern Standard Time:20261001T003000
LOCATION:https://stanford.zoom.us/j/1
RRULE:FREQ=WEEKLY;BYDAY=WE
EXDATE;TZID=Eastern Standard Time:20261021T233000
STATUS:CONFIRMED
X-MICROSOFT-CDO-BUSYSTATUS:BUSY
END:VEVENT
BEGIN:VEVENT
UID:ssig-uid
RECURRENCE-ID;TZID=Eastern Standard Time:20261007T233000
SUMMARY:SSIG Weekly Leadership Sync
DTSTART;TZID=Eastern Standard Time:20261008T233000
DTEND;TZID=Eastern Standard Time:20261009T003000
STATUS:CONFIRMED
X-MICROSOFT-CDO-BUSYSTATUS:BUSY
END:VEVENT
"""

RETREAT = """BEGIN:VEVENT
UID:retreat-uid
SUMMARY:SSS Retreat
DTSTART;VALUE=DATE:20261010
DTEND;VALUE=DATE:20261011
X-MICROSOFT-CDO-ALLDAYEVENT:TRUE
STATUS:CONFIRMED
X-MICROSOFT-CDO-BUSYSTATUS:FREE
END:VEVENT
"""

OLD = """BEGIN:VEVENT
UID:old-uid
SUMMARY:Last year's thing
DTSTART;TZID=Pacific Standard Time:20250925T100000
DTEND;TZID=Pacific Standard Time:20250925T110000
STATUS:CONFIRMED
X-MICROSOFT-CDO-BUSYSTATUS:BUSY
END:VEVENT
BEGIN:VEVENT
UID:ended-uid
SUMMARY:Ended series
DTSTART;TZID=Pacific Standard Time:20250901T100000
DTEND;TZID=Pacific Standard Time:20250901T110000
RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20260101T000000Z
STATUS:CONFIRMED
X-MICROSOFT-CDO-BUSYSTATUS:BUSY
END:VEVENT
"""


def ics(*events: str) -> str:
    return "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Microsoft Exchange Server 2010//EN\n" + VTZ + "".join(events) + "END:VCALENDAR\n"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_parse_ics_converts_zones_splits_exceptions_and_keeps_series_rules():
    evs = {e.uid: e for e in parse_ics(ics(TIM, SSIG, RETREAT), tz=TZ)}
    tim = evs["tim-uid"]
    assert tim.start == datetime(2026, 9, 25, 9, 0, tzinfo=TZ) and tim.end == datetime(2026, 9, 25, 9, 30, tzinfo=TZ)
    assert tim.busy == "TENTATIVE" and tim.location == "https://meet.google.com/xyz" and tim.description == "Intro chat\nBring questions"
    series = evs["ssig-uid"]
    assert series.start == datetime(2026, 9, 30, 20, 30, tzinfo=TZ)                  # 11:30pm Eastern is 8:30pm Pacific
    assert series.rrule == "FREQ=WEEKLY;BYDAY=WE"
    assert series.exdates == (datetime(2026, 10, 7, 20, 30, tzinfo=TZ), datetime(2026, 10, 21, 20, 30, tzinfo=TZ))   # the moved one + the cancelled one
    moved = evs["ssig-uid#2026-10-07T20:30:00-07:00"]
    assert moved.start == datetime(2026, 10, 8, 20, 30, tzinfo=TZ) and moved.rrule is None
    retreat = evs["retreat-uid"]
    assert retreat.all_day and retreat.start.date() == date(2026, 10, 10) and retreat.busy == "FREE"
    assert len({e.key for e in evs.values()}) == 4                                    # keys are stable ints, one per item


def test_in_window_drops_the_past_and_ended_series_but_keeps_live_series():
    evs = in_window(parse_ics(ics(TIM, SSIG, RETREAT, OLD), tz=TZ), now=NOW)
    assert {e.title for e in evs} == {"Faith <> Tim", "SSIG Weekly Leadership Sync", "SSS Retreat"}
    assert len(evs) == 4                                                            # series master, its moved occurrence, tim, retreat


def test_outlook_body_carries_everything_google_needs():
    series = next(e for e in parse_ics(ics(SSIG), tz=TZ) if e.rrule)
    body = outlook_body(series, tz=TZ, note="from outlook")
    assert body["summary"] == "SSIG Weekly Leadership Sync"
    assert body["start"] == {"dateTime": "2026-09-30T20:30:00-07:00", "timeZone": "America/Los_Angeles"}
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=WE", "EXDATE;TZID=America/Los_Angeles:20261007T203000,20261021T203000"]
    assert body["extendedProperties"]["private"]["outlook_uid"] == "ssig-uid" and body["location"] == "https://stanford.zoom.us/j/1"
    assert body["description"].endswith("from outlook")
    retreat = parse_ics(ics(RETREAT), tz=TZ)[0]
    body = outlook_body(retreat, tz=TZ, note="from outlook")
    assert body["start"] == {"date": "2026-10-10"} and body["end"] == {"date": "2026-10-11"}


class Outbox:
    def __init__(self):
        self.sent: list[str] = []

    async def __call__(self, text):
        self.sent.append(text)


def make_sync(tmp_path, feed: str, gcal_events=None):
    store = Store(tmp_path / "t.sqlite3")
    cal = FakeCalendar({date(2026, 9, 25): gcal_events or []})
    out = Outbox()
    box = {"ics": feed, "fail": False}

    def fetch():
        if box["fail"]:
            raise ConnectionError("outlook is down")
        return box["ics"]

    sync = OutlookSync(fetch=fetch, calendar=cal, store=store, target_calendar="Stanford", search_calendars=["Stanford", "TA"],
                       tz=TZ, send=out, now=lambda: NOW)
    return sync, store, cal, out, box


async def test_first_run_proposes_matches_and_new_items_then_copies_on_yes(tmp_path):
    hand_made = Event("Faith / Tim intro", datetime(2026, 9, 25, 9, 0, tzinfo=TZ), datetime(2026, 9, 25, 9, 30, tzinfo=TZ), None, False, "Stanford")
    sync, store, cal, out, _ = make_sync(tmp_path, ics(TIM, SSIG, RETREAT, OLD), [hand_made])
    await sync.run()
    await sync.run()                                                            # still unanswered: asked once
    assert len(out.sent) == 1
    text = out.sent[0]
    assert text.splitlines()[0] == "outlook: 4 upcoming meetings aren't on your google calendar yet."
    assert "looks like one you already have:\n- Faith <> Tim (fri sep 25 9:00am) → Faith / Tim intro" in text
    assert "new (i'd add to Stanford):" in text
    assert "- SSIG Weekly Leadership Sync, weekly from wed sep 30 8:30–9:30pm" in text
    assert "- SSIG Weekly Leadership Sync, thu oct 8 8:30–9:30pm (moved occurrence)" in text
    assert "- SSS Retreat, sat oct 10 all day (free)" in text
    assert text.endswith("reply yes to add them, or no to skip these (i'll still ask about new ones)")
    assert len(cal.events) == 1                                                 # nothing written yet

    payload = json.loads(store.kv_get("pending_job"))["payload"]
    assert await sync.approve(payload, True) == "linked 1 existing event, added 3 to Stanford"
    links = {k[1]: v for k, v in store.links().items() if k[0] == "outlook_event"}
    assert len(links) == 4
    series = next(e for e in cal.events.values() if e.title == "SSIG Weekly Leadership Sync" and e.start.day == 30)
    body = cal.bodies[series.id]
    assert body["recurrence"][0] == "RRULE:FREQ=WEEKLY;BYDAY=WE" and series.calendar_id == "cal-stanford"
    assert body["description"].endswith("from outlook")
    tim_patch = next(p for p in cal.patches if p[1] == "ev1")
    assert tim_patch[2] == {"extendedProperties": {"private": {"outlook_uid": "tim-uid"}}}   # the hand-made one is tagged
    retreat = next(e for e in cal.events.values() if e.title == "SSS Retreat")
    assert cal.bodies[retreat.id]["description"].endswith("from outlook, marked free")

    await sync.run()                                                            # idempotent
    assert len(out.sent) == 1 and len(cal.events) == 4


async def test_declined_items_are_not_asked_again_but_a_new_invite_is(tmp_path):
    sync, store, cal, out, box = make_sync(tmp_path, ics(TIM))
    await sync.run()
    payload = json.loads(store.kv_get("pending_job"))["payload"]
    assert await sync.approve(payload, False) == "ok, skipped those. i'll only ask about new outlook meetings from now on"
    await sync.run()
    assert len(out.sent) == 1 and cal.events == {}
    box["ics"] = ics(TIM, RETREAT)
    await sync.run()
    assert len(out.sent) == 2
    assert out.sent[1].splitlines()[0] == "outlook: 1 upcoming meeting isn't on your google calendar yet."
    assert "SSS Retreat" in out.sent[1] and "Faith <> Tim" not in out.sent[1]


async def test_after_approval_moves_are_applied_and_disappearances_reported_once(tmp_path):
    sync, store, cal, out, box = make_sync(tmp_path, ics(TIM, RETREAT))
    await sync.run()
    await sync.approve(json.loads(store.kv_get("pending_job"))["payload"], True)
    box["ics"] = ics(TIM.replace("T090000", "T100000").replace("T093000", "T103000"), RETREAT)
    await sync.run()
    tim = next(e for e in cal.events.values() if e.title == "Faith <> Tim")
    assert tim.start == datetime(2026, 9, 25, 10, 0, tzinfo=TZ)
    assert out.sent[-1] == "outlook\nmoved 1:\n  - Faith <> Tim → fri sep 25 10:00–10:30am"
    box["ics"] = ics(TIM.replace("T090000", "T100000").replace("T093000", "T103000"))
    await sync.run()
    assert out.sent[-1] == ("outlook\ngone from your outlook calendar (left on google; say 'delete it' if it's really off):\n"
                            "  - SSS Retreat (sat oct 10)")
    n = len(out.sent)
    await sync.run()
    assert len(out.sent) == n and len(cal.deleted) == 0                        # reported once; never deleted


async def test_quiet_run_returns_the_question_for_sync_now_and_a_dead_feed_is_quiet(tmp_path):
    sync, store, cal, out, box = make_sync(tmp_path, ics(TIM))
    text = await sync.run(quiet=True)
    assert text.startswith("outlook: 1 upcoming meeting") and out.sent == []
    assert store.pending_job()["kind"] == "outlook_new"
    box["fail"] = True
    assert await sync.run() is None and out.sent == []
    assert await sync.run(quiet=True) == "outlook: couldn't fetch the calendar (ConnectionError)"


def test_an_occurrence_edited_but_not_moved_is_left_to_the_series():
    unmoved = SSIG.replace("DTSTART;TZID=Eastern Standard Time:20261008T233000", "DTSTART;TZID=Eastern Standard Time:20261007T233000") \
                  .replace("DTEND;TZID=Eastern Standard Time:20261009T003000", "DTEND;TZID=Eastern Standard Time:20261008T003000")
    evs = parse_ics(ics(unmoved), tz=TZ)
    assert [e.uid for e in evs] == ["ssig-uid"]                                   # no stand-alone copy of it
    assert evs[0].exdates == (datetime(2026, 10, 21, 20, 30, tzinfo=TZ),)         # and no EXDATE for its slot


async def test_a_series_claims_a_hand_made_event_before_its_moved_occurrence_does(tmp_path):
    """Her hand-made weekly copy should link to the series, not to a single moved occurrence."""
    hand_made = Event("SSIG Weekly Leadership Sync", datetime(2026, 10, 8, 20, 30, tzinfo=TZ), datetime(2026, 10, 8, 21, 30, tzinfo=TZ), None, False, "Stanford")
    series_on_oct_8 = SSIG.replace("20260930T233000", "20261008T233000").replace("20261001T003000", "20261009T003000")
    sync, store, cal, out, _ = make_sync(tmp_path, ics(series_on_oct_8), [hand_made])
    await sync.run()
    text = out.sent[0]
    assert "- SSIG Weekly Leadership Sync (thu oct 8 8:30pm) → SSIG Weekly Leadership Sync" in text
    assert "weekly from" not in text and "(moved occurrence)" in text            # the series is the match; the occurrence is new


async def test_waits_while_another_jobs_proposal_is_pending(tmp_path):
    """One proposal at a time: a bare yes must never land on the wrong question."""
    sync, store, cal, out, box = make_sync(tmp_path, ics(TIM))
    store.propose_job("calendar_first_run", {"digest": "x"}, "canvas calendar: 10 events. yes or no?", at=NOW)
    await sync.run()
    assert out.sent == [] and store.pending_job()["kind"] == "calendar_first_run"
    text = await sync.run(quiet=True)
    assert text == "outlook: 1 meeting to propose, once you've answered the canvas calendar proposal"
