"""Is this new Gradescope assignment a task Faith already wrote down? (A guess, so it is asked.)

Faith adds the quarter's work from the syllabi before it exists anywhere: "ENGR 40M: PSET 1
(Gradescope)", "MATSCI 88Q: Pre-lab 2 (Gradescope)". When the real assignment appears on
Gradescope it has no link to those tasks and often a different name ("Lab 2: Pre Lab"), so the
sync would make a second task. This module finds the plausible pairs; the Gradescope job asks
about them over Telegram and links only on a yes. Title matching duplicates on renames and
mismatches on lookalikes (research, DECISIONS.md), which is why a match here is a question,
never a link.

What has to agree, besides the course:
  * the numbers in the name ("PSET 1", "Pset1", "Problem Set 1" → 1; "Lab 2A" → 2a), never the
    course code's own digits;
  * the kind words: pre / post / lab / pset / quiz / exam ... (so a pre-lab never pairs with a post-lab);
  * the due dates, within two days (her dates are often inferred from a syllabus). A Todoist
    deadline counts as a due date too: on planned work the due date is when she'll do it and the
    deadline is when it's due (2026-10-06, EE 160A HW2), so the closer of the two decides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .canvas_client import CanvasItem
from .config import Course
from .tasks import deadline_of

WINDOW = timedelta(days=2)
SOURCE_RE = re.compile(r"\((?:gradescope|paperless|canvas|ed|check date)\)", re.IGNORECASE)
ALIASES = [                                          # spellings of the same kind of work → one word
    (re.compile(r"problem\s*sets?|home\s*works?|\bhw|\bpsets?|\bps(?=\s*#?\s*\d)"), " pset "),
    (re.compile(r"\bpre\s*-?\s*labs?"), " pre lab "),
    (re.compile(r"\bpost\s*-?\s*labs?"), " post lab "),
    (re.compile(r"\bquizzes\b"), " quiz "),
]
KINDS = {"pre", "post", "lab", "pset", "quiz", "exam", "midterm", "final", "project", "reading", "survey", "essay"}
TOKEN_RE = re.compile(r"\d+[a-z]?(?![a-z0-9])|\d+|[a-z]+")


@dataclass(frozen=True)
class Signature:
    numbers: tuple[str, ...]
    kinds: frozenset[str]
    words: frozenset[str] = field(default=frozenset(), compare=False)   # only for names with no kind word


def _strip_course(text: str, course_code: str) -> str:
    parts = course_code.lower().split()
    if not parts:
        return text
    return re.sub(r"\s*".join(map(re.escape, parts)) + r"\s*:?", " ", text, count=1)


def signature(text: str, course_code: str = "") -> Signature:
    s = SOURCE_RE.sub(" ", text.lower())
    s = _strip_course(s, course_code)
    for pattern, word in ALIASES:
        s = pattern.sub(word, s)
    s = re.sub(r"(?<=[a-z])(?=\d)", " ", s)          # "pset1" → "pset 1"
    tokens = TOKEN_RE.findall(s)
    numbers = tuple(sorted({(t.lstrip("0") or "0") if t.isdigit() else (t[:-1].lstrip("0") or "0") + t[-1]
                            for t in tokens if t[0].isdigit()}))
    words = frozenset(t for t in tokens if t.isalpha())
    return Signature(numbers, frozenset(words & KINDS), words - KINDS)


def same_work(a: Signature, b: Signature) -> bool:
    if not a.numbers or a.numbers != b.numbers or a.kinds != b.kinds:
        return False
    return bool(a.kinds) or a.words <= b.words or b.words <= a.words


def _due(task, tz: ZoneInfo) -> datetime | date | None:
    raw = getattr(getattr(task, "due", None), "date", None)
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=tz)     # a floating time is her local time
    return raw


def due_gap(item_due: datetime, task, tz: ZoneInfo) -> timedelta | None:
    """How far apart the two due dates are; None if the task has no date. A date-only task
    compares by day. Her Todoist deadline is a date too, and the closer one counts."""
    gaps = []
    for due in (_due(task, tz), deadline_of(task)):
        if isinstance(due, datetime):
            gaps.append(abs(item_due - due))
        elif due is not None:
            gaps.append(abs(item_due.astimezone(tz).date() - due))
    return min(gaps, default=None)


def plausible_matches(items: list[CanvasItem], tasks, *, course_for: dict[int, Course], task_course: dict[str, str],
                      tz: ZoneInfo, window: timedelta = WINDOW) -> list[tuple[CanvasItem, object]]:
    """(item, task) pairs worth asking about. `tasks` should be the hand-made ones (linked to no
    source). Each item and each task appears at most once: the closest due dates pair first."""
    candidates = []
    for i, it in enumerate(items):
        course = course_for.get(it.course_id)
        if course is None or it.due_at is None:
            continue
        mine = signature(it.name, course.code)
        for t in tasks:
            if task_course.get(t.id) != course.code or not same_work(mine, signature(t.content, course.code)):
                continue
            gap = due_gap(it.due_at, t, tz)
            if gap is not None and gap <= window:
                created = getattr(t, "created_at", None) or datetime.max.replace(tzinfo=timezone.utc)
                candidates.append((gap, str(created), i, it, t))
    pairs: dict[int, tuple[CanvasItem, object]] = {}
    used: set[str] = set()
    for gap, _, i, it, t in sorted(candidates, key=lambda c: c[:3]):
        if i in pairs or t.id in used:
            continue
        pairs[i] = (it, t)
        used.add(t.id)
    return [pairs[i] for i in sorted(pairs)]
