"""Google Calendar write helpers: the request body for an event, and ids on parsed events."""

from datetime import datetime
from zoneinfo import ZoneInfo

from assistant.gcal import event_body, events_from_api

TZ = ZoneInfo("America/Los_Angeles")


def test_event_body_carries_times_location_and_canvas_id():
    body = event_body(title="EE 310 Seminar", start=datetime(2026, 9, 24, 16, 30, tzinfo=TZ), end=datetime(2026, 9, 24, 17, 30, tzinfo=TZ),
                      location="Zoom", description="from canvas", canvas_id=884165, source_url="https://canvas.stanford.edu/calendar?event_id=884165")
    assert body["summary"] == "EE 310 Seminar" and body["location"] == "Zoom"
    assert body["start"] == {"dateTime": "2026-09-24T16:30:00-07:00", "timeZone": "America/Los_Angeles"}
    assert body["end"]["dateTime"] == "2026-09-24T17:30:00-07:00"
    assert body["extendedProperties"] == {"private": {"canvas_id": "884165"}}
    assert body["source"] == {"title": "Canvas", "url": "https://canvas.stanford.edu/calendar?event_id=884165"}
    assert "from canvas" in body["description"]


def test_event_body_defaults_end_to_one_hour_and_omits_empty_fields():
    body = event_body(title="Coffee", start=datetime(2026, 9, 24, 9, 0, tzinfo=TZ))
    assert body["end"]["dateTime"] == "2026-09-24T10:00:00-07:00"
    assert "location" not in body and "extendedProperties" not in body and "source" not in body


def test_parsed_events_keep_their_ids_and_calendar():
    items = [{"id": "abc", "status": "confirmed", "summary": "X", "start": {"dateTime": "2026-09-23T13:00:00-07:00"}, "end": {"dateTime": "2026-09-23T14:00:00-07:00"},
              "extendedProperties": {"private": {"canvas_id": "884165"}}}]
    (e,) = events_from_api(items, calendar="Stanford", tz=TZ, calendar_id="cal-1")
    assert e.id == "abc" and e.calendar_id == "cal-1" and e.canvas_id == 884165
