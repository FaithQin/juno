"""The class check: once a day, compare what Canvas and Todoist say about Faith's classes with
juno's class list (courses.yaml), and text her once about each difference.

On 2026-10-03 juno turned out to know nothing about three Todoist class projects she had made
(EE 160A, EE 227, EE 260A) or two courses Canvas listed (Robot Autonomy, Robot Perception). juno
can't edit its own configuration, so this only tells her; a difference is texted once, and
forgotten when it goes away, so a later return is news again.

What counts as a difference:
  * a Canvas course with a real course code (F26-…) that no configured code, alias or dropped
    code matches, and whose id isn't a configured `canvas_id` (a cross-listed site is named after
    its first listing, cut short: EE 160A's is "F26-AA-174A-01..."). Canvas's one-off modules (the
    honor-code course) have no such code;
  * a Todoist project directly under Classes that no course owns, unless it is named after a
    dropped course (its project may linger, empty or archived);
  * a graded course juno syncs from Canvas that Canvas no longer lists (probably dropped).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Awaitable, Callable

from .config import CoursesConfig
from .db import Store

Send = Callable[[str], Awaitable[None]]
SEEN_KEY = "course_watch_seen"
COURSE_CODE_RE = re.compile(r"^[A-Z]\d{2}-([A-Z]+)-(\d+[A-Z]*)")      # F26-EE-227-01/CS-227A-01 → EE 227
FOOTER = "juno's class list lives in courses.yaml; ask claude code to change it"
log = logging.getLogger(__name__)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def find_changes(*, canvas_courses: list[tuple[int, str, str]], projects, courses_cfg: CoursesConfig,
                 parent_id: str) -> list[tuple[str, str]]:
    """(key, sentence) for each difference, in a stable order: Canvas, then Todoist, then gone."""
    known = {_squash(code) for c in courses_cfg.courses for code in [c.code, *c.aliases]}
    known |= {_squash(code) for d in courses_cfg.dropped for code in [d.code, *d.aliases]}
    known.discard("")
    configured = {c.canvas_id for c in courses_cfg.courses if c.canvas_id is not None}
    out: list[tuple[str, str]] = []
    for cid, code, name in canvas_courses:
        m = COURSE_CODE_RE.match(code or "")
        if not m or cid in configured or any(k in _squash(code) for k in known):
            continue
        out.append((f"canvas:{cid}", f"canvas lists {m[1]} {m[2]} ({name}), which juno doesn't know as a class"))
    owned = {c.project_id for c in courses_cfg.courses if c.project_id}
    dropped = {_squash(d.code) for d in courses_cfg.dropped}
    for p in projects:
        if getattr(p, "parent_id", None) != parent_id or p.id in owned or _squash(p.name) in dropped:
            continue
        out.append((f"todoist:{p.id}", f"todoist has a project {p.name!r} under Classes that juno doesn't know as a class"))
    active = {cid for cid, _, _ in canvas_courses}
    for c in courses_cfg.graded():
        if c.canvas_id and c.canvas_id not in active:
            out.append((f"gone:{c.code}", f"canvas no longer lists {c.code}; if you dropped it, juno should stop syncing it"))
    return out


class CourseWatch:
    def __init__(self, *, fetch_canvas: Callable[[], list[tuple[int, str, str]]], fetch_projects: Callable[[], list],
                 courses_cfg: CoursesConfig, parent_id: str, store: Store, send: Send):
        self.fetch_canvas = fetch_canvas
        self.fetch_projects = fetch_projects
        self.courses_cfg = courses_cfg
        self.parent_id = parent_id
        self.store = store
        self.send = send

    async def run(self) -> str | None:
        canvas = await asyncio.to_thread(self.fetch_canvas)
        projects = await asyncio.to_thread(self.fetch_projects)
        changes = find_changes(canvas_courses=canvas, projects=projects, courses_cfg=self.courses_cfg, parent_id=self.parent_id)
        seen = set(json.loads(self.store.kv_get(SEEN_KEY) or "[]"))
        self.store.kv_set(SEEN_KEY, json.dumps(sorted(k for k, _ in changes)))   # forget what's no longer true
        new = [text for key, text in changes if key not in seen]
        if not new:
            return None
        text = "class check:\n" + "\n".join(f"- {t}" for t in new) + "\n" + FOOTER
        await self.send(text)
        return text
