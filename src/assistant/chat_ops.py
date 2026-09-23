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
from .db import Store
from .reminders import DueTask
from .tasks import due_task_from, match_tasks, normalize_course

MIN_PRIORITY_ELSEWHERE = 3          # Todoist API: 4 = p1, 3 = p2 (Faith: "Classes plus p1/p2 anywhere")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DUE_ERROR = "error: due must be an ISO date (2026-09-28) or datetime (2026-09-28T23:59); ask if unsure"


class ChatOps:
    def __init__(self, *, store: Store, todoist, calendar, tz: ZoneInfo, courses: list[str],
                 sections: dict[str, str], classes_project_id: str, calendar_names: list[str],
                 now: Callable[[], datetime], web=None):
        self.web = web                        # WebReader, or None when links can't be opened
        self.store = store
        self.todoist = todoist
        self.calendar = calendar
        self.tz = tz
        self.courses = list(courses)
        self.section_by_course = dict(sections)                       # "CME 102" → section id
        self.course_by_section = {v: k for k, v in sections.items()}  # section id → "CME 102"
        self.classes_project_id = classes_project_id
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
        for t in list(self.todoist.tasks(self.classes_project_id)) + list(self.todoist.priority_tasks(MIN_PRIORITY_ELSEWHERE)):
            if t.id in seen:
                continue
            seen.add(t.id)
            out.append(t)
        return out

    def due_tasks(self) -> list[DueTask]:
        """Classes plus p1/p2 anywhere: what the nudges and the chat cover."""
        out = [d for d in (due_task_from(t, tz=self.tz, sections=self.course_by_section) for t in self._candidates()) if d]
        return sorted(out, key=lambda d: d.due_at)

    def all_due_tasks(self) -> list[DueTask]:
        """Every dated task in the account: what the morning brief covers."""
        out = [d for d in (due_task_from(t, tz=self.tz, sections=self.course_by_section) for t in self.todoist.all_tasks()) if d]
        return sorted(out, key=lambda d: d.due_at)

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

        if scope == "today":
            picked, header = [t for t in tasks if day_of(t) == today], "due today:"
        elif scope == "tomorrow":
            picked, header = [t for t in tasks if day_of(t) == today + timedelta(days=1)], "due tomorrow:"
        elif scope == "week":
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
        return "\n".join([header] + [f"- {self._stamp(t, scope)} {t.content}{self._priority_tag(t)}" for t in picked])

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

    def add_task(self, title: str, due: str | None = None, course: str | None = None, notes: str | None = None) -> str:
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
        content = f"{code}: {title}" if title else code
        task = self.todoist.add_task(
            content=content, description=notes or "", project_id=self.classes_project_id,
            section_id=self.section_by_course.get(code), due_at=due_at, due_date=due_date, priority=1,
        )
        self.store.log_action("add_task", {"task_id": task.id, "content": content}, at=self.now())
        when = self._when(due_at or due_date) if (due_at or due_date) else "no date"
        return f"added: {content} ({when})"

    def _pick(self, query: str) -> object | str:
        matches = match_tasks(query, self._candidates(), sections=self.course_by_section)
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
        elif a.kind == "snooze":
            self.store.clear_snooze(p["task_id"])
            msg = f"undone: snooze for {p['content']} cleared"
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

    # ----------------------------------------------------------------------
    # what the model sees every turn (dynamic instructions)
    # ----------------------------------------------------------------------

    def context_block(self) -> str:
        local = self._local(self.now())
        lines = [
            f"now: {local.strftime('%a %b %-d, %-I:%M%p').lower()} ({str(self.tz).lower()})",
            f"courses: {self._courses_list()}",
        ]
        facts = self.store.facts()
        if facts:
            lines.append("things faith told me to remember:")
            lines.extend(f"- {f.text}" for f in facts)
        return "\n".join(lines)
