"""Repeating and all-day events (Faith, 2026-10-06: "juno said it can't create recurring events, fix that").

- add_event takes a repeat (daily, weekly, monthly, yearly), every N, weekdays, and an end: a date,
  a number of times, or by default the end of the current quarter (her choice).
- A date with no time is an all-day event; an end date is the last day, inclusive.
- delete_event can remove a whole series; undo puts it back, repeat rule and all.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from assistant.brief import Event
from assistant.chat_ops import ChatOps
from assistant.db import Store
from assistant.gcal import event_body
from fakes import FakeCalendar, FakeTodoist

TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 10, 6, 17, 0, tzinfo=timezone.utc)      # Tue Oct 6, 10:00am Pacific
QUARTER_ENDS = [date(2026, 12, 11), date(2027, 3, 19), date(2027, 6, 9), date(2027, 8, 14)]   # Stanford 2026-27 finals


def make(tmp_path, quarter_ends=QUARTER_ENDS):
    store = Store(tmp_path / "t.sqlite3")
    cal = FakeCalendar({})
    ops = ChatOps(store=store, todoist=FakeTodoist(), calendar=cal, tz=TZ, courses=["CME 102"], sections={},
                  classes_project_id="CLASSES", calendar_names=["Stanford", "TA", "faithclairvoyant333@gmail.com"], now=lambda: NOW,
                  quarter_ends=quarter_ends)
    return ops, cal, store


def only_body(cal):
    (body,) = cal.bodies.values()
    return body


# -- the body Google gets ------------------------------------------------------------------------

def test_event_body_for_all_day_events_and_repeats():
    body = event_body(title="Retreat", start=date(2026, 10, 10))
    assert body["start"] == {"date": "2026-10-10"} and body["end"] == {"date": "2026-10-11"}     # Google's end is exclusive
    body = event_body(title="Retreat", start=date(2026, 10, 10), end=date(2026, 10, 11))         # her end is the last day
    assert body["end"] == {"date": "2026-10-12"}
    body = event_body(title="x", start=datetime(2026, 10, 8, 15, 0, tzinfo=TZ), recurrence=["RRULE:FREQ=WEEKLY;COUNT=3"])
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;COUNT=3"] and "dateTime" in body["start"]


# -- add_event ------------------------------------------------------------------------------------

def test_a_weekly_event_until_a_date(tmp_path):
    ops, cal, store = make(tmp_path)
    reply = ops.add_event("CME 102 study block", "2026-10-08T15:00", "2026-10-08T16:00", calendar="Stanford",
                          repeat="weekly", until="2026-11-19")
    assert reply == "added: CME 102 study block, thu oct 8 3:00–4:00pm, every week until thu nov 19 (Stanford)"
    body = only_body(cal)
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;UNTIL=20261120T075959Z"]       # 11:59:59pm Pacific on nov 19, in UTC
    assert body["start"]["dateTime"] == "2026-10-08T15:00:00-07:00"


def test_with_no_end_it_stops_at_the_end_of_the_quarter(tmp_path):
    ops, cal, _ = make(tmp_path)
    reply = ops.add_event("CME 102 study block", "2026-10-08T15:00", calendar="Stanford", repeat="weekly")
    assert reply.endswith("every week until fri dec 11, the end of the quarter (Stanford)")
    assert only_body(cal)["recurrence"] == ["RRULE:FREQ=WEEKLY;UNTIL=20261212T075959Z"]


def test_a_start_after_finals_rolls_to_the_next_quarter_and_unknown_quarters_ask(tmp_path):
    ops, cal, _ = make(tmp_path)
    assert ops.add_event("Gym", "2026-12-15T07:00", repeat="daily").endswith("every day until fri mar 19, the end of the quarter (personal calendar)")
    ops, cal, _ = make(tmp_path, quarter_ends=[])
    assert ops.add_event("Gym", "2026-10-08T07:00", repeat="daily") == \
        "how long should it repeat? give an end date (until) or a number of times (count)"
    assert cal.bodies == {}


def test_weekdays_every_other_week_and_a_count(tmp_path):
    ops, cal, _ = make(tmp_path)
    reply = ops.add_event("SSIG sync", "2026-10-08T20:30", repeat="weekly", every=2, days=["mon", "Wednesday"], count=6)
    assert reply == "added: SSIG sync, mon oct 12 8:30–9:30pm, every 2 weeks on mon, wed, 6 times (personal calendar)"   # moved to the first monday
    body = only_body(cal)
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;COUNT=6"]
    assert body["start"]["dateTime"] == "2026-10-12T20:30:00-07:00"


def test_a_repeating_all_day_event(tmp_path):
    """Her 5:22pm ask: a tomato all-day "PSET DUE" on Stanford, every week."""
    ops, cal, _ = make(tmp_path)
    reply = ops.add_event("CME 102 PSET DUE", "2026-10-08", calendar="Stanford", color="tomato", repeat="weekly")
    assert reply == "added: CME 102 PSET DUE, thu oct 8 all day, every week until fri dec 11, the end of the quarter (Stanford, tomato)"
    body = only_body(cal)
    assert body["start"] == {"date": "2026-10-08"} and body["end"] == {"date": "2026-10-09"}
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;UNTIL=20261211"] and body["colorId"] == "11"


def test_a_one_off_all_day_event_over_two_days(tmp_path):
    ops, cal, _ = make(tmp_path)
    assert ops.add_event("SSS Retreat", "2026-10-10", "2026-10-11") == "added: SSS Retreat, sat oct 10 – sun oct 11 all day (personal calendar)"
    assert only_body(cal)["end"] == {"date": "2026-10-12"} and "recurrence" not in only_body(cal)


def test_monthly_and_bad_repeats_are_explained(tmp_path):
    ops, cal, _ = make(tmp_path)
    assert ops.add_event("Rent", "2026-11-01", repeat="monthly", until="2027-06-01").endswith("every month until tue jun 1 (personal calendar)")
    assert only_body(cal)["recurrence"] == ["RRULE:FREQ=MONTHLY;UNTIL=20270601"]
    errors = {
        "hourly": dict(repeat="hourly"),
        "days": dict(repeat="daily", days=["mon"]),
        "both": dict(repeat="weekly", until="2026-11-01", count=3),
        "before": dict(repeat="weekly", until="2026-10-01"),
        "funday": dict(repeat="weekly", days=["funday"]),
        "no repeat": dict(until="2026-11-01"),
        "every": dict(repeat="weekly", every=0),
    }
    replies = {k: ops.add_event("x", "2026-10-08T09:00", **kw) for k, kw in errors.items()}
    assert replies == {
        "hourly": "error: repeat must be daily, weekly, monthly or yearly",
        "days": "error: days only go with a weekly repeat",
        "both": "error: give an end date (until) or a number of times (count), not both",
        "before": "error: until is before the first one (thu oct 8)",
        "funday": "error: days must be weekdays like mon, tue, wed",
        "no repeat": "error: until, count, every and days need a repeat",
        "every": "error: every must be 1 or more",
    }
    assert ops.add_event("x", "2026-10-08", "2026-10-08T10:00") == "error: start and end must both be dates or both be times"
    assert len(cal.bodies) == 1


def test_undo_takes_the_whole_series_back(tmp_path):
    ops, cal, store = make(tmp_path)
    ops.add_event("CME 102 study block", "2026-10-08T15:00", repeat="weekly")
    (series_id,) = cal.bodies
    assert ops.undo() == "undone: deleted CME 102 study block"
    assert cal.deleted == [series_id]


# -- delete_event: one occurrence or the whole series ------------------------------------------------

def test_delete_every_occurrence_of_a_series_and_undo_brings_it_back(tmp_path):
    ops, cal, store = make(tmp_path)
    ops.add_event("CME 102 study block", "2026-10-08T15:00", calendar="Stanford", repeat="weekly")
    (series_id,) = cal.bodies
    first = cal.events.pop(series_id)                                           # google lists occurrences, not the series
    for day in (8, 15):
        cal.events[f"{series_id}_{day}"] = Event(first.title, datetime(2026, 10, day, 15, 0, tzinfo=TZ), datetime(2026, 10, day, 16, 0, tzinfo=TZ),
                                                 None, False, "Stanford", id=f"{series_id}_{day}", calendar_id="cal-stanford",
                                                 recurring_id=series_id)
    assert ops.delete_event("study block").startswith("which one?")             # two occurrences: which?
    assert ops.delete_event("study block", all_occurrences=True) == "deleted every CME 102 study block"
    assert cal.deleted[-1] == series_id
    assert ops.undo() == "undone: every CME 102 study block is back"
    restored = cal.bodies[max(cal.bodies, key=lambda k: int(k[2:]))]
    assert restored["recurrence"] == ["RRULE:FREQ=WEEKLY;UNTIL=20261212T075959Z"] and restored["summary"] == "CME 102 study block"
    assert "id" not in restored


def test_deleting_one_all_day_event_and_undo_keeps_it_all_day(tmp_path):
    ops, cal, store = make(tmp_path)
    ops.add_event("SSS Retreat", "2026-10-10")
    assert ops.delete_event("retreat") == "deleted: SSS Retreat (sat oct 10 all day)"
    assert ops.undo() == "undone: SSS Retreat is back on sat oct 10"
    restored = cal.bodies[max(cal.bodies, key=lambda k: int(k[2:]))]
    assert restored["start"] == {"date": "2026-10-10"} and restored["end"] == {"date": "2026-10-11"}
