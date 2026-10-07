"""Outlook meetings → your Google Calendar, from a published Outlook calendar link.

Outlook on the web can publish a calendar as a private ICS URL (Settings → Calendar → Shared
calendars → Publish a calendar). Anything on the Outlook calendar is in that feed, and an invite
lands on the calendar as *tentative* the moment it arrives, so "a meeting was sent to my
outlook" and "i put a meeting on my outlook calendar" look the same here. No Microsoft app
registration, nothing that expires; the URL is the secret and lives in `.env`.

Same shape as the other syncs: identity by Outlook UID (hashed to an int for `item_links`),
never delete. Every new item is copied straight to Google and juno texts what it added (until
2026-10-06 it asked first, and an unanswered question elsewhere kept an interview off her
calendar). A meeting she already put on Google by hand is linked, not copied. 30 minutes
before each Outlook meeting she gets a heads-up (`heads_up`, every 10 minutes).
A series is copied as a series (its RRULE and EXDATEs go straight to Google, in Faith's
timezone); an occurrence Outlook moved becomes a stand-alone event, and the series gets an
EXDATE for the original slot. Attendees are not in a published feed, and even if they were,
Google would email them: the copy is hers alone.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from icalendar import Calendar, vRecur

from .brief import Event, _span
from .calendar_sync import match_existing
from .db import Store

Send = Callable[[str], Awaitable[None]]
JOB_KIND = "outlook_new"
KIND = "outlook_event"
DECLINED_KEY = "outlook_declined"
GONE_KEY = "outlook_gone"
MAX_DESCRIPTION = 4000
HEADS_UP = timedelta(minutes=30)
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutlookEvent:
    uid: str                      # Outlook UID; a moved occurrence is "<uid>#<original start>"
    title: str
    start: datetime               # aware, in Faith's timezone (midnight for all-day)
    end: datetime
    all_day: bool
    location: str | None
    description: str | None
    busy: str                     # BUSY | TENTATIVE | FREE | OOF, as Outlook shows it
    rrule: str | None = None      # "FREQ=WEEKLY;BYDAY=WE" for a series master
    exdates: tuple[datetime, ...] = ()
    occurrence: bool = False      # one occurrence of a series that Outlook moved

    @property
    def key(self) -> int:
        """A stable 60-bit integer for `item_links`, which keys on ints."""
        return int(hashlib.sha1(self.uid.encode()).hexdigest()[:15], 16)

    @property
    def signature(self) -> str:
        """What a change looks like: title or time. Stored on the link, compared on every run."""
        kind = "series" if self.rrule else "single"
        return f"{self.title}|{self.start.isoformat()}|{self.end.isoformat()}|{kind}"


# -- parsing -----------------------------------------------------------------------------------

def _as_local(value, tz: ZoneInfo) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)      # floating time: assume hers
        return value.astimezone(tz), False
    return datetime.combine(value, time(0, 0), tzinfo=tz), True


def _text(component, name: str) -> str | None:
    value = component.get(name)
    text = str(value).strip() if value is not None else ""
    return text or None


def _rrule_text(rr: vRecur, *, tz: ZoneInfo) -> str:
    """Google wants UNTIL in UTC when the event has a time; Outlook sometimes sends a bare date."""
    rr = vRecur(rr)
    until = rr.get("UNTIL")
    if until:
        u = until[0]
        if not isinstance(u, datetime):
            u = datetime.combine(u, time(23, 59, 59), tzinfo=tz)
        elif u.tzinfo is None:
            u = u.replace(tzinfo=tz)
        rr["UNTIL"] = [u.astimezone(timezone.utc)]
    return rr.to_ical().decode()


def _until(rrule: str) -> datetime | None:
    until = vRecur.from_ical(rrule).get("UNTIL")
    if not until:
        return None
    u = until[0]
    if not isinstance(u, datetime):
        return datetime.combine(u, time(23, 59, 59), tzinfo=timezone.utc)
    return u if u.tzinfo else u.replace(tzinfo=timezone.utc)


def parse_ics(text: str, *, tz: ZoneInfo) -> list[OutlookEvent]:
    cal = Calendar.from_ical(text)
    out: list[OutlookEvent] = []
    masters: dict[str, tuple[dict, str, list[datetime]]] = {}
    moved_by_uid: dict[str, list[datetime]] = {}
    for ev in cal.walk("VEVENT"):
        uid = _text(ev, "UID")
        if not uid or "DTSTART" not in ev or str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        start, all_day = _as_local(ev.decoded("DTSTART"), tz)
        if "DTEND" in ev:
            end, _ = _as_local(ev.decoded("DTEND"), tz)
        elif "DURATION" in ev:
            end = start + ev.decoded("DURATION")
        else:
            end = start + (timedelta(days=1) if all_day else timedelta(hours=1))
        base = dict(
            title=_text(ev, "SUMMARY") or "(untitled)", start=start, end=end, all_day=all_day,
            location=_text(ev, "LOCATION"), description=(_text(ev, "DESCRIPTION") or "")[:MAX_DESCRIPTION] or None,
            busy=str(ev.get("X-MICROSOFT-CDO-BUSYSTATUS", "BUSY")).upper(),
        )
        if "RECURRENCE-ID" in ev:
            original, _ = _as_local(ev.decoded("RECURRENCE-ID"), tz)
            if original == start:
                continue                          # edited in place (notes, location): the series still covers it
            moved_by_uid.setdefault(uid, []).append(original)
            out.append(OutlookEvent(uid=f"{uid}#{original.isoformat()}", occurrence=True, **base))
            continue
        exdates: list[datetime] = []
        raw = ev.get("EXDATE")
        for prop in (raw if isinstance(raw, list) else [raw]) if raw is not None else []:
            exdates.extend(_as_local(d.dt, tz)[0] for d in prop.dts)
        rr = ev.get("RRULE")
        if rr is not None:
            masters[uid] = (base, _rrule_text(rr, tz=tz), exdates)
        else:
            out.append(OutlookEvent(uid=uid, **base))
    for uid, (base, rrule, exdates) in masters.items():
        skipped = tuple(sorted(set(exdates) | set(moved_by_uid.get(uid, []))))
        out.append(OutlookEvent(uid=uid, rrule=rrule, exdates=skipped, **base))
    return out


def in_window(events: list[OutlookEvent], *, now: datetime, before: timedelta = timedelta(days=1),
              after: timedelta = timedelta(days=120)) -> list[OutlookEvent]:
    """Upcoming items only. A series stays as long as it hasn't ended, however long ago it began."""
    lo, hi = now - before, now + after
    keep = []
    for e in events:
        if e.start > hi:
            continue
        if e.rrule:
            until = _until(e.rrule)
            if until is not None and until < lo:
                continue
        elif e.end < lo:
            continue
        keep.append(e)
    return keep


# -- the Google side -----------------------------------------------------------------------------

def recurrence_lines(ev: OutlookEvent, tz: ZoneInfo) -> list[str]:
    lines = [f"RRULE:{ev.rrule}"]
    if ev.exdates:
        if ev.all_day:
            lines.append("EXDATE;VALUE=DATE:" + ",".join(d.strftime("%Y%m%d") for d in ev.exdates))
        else:
            lines.append(f"EXDATE;TZID={tz}:" + ",".join(d.astimezone(tz).strftime("%Y%m%dT%H%M%S") for d in ev.exdates))
    return lines


def _times(ev: OutlookEvent, tz: ZoneInfo) -> dict:
    if ev.all_day:
        return {"start": {"date": ev.start.date().isoformat()}, "end": {"date": ev.end.date().isoformat()}}
    return {
        "start": {"dateTime": ev.start.astimezone(tz).isoformat(timespec="seconds"), "timeZone": str(tz)},
        "end": {"dateTime": ev.end.astimezone(tz).isoformat(timespec="seconds"), "timeZone": str(tz)},
    }


def outlook_body(ev: OutlookEvent, *, tz: ZoneInfo, note: str) -> dict:
    """The JSON Google expects, with everything Outlook told us and a note saying where it came from."""
    body: dict = {"summary": ev.title, **_times(ev, tz)}
    if ev.location:
        body["location"] = ev.location
    body["description"] = (ev.description + "\n\n" if ev.description else "") + note
    body["extendedProperties"] = {"private": {"outlook_uid": ev.uid}}
    if ev.rrule:
        body["recurrence"] = recurrence_lines(ev, tz)
    return body


def _cadence(rrule: str) -> str:
    rr = vRecur.from_ical(rrule)
    freq = str((rr.get("FREQ") or ["WEEKLY"])[0]).upper()
    n = int((rr.get("INTERVAL") or [1])[0])
    unit = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}.get(freq)
    if unit is None:
        return "repeating"
    if n == 1:
        return {"day": "daily", "week": "weekly", "month": "monthly", "year": "yearly"}[unit]
    return f"every {n} {unit}s"


def _dump(ev: OutlookEvent) -> dict:
    d = ev.__dict__.copy()
    d["start"], d["end"] = ev.start.isoformat(), ev.end.isoformat()
    d["exdates"] = [x.isoformat() for x in ev.exdates]
    return d


def _load(d: dict) -> OutlookEvent:
    return OutlookEvent(**{**d, "start": datetime.fromisoformat(d["start"]), "end": datetime.fromisoformat(d["end"]),
                           "exdates": tuple(datetime.fromisoformat(x) for x in d.get("exdates", []))})


def _split(task_id: str) -> tuple[str, str]:
    cal_id, _, event_id = task_id.partition("|")
    return cal_id, event_id


class OutlookSync:
    def __init__(self, *, fetch: Callable[[], str], calendar, store: Store, target_calendar: str,
                 search_calendars: list[str], tz: ZoneInfo, send: Send, now: Callable[[], datetime]):
        self.fetch = fetch                    # () -> ICS text; the real one GETs the published link
        self.calendar = calendar
        self.store = store
        self.target = target_calendar
        self.search_calendars = list(search_calendars)
        self.tz = tz
        self.send = send
        self.now = now

    # -- helpers ------------------------------------------------------------------

    def _target_id(self) -> str:
        ids = self.calendar.calendar_ids()
        if self.target not in ids:
            raise RuntimeError(f"no calendar named {self.target!r}")
        return ids[self.target]

    def _day(self, dt: datetime) -> str:
        return dt.astimezone(self.tz).strftime("%a %b %-d").lower()

    def _when(self, ev: OutlookEvent) -> str:
        if ev.all_day:
            return f"{self._day(ev.start)} all day"
        return f"{self._day(ev.start)} {_span(Event('', ev.start, ev.end, None, False, ''), self.tz)}"

    def _note(self, ev: OutlookEvent) -> str:
        tags = {"TENTATIVE": ", tentative (not responded to)", "FREE": ", marked free", "OOF": ", out of office"}
        return "from outlook" + tags.get(ev.busy, "")

    def _link(self, ev: OutlookEvent, calendar_id: str, event_id: str, *, adopted: bool) -> None:
        self.store.link(KIND, ev.key, None, f"{calendar_id}|{event_id}", adopted=adopted, name=ev.title,
                        due_at=ev.signature, submitted=False)

    def _kv_set_list(self, key: str, values) -> None:
        self.store.kv_set(key, json.dumps(sorted(values)))

    def _kv_list(self, key: str) -> set:
        return set(json.loads(self.store.kv_get(key) or "[]"))

    # -- the run ----------------------------------------------------------------------

    async def run(self, now: datetime | None = None, *, quiet: bool = False) -> str | None:
        """Sync once. Returns the text it sent (or would have sent, with quiet=True)."""
        now = now or self.now()
        try:
            text = await asyncio.to_thread(self.fetch)
            events = in_window(parse_ics(text, tz=self.tz), now=now)
        except Exception as e:
            log.warning("outlook: couldn't fetch or parse the calendar (%s: %s)", type(e).__name__, str(e)[:120])
            return f"outlook: couldn't fetch the calendar ({type(e).__name__})" if quiet else None

        links = {k[1]: v for k, v in self.store.links().items() if k[0] == KIND}
        by_key = {e.key: e for e in events}
        lo, hi = now - timedelta(days=1), now + timedelta(days=120)

        moved: list[str] = []
        for key, link in links.items():
            ev = by_key.get(key)
            if ev is None or link.due_at == ev.signature:
                continue
            cal_id, event_id = _split(link.task_id)
            try:
                await asyncio.to_thread(self.calendar.update_event, cal_id, event_id, {"summary": ev.title, **_times(ev, self.tz)})
            except Exception as e:
                log.warning("outlook: couldn't move %r on google (%s)", ev.title, type(e).__name__)
                continue
            self._link(ev, cal_id, event_id, adopted=link.adopted)
            moved.append(f"{ev.title} → {self._when(ev)}")

        reported = self._kv_list(GONE_KEY)
        gone: list[str] = []
        for key, link in links.items():
            if key in by_key:
                reported.discard(key)
                continue
            title, start_s, end_s, kind = (link.due_at or "|||").split("|")
            if kind != "single" or not start_s or key in reported:
                continue
            start, end = datetime.fromisoformat(start_s), datetime.fromisoformat(end_s)
            if end < lo or start > hi:
                continue                                 # simply in the past now, not gone
            reported.add(key)
            gone.append(f"{link.name} ({self._day(start)})")
        self._kv_set_list(GONE_KEY, reported)

        declined = self._kv_list(DECLINED_KEY)       # her "no" from when juno still asked: those stay off
        new = [e for e in events if e.key not in links and e.uid not in declined and (e.rrule or e.end > now)]
        added_text = None
        if new:
            linked_ids = {_split(l.task_id)[1] for l in links.values()}
            lo_m, hi_m = min(e.start for e in new) - timedelta(days=1), max(e.end for e in new) + timedelta(days=1)
            existing = await asyncio.to_thread(self.calendar.events_in_window, self.search_calendars, lo_m, hi_m, self.tz)
            candidates = [c for c in existing if c.id not in linked_ids]
            pairs: list[tuple[OutlookEvent, Event]] = []
            taken: set[str] = set()
            for ev in sorted(new, key=lambda e: (e.rrule is None, e.start)):   # a series claims her hand-made copy first
                m = match_existing(ev, "", [c for c in candidates if c.id not in taken], tz=self.tz)
                if m is not None:
                    pairs.append((ev, m))
                    taken.add(m.id)
            paired = {ev.key for ev, _ in pairs}
            fresh = [e for e in new if e.key not in paired]
            job = self.store.pending_job()
            if job is not None and job["kind"] == JOB_KIND:   # a question from when juno still asked: moot now
                self.store.kv_delete("pending_job")
            linked, added = await self._copy([(ev, m.calendar_id, m.id, m.title) for ev, m in pairs], fresh)
            added_text = self._added_text(linked, added)

        if added_text and not quiet:
            await self.send(added_text)
        report = None
        if moved or gone:
            lines = ["outlook"]
            if moved:
                lines.append(f"moved {len(moved)}:")
                lines += [f"  - {x}" for x in moved]
            if gone:
                lines.append("gone from your outlook calendar (left on google; say 'delete it' if it's really off):")
                lines += [f"  - {x}" for x in gone]
            report = "\n".join(lines)
            if not quiet:
                await self.send(report)
        return "\n\n".join(t for t in (added_text, report) if t) or None

    async def _copy(self, pairs: list[tuple[OutlookEvent, str, str, str]], fresh: list[OutlookEvent]):
        """Link her own copies (tagged so they're recognisable later) and copy the rest to the target
        calendar. One that Google refuses is left unlinked, so the next run tries it again."""
        linked: list[tuple[OutlookEvent, str]] = []
        for ev, cal_id, event_id, title in pairs:
            self._link(ev, cal_id, event_id, adopted=True)
            linked.append((ev, title))
            try:
                await asyncio.to_thread(self.calendar.update_event, cal_id, event_id,
                                        {"extendedProperties": {"private": {"outlook_uid": ev.uid}}})
            except Exception:
                pass
        added: list[OutlookEvent] = []
        if fresh:
            target_id = await asyncio.to_thread(self._target_id)
            for ev in fresh:
                try:
                    created = await asyncio.to_thread(self.calendar.create_event, target_id,
                                                      outlook_body(ev, tz=self.tz, note=self._note(ev)))
                except Exception as e:
                    log.warning("outlook: couldn't copy %r to google (%s)", ev.title, type(e).__name__)
                    continue
                self._link(ev, target_id, created["id"], adopted=False)
                added.append(ev)
        return linked, added

    def _item(self, ev: OutlookEvent) -> str:
        if ev.rrule:
            return f"- {ev.title}, {_cadence(ev.rrule)} from {self._when(ev)}"
        tag = " (moved occurrence)" if ev.occurrence else {"TENTATIVE": " (tentative)", "FREE": " (free)"}.get(ev.busy, "")
        return f"- {ev.title}, {self._when(ev)}{tag}"

    def _added_text(self, linked, added) -> str | None:
        if not linked and not added:
            return None
        lines = []
        if added:
            lines.append(f"outlook: added {len(added)} to your {self.target} calendar:")
            lines += [self._item(ev) for ev in sorted(added, key=lambda e: e.start)]
        if linked:
            lines.append("already on your calendar, now linked:" if added else
                         f"outlook: {len(linked)} meeting{'s' if len(linked) != 1 else ''} already on your calendar, now linked:")
            lines += [f"- {ev.title} ({ev.start.astimezone(self.tz).strftime('%a %b %-d %-I:%M%p').lower()}) → {title}"
                      for ev, title in linked]
        lines.append("i'll text you 30 min before each meeting. to take one off google, say delete and which one")
        return "\n".join(lines)

    # -- the heads-up ---------------------------------------------------------------------

    async def heads_up(self, now: datetime | None = None) -> list[str]:
        """A text 30 minutes before each Outlook meeting (its Google copy: her title, her place, every
        occurrence of a series), once per meeting time. Reads Google, not the feed, so a slow Outlook
        never costs her the reminder."""
        now = now or self.now()
        links = [_split(l.task_id) for k, l in self.store.links().items() if k[0] == KIND]
        if not links:
            return []
        ours = {event_id for _, event_id in links}
        # her own weekly copy is linked by the occurrence Google listed, "<series>_<time>" (plain ids have no "_")
        ours |= {event_id.rsplit("_", 1)[0] for event_id in ours if "_" in event_id}
        names = list(dict.fromkeys([self.target, *self.search_calendars]))
        try:
            soon = await asyncio.to_thread(self.calendar.events_in_window, names, now, now + HEADS_UP + timedelta(minutes=1), self.tz)
        except Exception as e:
            log.warning("outlook: couldn't read google for heads-ups (%s)", type(e).__name__)
            return []
        sent_before = self.store.sent_nudges()
        texts = []
        for e in soon:
            if e.all_day or not (e.id in ours or e.recurring_id in ours):
                continue
            lead = e.start - now
            if not timedelta(0) < lead <= HEADS_UP:
                continue
            key = f"outlook-heads-up:{e.id}:{e.start.isoformat()}"
            if key in sent_before:
                continue
            text = f"in {round(lead.total_seconds() / 60)} min: {e.title}, {_span(e, self.tz)}"
            if e.location:
                text += f" · {e.location}"
            await self.send(text)
            self.store.mark_nudge(key, at=now)
            texts.append(text)
        return texts

    # -- a question still out from when juno asked first (before 2026-10-06) ------------------------------------------------------------

    async def approve(self, payload: dict, approved: bool) -> str:
        pairs = payload.get("pairs", [])
        new = [_load(d) for d in payload.get("new", [])]
        if not approved:
            declined = self._kv_list(DECLINED_KEY) | {pr["event"]["uid"] for pr in pairs} | {e.uid for e in new}
            self._kv_set_list(DECLINED_KEY, declined)
            return "ok, skipped those. i'll only ask about new outlook meetings from now on"
        linked, added = await self._copy(
            [(_load(pr["event"]), pr["gcal_calendar_id"], pr["gcal_id"], pr.get("gcal_title", "")) for pr in pairs], new)
        n = len(linked)
        parts = []
        if n:
            parts.append(f"linked {n} existing event{'s' if n != 1 else ''}")
        parts.append(f"added {len(added)} to {self.target}" if added else "nothing new to add")
        return ", ".join(parts)
