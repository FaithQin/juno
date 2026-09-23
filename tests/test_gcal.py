"""Google Calendar: turning API JSON into Event objects (pure; the network part is thin)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from assistant.gcal import events_from_api

TZ = ZoneInfo("America/Los_Angeles")

API_ITEMS = [
    {
        "id": "a", "status": "confirmed", "summary": "CME 102 MATLAB Tutorial (TA Yifa Yu)",
        "location": "Wallenberg Hall, 450 Jane Stanford Way #B40, Stanford, CA 94305",
        "start": {"dateTime": "2026-09-23T13:00:00-07:00", "timeZone": "America/Los_Angeles"},
        "end": {"dateTime": "2026-09-23T14:30:00-07:00", "timeZone": "America/Los_Angeles"},
    },
    {
        "id": "b", "status": "confirmed", "summary": "Democracy Day",
        "start": {"date": "2026-09-23"}, "end": {"date": "2026-09-24"},
    },
    {
        "id": "c", "status": "cancelled", "summary": "Gone",
        "start": {"dateTime": "2026-09-23T15:00:00-07:00"}, "end": {"dateTime": "2026-09-23T16:00:00-07:00"},
    },
    {
        "id": "d", "status": "confirmed",
        "start": {"dateTime": "2026-09-23T09:00:00Z"}, "end": {"dateTime": "2026-09-23T09:30:00Z"},
    },
]


def test_events_from_api_handles_timed_all_day_cancelled_and_untitled():
    events = events_from_api(API_ITEMS, calendar="TA", tz=TZ)
    assert [e.title for e in events] == ["CME 102 MATLAB Tutorial (TA Yifa Yu)", "Democracy Day", "(untitled)"]
    timed, allday, untitled = events
    assert timed.start == datetime(2026, 9, 23, 13, 0, tzinfo=TZ) and timed.end == datetime(2026, 9, 23, 14, 30, tzinfo=TZ)
    assert timed.all_day is False and timed.location.startswith("Wallenberg Hall") and timed.calendar == "TA"
    assert allday.all_day is True and allday.start == datetime(2026, 9, 23, 0, 0, tzinfo=TZ) and allday.end is None
    assert untitled.start == datetime(2026, 9, 23, 2, 0, tzinfo=TZ)   # 09:00Z is 2:00am Pacific
