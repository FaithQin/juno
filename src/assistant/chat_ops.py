"""What juno can *do* from a text: the operations behind every chat tool.

No language model in here. The agent (agent.py) decides *which* of these to
call and with what arguments; this module does the work, returns short text
in juno's voice, and logs every write so `undo` can reverse it. Keeping the
two apart means all of this is testable with fakes in milliseconds.

Rules from DECISIONS.md: act then echo (no confirmation for your own tasks);
ambiguous matches ask "which one?" rather than guessing; an unknown course
asks rather than filing the task somewhere random.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from .brief import Event, short_location, _span
from .colors import NAMES as COLOR_NAMES, ColorScheme, color_id, color_name
from .gcal import event_body
from .db import Store
from .reminders import DueTask, deadline_words, duration_words, planned_tail
from .tasks import due_task_from, match_tasks, normalize_course
from .web import canvas_api_path, is_canvas_url

MIN_PRIORITY_ELSEWHERE = 3          # Todoist API: 4 = p1, 3 = p2 (Faith: "Classes plus p1/p2 anywhere")
PRIORITY_WORDS = {"p1": 4, "p2": 3, "p3": 2, "p4": 1}   # what she says → Todoist API level
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DUE_ERROR = "error: due must be an ISO date (2026-09-28) or datetime (2026-09-28T23:59); ask if unsure"


class ChatOps:
    def __init__(self, *, store: Store, todoist, calendar, tz: ZoneInfo, courses: list[str],
                 sections: dict[str, str], classes_project_id: str, calendar_names: list[str],
                 now: Callable[[], datetime], web=None, browser=None, ed=None,
                 course_projects: dict[str, str] | None = None, colors: ColorScheme | None = None,
                 audits: list[str] | None = None):
        self.web = web                        # WebReader, or None when links can't be opened
        self.browser = browser                # BrowserSession, or None when there is no browser
        self.ed = ed                          # EdClient, or None without ED_API_TOKEN
        self.sync_canvas = None               # () -> Report, wired by app.py
        self.sync_gradescope = None           # () -> str | None, wired by app.py (runs the async job on the main loop)
        self.sync_outlook = None              # () -> str | None, wired by app.py when OUTLOOK_ICS_URL is set
        self.check_duplicates = None          # () -> str | None, wired by app.py (runs the duplicate check on the main loop)
        self.answer_job = None                # async (approved) -> str, wired by ChatSession
        self.colors = colors                  # her scheme for events juno adds; None = no automatic colors
        self.audit_codes = set(audits or [])  # courses she audits: no nudges, tagged in the brief
        self.store = store
        self.todoist = todoist
        self.calendar = calendar
        self.tz = tz
        self.courses = list(courses)
        # Legacy layout: a course's section inside Classes. Kept for courses without a sub-project,
        # and so tasks not yet moved out of an old section still read as their course.
        self.section_by_course = dict(sections)                       # "CME 102" → section id
        self.course_by_section = {v: k for k, v in sections.items()}  # section id → "CME 102"
        # Each course's own sub-project under Classes (docs/09-per-course-projects.md).
        self.project_by_course = dict(course_projects or {})          # "CME 102" → sub-project id
        self.course_by_project = {v: k for k, v in self.project_by_course.items()}
        self.classes_project_id = classes_project_id
        self.class_project_ids = list(dict.fromkeys([classes_project_id, *self.project_by_course.values()]))
        self.calendar_names = list(calendar_names)
        self.now = now

    # ----------------------------------------------------------------------
    # formatting helpers (juno's words lowercase; task names as they are)
    # ----------------------------------------------------------------------

    def _local(self, dt: datetime) -> datetime:
        return dt.astimezone(self.tz)

    def _clock(self, dt: datetime) -> str:
        return self._local(dt).strftime("%-I:%M%p").lower()

    def _day_clock(self, dt: datetime) -> str:
        return self._local(dt).strftime("%a %-I:%M%p").lower()

    def _date_words(self, d: date) -> str:
        return d.strftime("%a %b %-d").lower()

    def _when(self, value) -> str:
        """'thu 11:59pm' for datetimes, 'mon sep 28' for dates."""
        if isinstance(value, datetime):
            return self._day_clock(value)
        return self._date_words(value)

    def _stamp(self, t: DueTask, scope: str) -> str:
        local = self._local(t.due_at)
        if scope in ("today", "tomorrow"):
            return self._clock(t.due_at) if t.has_time else "any time"
        words = self._date_words(local.date())
        return f"{words} {self._clock(t.due_at)}" if t.has_time else words

    @staticmethod
    def _priority_tag(t: DueTask) -> str:
        return f" [p{5 - t.priority}]" if t.priority >= MIN_PRIORITY_ELSEWHERE else ""

    def _courses_list(self) -> str:
        return ", ".join(self.courses)

    # ----------------------------------------------------------------------
    # reads
    # ----------------------------------------------------------------------

    def _candidates(self) -> list:
        seen: set[str] = set()
        out = []
        for t in list(self.todoist.tasks_in(self.class_project_ids, strict=False)) + list(self.todoist.priority_tasks(MIN_PRIORITY_ELSEWHERE)):
            if t.id in seen:
                continue
            seen.add(t.id)
            out.append(t)
        return out

    def _tracked(self) -> set[str]:
        """Tasks a sync keeps (Canvas, Gradescope): assignments, so their dates are deadlines."""
        return {link.task_id for link in self.store.links().values()}

    def _due(self, tasks) -> list[DueTask]:
        tracked = self._tracked()
        out = [d for d in (due_task_from(t, tz=self.tz, sections=self.course_by_section, projects=self.course_by_project,
                                         tracked=tracked) for t in tasks) if d]
        return sorted(out, key=lambda d: d.due_at)

    def due_tasks(self) -> list[DueTask]:
        """Classes plus p1/p2 anywhere: what the chat covers."""
        return self._due(self._candidates())

    def nudge_tasks(self) -> list[DueTask]:
        """What the nudges cover: the chat's tasks minus audited courses (Faith, 2026-10-03)."""
        return [t for t in self.due_tasks() if t.course not in self.audit_codes]

    def all_due_tasks(self) -> list[DueTask]:
        """Every dated task in the account: what the morning brief covers."""
        return self._due(self.todoist.all_tasks())

    def tasks_overview(self, scope: str, course: str | None = None) -> str:
        """scope: today | tomorrow | week | overdue | all."""
        now = self.now()
        today = self._local(now).date()
        code = None
        if course:
            code = normalize_course(course, self.courses)
            if not code:
                return f"'{course}' isn't one of your courses ({self._courses_list()})"
        tasks = [t for t in self.due_tasks() if not code or t.course == code]

        def day_of(t: DueTask) -> date:
            return self._local(t.due_at).date()

        if scope in ("today", "tomorrow"):
            d = today if scope == "today" else today + timedelta(days=1)
            due = [t for t in tasks if t.kind == "due" and day_of(t) == d]
            deadline_only = [t for t in tasks if t.kind == "planned" and t.deadline == d and day_of(t) != d]
            planned = [t for t in tasks if t.kind == "planned" and day_of(t) == d]
            lines: list[str] = []
            if due or deadline_only:
                lines.append(f"{code.lower()}:" if code else f"due {scope}:")
                lines += [f"- {self._stamp(t, scope)} {t.content}{self._priority_tag(t)}" for t in due]
                lines += [f"- deadline · {t.content} (planned {self._local(t.due_at).strftime('%a').lower()})" for t in deadline_only]
            else:
                lines.append(f"nothing due {scope} for {code}" if code else f"nothing due {scope}")
            if planned:
                lines.append(f"planned {scope} (work time, not deadlines):")
                lines += [f"- {self._stamp(t, scope)} {t.content}{planned_tail(t, today=today)}{self._priority_tag(t)}" for t in planned]
            return "\n".join(lines)
        if scope == "week":
            picked, header = [t for t in tasks if now <= t.due_at and day_of(t) <= today + timedelta(days=7)], "this week:"
        elif scope == "overdue":
            picked, header = [t for t in tasks if t.due_at < now], "overdue:"
        else:
            scope = "all"
            picked, header = [t for t in tasks if t.due_at >= now], "everything upcoming:"

        if not picked:
            what = {"today": "nothing due today", "tomorrow": "nothing due tomorrow", "week": "nothing due this week",
                    "overdue": "nothing overdue", "all": "nothing upcoming"}[scope]
            return f"{what} for {code}" if code else what
        if code:
            header = f"{code.lower()}:"
        def line(t: DueTask) -> str:
            tail = planned_tail(t, today=today, label=True) if t.kind == "planned" else ""
            return f"- {self._stamp(t, scope)} {t.content}{tail}{self._priority_tag(t)}"

        return "\n".join([header] + [line(t) for t in picked])

    def schedule(self, day: str = "today") -> str:
        today = self._local(self.now()).date()
        if day == "today":
            d, label = today, "today"
        elif day == "tomorrow":
            d, label = today + timedelta(days=1), "tomorrow"
        else:
            try:
                d = date.fromisoformat(day)
            except ValueError:
                return "error: day must be today, tomorrow, or an ISO date like 2026-09-28"
            label = self._date_words(d)
        if self.calendar is None:
            return "calendar isn't connected yet. run: uv run assistant gcal-auth"
        try:
            events: list[Event] = self.calendar.events_for_day(self.calendar_names, d, self.tz)
        except FileNotFoundError:
            return "calendar isn't connected yet. run: uv run assistant gcal-auth"
        except Exception as e:  # network, expired consent, revoked token
            return f"couldn't read the calendar ({type(e).__name__}). try again in a bit"
        if not events:
            return f"nothing on the calendar for {self._date_words(d)}"
        lines = [f"{label} ({self._date_words(d)}):"] if label != self._date_words(d) else [f"{label}:"]
        for e in sorted(events, key=lambda e: (not e.all_day, e.start)):
            loc = short_location(e.location)
            lines.append(f"- {_span(e, self.tz)} {e.title}" + (f" · {loc}" if loc else ""))
        return "\n".join(lines)

    # ----------------------------------------------------------------------
    # writes (act, echo, log for undo)
    # ----------------------------------------------------------------------

    def _parse_due(self, due: str | None) -> tuple[datetime | None, date | None] | str:
        if not due:
            return (None, None)
        due = due.strip()
        if DATE_RE.match(due):
            try:
                return (None, date.fromisoformat(due))
            except ValueError:
                return DUE_ERROR
        try:
            dt = datetime.fromisoformat(due)
        except ValueError:
            return DUE_ERROR
        return (dt if dt.tzinfo else dt.replace(tzinfo=self.tz), None)

    def _course_from_title(self, title: str) -> tuple[str | None, str]:
        tokens = title.split()
        for n in (2, 1):
            if len(tokens) >= n:
                code = normalize_course(" ".join(tokens[:n]), self.courses)
                if code:
                    rest = " ".join(tokens[n:]).lstrip(":- ").strip()
                    return code, rest
        return None, title

    def add_task(self, title: str, due: str | None = None, course: str | None = None, notes: str | None = None,
                 duration: int | None = None, deadline: str | None = None) -> str:
        code = None
        if course:
            code = normalize_course(course, self.courses)
            if not code:
                return f"'{course}' isn't one of your courses ({self._courses_list()})"
        title = title.strip()
        if not code:
            code, title = self._course_from_title(title)
        if not code:
            return f"which course is that for? ({self._courses_list()})"
        parsed = self._parse_due(due)
        if isinstance(parsed, str):
            return parsed
        due_at, due_date = parsed
        deadline_date = None
        if deadline:
            if not DATE_RE.match(deadline.strip()):
                return "error: deadline must be an ISO date (2026-10-08); ask if unsure"
            deadline_date = date.fromisoformat(deadline.strip())
        content = f"{code}: {title}" if title else code
        if code in self.project_by_course:          # the course's own sub-project, no section
            project_id, section_id = self.project_by_course[code], None
        else:                                       # legacy: its section inside Classes
            project_id, section_id = self.classes_project_id, self.section_by_course.get(code)
        extra: dict = {}
        if duration:
            extra["duration_minutes"] = int(duration)
        if deadline_date:
            extra["deadline"] = deadline_date
        task = self.todoist.add_task(
            content=content, description=notes or "", project_id=project_id,
            section_id=section_id, due_at=due_at, due_date=due_date, priority=1, **extra,
        )
        self.store.log_action("add_task", {"task_id": task.id, "content": content}, at=self.now())
        bits = [self._when(due_at or due_date) if (due_at or due_date) else "no date"]
        if duration:
            bits.append(duration_words(int(duration)))
        if deadline_date:
            bits.append(f"deadline {deadline_words(deadline_date, today=self._local(self.now()).date())}")
        return f"added: {content} ({' · '.join(bits)})"

    def _pick(self, query: str) -> object | str:
        matches = match_tasks(query, self._candidates(), sections=self.course_by_section,
                              projects=self.course_by_project)
        if not matches:
            return f"no task matches '{query}'"
        if len(matches) > 1:
            return "which one?\n" + "\n".join(f"- {t.content}" for t in matches[:6])
        return matches[0]

    def complete_task(self, query: str) -> str:
        t = self._pick(query)
        if isinstance(t, str):
            return t
        self.todoist.complete_task(t.id)
        self.store.log_action("complete_task", {"task_id": t.id, "content": t.content}, at=self.now())
        return f"done: {t.content}"

    @staticmethod
    def _due_payload(task) -> dict:
        raw = getattr(getattr(task, "due", None), "date", None)
        if raw is None:
            return {"old_due": None}
        return {"old_due": raw.isoformat(), "old_kind": "datetime" if isinstance(raw, datetime) else "date"}

    def reschedule_task(self, query: str, due: str) -> str:
        t = self._pick(query)
        if isinstance(t, str):
            return t
        parsed = self._parse_due(due)
        if isinstance(parsed, str):
            return parsed
        due_at, due_date = parsed
        payload = {"task_id": t.id, "content": t.content, **self._due_payload(t)}
        self.todoist.update_task(t.id, due_at=due_at, due_date=due_date, clear_due=not (due_at or due_date))
        self.store.log_action("reschedule_task", payload, at=self.now())
        when = self._when(due_at or due_date) if (due_at or due_date) else "no date"
        return f"moved: {t.content} → {when}"

    def edit_task(self, query: str, title: str | None = None, notes: str | None = None, priority: str | None = None) -> str:
        if not title and notes is None and not priority:
            return "nothing to change: give a new title, notes, or priority"
        api_priority = None
        if priority:
            api_priority = PRIORITY_WORDS.get(priority.strip().lower())
            if api_priority is None:
                return "error: priority must be p1, p2, p3 or p4"
        t = self._pick(query)
        if isinstance(t, str):
            return t
        old = {"content": t.content, "description": getattr(t, "description", "") or "", "priority": getattr(t, "priority", 1)}
        kwargs: dict = {}
        changed: list[str] = []
        if title:
            kwargs["content"] = title.strip()
            changed.append("title")
        if notes is not None:
            kwargs["description"] = notes
            changed.append("notes")
        if api_priority:
            kwargs["priority"] = api_priority
            changed.append(f"priority {priority.strip().lower()}")
        self.todoist.update_task(t.id, **kwargs)
        new_content = kwargs.get("content", t.content)
        self.store.log_action("edit_task", {"task_id": t.id, "content": new_content, "old": old}, at=self.now())
        return f"updated: {new_content} ({', '.join(changed)})"

    def snooze(self, query: str, at: str) -> str:
        t = self._pick(query)
        if isinstance(t, str):
            return t
        parsed = self._parse_due(at)
        if isinstance(parsed, str) or parsed[0] is None:
            return "error: at must be an ISO datetime like 2026-09-25T21:00"
        when = parsed[0]
        self.store.set_snooze(t.id, when)
        self.store.log_action("snooze", {"task_id": t.id, "content": t.content}, at=self.now())
        return f"ok, i'll remind you about {t.content} at {self._day_clock(when)}"

    def remember(self, text: str) -> str:
        fid = self.store.remember(text, now=self.now())
        self.store.log_action("remember", {"fact_id": fid, "text": text.strip()}, at=self.now())
        return "noted"

    def forget(self, query: str) -> str:
        facts = self.store.find_facts(query)
        if not facts:
            return f"nothing matches '{query}'"
        if len(facts) > 1:
            return "which one?\n" + "\n".join(f"- {f.text}" for f in facts[:6])
        self.store.forget(facts[0].id)
        return f"forgot: {facts[0].text}"

    def undo(self) -> str:
        a = self.store.last_undoable()
        if a is None:
            return "nothing to undo"
        p = a.payload
        if a.kind == "add_task":
            self.todoist.delete_task(p["task_id"])
            msg = f"undone: deleted {p['content']}"
        elif a.kind == "complete_task":
            self.todoist.uncomplete_task(p["task_id"])
            msg = f"undone: reopened {p['content']}"
        elif a.kind == "reschedule_task":
            if p.get("old_due") is None:
                self.todoist.update_task(p["task_id"], clear_due=True)
                msg = f"undone: {p['content']} has no due date again"
            elif p.get("old_kind") == "date":
                old = date.fromisoformat(p["old_due"])
                self.todoist.update_task(p["task_id"], due_date=old)
                msg = f"undone: {p['content']} back to {self._when(old)}"
            else:
                old = datetime.fromisoformat(p["old_due"])
                old = old if old.tzinfo else old.replace(tzinfo=self.tz)
                self.todoist.update_task(p["task_id"], due_at=old)
                msg = f"undone: {p['content']} back to {self._when(old)}"
        elif a.kind == "edit_task":
            old = p["old"]
            self.todoist.update_task(p["task_id"], content=old["content"], description=old["description"], priority=old["priority"])
            msg = f"undone: {old['content']} restored"
        elif a.kind == "snooze":
            self.store.clear_snooze(p["task_id"])
            msg = f"undone: snooze for {p['content']} cleared"
        elif a.kind == "add_event":
            self.calendar.delete_event(p["calendar_id"], p["event_id"])
            msg = f"undone: deleted {p['title']}"
        elif a.kind == "move_event":
            old_start = datetime.fromisoformat(p["old_start"])
            old_end = datetime.fromisoformat(p["old_end"]) if p.get("old_end") else old_start + timedelta(hours=1)
            tzname = str(self.tz)
            self.calendar.update_event(p["calendar_id"], p["event_id"], {
                "start": {"dateTime": old_start.isoformat(timespec="seconds"), "timeZone": tzname},
                "end": {"dateTime": old_end.isoformat(timespec="seconds"), "timeZone": tzname},
            })
            msg = f"undone: {p['title']} back to {self._day_span(old_start, old_end)}"
        elif a.kind == "color_event":
            self.calendar.update_event(p["calendar_id"], p["event_id"], {"colorId": p.get("old") or None})
            what = f"every {p['title']}" if p.get("series") else p["title"]
            msg = f"undone: {what} is {color_name(p.get('old'))} again"
        elif a.kind == "delete_event":
            self.calendar.create_event(p["calendar_id"], p["body"])
            msg = f"undone: {p['title']} is back on {p['day']}"
        elif a.kind == "delete_task":
            snap = p["snapshot"]
            due_at = due_date = None
            if snap.get("due"):
                if snap.get("due_kind") == "datetime":
                    due_at = datetime.fromisoformat(snap["due"])
                    due_at = due_at if due_at.tzinfo else due_at.replace(tzinfo=self.tz)
                else:
                    due_date = date.fromisoformat(snap["due"])
            project_id, section_id = snap["project_id"], snap["section_id"]
            code = self.course_by_section.get(section_id)
            if code in self.project_by_course:       # deleted before its course moved to a sub-project
                project_id, section_id = self.project_by_course[code], None
            self.todoist.add_task(content=snap["content"], description=snap["description"], project_id=project_id,
                                  section_id=section_id, due_at=due_at, due_date=due_date, priority=snap["priority"])
            msg = f"undone: {snap['content']} is back"
        elif a.kind == "remember":
            self.store.forget(p["fact_id"])
            msg = f"undone: forgot '{p['text']}'"
        else:
            return f"can't undo a {a.kind}"
        self.store.mark_undone(a.id)
        return msg

    def read_link(self, url: str) -> str:
        if self.web is None:
            return "i can't open links right now"
        return self.web.read(url)

    # -- calendar writes and deletes (phase 6): act, echo, undo ------------------------

    START_ERROR = "error: start must be an ISO datetime like 2026-09-24T09:00"

    def _parse_dt(self, raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.strip())
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=self.tz)

    def _day_span(self, start: datetime, end: datetime | None) -> str:
        ev = Event("", start, end, None, False, "")
        return f"{self._date_words(self._local(start).date())} {_span(ev, self.tz)}"

    def _calendar_id(self, name: str | None) -> tuple[str, str] | str:
        """(calendar id, label) for a display name; None means the personal calendar."""
        if not name:
            return "primary", "personal calendar"
        ids = self.calendar.calendar_ids()
        for known, cal_id in ids.items():
            if known.lower() == name.strip().lower():
                return cal_id, known
        return f"no calendar called '{name}' (i know {', '.join(self.calendar_names)})"

    def _pick_event(self, query: str, *, series_ok: bool = False) -> Event | str:
        if self.calendar is None:
            return "calendar isn't connected yet. run: uv run assistant gcal-auth"
        now = self.now()
        try:
            events = self.calendar.events_in_window(self.calendar_names, now - timedelta(days=1), now + timedelta(days=14), self.tz)
        except Exception as e:
            return f"couldn't read the calendar ({type(e).__name__}). try again in a bit"
        words = [w for w in query.lower().split() if w]
        matches = []
        for e in events:
            hay = e.title.lower()
            tokens = set(re.findall(r"[a-z0-9]+", hay))
            squashed = re.sub(r"[^a-z0-9]", "", hay)
            if words and all(w in tokens or (len(w) >= 3 and (w in hay or re.sub(r"[^a-z0-9]", "", w) in squashed)) for w in words):
                matches.append(e)
        if not matches:
            return f"no event matches '{query}' in the next two weeks"
        if series_ok and matches[0].recurring_id and all(m.recurring_id == matches[0].recurring_id for m in matches):
            return matches[0]                       # several occurrences of one series: that's one thing
        if len(matches) > 1:
            return "which one?\n" + "\n".join(f"- {e.title} ({self._day_span(e.start, e.end)})" for e in matches[:6])
        return matches[0]

    COLOR_ERROR = f"error: color must be one of {COLOR_NAMES} (or default)"

    def add_event(self, title: str, start: str, end: str | None = None, location: str | None = None,
                  calendar: str | None = None, notes: str | None = None, color: str | None = None) -> str:
        if self.calendar is None:
            return "calendar isn't connected yet. run: uv run assistant gcal-auth"
        if color is not None:
            cid = color_id(color)
            if cid is None:
                return self.COLOR_ERROR
        else:                                       # her scheme: classes flamingo, audits grape, exams tomato
            cid = self.colors.pick(title) if self.colors else None
        target = self._calendar_id(calendar)
        if isinstance(target, str):
            return target
        cal_id, label = target
        start_dt = self._parse_dt(start)
        if start_dt is None:
            return self.START_ERROR
        end_dt = self._parse_dt(end) if end else None
        body = event_body(title=title.strip(), start=start_dt, end=end_dt, location=location, description=notes, color_id=cid or None)
        created = self.calendar.create_event(cal_id, body)
        self.store.log_action("add_event", {"calendar_id": cal_id, "event_id": created["id"], "title": title.strip()}, at=self.now())
        where = f" at {location}" if location else ""
        tag = f"{label}, {color_name(cid)}" if cid else label
        return f"added: {title.strip()}, {self._day_span(start_dt, end_dt or start_dt + timedelta(hours=1))}{where} ({tag})"

    def move_event(self, query: str, start: str, end: str | None = None) -> str:
        e = self._pick_event(query)
        if isinstance(e, str):
            return e
        new_start = self._parse_dt(start)
        if new_start is None:
            return self.START_ERROR
        duration = (e.end - e.start) if e.end else timedelta(hours=1)
        new_end = self._parse_dt(end) if end else new_start + duration
        tzname = str(self.tz)
        self.calendar.update_event(e.calendar_id, e.id, {
            "start": {"dateTime": new_start.isoformat(timespec="seconds"), "timeZone": tzname},
            "end": {"dateTime": new_end.isoformat(timespec="seconds"), "timeZone": tzname},
        })
        self.store.log_action("move_event", {"calendar_id": e.calendar_id, "event_id": e.id, "title": e.title,
                                             "old_start": e.start.isoformat(), "old_end": e.end.isoformat() if e.end else None}, at=self.now())
        return f"moved: {e.title} → {self._day_span(new_start, new_end)}"

    def color_event(self, query: str, color: str, all_occurrences: bool = False) -> str:
        cid = color_id(color)
        if cid is None:
            return self.COLOR_ERROR
        e = self._pick_event(query, series_ok=all_occurrences)
        if isinstance(e, str):
            return e
        series = bool(all_occurrences and e.recurring_id)
        target = e.recurring_id if series else e.id
        if series:
            master = self.calendar.get_event(e.calendar_id, target)
            old = master.get("colorId") if isinstance(master, dict) else None
        else:
            old = e.color_id
        self.calendar.update_event(e.calendar_id, target, {"colorId": cid or None})   # None (JSON null) clears it
        self.store.log_action("color_event", {"calendar_id": e.calendar_id, "event_id": target, "title": e.title,
                                              "old": old, "series": series}, at=self.now())
        if series:
            return f"colored every {e.title} {color_name(cid)}"
        return f"colored {e.title} {color_name(cid)} ({self._day_span(e.start, e.end)})"

    def delete_event(self, query: str) -> str:
        e = self._pick_event(query)
        if isinstance(e, str):
            return e
        body = event_body(title=e.title, start=e.start, end=e.end, location=e.location, description=e.description, canvas_id=e.canvas_id,
                          color_id=e.color_id)
        self.calendar.delete_event(e.calendar_id, e.id)
        self.store.log_action("delete_event", {"calendar_id": e.calendar_id, "body": body, "title": e.title,
                                               "day": self._date_words(self._local(e.start).date())}, at=self.now())
        return f"deleted: {e.title} ({self._day_span(e.start, e.end)})"

    def delete_task(self, query: str) -> str:
        t = self._pick(query)
        if isinstance(t, str):
            return t
        due = getattr(getattr(t, "due", None), "date", None)
        snapshot = {
            "content": t.content, "description": getattr(t, "description", "") or "", "project_id": getattr(t, "project_id", self.classes_project_id),
            "section_id": getattr(t, "section_id", None), "priority": getattr(t, "priority", 1) or 1,
            "due": due.isoformat() if due is not None else None, "due_kind": "datetime" if isinstance(due, datetime) else "date" if due else None,
        }
        self.todoist.delete_task(t.id)
        self.store.log_action("delete_task", {"task_id": t.id, "content": t.content, "snapshot": snapshot}, at=self.now())
        return f"deleted: {t.content}"

    def sync_now(self, source: str = "all") -> str:
        """Run the Canvas and/or Gradescope sync immediately and return what changed."""
        from .sync import format_report

        if source == "outlook" and self.sync_outlook is None:
            return "outlook isn't connected (OUTLOOK_ICS_URL in .env)"
        if self.sync_canvas is None and self.sync_gradescope is None and self.sync_outlook is None:
            return "syncs aren't wired up in this context"
        parts: list[str] = []
        if source in ("all", "canvas") and self.sync_canvas is not None:
            try:
                report = self.sync_canvas()
                body = "\n".join(format_report(report).splitlines()[1:]) or "nothing to change"
                parts.append(f"canvas: {body}")
            except Exception as e:
                parts.append(f"canvas: sync failed ({type(e).__name__})")
        if source in ("all", "gradescope") and self.sync_gradescope is not None:
            try:
                text = self.sync_gradescope()
                parts.append(text or "gradescope: nothing new")
            except Exception as e:
                parts.append(f"gradescope: sync failed ({type(e).__name__})")
        if source in ("all", "outlook") and self.sync_outlook is not None:
            try:
                text = self.sync_outlook()
                parts.append(text or "outlook: nothing new")
            except Exception as e:
                parts.append(f"outlook: sync failed ({type(e).__name__})")
        return "\n\n".join(parts) if parts else "nothing to sync for that source"

    def find_duplicates(self) -> str:
        if self.check_duplicates is None:
            return "the duplicate check isn't available in this context"
        try:
            return self.check_duplicates() or "todoist: no duplicate tasks"
        except Exception as e:
            return f"couldn't check for duplicates ({type(e).__name__})"

    def ed_announcements(self, course: str, limit: int = 5) -> str:
        from .ed import format_announcements, match_course

        code = normalize_course(course, self.courses)
        if not code:
            return f"'{course}' isn't one of your courses ({self._courses_list()})"
        if self.ed is None:
            return "ed isn't connected yet (ED_API_TOKEN in .env)"
        try:
            ed_course = match_course(self.ed.courses(), code)
            if ed_course is None:
                return f"i can't find {code} on ed"
            threads = self.ed.threads(ed_course.id, limit=40)
        except Exception as e:
            return f"couldn't reach ed ({type(e).__name__}). try again in a bit"
        return format_announcements(threads, course_code=code, tz=self.tz, limit=limit)

    # -- the real browser (phase 3) -------------------------------------------

    async def _browser_call(self, action: str, *args) -> str:
        from .browser import render_snapshot

        if self.browser is None:
            return "the browser isn't available right now"
        try:
            snap = await getattr(self.browser, action)(*args)
        except Exception as e:
            return f"browser error: {type(e).__name__}: {str(e).splitlines()[0][:200]}"
        return render_snapshot(snap, site_key=getattr(self.browser, "site_key", None))

    CANVAS_NOTE = ("i don't browse canvas (its login expires within a day; the api token doesn't): tasks and due "
                   "dates come from get_tasks, events from get_schedule, and an assignment, page, quiz or "
                   "discussion link from read_link")

    async def browse(self, url: str) -> str:
        if self.web is not None and is_canvas_url(url, self.web.canvas_url):
            return self.read_link(url) if canvas_api_path(url, self.web.canvas_url) else self.CANVAS_NOTE
        return await self._browser_call("open", url)

    async def browser_click(self, ref: int) -> str:
        return await self._browser_call("click", ref)

    async def browser_type(self, ref: int, text: str) -> str:
        return await self._browser_call("type", ref, text)

    async def browser_select(self, ref: int, value: str) -> str:
        return await self._browser_call("select", ref, value)

    async def browser_submit(self, ref: int) -> str:
        return await self._browser_call("submit", ref)

    async def browser_back(self) -> str:
        return await self._browser_call("back")

    # -- proposals from scheduled jobs ------------------------------------------

    async def answer_proposal(self, approved: bool) -> str:
        if self.answer_job is None or self.store.pending_job() is None:
            return "there's no proposal waiting"
        return await self.answer_job(approved)

    # ----------------------------------------------------------------------
    # what the model sees every turn (dynamic instructions)
    # ----------------------------------------------------------------------

    def context_block(self) -> str:
        lines = [   # nothing here may change minute to minute: the whole block is part of the provider's cached prefix
            f"timezone: {str(self.tz).lower()}",
            f"courses: {self._courses_list()}",
        ]
        facts = self.store.facts()
        if facts:
            lines.append("things faith told me to remember:")
            lines.extend(f"- {f.text}" for f in facts)
        job = self.store.pending_job()
        if job and job.get("question"):
            lines.append("a scheduled job is still waiting on her yes or no to this (answer_proposal, only when she clearly means it):")
            lines.append(job["question"])
        return "\n".join(lines)
