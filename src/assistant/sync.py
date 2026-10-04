"""Canvas → Todoist sync.

Design (each is a lesson from RESEARCH.md):

  1. Plan first, act second.  `plan_sync()` is a pure function: Canvas items +
     remembered state in, a `Plan` of intended changes out. `apply_plan()` is
     the only place that touches Todoist. This is what makes `--dry-run`
     honest and the logic testable without network access.
  2. Identity is the Canvas id, never the title.  Renames don't duplicate.
  3. Adopt, don't clobber.  Hand-made tasks that link to a Canvas assignment
     become the sync's record for that assignment. The sync only ever changes
     their due date when *Canvas* changes it.
  4. Batch the small stuff.  Items in the same course, same assignment group,
     same due time become one task with a checklist in the description
     (e.g. "ENGR 40M quizzes 2–8"). A quiz added later joins the batch.
  5. Never delete, never un-complete.  Gone from Canvas → noted, not removed.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .canvas_client import CanvasItem
from .config import Course
from .db import ItemLink, Store, TaskRow
from .tasks import course_of

CANVAS_LINK_RE = re.compile(r"https?://[^\s/)]+/courses/(\d+)/(assignments|quizzes)/(\d+)")
GRADESCOPE_LINK_RE = re.compile(r"https?://(?:www\.)?gradescope\.com/courses/(\d+)/assignments/(\d+)")
LEADING_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\.?\s+")

SUBMISSION_PHRASES = {
    "online_upload": "File upload",
    "online_text_entry": "Text entry",
    "online_quiz": "Online quiz",
    "online_url": "URL submission",
    "discussion_topic": "Discussion post",
    "media_recording": "Media recording",
    "external_tool": "External tool",
    "on_paper": "On paper",
    "none": "No submission",
    "not_graded": "Not graded",
}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def links_in(text: str | None) -> set[tuple[str, int]]:
    """Every Canvas assignment/quiz link in a piece of text → {(kind, id)}."""
    found: set[tuple[str, int]] = set()
    for m in GRADESCOPE_LINK_RE.finditer(text or ""):
        found.add(("gradescope", int(m.group(2))))
    for m in CANVAS_LINK_RE.finditer(text or ""):
        if "gradescope.com" in m.group(0):
            continue
        kind = "assignment" if m.group(2) == "assignments" else "quiz"
        found.add((kind, int(m.group(3))))
    return found


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


def parse_iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def fmt_due(dt: datetime | None, tz: ZoneInfo, with_date: bool = False) -> str:
    if dt is None:
        return "no date"
    local = dt.astimezone(tz)
    time = local.strftime("%-I:%M%p").replace("AM", "am").replace("PM", "pm")
    return f"{local.strftime('%b %-d')} {time}" if with_date else f"{local.strftime('%a')} {time}"


def leading_number(name: str) -> str | None:
    m = LEADING_NUMBER_RE.match(name)
    return m.group(1) if m else None


def _sort_key(item: CanvasItem):
    n = leading_number(item.name)
    return (0, float(n), item.name) if n else (1, 0.0, item.name.lower())


def group_word(group_name: str | None) -> str:
    g = (group_name or "items").strip().lower()
    return "quizzes" if "quiz" in g else g


def submission_phrase(item: CanvasItem) -> str:
    if item.is_gradescope:
        return "Gradescope assignment"
    for t in item.submission_types:
        if t in SUBMISSION_PHRASES:
            return SUBMISSION_PHRASES[t]
    return "Assignment"


# --------------------------------------------------------------------------
# naming, matching the convention already in the Classes project
# --------------------------------------------------------------------------

def single_content(item: CanvasItem, course: Course) -> str:
    if item.kind == "gradescope":
        return f"{course.code}: {item.name} (Gradescope)"     # the convention already in the Classes project
    return f"{course.code}: {item.name}"


def single_description(item: CanvasItem) -> str:
    if item.kind == "gradescope":
        return f"Gradescope assignment on [Gradescope]({item.html_url})"
    return f"{submission_phrase(item)} on [Canvas]({item.html_url})"


def batch_content(items: list[CanvasItem], course: Course) -> str:
    word = group_word(items[0].group_name)
    nums = [leading_number(i.name) for i in items]
    if nums and all(nums):
        ordered = sorted(nums, key=float)
        return f"{course.code} {word} {ordered[0]}–{ordered[-1]}"
    return f"{course.code}: {len(items)} {word}"


def link_line(item: CanvasItem) -> str:
    return f"- [{item.name}]({item.html_url})"


def batch_description(items: list[CanvasItem], tz: ZoneInfo) -> str:
    head = f"Canvas {group_word(items[0].group_name)} due {fmt_due(items[0].due_at, tz)}:"
    lines = [link_line(i) for i in sorted(items, key=_sort_key)]
    return head + "\n" + "\n".join(lines)


# --------------------------------------------------------------------------
# the plan
# --------------------------------------------------------------------------

@dataclass
class Create:
    key: str
    items: list[CanvasItem]
    course: Course
    content: str
    description: str
    due_at: datetime | None

    @property
    def is_batch(self) -> bool:
        return self.key.startswith("batch:")


@dataclass
class Join:
    task_id: str
    item: CanvasItem
    course: Course


@dataclass
class DueUpdate:
    task_id: str
    items: list[CanvasItem]
    course: Course
    old: datetime | None
    new: datetime | None


@dataclass
class Complete:
    task_id: str
    items: list[CanvasItem]
    course: Course


@dataclass
class Progress:
    """Some, not all, members of a batch task are now submitted: tick them inside the description."""
    task_id: str
    items: list[CanvasItem]          # every member
    course: Course
    done: int
    total: int
    newly_done: list[CanvasItem]


@dataclass
class Skip:
    item: CanvasItem
    reason: str


@dataclass
class Plan:
    creates: list[Create] = field(default_factory=list)
    joins: list[Join] = field(default_factory=list)
    due_updates: list[DueUpdate] = field(default_factory=list)
    completes: list[Complete] = field(default_factory=list)
    progress: list[Progress] = field(default_factory=list)
    skips: list[Skip] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.creates or self.joins or self.due_updates or self.completes or self.progress)


def single_key(item: CanvasItem) -> str:
    return f"{item.kind}:{item.canvas_id}"


def batch_key(item: CanvasItem) -> str:
    if item.group_id is not None and item.due_at is not None:
        return f"batch:{item.course_id}:{iso(item.due_at)}:{item.group_id}"
    return single_key(item)


def plan_sync(
    items: list[CanvasItem],
    courses: dict[int, Course],
    links: dict[tuple[str, int], ItemLink],
    tasks: dict[str, TaskRow],
    *,
    tz: ZoneInfo,
    complete_when_submitted: bool = True,
    include_undated: bool = False,
    batch_min_size: int = 2,
) -> Plan:
    plan = Plan()

    # 1. filter
    usable: list[CanvasItem] = []
    for it in items:
        if it.course_id not in courses:
            plan.skips.append(Skip(it, "course not in courses.yaml"))
        elif not it.published:
            plan.skips.append(Skip(it, "unpublished"))
        elif it.due_at is None and not include_undated:
            plan.skips.append(Skip(it, "no due date"))
        else:
            usable.append(it)

    # 2. group: same course + same due time + same assignment group → one task
    grouped: dict[str, list[CanvasItem]] = defaultdict(list)
    for it in usable:
        grouped[batch_key(it)].append(it)
    groups: list[tuple[str, list[CanvasItem]]] = []
    for key, members in grouped.items():
        if key.startswith("batch:") and len(members) < batch_min_size:
            groups.extend((single_key(m), [m]) for m in members)
        else:
            groups.append((key, members))

    # 3. decide per group
    for key, members in groups:
        course = courses[members[0].course_id]
        members = sorted(members, key=_sort_key)

        linked_ids = [links[m.key].task_id for m in members if m.key in links]
        if not linked_ids:
            existing = next((t for t in tasks.values() if t.batch_key == key), None)
            if existing is not None:
                linked_ids = [existing.task_id]

        if linked_ids:
            task_id = Counter(linked_ids).most_common(1)[0][0]
            task = tasks.get(task_id)

            for m in members:
                if m.key in links:
                    continue
                if m.submitted:
                    plan.skips.append(Skip(m, "already submitted"))
                else:
                    plan.joins.append(Join(task_id, m, course))

            linked = [m for m in members if m.key in links]
            changed = [
                m for m in linked
                if links[m.key].due_at is not None and links[m.key].due_at != iso(m.due_at)
            ]
            if changed:
                new_dues = {iso(m.due_at) for m in changed}
                if len(changed) == len(linked) and len(new_dues) == 1:
                    old = parse_iso(links[changed[0].key].due_at)
                    plan.due_updates.append(DueUpdate(task_id, changed, course, old, changed[0].due_at))
                else:
                    for m in changed:
                        plan.notes.append(
                            f"{course.code}: '{m.name}' moved to {fmt_due(m.due_at, tz, True)} "
                            f"but shares a task with others; adjust by hand"
                        )

            if (
                complete_when_submitted
                and members
                and all(m.submitted for m in members)
                and not (task and task.completed)
            ):
                plan.completes.append(Complete(task_id, members, course))
            elif len(members) > 1:
                newly = [m for m in linked if m.submitted and not links[m.key].submitted]
                if newly:
                    done = sum(1 for m in members if m.submitted)
                    plan.progress.append(Progress(task_id, members, course, done, len(members), newly))
            continue

        # nothing linked yet
        open_members = [m for m in members if not m.submitted]
        plan.skips.extend(Skip(m, "already submitted") for m in members if m.submitted)
        if not open_members:
            continue
        if len(open_members) == 1:
            it = open_members[0]
            plan.creates.append(Create(
                single_key(it), [it], course, single_content(it, course), single_description(it), it.due_at,
            ))
        else:
            plan.creates.append(Create(
                key, open_members, course, batch_content(open_members, course),
                batch_description(open_members, tz), open_members[0].due_at,
            ))

    return plan


# --------------------------------------------------------------------------
# adoption of hand-made tasks and reconciliation with Todoist
# --------------------------------------------------------------------------

def adopt_links(active_tasks, items: list[CanvasItem], links: dict[tuple[str, int], ItemLink]) -> list[ItemLink]:
    """Hand-made tasks that link to a Canvas item become that item's record.

    Returns the new links (not yet persisted). The Canvas due date is recorded
    from the item when we have it, so the first real sync doesn't "fix" a due
    date you set on purpose.
    """
    by_key = {it.key: it for it in items}
    new: list[ItemLink] = []
    seen: set[tuple[str, int]] = set(links)
    for t in active_tasks:
        for key in links_in(t.content) | links_in(getattr(t, "description", None)):
            if key in seen:
                continue
            seen.add(key)
            it = by_key.get(key)
            new.append(ItemLink(
                kind=key[0], canvas_id=key[1], course_id=it.course_id if it else None,
                task_id=t.id, adopted=True, name=it.name if it else None,
                due_at=iso(it.due_at) if it else None, submitted=it.submitted if it else False,
            ))
    return new


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def adopt_by_title(items: list[CanvasItem], active_tasks, *, course_for: dict[int, Course],
                   task_course: dict[str, str]) -> list[tuple[CanvasItem, object]]:
    """Hand-made tasks without a link, matched by course plus title (the Gradescope first run).

    Only proposed, never applied silently: the research is clear that title matching
    duplicates on renames, so Faith confirms the list once and links are recorded from then on.
    """
    pairs: list[tuple[CanvasItem, object]] = []
    used: set[str] = set()
    for it in items:
        course = course_for.get(it.course_id)
        if course is None:
            continue
        key = _squash(it.name)
        if len(key) < 3:
            continue
        for t in active_tasks:
            if t.id in used or task_course.get(t.id) != course.code:
                continue
            body = _squash(t.content)
            body_wo_course = body.replace(_squash(course.code), "", 1).replace("gradescope", "")
            if key == body_wo_course or (len(key) >= 5 and key in body_wo_course):
                pairs.append((it, t))
                used.add(t.id)
                break
    return pairs


SOURCE_SUFFIX_RE = re.compile(r"\((gradescope|paperless|canvas)\)\s*$", re.IGNORECASE)


def _title_key(text: str, course: Course) -> str:
    """'MATSCI 88Q: Pre-lab 1 (Gradescope)' → 'prelab1' for MATSCI 88Q: course code and a trailing
    source suffix ignored, case and punctuation too."""
    body = _squash(SOURCE_SUFFIX_RE.sub("", text))
    code = _squash(course.code)
    return body[len(code):] if code and body.startswith(code) else body


def adopt_same_title(items: list[CanvasItem], active_tasks, links: dict[tuple[str, int], ItemLink], *,
                     course_for: dict[int, Course], task_course: dict[str, str]) -> list[ItemLink]:
    """Unlinked items whose name is *exactly* an existing task's title, in the same course.

    This is where the Canvas sync and the Gradescope sync meet: each sees one side of a
    Gradescope-linked assignment and would otherwise make its own task for it. Exact equality
    only (the research is clear that looser title matching duplicates on renames); the oldest
    match wins if there are several, and the duplicate check reports the rest. Returns the new
    links (not yet persisted), with the item's due date so the next sync doesn't "fix" one she set.
    """
    new: list[ItemLink] = []
    used: set[str] = set()
    for it in items:
        if it.key in links:
            continue
        course = course_for.get(it.course_id)
        if course is None:
            continue
        key = _title_key(it.name, course)
        if len(key) < 3:
            continue
        matches = [t for t in active_tasks
                   if t.id not in used and task_course.get(t.id) == course.code and _title_key(t.content, course) == key]
        if not matches:
            continue
        t = sorted(matches, key=lambda t: (str(getattr(t, "created_at", "") or ""), t.id))[0]
        used.add(t.id)
        new.append(ItemLink(kind=it.kind, canvas_id=it.canvas_id, course_id=it.course_id, task_id=t.id, adopted=True,
                            name=it.name, due_at=iso(it.due_at), submitted=it.submitted))
    return new


def task_title(task_id: str, active: dict, rows: dict[str, TaskRow]) -> str:
    """A task's title for a report: the live one, else the last one remembered (it may be done)."""
    if task_id in active:
        return active[task_id].content
    row = rows.get(task_id)
    return row.content if row is not None and row.content else f"task {task_id}"


def _task_due_iso(task) -> str | None:
    due = getattr(task, "due", None)
    if due is None or getattr(due, "date", None) is None:
        return None
    d = due.date
    if isinstance(d, datetime):
        return iso(d if d.tzinfo else d.replace(tzinfo=timezone.utc))
    return d.isoformat()


# --------------------------------------------------------------------------
# applying the plan
# --------------------------------------------------------------------------

@dataclass
class Report:
    dry_run: bool
    adopted: list[str] = field(default_factory=list)      # "item → task you already had" (exact title match)
    created: list[str] = field(default_factory=list)
    joined: list[str] = field(default_factory=list)
    due_updated: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    progress: list[str] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.adopted or self.created or self.joined or self.due_updated or self.completed or self.progress)


def _destination(course: Course, *, todoist, project_id: str, sections: dict) -> tuple[str, str | None]:
    """Where a new task for this course goes: its own sub-project with no section, or (legacy,
    no project_id) the course's section inside the parent, created if missing. A course with a
    project never touches sections, so the old ones stay gone once removed."""
    if course.project_id:
        return course.project_id, None
    return project_id, todoist.ensure_section(project_id, course.section_name, sections).id


def apply_plan(plan: Plan, *, todoist, store: Store, project_id: str, sections: dict, tz: ZoneInfo,
               dry_run: bool) -> Report:
    """`project_id` is the parent (Classes); `sections` is the legacy {name: Section} cache for
    courses without a sub-project, and gains any section created here. Only creates choose a
    place: joins, due updates, completes and progress address tasks by id and never move them."""
    report = Report(dry_run=dry_run, notes=list(plan.notes))
    for s in plan.skips:
        report.skipped[s.reason] += 1

    for c in plan.creates:
        label = f"{c.content} (due {fmt_due(c.due_at, tz, True)})"
        try:
            if not dry_run:
                dest_project, dest_section = _destination(c.course, todoist=todoist, project_id=project_id,
                                                          sections=sections)
                task = todoist.add_task(
                    content=c.content, description=c.description, project_id=dest_project,
                    section_id=dest_section, due_at=c.due_at,
                )
                store.upsert_task(
                    task.id, batch_key=c.key if c.is_batch else None, managed=True, content=c.content,
                    description=c.description, due_at=iso(c.due_at), completed=False,
                )
                for it in c.items:
                    store.link(it.kind, it.canvas_id, it.course_id, task.id, adopted=False,
                               name=it.name, due_at=iso(it.due_at), submitted=it.submitted)
            report.created.append(label)
        except Exception as e:  # keep going; report at the end
            report.errors.append(f"create failed: {label}: {e}")

    for j in plan.joins:
        label = f"{j.item.name} → task {j.task_id}"
        try:
            if not dry_run:
                current = todoist.get_task(j.task_id)
                desc = (current.description or "").rstrip()
                desc = f"{desc}\n{link_line(j.item)}" if desc else link_line(j.item)
                todoist.update_task(j.task_id, description=desc)
                store.upsert_task(j.task_id, batch_key=None, managed=False, content=current.content,
                                  description=desc, due_at=_task_due_iso(current), completed=False)
                store.link(j.item.kind, j.item.canvas_id, j.item.course_id, j.task_id, adopted=True,
                           name=j.item.name, due_at=iso(j.item.due_at), submitted=j.item.submitted)
            report.joined.append(label)
        except Exception as e:
            report.errors.append(f"join failed: {label}: {e}")

    for u in plan.due_updates:
        label = f"{u.course.code}: {u.items[0].name} {fmt_due(u.old, tz, True)} → {fmt_due(u.new, tz, True)}"
        try:
            if not dry_run:
                todoist.update_task(u.task_id, due_at=u.new)
                for it in u.items:
                    store.link(it.kind, it.canvas_id, it.course_id, u.task_id, adopted=False,
                               name=it.name, due_at=iso(it.due_at), submitted=it.submitted)
            report.due_updated.append(label)
        except Exception as e:
            report.errors.append(f"due update failed: {label}: {e}")

    for cp in plan.completes:
        label = f"{cp.course.code}: {cp.items[0].name}" + (f" (+{len(cp.items) - 1})" if len(cp.items) > 1 else "")
        try:
            if not dry_run:
                todoist.complete_task(cp.task_id)
                store.upsert_task(cp.task_id, batch_key=None, managed=False, content=None, description=None,
                                  due_at=None, completed=True)
                for it in cp.items:
                    store.link(it.kind, it.canvas_id, it.course_id, cp.task_id, adopted=False,
                               name=it.name, due_at=iso(it.due_at), submitted=True)
            report.completed.append(label)
        except Exception as e:
            report.errors.append(f"complete failed: {label}: {e}")

    for pr in plan.progress:
        names = ", ".join(it.name for it in pr.newly_done)
        try:
            current = todoist.get_task(pr.task_id)        # a read, so a dry run can name the task too
            content = current.content
            if not dry_run:
                desc = mark_done_lines(current.description or "", [it.html_url for it in pr.items if it.submitted])
                if desc != (current.description or ""):
                    todoist.update_task(pr.task_id, description=desc)
                for it in pr.items:
                    store.link(it.kind, it.canvas_id, it.course_id, pr.task_id, adopted=False,
                               name=it.name, due_at=iso(it.due_at), submitted=it.submitted)
            report.progress.append(f"{content}: {pr.done}/{pr.total} done ({names})")
        except Exception as e:
            report.errors.append(f"progress update failed: {pr.task_id}: {e}")

    return report


DONE_MARK = "✅ "


def mark_done_lines(description: str, done_urls: list[str]) -> str:
    """Prefix the checklist line for each submitted item with ✅, leaving everything else untouched."""
    out = []
    for line in description.splitlines():
        stripped = line.lstrip("-•* ").strip()
        hit = any(url and url in line for url in done_urls)
        if hit and not stripped.startswith(DONE_MARK):
            indent = line[: len(line) - len(line.lstrip())]
            bullet = "- " if line.lstrip().startswith(("-", "•", "*")) else ""
            out.append(f"{indent}{bullet}{DONE_MARK}{stripped}")
        else:
            out.append(line)
    return "\n".join(out)


def format_report(r: Report) -> str:
    lines = ["sync" + (" (dry run, nothing written)" if r.dry_run else "")]
    if r.adopted:
        lines.append(f"linked {len(r.adopted)} to tasks you already had:")
        lines += [f"  - {x}" for x in r.adopted]
    if r.created:
        lines.append(f"added {len(r.created)}:")
        lines += [f"  - {x}" for x in r.created]
    if r.joined:
        lines.append(f"joined {len(r.joined)} into existing tasks:")
        lines += [f"  - {x}" for x in r.joined]
    if r.due_updated:
        lines.append(f"due dates updated {len(r.due_updated)}:")
        lines += [f"  - {x}" for x in r.due_updated]
    if r.completed:
        lines.append(f"completed {len(r.completed)} (submitted on Canvas):")
        lines += [f"  - {x}" for x in r.completed]
    if r.progress:
        lines.append(f"progress {len(r.progress)}:")
        lines += [f"  - {x}" for x in r.progress]
    if not r.changed:
        lines.append("nothing to change")
    if r.skipped:
        lines.append("skipped: " + ", ".join(f"{n} {reason}" for reason, n in r.skipped.most_common()))
    if r.notes:
        lines.append("notes:")
        lines += [f"  - {x}" for x in r.notes]
    if r.errors:
        lines.append(f"errors ({len(r.errors)}):")
        lines += [f"  - {x}" for x in r.errors]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------

def reconcile_tasks(active, tasks: dict[str, TaskRow], store: Store, *, dry_run: bool) -> None:
    """Bring the remembered task rows in line with what is active in the class projects.

    `active` must be the union of Classes and every course sub-project: a task moved between
    them keeps its id, so it is the same task, still open. Two rules, unchanged from before
    sub-projects:
      * new active task → remember it, open;
      * remembered open task no longer active anywhere we read → completed or deleted in
        Todoist; either way, leave it be.
    A completed row stays completed even if the task shows up active again: that is Faith
    reopening it on purpose, and re-opening the row would make the next sync tick it again.
    (A read that misses a project can't wrongly close rows: `tasks_in` raises instead.)
    """
    active_ids = {t.id for t in active}
    for t in active:
        if t.id not in tasks:
            tasks[t.id] = TaskRow(t.id, None, False, t.content, t.description, _task_due_iso(t), False)
            if not dry_run:
                store.upsert_task(t.id, batch_key=None, managed=False, content=t.content,
                                  description=t.description, due_at=_task_due_iso(t), completed=False)
    for tid, row in tasks.items():
        if tid not in active_ids and not row.completed:
            row.completed = True  # completed or deleted in Todoist; either way, leave it be
            if not dry_run:
                store.upsert_task(tid, batch_key=None, managed=row.managed, content=row.content,
                                  description=row.description, due_at=row.due_at, completed=True)


def run_sync(settings, courses_cfg, *, dry_run: bool = False, verbose: bool = False,
             todoist=None, canvas=None, store: Store | None = None) -> Report:
    """One Canvas → Todoist pass. `todoist`, `canvas` and `store` default to the real ones
    (tests pass fakes)."""
    from .canvas_client import CanvasClient
    from .todoist_client import TodoistClient
    from .twins import link_twins, load_twins, record_twins, twins_in

    store = store or Store(settings.db_path)
    run_id = store.start_run("sync")
    try:
        canvas = canvas or CanvasClient(settings.canvas_url, settings.canvas_token)
        todoist = todoist or TodoistClient(settings.todoist_token)

        project = todoist.project(project_id=courses_cfg.todoist.project_id, name=courses_cfg.todoist.project_name)
        sections = todoist.sections(project.id)          # legacy: courses without a sub-project file here
        read_ids = courses_cfg.class_project_ids(project.id)
        active = todoist.tasks_in(read_ids)              # Classes plus every course sub-project
        if verbose:
            print(f"todoist: {project.name!r} ({project.id}) + {len(read_ids) - 1} course sub-projects, "
                  f"{len(sections)} legacy sections, {len(active)} active tasks")

        by_id = courses_cfg.by_canvas_id()
        items: list[CanvasItem] = []
        for cid, course in by_id.items():
            got = canvas.items_for_course(cid)
            if verbose:
                print(f"canvas: {course.code} ({cid}) → {len(got)} items")
            items.extend(got)

        # adopt hand-made tasks (by link), join a Gradescope assignment's task (by id), then by exact
        # title; then line the remembered rows up with what is active
        links = store.links()
        tasks = store.tasks()
        live_sections = {name: sec.id for name, sec in sections.items()}
        by_section = {sid: code for code, sid in courses_cfg.course_sections(live_sections).items()}
        task_course = {t.id: course_of(t, sections=by_section, projects=courses_cfg.course_by_project()) for t in active}
        by_task_id = {t.id: t for t in active}
        twins = {**load_twins(store), **twins_in(items)} if dry_run else record_twins(store, items)
        by_link = adopt_links(active, items, links)
        by_twin = link_twins(items, {**links, **{l.key: l for l in by_link}}, twins)
        same_title = adopt_same_title(items, active, {**links, **{l.key: l for l in by_link + by_twin}},
                                      course_for=by_id, task_course=task_course)
        for link in by_link + by_twin + same_title:
            links[link.key] = link
            if not dry_run:
                store.link(link.kind, link.canvas_id, link.course_id, link.task_id, adopted=True,
                           name=link.name, due_at=link.due_at, submitted=link.submitted)
        reconcile_tasks(active, tasks, store, dry_run=dry_run)

        plan = plan_sync(
            items, by_id, links, tasks, tz=settings.tz,
            complete_when_submitted=settings.complete_when_submitted,
            include_undated=settings.include_undated,
            batch_min_size=settings.batch_min_size,
        )
        report = apply_plan(plan, todoist=todoist, store=store, project_id=project.id, sections=sections,
                            tz=settings.tz, dry_run=dry_run)
        report.adopted += [f"{l.name} → {task_title(l.task_id, by_task_id, tasks)}" for l in by_twin + same_title]

        # bookkeeping: refresh what Canvas says for every linked item we saw
        if not dry_run:
            for it in items:
                link = links.get(it.key)
                if link and link.due_at is not None:
                    store.link(it.kind, it.canvas_id, it.course_id, link.task_id, adopted=link.adopted,
                               name=it.name, due_at=iso(it.due_at), submitted=it.submitted)

        store.finish_run(run_id, ok=not report.errors, summary=format_report(report))
        return report
    except Exception as e:
        store.finish_run(run_id, ok=False, summary=f"crashed: {e}")
        raise
