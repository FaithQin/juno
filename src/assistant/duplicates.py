"""Duplicate tasks in Todoist: find them, propose removing the copies, act only on a yes.

Two syncs (Canvas, Gradescope) and Faith's own hands all write to Todoist, so twins happen: the
Canvas sync and the Gradescope sync each made a task for the same Gradescope-linked assignment
before they learned to share one (see `sync.adopt_same_title`). This check runs after every
Canvas sync and on demand from chat ("check for duplicates").

"Duplicate" is deliberately narrow. Two active tasks are copies when they sit in the same project
and their titles are the same once the course code, a source suffix like "(Gradescope)", case and
punctuation are ignored, with due dates no more than a day apart (a weekly "reading" task a week
apart is a series, not a copy, and so is "Breakfast" at 8:15am on two days); or, in any project,
their descriptions point at the same Canvas or Gradescope assignment and their titles are that same,
or both are just the assignment's name worded differently (`assignment_named`: "Lab 1 prelab" =
"Prelab 1"; her "Pset1: work block" tasks carry the link too, but say more than the assignment, so
they are steps, not copies); or they are linked to the two halves of one assignment (a Canvas
external tool that opens a Gradescope assignment, by id; see twins.py). A question whose copies are
no longer found (done, deleted, or no longer alike) is withdrawn, so it can't hold up the queue.
The kept task is the one a sync
tracks (a Canvas link, then a Gradescope link, then the Canvas half of a Gradescope assignment,
which only ticks once grades flow back), else the older one. The copies are deleted only after
Faith says yes, each with an undo snapshot; notes she wrote on a copy are added to the kept task
first, and any sync link on a copy moves to the kept task so a submission still ticks it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from .db import ItemLink, Store
from .matching import signature
from .sync import links_in
from .twins import load_twins

Send = Callable[[str], Awaitable[None]]
JOB_KIND = "duplicates"
DECLINED_KEY = "duplicates_declined"
SUFFIX_RE = re.compile(r"\((gradescope|paperless|canvas|ed)\)", re.IGNORECASE)
LINK_SCORE = {"assignment": 3, "quiz": 3, "gradescope": 2}
TWIN_SCORE = 1                     # the Canvas half of a Gradescope assignment: Canvas sees no submission, only grades
LINK_RE = re.compile(r"\[[^\]]*\]\([^)]*\)|https?://\S+")
GENERATED_RE = re.compile(r"^[A-Z][\w ]* on \[(?:Canvas|Gradescope)\]\(\S+\)$")
BRACKETS_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
COURSE_CODE_RE = re.compile(r"^\s*[A-Z]{2,10}\s?\d{1,3}[A-Z]{0,2}\s*:")   # "EE 160A:", a course no sync follows
log = logging.getLogger(__name__)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def normalize_title(content: str, *, courses: list[str]) -> str:
    """'MATSCI 88Q: Pre-lab 1 (Gradescope)' → 'prelab1': what two titles must share to be the same task."""
    body = _squash(SUFFIX_RE.sub("", content))
    for code in sorted((_squash(c) for c in courses), key=len, reverse=True):
        if code and body.startswith(code):
            return body[len(code):]
    return body


def assignment_named(content: str, *, courses: list[str]) -> tuple | None:
    """The assignment a name is just the name of, however it is worded: (numbers, assignment words),
    with the course code and anything in brackets dropped. 'ENGR 40M: Lab 1 prelab (Gradescope)'
    and 'Prelab 1' are both (1, {pre, lab}). 'CME 102 Pset1: work block (Tue night)' says more than
    the assignment, so it is a step towards Pset1 and gets None; so does a name with no number
    (no number, no guess, as in matching.py)."""
    code = next((c for c in sorted(courses, key=len, reverse=True) if _squash(content).startswith(_squash(c))), "")
    text = BRACKETS_RE.sub(" ", content)
    sig = signature(text if code else COURSE_CODE_RE.sub(" ", text), code)
    return (sig.numbers, sig.kinds) if sig.numbers and not sig.words else None


def _due(task):
    return getattr(getattr(task, "due", None), "date", None)


def _local(task, tz: ZoneInfo) -> datetime | None:
    raw = _due(task)
    if isinstance(raw, datetime):
        return (raw if raw.tzinfo else raw.replace(tzinfo=tz)).astimezone(tz)
    return None


def _due_day(task, tz: ZoneInfo) -> date | None:
    at = _local(task, tz)
    return at.date() if at is not None else _due(task)


def _close_enough(a, b, tz: ZoneInfo) -> bool:
    da, db = _due_day(a, tz), _due_day(b, tz)
    if da is None or db is None:
        return True
    ta, tb = _local(a, tz), _local(b, tz)
    if da != db and ta is not None and tb is not None and ta.time() == tb.time():
        return False                                   # same clock time on another day: a daily habit, not a copy
    return abs(da - db) <= timedelta(days=1)


def hand_written(description: str | None) -> bool:
    """Notes Faith wrote, as opposed to the one-line link a sync puts on the tasks it makes."""
    text = (description or "").strip()
    if not text or GENERATED_RE.match(text):
        return False
    lines = text.splitlines()
    if lines[0].startswith("Canvas ") and all(l.lstrip().startswith("-") for l in lines[1:] if l.strip()):
        return False                                   # a sync's batch checklist
    words = LINK_RE.sub(" ", text)                      # links alone are not notes
    return bool(re.search(r"[A-Za-z]{2}", words))


def _created(task) -> str:
    c = getattr(task, "created_at", None)
    return c.isoformat() if isinstance(c, datetime) else str(c or "")


@dataclass
class DupGroup:
    keep: object
    extras: list

    @property
    def fingerprint(self) -> str:
        return ",".join(sorted(t.id for t in [self.keep, *self.extras]))


def find_duplicates(tasks, *, links: dict[tuple[str, int], ItemLink], courses: list[str],
                    tz: ZoneInfo = ZoneInfo("America/Los_Angeles"), twins: dict[int, int] | None = None) -> list[DupGroup]:
    """`twins` is {gradescope id: canvas assignment id} (twins.load_twins): tasks linked to the two
    halves of one assignment are copies whatever their titles."""
    tasks = list(tasks)
    twins = twins or {}
    parent = {t.id: t.id for t in tasks}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    by_link: dict[tuple[str, int], list] = {}
    by_title: dict[tuple[str, str], list] = {}
    norm: dict[str, str] = {}
    for t in tasks:
        for key in links_in(getattr(t, "description", None)):
            by_link.setdefault(key, []).append(t)
        norm[t.id] = normalize_title(t.content, courses=courses)
        if len(norm[t.id]) >= 3:
            by_title.setdefault((getattr(t, "project_id", None), norm[t.id]), []).append(t)
    for group in by_link.values():                    # the same assignment link and the same name: copies whatever the
        named = {t.id: assignment_named(t.content, courses=courses) for t in group}   # dates (her work blocks carry
        for i, a in enumerate(group):                 # the link too, but under longer names)
            for b in group[i + 1:]:
                if norm[a.id] == norm[b.id] or named[a.id] is not None and named[a.id] == named[b.id]:
                    union(a.id, b.id)
    for group in by_title.values():                   # the same title: copies unless they are a series
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if _close_enough(a, b, tz):
                    union(a.id, b.id)
    for gs_id, canvas_id in twins.items():            # one assignment's two halves: copies, by id
        a, b = links.get(("gradescope", gs_id)), links.get(("assignment", canvas_id))
        if a is not None and b is not None and a.task_id in parent and b.task_id in parent:
            union(a.task_id, b.task_id)

    canvas_halves = set(twins.values())
    score: dict[str, int] = {}
    for link in links.values():
        points = TWIN_SCORE if link.kind == "assignment" and link.canvas_id in canvas_halves else LINK_SCORE.get(link.kind, 1)
        score[link.task_id] = max(score.get(link.task_id, 0), points)
    clusters: dict[str, list] = {}
    for t in tasks:
        clusters.setdefault(find(t.id), []).append(t)
    out: list[DupGroup] = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda t: (-score.get(t.id, 0), _created(t), t.id))
        out.append(DupGroup(ordered[0], ordered[1:]))
    return sorted(out, key=lambda g: g.keep.content.lower())


class DuplicateCheck:
    def __init__(self, *, todoist, store: Store, courses: list[str], tz: ZoneInfo, send: Send,
                 now: Callable[[], datetime]):
        self.todoist = todoist
        self.store = store
        self.courses = list(courses)
        self.tz = tz
        self.send = send
        self.now = now

    # -- helpers --------------------------------------------------------------------

    def _when(self, task) -> str | None:
        raw = _due(task)
        if raw is None:
            return None
        if isinstance(raw, datetime):
            raw = raw if raw.tzinfo else raw.replace(tzinfo=self.tz)
            return raw.astimezone(self.tz).strftime("%a %b %-d %-I:%M%p").lower()
        return raw.strftime("%a %b %-d").lower()

    def _dump(self, t) -> dict:
        """Everything undo needs to put the task back (same shape as ChatOps.delete_task's snapshot)."""
        raw = _due(t)
        return {
            "id": t.id, "content": t.content, "description": getattr(t, "description", "") or "",
            "project_id": getattr(t, "project_id", None), "section_id": getattr(t, "section_id", None),
            "priority": getattr(t, "priority", 1) or 1,
            "due": raw.isoformat() if raw is not None else None,
            "due_kind": "datetime" if isinstance(raw, datetime) else "date" if raw else None,
        }

    @staticmethod
    def _carries(extra, keep) -> bool:
        notes = (getattr(extra, "description", "") or "").strip()
        return hand_written(notes) and notes not in (getattr(keep, "description", "") or "")

    def _declined(self) -> set[str]:
        return set(json.loads(self.store.kv_get(DECLINED_KEY) or "[]"))

    @staticmethod
    def _count(n: int) -> str:
        return f"{n} pair{'s' if n != 1 else ''} look{'s' if n == 1 else ''} like duplicates"

    def _question(self, groups: list[DupGroup]) -> str:
        lines = [f"todoist: {self._count(len(groups))}."]
        for g in groups:
            keep_when = self._when(g.keep)
            for extra in g.extras:
                when = self._when(extra)
                bits = []
                if when and keep_when and when == keep_when:
                    bits.append(f"both due {when}")
                elif when and keep_when:
                    bits.append(f"due {when} vs {keep_when}")
                if self._carries(extra, g.keep):
                    bits.append("your notes move over")
                note = f" ({'; '.join(bits)})" if bits else ""
                lines.append(f"- {extra.content} looks like a copy of {g.keep.content}{note}")
        lines.append("reply yes to delete the copies (undoable), or no to keep them all")
        return "\n".join(lines)

    # -- the run ------------------------------------------------------------------------

    async def run(self, now: datetime | None = None, *, quiet: bool = False) -> str | None:
        """Check once. Returns the text it sent (or would have sent, with quiet=True)."""
        now = now or self.now()
        try:
            tasks = await asyncio.to_thread(self.todoist.all_tasks)
        except Exception as e:
            log.warning("duplicates: couldn't read todoist (%s)", type(e).__name__)
            return f"todoist: couldn't read your tasks ({type(e).__name__})" if quiet else None
        declined = self._declined()
        groups = [g for g in find_duplicates(tasks, links=self.store.links(), courses=self.courses, tz=self.tz,
                                             twins=load_twins(self.store))
                  if g.fingerprint not in declined]
        if not groups:
            job = self.store.pending_job()
            if job is not None and job["kind"] == JOB_KIND:   # its tasks are done, gone, or no longer look alike
                self.store.kv_delete("pending_job")
                text = "todoist: no need to answer my duplicates question, it's out of date (nothing was deleted)"
                if not quiet:
                    await self.send(text)
                return text
            return "todoist: no duplicate tasks" if quiet else None
        digest = hashlib.sha1(";".join(g.fingerprint for g in groups).encode()).hexdigest()
        slot = self.store.proposal_slot(JOB_KIND, digest)
        if slot not in ("free", "asked"):
            return f"todoist: {self._count(len(groups))}, once you've answered the {slot} proposal" if quiet else None
        question = self._question(groups)
        if slot == "free":
            payload = {"digest": digest,
                       "groups": [{"keep": self._dump(g.keep), "extras": [self._dump(t) for t in g.extras]} for g in groups]}
            self.store.propose_job(JOB_KIND, payload, question, at=now)
            if not quiet:
                await self.send(question)
        return question

    # -- the answer, from chat ----------------------------------------------------------

    async def approve(self, payload: dict, approved: bool) -> str:
        groups = payload.get("groups", [])
        if not approved:
            fingerprints = {",".join(sorted([g["keep"]["id"], *(t["id"] for t in g["extras"])])) for g in groups}
            self.store.kv_set(DECLINED_KEY, json.dumps(sorted(self._declined() | fingerprints)))
            return "ok, keeping them. i won't ask about those again"
        links = self.store.links()
        deleted: list[str] = []
        noted: list[str] = []
        for g in groups:
            keep_id = g["keep"]["id"]
            if await self._carry_notes(g):
                noted.append(g["keep"]["content"])
            for extra in g["extras"]:
                try:
                    await asyncio.to_thread(self.todoist.delete_task, extra["id"])
                except Exception as e:
                    log.warning("duplicates: couldn't delete %r (%s)", extra["content"], type(e).__name__)
                    continue
                snapshot = {k: extra.get(k) for k in ("content", "description", "project_id", "section_id", "priority", "due", "due_kind")}
                self.store.log_action("delete_task", {"task_id": extra["id"], "content": extra["content"], "snapshot": snapshot},
                                      at=self.now())
                for link in links.values():   # whatever tracked the copy now tracks the kept task
                    if link.task_id == extra["id"]:
                        self.store.link(link.kind, link.canvas_id, link.course_id, keep_id, adopted=True,
                                        name=link.name, due_at=link.due_at, submitted=link.submitted)
                deleted.append(extra["content"])
        if not deleted:
            return "couldn't delete any of them (todoist said no); nothing changed" + (
                f" except your notes, now also on {', '.join(noted)}" if noted else "")
        notes = f" your notes are on {', '.join(noted)} now." if noted else ""
        return (f"deleted {len(deleted)} cop{'ies' if len(deleted) != 1 else 'y'}: {', '.join(deleted)}.{notes} "
                f"undo brings the last one back")

    async def _carry_notes(self, group: dict) -> bool:
        """Before a copy goes, what she wrote on it is appended to the kept task (logged, so undo
        can take it back once the copies are restored)."""
        keep = group["keep"]
        try:
            current = await asyncio.to_thread(self.todoist.get_task, keep["id"])
            base = getattr(current, "description", "") or ""
        except Exception:
            base = keep.get("description") or ""
        carry = []
        for extra in group["extras"]:
            notes = (extra.get("description") or "").strip()
            if hand_written(notes) and notes not in base and notes not in carry:
                carry.append(notes)
        if not carry:
            return False
        merged = "\n\n".join([base.rstrip(), *carry]) if base.strip() else "\n\n".join(carry)
        try:
            await asyncio.to_thread(self.todoist.update_task, keep["id"], description=merged)
        except Exception as e:
            log.warning("duplicates: couldn't copy notes onto %r (%s)", keep["content"], type(e).__name__)
            return False
        self.store.log_action("edit_task", {"task_id": keep["id"], "content": keep["content"],
                                            "old": {"content": keep["content"], "description": base,
                                                    "priority": keep.get("priority", 1)}}, at=self.now())
        return True
