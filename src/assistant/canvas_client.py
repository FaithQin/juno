"""Read-only Canvas access, normalised into `CanvasItem`s.

Two Canvas objects matter for a student:
  * assignments  — anything gradable, including Gradescope assignments an
                   instructor linked into Canvas (they show up as
                   submission_type "external_tool" with a gradescope URL)
  * quizzes      — practice quizzes and surveys that are *not* assignments
                   (graded quizzes already appear as assignments)

Calls are sequential on purpose: Canvas throttles parallel requests harder
than a steady stream (see RESEARCH.md → Canvas API cheat sheet).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from canvasapi import Canvas
from canvasapi.exceptions import Forbidden, ResourceDoesNotExist, Unauthorized

SUBMITTED_STATES = {"submitted", "graded", "pending_review"}


@dataclass(frozen=True)
class CanvasItem:
    kind: str                       # "assignment" | "quiz"
    canvas_id: int
    course_id: int
    name: str
    due_at: datetime | None         # timezone-aware UTC, or None
    html_url: str
    submission_types: tuple[str, ...]
    external_url: str | None        # for external_tool assignments (Gradescope etc.)
    group_id: int | None            # Canvas assignment group; None for stand-alone quizzes
    group_name: str | None
    submitted: bool
    published: bool
    gradescope_id: int | None = None  # the Gradescope assignment an external tool opens, when Canvas says

    @property
    def key(self) -> tuple[str, int]:
        return (self.kind, self.canvas_id)

    @property
    def is_gradescope(self) -> bool:
        return self.gradescope_id is not None or bool(self.external_url and "gradescope" in self.external_url.lower())


def parse_canvas_time(value: str | None) -> datetime | None:
    """Canvas sends '2026-09-25T06:59:59Z'. Return an aware UTC datetime."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc)


GRADESCOPE_RESOURCE_RE = re.compile(r"assignment-(\d+)")
GRADESCOPE_URL_RE = re.compile(r"gradescope\.com/courses/\d+/assignments/(\d+)")


def gradescope_id_of(ext: dict | None) -> int | None:
    """Which Gradescope assignment a Canvas external-tool assignment opens, if Canvas says.

    Stanford's Gradescope tool launches through a proxy (lti.int.turnitin.com/launch/gs-proxy),
    so the URL doesn't name the assignment, but the launch parameters do:
    custom_params.custom_gradescope_resource_id = "assignment-8676496". That id is the same one
    the Gradescope sync links, which is how one task can carry both (see twins.py).
    """
    if not isinstance(ext, dict):
        return None
    params = ext.get("custom_params") or {}
    m = GRADESCOPE_RESOURCE_RE.fullmatch(str(params.get("custom_gradescope_resource_id") or "").strip())
    if m is None:
        m = GRADESCOPE_URL_RE.search(str(ext.get("url") or ""))
    return int(m[1]) if m else None


def _is_submitted(submission: dict | None) -> bool:
    if not submission:
        return False
    if submission.get("submitted_at"):
        return True
    return submission.get("workflow_state") in SUBMITTED_STATES


class CanvasClient:
    def __init__(self, base_url: str, token: str):
        self.api = Canvas(base_url, token)

    def active_courses(self) -> list[tuple[int, str, str]]:
        """(id, course_code, name) for every course you're currently enrolled in."""
        user = self.api.get_current_user()
        out = []
        for c in user.get_courses(enrollment_state="active"):
            out.append((c.id, getattr(c, "course_code", "") or "", getattr(c, "name", "") or ""))
        return out

    def items_for_course(self, course_id: int) -> list[CanvasItem]:
        course = self.api.get_course(course_id)
        groups = {g.id: g.name for g in course.get_assignment_groups()}
        items: list[CanvasItem] = []

        for a in course.get_assignments(include=["submission"], per_page=100):
            ext = getattr(a, "external_tool_tag_attributes", None) or {}
            group_id = getattr(a, "assignment_group_id", None)
            items.append(CanvasItem(
                kind="assignment",
                canvas_id=a.id,
                course_id=course_id,
                name=(a.name or "").strip(),
                due_at=parse_canvas_time(getattr(a, "due_at", None)),
                html_url=a.html_url,
                submission_types=tuple(getattr(a, "submission_types", None) or []),
                external_url=ext.get("url") if isinstance(ext, dict) else None,
                group_id=group_id,
                group_name=groups.get(group_id),
                submitted=_is_submitted(getattr(a, "submission", None)),
                published=bool(getattr(a, "published", True)),
                gradescope_id=gradescope_id_of(ext),
            ))

        try:
            quizzes = list(course.get_quizzes(per_page=100))
        except (ResourceDoesNotExist, Forbidden, Unauthorized):
            quizzes = []  # Quizzes tab disabled (or New Quizzes only) for this course
        for q in quizzes:
            if getattr(q, "assignment_id", None):
                continue  # graded quiz: already listed as an assignment
            items.append(CanvasItem(
                kind="quiz",
                canvas_id=q.id,
                course_id=course_id,
                name=(getattr(q, "title", "") or "").strip(),
                due_at=parse_canvas_time(getattr(q, "due_at", None)),
                html_url=q.html_url,
                submission_types=("online_quiz",),
                external_url=None,
                group_id=None,
                group_name=getattr(q, "quiz_type", None),
                submitted=False,  # Canvas doesn't report this cheaply for practice quizzes
                published=bool(getattr(q, "published", True)),
            ))

        return items
