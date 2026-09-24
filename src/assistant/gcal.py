"""Google Calendar: one-time OAuth, then reading (and later writing) events.

`events_from_api()` is the pure part and is what the tests cover. The
`GoogleCalendar` class is a thin wrapper over the official client; run
`uv run assistant gcal-auth` once to create the token file.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .brief import Event

# Read everything, write events. Chosen in DECISIONS.md so Phase 3 needs no re-consent.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def _parse_point(obj: dict, tz: ZoneInfo) -> tuple[datetime, bool]:
    if obj.get("dateTime"):
        dt = datetime.fromisoformat(obj["dateTime"].replace("Z", "+00:00"))
        return dt.astimezone(tz), False
    return datetime.combine(date.fromisoformat(obj["date"]), time(0, 0), tzinfo=tz), True


def events_from_api(items: list[dict], *, calendar: str, tz: ZoneInfo, calendar_id: str | None = None) -> list[Event]:
    events: list[Event] = []
    for it in items:
        if it.get("status") == "cancelled" or "start" not in it:
            continue
        start, all_day = _parse_point(it["start"], tz)
        end = None
        if not all_day and it.get("end"):
            end, _ = _parse_point(it["end"], tz)
        private = (it.get("extendedProperties") or {}).get("private") or {}
        canvas_id = private.get("canvas_id")
        events.append(Event(
            title=(it.get("summary") or "").strip() or "(untitled)",
            start=start,
            end=end,
            location=it.get("location"),
            all_day=all_day,
            calendar=calendar,
            id=it.get("id"),
            calendar_id=calendar_id,
            description=it.get("description"),
            canvas_id=int(canvas_id) if str(canvas_id or "").isdigit() else None,
        ))
    return events


def event_body(*, title: str, start: datetime, end: datetime | None = None, location: str | None = None,
               description: str | None = None, canvas_id: int | None = None, source_url: str | None = None) -> dict:
    """The JSON Google expects for insert/patch. End defaults to one hour after start."""
    end = end or start + timedelta(hours=1)
    tzname = str(start.tzinfo) if isinstance(start.tzinfo, ZoneInfo) else "America/Los_Angeles"
    body: dict = {
        "summary": title,
        "start": {"dateTime": start.isoformat(timespec="seconds"), "timeZone": tzname},
        "end": {"dateTime": end.isoformat(timespec="seconds"), "timeZone": tzname},
    }
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    if canvas_id is not None:
        body["extendedProperties"] = {"private": {"canvas_id": str(canvas_id)}}
    if source_url:
        body["source"] = {"title": "Canvas", "url": source_url}
    return body


class GoogleCalendar:
    def __init__(self, credentials_path: Path, token_path: Path):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._service = None
        self._ids: dict[str, str] | None = None

    # -- auth ----------------------------------------------------------------

    def authorize(self) -> None:
        """Interactive: opens a browser once, then saves the refreshable token."""
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"{self.credentials_path} not found. Download the OAuth client JSON from Google Cloud "
                "(APIs & Services → Credentials → your Desktop client) and save it there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), SCOPES)
        creds = flow.run_local_server(port=0)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json())
        self.token_path.chmod(0o600)

    def _credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not self.token_path.exists():
            raise FileNotFoundError("Google token missing. Run: uv run assistant gcal-auth")
        creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.token_path.write_text(creds.to_json())
        return creds

    def service(self):
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build("calendar", "v3", credentials=self._credentials(), cache_discovery=False)
        return self._service

    # -- reads ---------------------------------------------------------------

    def calendar_ids(self) -> dict[str, str]:
        """Calendar display name → calendar id (cached per process)."""
        if self._ids is not None:
            return self._ids
        out: dict[str, str] = {}
        page = None
        while True:
            resp = self.service().calendarList().list(pageToken=page).execute()
            for c in resp.get("items", []):
                out[c.get("summaryOverride") or c.get("summary", "")] = c["id"]
                if c.get("primary"):
                    out.setdefault("primary", c["id"])
            page = resp.get("nextPageToken")
            if not page:
                self._ids = out
                return out

    def events_in_window(self, calendar_names: list[str], start: datetime, end: datetime, tz: ZoneInfo) -> list[Event]:
        ids = self.calendar_ids()
        events: list[Event] = []
        for name in calendar_names:
            cal_id = ids.get(name)
            if cal_id is None:
                continue
            events.extend(events_from_api(self.events_between(cal_id, start, end), calendar=name, tz=tz, calendar_id=cal_id))
        return sorted(events, key=lambda e: (not e.all_day, e.start))

    # -- writes --------------------------------------------------------------

    def get_event(self, calendar_id: str, event_id: str) -> dict:
        return self.service().events().get(calendarId=calendar_id, eventId=event_id).execute()

    def create_event(self, calendar_id: str, body: dict) -> dict:
        return self.service().events().insert(calendarId=calendar_id, body=body).execute()

    def update_event(self, calendar_id: str, event_id: str, patch: dict) -> dict:
        return self.service().events().patch(calendarId=calendar_id, eventId=event_id, body=patch).execute()

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self.service().events().delete(calendarId=calendar_id, eventId=event_id).execute()

    def events_between(self, calendar_id: str, start: datetime, end: datetime) -> list[dict]:
        items: list[dict] = []
        page = None
        while True:
            resp = self.service().events().list(
                calendarId=calendar_id, timeMin=start.isoformat(), timeMax=end.isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=250, pageToken=page,
            ).execute()
            items.extend(resp.get("items", []))
            page = resp.get("nextPageToken")
            if not page:
                return items

    def events_for_day(self, calendar_names: list[str], day: date, tz: ZoneInfo) -> list[Event]:
        ids = self.calendar_ids()
        start = datetime.combine(day, time(0, 0), tzinfo=tz)
        end = start + timedelta(days=1)
        events: list[Event] = []
        for name in calendar_names:
            cal_id = ids.get(name)
            if cal_id is None:
                continue  # misspelt in assistant.yaml; reported by `assistant check`
            events.extend(events_from_api(self.events_between(cal_id, start, end), calendar=name, tz=tz))
        return sorted(events, key=lambda e: (not e.all_day, e.start))
