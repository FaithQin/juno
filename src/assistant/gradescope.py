"""Gradescope has no API; these parse the pages juno's browser loads with your saved login.

Two pages matter: the dashboard (course cards) and a course page (the
`#assignments-student-table`). Before you've submitted, an assignment row is a
<button data-assignment-id>; after, it's a link to your submission. Due dates
are <time datetime="…"> elements, with a second one for the late deadline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from bs4 import BeautifulSoup

BASE = "https://www.gradescope.com"


@dataclass(frozen=True)
class GsCourse:
    id: int
    shortname: str
    name: str


@dataclass(frozen=True)
class GsAssignment:
    id: int
    course_id: int
    name: str
    submitted: bool
    status: str
    due_at: datetime | None
    late_due_at: datetime | None
    released_at: datetime | None
    url: str


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _time(el) -> datetime | None:
    raw = el.get("datetime") if el is not None else None
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S %z").astimezone(timezone.utc)
    except ValueError:
        return None


def parse_dashboard(html: str) -> list[GsCourse]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[GsCourse] = []
    for a in soup.select("a.courseBox"):
        m = re.fullmatch(r"/courses/(\d+)", a.get("href", ""))
        if not m:
            continue  # the "enroll in course" tile
        short = a.select_one(".courseBox--shortname")
        name = a.select_one(".courseBox--name")
        out.append(GsCourse(int(m[1]), short.get_text(" ", strip=True) if short else "", name.get_text(" ", strip=True) if name else ""))
    return out


def match_courses(gs_courses: list[GsCourse], course_codes: list[str]) -> dict[str, GsCourse]:
    """'CME 102' ↔ 'F26-CME-102-01/ENGR-155A-01' by comparing with punctuation and case removed."""
    matched: dict[str, GsCourse] = {}
    for code in course_codes:
        key = _squash(code)
        for c in gs_courses:
            if key and key in _squash(c.shortname):
                matched[code] = c
                break
    return matched


def parse_course(html: str, *, course_id: int) -> list[GsAssignment]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find(id="assignments-student-table")
    if table is None:
        return []
    out: list[GsAssignment] = []
    for tr in table.find_all("tr"):
        th = tr.find("th")
        if th is None or th.find_parent("thead") is not None:
            continue
        name = th.get_text(" ", strip=True)
        button = th.find("button")
        link = th.find("a")
        aid = None
        if button is not None and button.get("data-assignment-id"):
            aid = int(button["data-assignment-id"])
        elif link is not None:
            m = re.search(r"/assignments/(\d+)", link.get("href", ""))
            aid = int(m[1]) if m else None
        if aid is None or not name:
            continue
        status_el = tr.select_one(".submissionStatus--text, .submissionStatus--score")
        status = status_el.get_text(" ", strip=True) if status_el else ""
        submitted = "no submission" not in status.lower() and (link is not None or bool(status))
        times = tr.select("time.submissionTimeChart--dueDate")
        out.append(GsAssignment(
            id=aid, course_id=course_id, name=name, submitted=submitted, status=status,
            due_at=_time(times[0]) if times else None,
            late_due_at=_time(times[1]) if len(times) > 1 else None,
            released_at=_time(tr.select_one("time.submissionTimeChart--releaseDate")),
            url=f"{BASE}/courses/{course_id}/assignments/{aid}",
        ))
    return out
