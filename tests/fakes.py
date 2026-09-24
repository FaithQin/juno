"""In-memory stand-ins for Todoist, Canvas and Google Calendar so tests never touch the network."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from types import SimpleNamespace

from assistant.brief import Event


@dataclass
class FakeDue:
    date: object
    string: str = ""
    timezone: str | None = None


@dataclass
class FakeTask:
    id: str
    content: str
    due: FakeDue | None = None
    priority: int = 1
    section_id: str | None = None
    project_id: str = "CLASSES"
    created_at: datetime = field(default_factory=lambda: datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc))
    description: str = ""
    is_completed: bool = False


class FakeTodoist:
    """Mimics TodoistClient: the reads and writes ChatOps, the syncs and `check` use.

    Like the real API, `tasks(project_id)` returns only tasks directly in that project, so a
    reader that forgets a course sub-project really does miss its tasks here too.
    `projects` are (id, name, parent_id); `sections` are {project id: {section name: id}}.
    """

    def __init__(self, tasks: list[FakeTask] | None = None, *, projects: list[tuple[str, str, str | None]] | None = None,
                 sections: dict[str, dict[str, str]] | None = None):
        self._tasks: dict[str, FakeTask] = {t.id: t for t in (tasks or [])}
        self._projects = [SimpleNamespace(id=i, name=n, parent_id=parent) for i, n, parent in
                          (projects or [("CLASSES", "Classes", None)])]
        self._sections: dict[str, dict[str, str]] = {pid: dict(v) for pid, v in (sections or {}).items()}
        self.deleted: list[str] = []
        self.sections_created: list[tuple[str, str]] = []     # every (project, name) ensure_section had to add
        self._n = 100

    # reads
    def projects(self) -> list[SimpleNamespace]:
        return list(self._projects)

    def project(self, *, project_id: str | None = None, name: str = "Classes") -> SimpleNamespace:
        for p in self._projects:
            if (project_id and p.id == project_id) or (not project_id and p.name.lower() == name.lower()):
                return p
        raise LookupError(f"No Todoist project {project_id or name!r}")

    def sections(self, project_id: str) -> dict[str, SimpleNamespace]:
        return {n: SimpleNamespace(id=sid, name=n) for n, sid in self._sections.get(project_id, {}).items()}

    def tasks(self, project_id: str) -> list[FakeTask]:
        return [t for t in self._tasks.values() if t.project_id == project_id and not t.is_completed]

    def tasks_in(self, project_ids: list[str]) -> list[FakeTask]:
        """Same contract as TodoistClient.tasks_in; goes through self.tasks so tests can make it fail."""
        seen: set[str] = set()
        out = []
        for pid in dict.fromkeys(project_ids):
            for t in self.tasks(pid):
                if t.id not in seen:
                    seen.add(t.id)
                    out.append(t)
        return out

    def all_tasks(self) -> list[FakeTask]:
        return [t for t in self._tasks.values() if not t.is_completed]

    def priority_tasks(self, min_api_priority: int) -> list[FakeTask]:
        return [t for t in self._tasks.values() if t.priority >= min_api_priority and not t.is_completed]

    def get_task(self, task_id: str) -> FakeTask:
        return self._tasks[task_id]

    def ensure_section(self, project_id, name, cache):
        if name not in cache:
            cache[name] = SimpleNamespace(id=f"S-{name}", name=name)
            self._sections.setdefault(project_id, {})[name] = cache[name].id
            self.sections_created.append((project_id, name))
        return cache[name]

    # the orchestrator's move (juno never moves tasks): same id, new place
    def move(self, task_id, *, project_id, section_id=None):
        t = self._tasks[task_id]
        t.project_id, t.section_id = project_id, section_id
        return t

    # writes
    def add_task(self, *, content, description="", project_id, section_id=None, due_at=None, due_date=None, priority=1):
        self._n += 1
        due = FakeDue(due_at) if due_at else FakeDue(due_date) if due_date else None
        t = FakeTask(f"T{self._n}", content, due, priority, section_id, project_id, description=description,
                     created_at=datetime.now(timezone.utc))
        self._tasks[t.id] = t
        return t

    def update_task(self, task_id, *, content=None, description=None, due_at=None, due_date=None, clear_due=False,
                    priority=None):
        t = self._tasks[task_id]
        if content is not None:
            t.content = content
        if description is not None:
            t.description = description
        if priority is not None:
            t.priority = priority
        if clear_due:
            t.due = None
        elif due_at is not None:
            t.due = FakeDue(due_at)
        elif due_date is not None:
            t.due = FakeDue(due_date)
        return t

    def complete_task(self, task_id):
        self._tasks[task_id].is_completed = True
        return True

    def uncomplete_task(self, task_id):
        self._tasks[task_id].is_completed = False
        return True

    def delete_task(self, task_id):
        self.deleted.append(task_id)
        self._tasks.pop(task_id, None)
        return True


class FakeCanvas:
    """CanvasClient.items_for_course over a fixed list of CanvasItems."""

    def __init__(self, items=()):
        self.items = list(items)

    def items_for_course(self, course_id: int):
        return [it for it in self.items if it.course_id == course_id]


class FakeCalendar:
    """In-memory Google Calendar: events keyed by id, with the same surface GoogleCalendar exposes."""

    def __init__(self, events_by_day: dict[date, list[Event]] | None = None, names: dict[str, str] | None = None):
        self.names = names or {"Stanford": "cal-stanford", "TA": "cal-ta", "faithclairvoyant333@gmail.com": "primary"}
        self.events: dict[str, Event] = {}
        self.bodies: dict[str, dict] = {}                 # what create_event was given, by new id
        self.patches: list[tuple[str, str, dict]] = []    # (calendar_id, event_id, patch)
        self.deleted: list[str] = []
        self._n = 0
        for day, evs in (events_by_day or {}).items():
            for e in evs:
                self._add(e)

    def _add(self, e: Event) -> Event:
        self._n += 1
        e = Event(e.title, e.start, e.end, e.location, e.all_day, e.calendar, id=e.id or f"ev{self._n}",
                  calendar_id=e.calendar_id or self.names.get(e.calendar, "primary"), description=e.description)
        self.events[e.id] = e
        return e

    def calendar_ids(self):
        return dict(self.names)

    def events_for_day(self, calendar_names, day, tz):
        return [e for e in self.events.values() if e.start.astimezone(tz).date() == day]

    def events_in_window(self, calendar_names, start, end, tz):
        ids = {self.names.get(n) for n in calendar_names}
        return sorted((e for e in self.events.values() if start <= e.start < end and e.calendar_id in ids), key=lambda e: e.start)

    def get_event(self, calendar_id, event_id):
        return self.events[event_id]

    def create_event(self, calendar_id, body):
        name = next((n for n, i in self.names.items() if i == calendar_id), calendar_id)
        start = datetime.fromisoformat(body["start"]["dateTime"]) if "dateTime" in body["start"] else None
        end = datetime.fromisoformat(body["end"]["dateTime"]) if "dateTime" in body["end"] else None
        if start is None:   # all-day
            start = datetime.fromisoformat(body["start"]["date"]).replace(tzinfo=timezone.utc)
        e = self._add(Event(body["summary"], start, end, body.get("location"), "date" in body["start"], name, calendar_id=calendar_id,
                            description=body.get("description")))
        self.bodies[e.id] = body
        return {"id": e.id, "summary": e.title, "extendedProperties": body.get("extendedProperties", {})}

    def update_event(self, calendar_id, event_id, patch):
        self.patches.append((calendar_id, event_id, patch))
        e = self.events[event_id]
        start = datetime.fromisoformat(patch["start"]["dateTime"]) if "start" in patch else e.start
        end = datetime.fromisoformat(patch["end"]["dateTime"]) if "end" in patch else e.end
        self.events[event_id] = Event(patch.get("summary", e.title), start, end, patch.get("location", e.location), e.all_day,
                                      e.calendar, id=e.id, calendar_id=e.calendar_id, description=patch.get("description", e.description))
        return {"id": event_id}

    def delete_event(self, calendar_id, event_id):
        self.deleted.append(event_id)
        self.events.pop(event_id, None)
