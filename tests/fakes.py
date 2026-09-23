"""In-memory stand-ins for Todoist and Google Calendar so tests never touch the network."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

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
    """Mimics the subset of TodoistClient that ChatOps uses."""

    def __init__(self, tasks: list[FakeTask] | None = None):
        self._tasks: dict[str, FakeTask] = {t.id: t for t in (tasks or [])}
        self.deleted: list[str] = []
        self._n = 100

    # reads
    def tasks(self, project_id: str) -> list[FakeTask]:
        return [t for t in self._tasks.values() if t.project_id == project_id and not t.is_completed]

    def all_tasks(self) -> list[FakeTask]:
        return [t for t in self._tasks.values() if not t.is_completed]

    def priority_tasks(self, min_api_priority: int) -> list[FakeTask]:
        return [t for t in self._tasks.values() if t.priority >= min_api_priority and not t.is_completed]

    def get_task(self, task_id: str) -> FakeTask:
        return self._tasks[task_id]

    # writes
    def add_task(self, *, content, description="", project_id, section_id=None, due_at=None, due_date=None, priority=1):
        self._n += 1
        due = FakeDue(due_at) if due_at else FakeDue(due_date) if due_date else None
        t = FakeTask(f"T{self._n}", content, due, priority, section_id, project_id, description=description,
                     created_at=datetime.now(timezone.utc))
        self._tasks[t.id] = t
        return t

    def update_task(self, task_id, *, content=None, description=None, due_at=None, due_date=None, clear_due=False):
        t = self._tasks[task_id]
        if content is not None:
            t.content = content
        if description is not None:
            t.description = description
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


class FakeCalendar:
    def __init__(self, events_by_day: dict[date, list[Event]] | None = None):
        self.events_by_day = events_by_day or {}

    def events_for_day(self, calendar_names, day, tz):
        return self.events_by_day.get(day, [])
