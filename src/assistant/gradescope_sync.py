"""Gradescope → Todoist, every few hours, through the browser's saved login.

Same engine as the Canvas sync (`plan_sync` / `apply_plan`), same rules: identity by
Gradescope assignment id, update never recreate, tick when submitted. One addition,
from Faith's answer: the *first* run doesn't write anything. Hand-made Gradescope
tasks have no link to match on, so the job proposes title matches plus the new items
over Telegram and waits for a yes. After that, new assignments are created then texted, with
two exceptions:
  * an assignment Canvas also posts (an external tool that names this Gradescope id) joins the
    task the Canvas side already has, by id (twins.py);
  * an assignment that plausibly is a task Faith wrote down herself ("ENGR 40M: PSET 1
    (Gradescope)" from the syllabus) is asked about first, one question at a time, and linked
    only on a yes (matching.py). No makes it its own task, as before.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from .canvas_client import CanvasItem
from .config import CoursesConfig
from .db import Store
from .gradescope import BASE, match_courses, parse_course, parse_dashboard
from .matching import due_gap, plausible_matches
from .sync import (_task_due_iso, adopt_by_title, adopt_links, adopt_same_title, apply_plan, format_report, iso,
                   plan_sync, task_title)
from .tasks import course_of
from .twins import link_twins, load_twins

Send = Callable[[str], Awaitable[None]]
JOB_KIND = "gradescope_first_run"
MATCH_KIND = "gradescope_match"                   # "is this new assignment the task you already have?"
MATCH_DECLINED = "gradescope_match_declined"      # ["<gradescope id>:<task id>", ...] she said no to
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
        self.project_id = project_id                                    # the parent, Classes
        # Legacy sections inside Classes, {name: Section}. One cache for the job's lifetime:
        # apply_plan adds any section it creates, so the next run reuses it instead of adding another.
        self._sections = {name: SimpleNamespace(id=sid, name=name) for name, sid in sections.items()}
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

    def _read_ids(self) -> list[str]:
        """Classes plus every course sub-project: moved tasks keep their id, so they're the same tasks."""
        return self.courses_cfg.class_project_ids(self.project_id)

    def _course_of(self, task) -> str | None:
        """A task's course: its sub-project first, then its legacy section in Classes."""
        live = {name: s.id for name, s in self._sections.items()}
        by_section = {sid: code for code, sid in self.courses_cfg.course_sections(live).items()}
        return course_of(task, sections=by_section, projects=self.courses_cfg.course_by_project())

    async def run(self, now: datetime | None = None, *, quiet: bool = False) -> str | None:
        """Sync once. Returns the text it sent (or would have sent, with quiet=True)."""
        now = now or self.now()
        fetched = await self._fetch()
        if fetched is None:
            await self._login_needed(now)
            return None if not quiet else LOGIN_NAG
        items, course_for = fetched

        active = self.todoist.tasks_in(self._read_ids())
        links = self.store.links()
        tasks = self.store.tasks()
        for link in adopt_links(active, items, links):
            links[link.key] = link
            self.store.link(link.kind, link.canvas_id, link.course_id, link.task_id, adopted=True,
                            name=link.name, due_at=link.due_at, submitted=link.submitted)

        if not self.store.kv_get("gradescope_first_run_done"):
            open_items = [it for it in items if it.due_at is not None and not it.submitted and it.key not in links]
            task_course = {t.id: self._course_of(t) for t in active}
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
                question = self._question(pairs, new, course_for)
                slot = self.store.proposal_slot(JOB_KIND, digest)
                if slot == "free":
                    self.store.propose_job(JOB_KIND, payload, question, at=now)   # first time: ask; after that, wait
                    if not quiet:
                        await self.send(question)
                elif slot != "asked":
                    n = len(pairs) + len(new)
                    return (f"gradescope: {n} open assignment{'s' if n != 1 else ''} to propose, "
                            f"once you've answered the {slot} proposal") if quiet else None
                return question

        # after the first run. Identity first: the Canvas half of this assignment already has a task
        task_course = {t.id: self._course_of(t) for t in active}
        by_task = {t.id: t for t in active}
        by_twin = link_twins(items, links, load_twins(self.store))
        self._keep(by_twin, links)
        # an exact title of a task a sync already follows (the other sync's twin) is shared, not twinned
        followed = {l.task_id for l in links.values()}
        same_title = adopt_same_title(items, [t for t in active if t.id in followed], links,
                                      course_for=course_for, task_course=task_course)
        self._keep(same_title, links)
        # a task she wrote down herself is only ever a guess: ask, and hold the item back meanwhile
        held, notes, waiting = await self._ask_about_matches(items, active, links, course_for, task_course, now, quiet)

        plan = plan_sync([it for it in items if it.key not in held], course_for, links, tasks, tz=self.tz,
                         complete_when_submitted=self.complete_when_submitted)
        report = apply_plan(plan, todoist=self.todoist, store=self.store, project_id=self.project_id,
                            sections=self._sections, tz=self.tz, dry_run=False)
        report.adopted += [f"{l.name} → {task_title(l.task_id, by_task, tasks)}" for l in by_twin + same_title]
        report.notes += notes
        text = None
        if report.changed or report.errors or notes:
            text = "gradescope " + format_report(report)
            if not quiet:
                await self.send(text)
        if quiet and waiting:
            return "\n\n".join(x for x in (text, waiting) if x)
        return text

    def _keep(self, new_links, links) -> None:
        for link in new_links:
            links[link.key] = link
            self.store.link(link.kind, link.canvas_id, link.course_id, link.task_id, adopted=True,
                            name=link.name, due_at=link.due_at, submitted=link.submitted)

    # -- a new assignment that may be a task she already has ------------------------

    def _task_when(self, task) -> str:
        raw = getattr(getattr(task, "due", None), "date", None)
        if isinstance(raw, datetime):
            return _fmt_due(raw if raw.tzinfo else raw.replace(tzinfo=self.tz), self.tz)
        return raw.strftime("%a %b %-d").lower() if raw else "no date"

    def _same_instant(self, due_at: datetime, task) -> bool:
        raw = getattr(getattr(task, "due", None), "date", None)
        return isinstance(raw, datetime) and due_gap(due_at, task, self.tz) == timedelta(0)

    async def _ask_about_matches(self, items, active, links, course_for, task_course, now, quiet):
        """Returns (item keys to hold back from the plan, report notes, text for a quiet run)."""
        followed = {l.task_id for l in links.values()}
        hand_made = [t for t in active if t.id not in followed]
        fresh = [it for it in items if it.key not in links and it.due_at is not None and not it.submitted]
        declined = set(json.loads(self.store.kv_get(MATCH_DECLINED) or "[]"))
        pairs = [(it, t) for it, t in plausible_matches(fresh, hand_made, course_for=course_for,
                                                         task_course=task_course, tz=self.tz)
                 if f"{it.canvas_id}:{t.id}" not in declined]
        job = self.store.pending_job()
        if not pairs:
            if job and job["kind"] == MATCH_KIND:        # answered some other way (e.g. Canvas linked it by id)
                self.store.kv_delete("pending_job")
                names = ", ".join(p["name"] for p in job["payload"].get("pairs", []))
                return set(), [f"no need to answer my question about {names}, that's sorted"], None
            return set(), [], None

        held = {it.key for it, _ in pairs}
        n = len(pairs)
        digest = hashlib.sha1(";".join(sorted(f"{it.canvas_id}:{t.id}" for it, t in pairs)).encode()).hexdigest()
        slot = self.store.proposal_slot(MATCH_KIND, digest)
        if slot not in ("free", "asked"):
            return held, [], (f"gradescope: {n} new assignment{'s look' if n != 1 else ' looks'} like "
                              f"{'tasks' if n != 1 else 'a task'} you already have; i'll ask once you've answered the {slot} proposal")
        question = self._match_question(pairs)
        if slot == "free":
            payload = {
                "digest": digest,
                "pairs": [{"id": it.canvas_id, "course_id": it.course_id, "name": it.name, "due_at": iso(it.due_at),
                           "url": it.html_url, "submitted": it.submitted, "task_id": t.id, "content": t.content}
                          for it, t in pairs],
                "course_for": {str(gid): c.code for gid, c in course_for.items()},
            }
            self.store.propose_job(MATCH_KIND, payload, question, at=now)   # asked once; later runs wait
            if not quiet:
                await self.send(question)
        return held, [], question

    def _match_question(self, pairs) -> str:
        one = len(pairs) == 1
        lines = ["gradescope: a new assignment looks like a task you already have:" if one else
                 f"gradescope: {len(pairs)} new assignments look like tasks you already have:"]
        for it, t in pairs:
            theirs = _fmt_due(it.due_at, self.tz)
            when = f"both due {theirs}" if self._same_instant(it.due_at, t) else f"gradescope: {theirs}, yours: {self._task_when(t)}"
            lines.append(f"- {it.name} → {t.content} ({when})")
        lines.append("reply yes to link them (i'll tick it when you submit and follow gradescope's date changes), "
                     "or no to add it as a new task" if one else
                     "reply yes to link them (i'll tick them when you submit and follow gradescope's date changes), "
                     "or no to add them as new tasks")
        return "\n".join(lines)

    async def approve_match(self, payload: dict, approved: bool) -> str:
        """Yes: record each link (adopted), leaving her title, notes and date alone; Gradescope's later
        date changes and a submission reach the task from now on. No: make the Gradescope task, as
        without this question, and never pair those two again."""
        links = self.store.links()
        pairs = [p for p in payload.get("pairs", []) if ("gradescope", p["id"]) not in links]  # linked meanwhile: done
        if not approved:
            declined = set(json.loads(self.store.kv_get(MATCH_DECLINED) or "[]"))
            declined |= {f"{p['id']}:{p['task_id']}" for p in payload.get("pairs", [])}
            self.store.kv_set(MATCH_DECLINED, json.dumps(sorted(declined)))
            made = self._create(pairs, payload)
            if not made:
                return "ok, i'll keep them apart"
            return f"ok, added {'it as a new task' if len(made) == 1 else 'them as new tasks'}: {', '.join(made)}"

        linked, notes, gone = [], [], []
        for p in pairs:
            try:
                task = await asyncio.to_thread(self.todoist.get_task, p["task_id"])
            except Exception:
                gone.append(p)                             # she deleted it meanwhile: make the Gradescope task instead
                continue
            self.store.link("gradescope", p["id"], p["course_id"], p["task_id"], adopted=True,
                            name=p["name"], due_at=p["due_at"], submitted=p["submitted"])
            self.store.upsert_task(p["task_id"], batch_key=None, managed=False, content=task.content,
                                   description=getattr(task, "description", None), due_at=_task_due_iso(task),
                                   completed=bool(getattr(task, "is_completed", False)))
            linked.append(f"{p['name']} → {task.content}")
            due = datetime.fromisoformat(p["due_at"]) if p.get("due_at") else None
            if due is not None and not self._same_instant(due, task):
                yours = self._task_when(task)
                if yours != due.astimezone(self.tz).strftime("%a %b %-d").lower():   # a date-only task on the same day is fine
                    notes.append(f"heads up: gradescope has {task.content} due {_fmt_due(due, self.tz)}, "
                                 f"yours says {yours}. i left yours")
        lines = [f"linked {len(linked)}: {', '.join(linked)}"] if linked else []
        lines += notes
        made = self._create(gone, payload)
        if made:
            lines.append(f"couldn't find {'that task' if len(gone) == 1 else 'those tasks'} anymore, so i added: {', '.join(made)}")
        return "\n".join(lines) if lines else "nothing to link anymore; it's sorted"

    def _create(self, pairs: list[dict], payload: dict) -> list[str]:
        if not pairs:
            return []
        by_code = {c.code: c for c in self.courses_cfg.courses}
        course_for = {int(gid): by_code[code] for gid, code in payload.get("course_for", {}).items() if code in by_code}
        items = [CanvasItem(kind="gradescope", canvas_id=p["id"], course_id=p["course_id"], name=p["name"],
                            due_at=datetime.fromisoformat(p["due_at"]) if p["due_at"] else None, html_url=p["url"],
                            submission_types=("gradescope",), external_url=None, group_id=None, group_name=None,
                            submitted=p["submitted"], published=True)
                 for p in pairs]
        plan = plan_sync(items, course_for, self.store.links(), self.store.tasks(), tz=self.tz)
        report = apply_plan(plan, todoist=self.todoist, store=self.store, project_id=self.project_id,
                            sections=self._sections, tz=self.tz, dry_run=False)
        return [c.content for c in plan.creates][: len(report.created)]

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
                                sections=self._sections, tz=self.tz, dry_run=False)
            added = len(report.created)
        n = len(payload.get("pairs", []))
        linked = f"linked {n} existing task{'s' if n != 1 else ''}"
        return f"{linked}, added {added}" if added else f"{linked}, nothing new to add"
