"""Todoist helpers shared by the nudges, the brief and the chat tools.

Pure functions over Todoist `Task` objects (or anything with the same
attributes, which is what the tests use).
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .reminders import DueTask


def _squash(text: str) -> str:
    """'CME-102' → 'cme102': what's left after case and punctuation are ignored."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def normalize_course(text: str, courses: list[str]) -> str | None:
    """'cme102', 'CME-102', 'cme 102' → 'CME 102'. None if it isn't one of your courses."""
    key = _squash(text)
    if not key:
        return None
    for course in courses:
        if _squash(course) == key:
            return course
    return None


def course_of(task, *, sections: dict[str, str] | None = None, projects: dict[str, str] | None = None) -> str | None:
    """Which course a task belongs to: its course sub-project first, then its legacy section
    in Classes, else None (general, e.g. the add/drop deadline in the Classes root).

    `projects` maps sub-project id → code, `sections` maps legacy section id → code. The project
    wins, so a section Faith later makes *inside* a course sub-project still reads as that course.
    """
    code = (projects or {}).get(getattr(task, "project_id", None))
    return code or (sections or {}).get(getattr(task, "section_id", None))


def due_task_from(task, *, tz: ZoneInfo, sections: dict[str, str],
                  projects: dict[str, str] | None = None) -> DueTask | None:
    """Todoist task → DueTask, or None when it has no due date.

    Todoist due dates come in three shapes: a date (no time), a naive datetime
    (floating, meaning "in your timezone"), or an aware UTC datetime.
    """
    due = getattr(task, "due", None)
    raw = getattr(due, "date", None) if due is not None else None
    if raw is None:
        return None
    if isinstance(raw, datetime):
        due_at = raw if raw.tzinfo else raw.replace(tzinfo=tz)
        has_time = True
    else:
        due_at = datetime.combine(raw, time(23, 59), tzinfo=tz)
        has_time = False

    created = getattr(task, "created_at", None)
    if isinstance(created, str):
        created = datetime.fromisoformat(created.replace("Z", "+00:00"))

    return DueTask(
        task_id=task.id,
        content=task.content,
        due_at=due_at,
        priority=getattr(task, "priority", 1) or 1,
        course=course_of(task, sections=sections, projects=projects),
        created_at=created,
        has_time=has_time,
    )


def match_tasks(query: str, tasks: list, *, sections: dict[str, str], projects: dict[str, str] | None = None) -> list:
    """Every task whose title (plus course) contains every word of the query.

    Short or numeric words ("1", "a1") must match a whole token, so
    "assignment 1" doesn't also match "CS 106B" through the "1" in "106B".
    Longer words may match inside tokens, and with punctuation ignored, so
    "cs106b" finds "CS 106B".
    """
    words = [w for w in query.lower().split() if w]
    if not words:
        return []
    out = []
    for t in tasks:
        course = course_of(t, sections=sections, projects=projects) or ""
        hay = f"{t.content} {course}".lower()
        tokens = set(re.findall(r"[a-z0-9]+", hay))
        squashed = _squash(hay)
        if all(
            w in tokens or (len(w) >= 3 and (w in hay or _squash(w) in squashed))
            for w in words
        ):
            out.append(t)
    return out
