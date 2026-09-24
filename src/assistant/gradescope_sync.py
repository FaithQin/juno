"""Gradescope → Todoist, every few hours, through the browser's saved login.

Same engine as the Canvas sync (`plan_sync` / `apply_plan`), same rules: identity by
Gradescope assignment id, update never recreate, tick when submitted. One addition,
from Faith's answer: the *first* run doesn't write anything. Hand-made Gradescope
tasks have no link to match on, so the job proposes title matches plus the new items
over Telegram and waits for a yes. After that, new assignments are created then texted.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from types import SimpleNamespace
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from .canvas_client import CanvasItem
from .config import CoursesConfig
from .db import Store
from .gradescope import BASE, match_courses, parse_course, parse_dashboard
from .sync import adopt_by_title, adopt_links, apply_plan, format_report, iso, plan_sync

Send = Callable[[str], Awaitable[None]]
JOB_KIND = "gradescope_first_run"
LOGIN_NAG = "gradescope logged me out. on your mac: uv run assistant browser-login gradescope, then scripts/deploy.sh"


def _fmt_due(dt: datetime | None, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%a %b %-d %-I:%M%p").lower() if dt else "no date"


class GradescopeSync:
    def __init__(self, *, browser, todoist, store: Store, courses_cfg: CoursesConfig, project_id: str,
                 sections: dict[str, str], tz: ZoneInfo, send: Send, now: Callable[[], datetime],
                 complete_when_submitted: bool = True):
        self.browser = browser
        self.todoist = todoist
        self.store = store
        self.courses_cfg = courses_cfg
        self.project_id = project_id
        self.section_ids = dict(sections)                               # section name → id
        self.section_names = {v: k for k, v in sections.items()}        # id → name
        self.tz = tz
        self.send = send
        self.now = now
        self.complete_when_submitted = complete_when_submitted

    # -- fetching --------------------------------------------------------------

    @staticmethod
    def _item(a, gs_course_id: int) -> CanvasItem:
        return CanvasItem(
            kind="gradescope", canvas_id=a.id, course_id=gs_course_id, name=a.name, due_at=a.due_at,
            html_url=a.url, submission_types=("gradescope",), external_url=None, group_id=None, group_name=None,
            submitted=a.submitted, published=True,
        )

    async def _fetch(self) -> tuple[list[CanvasItem], dict[int, object]] | None:
        dash, login = await self.browser.html(BASE + "/")
        if login:
            return None
        by_code = {c.code: c for c in self.courses_cfg.courses}
        matched = match_courses(parse_dashboard(dash), list(by_code))
        course_for = {gs.id: by_code[code] for code, gs in matched.items()}
        items: list[CanvasItem] = []
        for code, gs in matched.items():
            html, login = await self.browser.html(f"{BASE}/courses/{gs.id}")
            if login:
                return None
            items.extend(self._item(a, gs.id) for a in parse_course(html, course_id=gs.id))
        return items, course_for

    async def _login_needed(self, now: datetime) -> None:
        today = now.astimezone(self.tz).date().isoformat()
        if self.store.kv_get("gradescope_login_nag") != today:
            self.store.kv_set("gradescope_login_nag", today)
            await self.send(LOGIN_NAG)

    # -- the run ---------------------------------------------------------------

    def _sections_cache(self) -> dict:
        return {name: SimpleNamespace(id=sid, name=name) for name, sid in self.section_ids.items()}

    async def run(self, now: datetime | None = None, *, quiet: bool = False) -> str | None:
        """Sync once. Returns the text it sent (or would have sent, with quiet=True)."""
        now = now or self.now()
        fetched = await self._fetch()
        if fetched is None:
            await self._login_needed(now)
            return None if not quiet else LOGIN_NAG
        items, course_for = fetched

        active = self.todoist.tasks(self.project_id)
        links = self.store.links()
        tasks = self.store.tasks()
        for link in adopt_links(active, items, links):
            links[link.key] = link
            self.store.link(link.kind, link.canvas_id, link.course_id, link.task_id, adopted=True,
                            name=link.name, due_at=link.due_at, submitted=link.submitted)

        if not self.store.kv_get("gradescope_first_run_done"):
            open_items = [it for it in items if it.due_at is not None and not it.submitted and it.key not in links]
            task_course = {t.id: self.section_names.get(getattr(t, "section_id", None)) for t in active}
            pairs = adopt_by_title(open_items, active, course_for=course_for, task_course=task_course)
            paired = {it.key for it, _ in pairs}
            new = [it for it in open_items if it.key not in paired]
            if not pairs and not new:
                self.store.kv_set("gradescope_first_run_done", "1")
            else:
                digest = hashlib.sha1(",".join(sorted(f"{k[1]}" for k in [it.key for it in open_items])).encode()).hexdigest()
                if self.store.kv_get("gradescope_declined_digest") == digest:
                    return
                payload = {
                    "digest": digest,
                    "pairs": [{"id": it.canvas_id, "course_id": it.course_id, "task_id": t.id, "name": it.name,
                               "content": t.content, "due_at": iso(it.due_at), "submitted": it.submitted} for it, t in pairs],
                    "new": [{"id": it.canvas_id, "course_id": it.course_id, "name": it.name, "due_at": iso(it.due_at),
                             "url": it.html_url, "submitted": it.submitted} for it in new],
                    "course_for": {str(gid): c.code for gid, c in course_for.items()},
                }
                self.store.kv_set("pending_job", json.dumps({"kind": JOB_KIND, "payload": payload, "question": ""}))
                question = self._question(pairs, new, course_for)
                if not quiet:
                    await self.send(question)
                return question

        plan = plan_sync(items, course_for, links, tasks, tz=self.tz, complete_when_submitted=self.complete_when_submitted)
        report = apply_plan(plan, todoist=self.todoist, store=self.store, project_id=self.project_id,
                            sections=self._sections_cache(), tz=self.tz, dry_run=False)
        if report.changed or report.errors:
            text = "gradescope " + format_report(report)
            if not quiet:
                await self.send(text)
            return text
        return None

    def _question(self, pairs, new, course_for) -> str:
        n = len(pairs) + len(new)
        courses = {it.course_id for it, _ in pairs} | {it.course_id for it in new}
        lines = [f"gradescope: i found {n} open assignment{'s' if n != 1 else ''} across {len(courses)} course{'s' if len(courses) != 1 else ''}."]
        if pairs:
            lines.append(f"looks like {'a task' if len(pairs) == 1 else 'tasks'} you already have:")
            lines.extend(f"- {it.name} → {t.content}" for it, t in pairs)
        if new:
            lines.append("new (i'd add these to todoist):")
            lines.extend(f"- {course_for[it.course_id].code}: {it.name} (Gradescope), due {_fmt_due(it.due_at, self.tz)}" for it in new)
        lines.append("reply yes to link and add, or no to skip")
        return "\n".join(lines)

    # -- the answer, from chat ---------------------------------------------------

    async def approve(self, payload: dict, approved: bool) -> str:
        if not approved:
            self.store.kv_set("gradescope_declined_digest", payload.get("digest", ""))
            return "ok, skipped. i'll only ask again if gradescope changes"

        for pr in payload.get("pairs", []):
            self.store.link("gradescope", pr["id"], pr["course_id"], pr["task_id"], adopted=True,
                            name=pr["name"], due_at=pr["due_at"], submitted=pr["submitted"])
            self.store.upsert_task(pr["task_id"], batch_key=None, managed=False, content=pr["content"],
                                   description=None, due_at=None, completed=False)
        self.store.kv_set("gradescope_first_run_done", "1")

        by_code = {c.code: c for c in self.courses_cfg.courses}
        course_for = {int(gid): by_code[code] for gid, code in payload.get("course_for", {}).items() if code in by_code}
        new_items = [
            CanvasItem(kind="gradescope", canvas_id=n["id"], course_id=n["course_id"], name=n["name"],
                       due_at=datetime.fromisoformat(n["due_at"]) if n["due_at"] else None, html_url=n["url"],
                       submission_types=("gradescope",), external_url=None, group_id=None, group_name=None,
                       submitted=n["submitted"], published=True)
            for n in payload.get("new", [])
        ]
        added = 0
        if new_items:
            plan = plan_sync(new_items, course_for, self.store.links(), self.store.tasks(), tz=self.tz)
            report = apply_plan(plan, todoist=self.todoist, store=self.store, project_id=self.project_id,
                                sections=self._sections_cache(), tz=self.tz, dry_run=False)
            added = len(report.created)
        n = len(payload.get("pairs", []))
        linked = f"linked {n} existing task{'s' if n != 1 else ''}"
        return f"{linked}, added {added}" if added else f"{linked}, nothing new to add"
