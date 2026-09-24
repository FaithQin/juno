"""Thin wrapper over the official Todoist SDK (unified API v1).

The SDK returns *pages* (an iterator of lists) for every list call; `_flatten`
hides that. Due datetimes are sent as aware UTC so Todoist renders them in
your account's timezone.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from todoist_api_python.api import TodoistAPI
from todoist_api_python.models import Project, Section, Task


def _flatten(pages):
    return [item for page in pages for item in page]


class TodoistClient:
    def __init__(self, token: str):
        self.api = TodoistAPI(token)

    # -- projects / sections -------------------------------------------------

    def project(self, *, project_id: str | None = None, name: str = "Classes") -> Project:
        projects: list[Project] = _flatten(self.api.get_projects())
        if project_id:
            for p in projects:
                if p.id == project_id:
                    return p
            raise LookupError(f"No Todoist project with id {project_id!r}")
        matches = [p for p in projects if p.name.strip().lower() == name.strip().lower()]
        if len(matches) != 1:
            raise LookupError(f"Expected exactly one project named {name!r}, found {len(matches)}")
        return matches[0]

    def sections(self, project_id: str) -> dict[str, Section]:
        """Section name → Section."""
        return {s.name: s for s in _flatten(self.api.get_sections(project_id=project_id))}

    def ensure_section(self, project_id: str, name: str, cache: dict[str, Section]) -> Section:
        if name not in cache:
            cache[name] = self.api.add_section(name, project_id)
        return cache[name]

    # -- tasks ---------------------------------------------------------------

    def tasks(self, project_id: str) -> list[Task]:
        """All *active* tasks in the project (completed ones are not returned)."""
        return _flatten(self.api.get_tasks(project_id=project_id))

    def all_tasks(self) -> list[Task]:
        """Every active task in the account."""
        return _flatten(self.api.get_tasks())

    def get_task(self, task_id: str) -> Task:
        return self.api.get_task(task_id)

    def priority_tasks(self, min_api_priority: int) -> list[Task]:
        """Active tasks anywhere with priority at or above the given API level (4 = p1, 3 = p2)."""
        labels = {4: "p1", 3: "p2", 2: "p3", 1: "p4"}
        query = " | ".join(labels[p] for p in range(4, min_api_priority - 1, -1))
        return _flatten(self.api.filter_tasks(query=query))

    def add_task(self, *, content: str, description: str = "", project_id: str, section_id: str | None,
                 due_at: datetime | None = None, due_date: date | None = None, priority: int = 1) -> Task:
        kwargs: dict = dict(
            description=description, project_id=project_id, section_id=section_id, priority=priority,
        )
        if due_at is not None:
            kwargs["due_datetime"] = due_at.astimezone(timezone.utc)
        elif due_date is not None:
            kwargs["due_date"] = due_date
        return self.api.add_task(content, **kwargs)

    def update_task(self, task_id: str, *, content: str | None = None, description: str | None = None,
                    due_at: datetime | None = None, due_date: date | None = None, clear_due: bool = False,
                    priority: int | None = None) -> Task:
        kwargs: dict = {}
        if content is not None:
            kwargs["content"] = content
        if description is not None:
            kwargs["description"] = description
        if priority is not None:
            kwargs["priority"] = priority
        if clear_due:
            kwargs["due_string"] = "no date"
        elif due_at is not None:
            kwargs["due_datetime"] = due_at.astimezone(timezone.utc)
        elif due_date is not None:
            kwargs["due_date"] = due_date
        return self.api.update_task(task_id, **kwargs)

    def complete_task(self, task_id: str) -> bool:
        return self.api.complete_task(task_id)

    def uncomplete_task(self, task_id: str) -> bool:
        return self.api.uncomplete_task(task_id)

    def delete_task(self, task_id: str) -> bool:
        return self.api.delete_task(task_id)
