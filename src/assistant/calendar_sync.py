"""Canvas calendar events (exams, review sessions, seminars) → your Google Calendar.

Same shape as the Gradescope job: identity by Canvas event id (stored on the Google
event as a private property and in `item_links`), never delete, and a first run that
proposes instead of writing, because you already entered a lot of this by hand.

Matching a Canvas event to a hand-made one is deliberately narrow: same day, starts
within an hour, and either your course code is in the title or the titles share a real
word. Anything looser would link the wrong things; anything narrower misses "EE 310"
standing in for "SystemX: … Seminar".
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from .brief import Event, _span
from .config import Course, CoursesConfig
from .db import Store
from .gcal import event_body

Send = Callable[[str], Awaitable[None]]
JOB_KIND = "calendar_first_run"
KIND = "canvas_event"
STOPWORDS = {"the", "and", "for", "with", "session", "meeting", "online", "class", "lecture"}


@dataclass(frozen=True)
class CanvasEvent:
    id: int
    course_id: int
    title: str
    start: datetime
    end: datetime | None
    location: str | None
    description: str | None
    html_url: str


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", text.lower()) if w not in STOPWORDS}


def _parse_ts(value: str | None) -> datetime | None:
    if not value or "T" not in value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def canvas_events_from_api(objs) -> list[CanvasEvent]:
    """canvasapi CalendarEvent objects → CanvasEvent. Date-only events are skipped for now."""
    out: list[CanvasEvent] = []
    for o in objs:
        if getattr(o, "hidden", False):
            continue
        start = _parse_ts(getattr(o, "start_at", None))
        if start is None:
            continue
        m = re.match(r"course_(\d+)", getattr(o, "context_code", "") or "")
        if not m:
            continue
        desc = re.sub(r"<[^>]+>", "", getattr(o, "description", None) or "").strip() or None
        out.append(CanvasEvent(
            id=int(o.id), course_id=int(m[1]), title=(getattr(o, "title", "") or "").strip(),
            start=start, end=_parse_ts(getattr(o, "end_at", None)), location=getattr(o, "location_name", None) or None,
            description=desc, html_url=getattr(o, "html_url", "") or "",
        ))
    return out


def match_existing(ev: CanvasEvent, course_code: str, candidates: list[Event], *, tz: ZoneInfo) -> Event | None:
    best: tuple[float, Event] | None = None
    code = _squash(course_code)
    ev_words = _words(ev.title)
    for c in candidates:
        if c.all_day or c.canvas_id is not None:
            continue
        if c.start.astimezone(tz).date() != ev.start.astimezone(tz).date():
            continue
        gap = abs((c.start - ev.start).total_seconds())
        if gap > 3600:
            continue
        title = c.title
        if not (code and code in _squash(title)) and not (ev_words & _words(title)):
            continue
        if best is None or gap < best[0]:
            best = (gap, c)
    return best[1] if best else None


class CalendarSync:
    def __init__(self, *, fetch_events: Callable[[datetime, datetime], list[CanvasEvent]], calendar, store: Store,
                 courses_cfg: CoursesConfig, target_calendar: str, tz: ZoneInfo, send: Send, now: Callable[[], datetime]):
        self.fetch_events = fetch_events
        self.calendar = calendar
        self.store = store
        self.courses_cfg = courses_cfg
        self.target = target_calendar
        self.tz = tz
        self.send = send
        self.now = now

    # -- helpers ----------------------------------------------------------------

    def _course_for(self) -> dict[int, Course]:
        return self.courses_cfg.calendar_courses()      # graded courses with canvas_events on; audits never sync

    def _target_id(self) -> str:
        ids = self.calendar.calendar_ids()
        if self.target not in ids:
            raise RuntimeError(f"no calendar named {self.target!r}")
        return ids[self.target]

    def _when(self, start: datetime, end: datetime | None) -> str:
        day = start.astimezone(self.tz).strftime("%a %b %-d").lower()
        return f"{day} {_span(Event('', start, end, None, False, ''), self.tz)}"

    def _body(self, ev: CanvasEvent, course: Course) -> dict:
        desc = f"{course.code} · from Canvas: {ev.html_url}" + (f"\n\n{ev.description}" if ev.description else "")
        return event_body(title=ev.title, start=ev.start.astimezone(self.tz), end=ev.end.astimezone(self.tz) if ev.end else None,
                          location=ev.location, description=desc, canvas_id=ev.id, source_url=ev.html_url)

    def _link(self, ev: CanvasEvent, gcal_id: str, *, adopted: bool) -> None:
        self.store.link(KIND, ev.id, ev.course_id, gcal_id, adopted=adopted, name=ev.title, due_at=ev.start.isoformat(), submitted=False)

    # -- the run ------------------------------------------------------------------

    async def run(self, now: datetime | None = None) -> None:
        now = now or self.now()
        course_for = self._course_for()
        fetched = await asyncio.to_thread(self.fetch_events, now - timedelta(days=7), now + timedelta(days=120))
        events = [e for e in fetched if e.course_id in course_for]
        if not events:
            return
        target_id = await asyncio.to_thread(self._target_id)
        links = {k: v for k, v in self.store.links().items() if k[0] == KIND}
        lo = min(e.start for e in events) - timedelta(days=1)
        hi = max(e.end or e.start for e in events) + timedelta(days=1)
        existing = await asyncio.to_thread(self.calendar.events_in_window, [self.target], lo, hi, self.tz)
        unlinked = [e for e in events if (KIND, e.id) not in links]

        if not self.store.kv_get("calendar_first_run_done"):
            pairs: list[tuple[CanvasEvent, Event]] = []
            taken: set[str] = set()
            for ev in unlinked:
                m = match_existing(ev, course_for[ev.course_id].code, [c for c in existing if c.id not in taken], tz=self.tz)
                if m is not None:
                    pairs.append((ev, m))
                    taken.add(m.id)
            paired = {ev.id for ev, _ in pairs}
            new = [ev for ev in unlinked if ev.id not in paired]
            if not pairs and not new:
                self.store.kv_set("calendar_first_run_done", "1")
            else:
                digest = hashlib.sha1(",".join(str(e.id) for e in sorted(unlinked, key=lambda e: e.id)).encode()).hexdigest()
                if self.store.kv_get("calendar_declined_digest") == digest:
                    return
                payload = {
                    "digest": digest,
                    "pairs": [{"id": ev.id, "course_id": ev.course_id, "title": ev.title, "start": ev.start.isoformat(),
                               "gcal_id": m.id, "gcal_calendar_id": m.calendar_id, "gcal_title": m.title} for ev, m in pairs],
                    "new": [{"id": ev.id, "course_id": ev.course_id, "title": ev.title, "start": ev.start.isoformat(),
                             "end": ev.end.isoformat() if ev.end else None, "location": ev.location, "description": ev.description,
                             "html_url": ev.html_url} for ev in new],
                }
                if self.store.proposal_slot(JOB_KIND, digest) != "free":
                    return                                   # asked already, or another job's question is out first
                question = self._question(len(events), pairs, new)
                self.store.propose_job(JOB_KIND, payload, question, at=now)
                await self.send(question)
                return

        added: list[str] = []
        moved: list[str] = []
        for ev in unlinked:
            created = await asyncio.to_thread(self.calendar.create_event, target_id, self._body(ev, course_for[ev.course_id]))
            self._link(ev, created["id"], adopted=False)
            added.append(f"{ev.title} ({self._when(ev.start, ev.end)})")
        for ev in events:
            link = links.get((KIND, ev.id))
            if link is None or link.due_at is None or link.due_at == ev.start.isoformat():
                continue
            patch = {"start": {"dateTime": ev.start.astimezone(self.tz).isoformat(timespec="seconds"), "timeZone": str(self.tz)}}
            if ev.end:
                patch["end"] = {"dateTime": ev.end.astimezone(self.tz).isoformat(timespec="seconds"), "timeZone": str(self.tz)}
            try:
                await asyncio.to_thread(self.calendar.update_event, target_id, link.task_id, patch)
            except Exception:
                continue
            self._link(ev, link.task_id, adopted=link.adopted)
            moved.append(f"{ev.title} → {self._when(ev.start, ev.end)}")
        if added or moved:
            lines = ["canvas calendar"]
            if added:
                lines.append(f"added {len(added)}:")
                lines += [f"  - {x}" for x in added]
            if moved:
                lines.append(f"moved {len(moved)}:")
                lines += [f"  - {x}" for x in moved]
            await self.send("\n".join(lines))

    def _question(self, total: int, pairs, new) -> str:
        lines = [f"canvas calendar: {total} event{'s' if total != 1 else ''} for your courses."]
        if pairs:
            lines.append(f"looks like {'an event' if len(pairs) == 1 else 'events'} you already have:")
            lines += [f"- {ev.title} ({ev.start.astimezone(self.tz).strftime('%a %b %-d %-I:%M%p').lower()}) → {m.title}" for ev, m in pairs]
        if new:
            lines.append(f"new (i'd add to {self.target}):")
            lines += [f"- {ev.title}, {self._when(ev.start, ev.end)}" for ev in new]
        lines.append("reply yes to link and add, or no to skip")
        return "\n".join(lines)

    # -- the answer, from chat ------------------------------------------------------

    async def approve(self, payload: dict, approved: bool) -> str:
        if not approved:
            self.store.kv_set("calendar_declined_digest", payload.get("digest", ""))
            return "ok, skipped. i'll only ask again if canvas adds events"
        course_for = self._course_for()
        for pr in payload.get("pairs", []):
            ev = CanvasEvent(pr["id"], pr["course_id"], pr["title"], datetime.fromisoformat(pr["start"]), None, None, None, "")
            self._link(ev, pr["gcal_id"], adopted=True)
            try:   # tag the hand-made event so a later search recognises it
                await asyncio.to_thread(self.calendar.update_event, pr["gcal_calendar_id"], pr["gcal_id"],
                                        {"extendedProperties": {"private": {"canvas_id": str(pr["id"])}}})
            except Exception:
                pass
        target_id = await asyncio.to_thread(self._target_id)
        added = 0
        for n in payload.get("new", []):
            course = course_for.get(n["course_id"])
            if course is None:
                continue
            ev = CanvasEvent(n["id"], n["course_id"], n["title"], datetime.fromisoformat(n["start"]),
                             datetime.fromisoformat(n["end"]) if n.get("end") else None, n.get("location"), n.get("description"), n.get("html_url", ""))
            created = await asyncio.to_thread(self.calendar.create_event, target_id, self._body(ev, course))
            self._link(ev, created["id"], adopted=False)
            added += 1
        self.store.kv_set("calendar_first_run_done", "1")
        n = len(payload.get("pairs", []))
        linked = f"linked {n} existing event{'s' if n != 1 else ''}"
        return f"{linked}, added {added}" if added else f"{linked}, nothing new to add"
