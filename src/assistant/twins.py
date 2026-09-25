"""One piece of work, two ids: a Canvas external tool that opens a Gradescope assignment.

MATSCI 88Q and CME 102 post every Gradescope assignment on Canvas too, as an external-tool
assignment ("Pre-lab 1" on Canvas is "Lab 1: Pre Lab" on Gradescope). The Canvas sync and the
Gradescope sync each saw their own half and each made a task, so Lab 1 ended up with three
(counting Faith's own). The names differ, so matching titles can't see it, but Canvas says which
Gradescope assignment the tool opens (`CanvasItem.gradescope_id`). That id is identity, not a
guess, so no question is needed: whichever half arrives second is linked to the task the first
half already has, and the sync report says so.

The Canvas sync is the only one that can see the pairing, and the Gradescope sync runs
separately, so the Canvas sync remembers every pairing it sees in `kv["gradescope_twins"]`
({gradescope assignment id: canvas assignment id}). Entries are never removed; an id pairing
doesn't stop being true.
"""

from __future__ import annotations

import json

from .canvas_client import CanvasItem
from .db import ItemLink, Store
from .sync import iso

TWINS_KEY = "gradescope_twins"


def twins_in(items: list[CanvasItem]) -> dict[int, int]:
    """{gradescope id: canvas assignment id} for the Canvas items that say which Gradescope assignment they open."""
    return {it.gradescope_id: it.canvas_id for it in items if it.kind == "assignment" and it.gradescope_id}


def load_twins(store: Store) -> dict[int, int]:
    raw = store.kv_get(TWINS_KEY)
    return {int(k): int(v) for k, v in json.loads(raw).items()} if raw else {}


def record_twins(store: Store, items: list[CanvasItem]) -> dict[int, int]:
    known = load_twins(store)
    merged = {**known, **twins_in(items)}
    if merged != known:
        store.kv_set(TWINS_KEY, json.dumps({str(k): v for k, v in sorted(merged.items())}))
    return merged


def link_twins(items: list[CanvasItem], links: dict[tuple[str, int], ItemLink], twins: dict[int, int]) -> list[ItemLink]:
    """Unlinked items whose other half already has a task → links to that task (not yet persisted).

    Works from either side: a Canvas item looks for its Gradescope id's link, a Gradescope item
    looks for its Canvas twin's link. The task may be finished already (submitted on Gradescope,
    ticked); it is still the same work, so the link stands and nothing new is made.
    """
    new: list[ItemLink] = []
    for it in items:
        if it.key in links:
            continue
        if it.kind == "gradescope":
            cid = twins.get(it.canvas_id)
            other = links.get(("assignment", cid)) if cid is not None else None
        elif it.kind == "assignment" and it.gradescope_id:
            other = links.get(("gradescope", it.gradescope_id))
        else:
            other = None
        if other is not None:
            new.append(ItemLink(kind=it.kind, canvas_id=it.canvas_id, course_id=it.course_id, task_id=other.task_id,
                                adopted=True, name=it.name, due_at=iso(it.due_at), submitted=it.submitted))
    return new
