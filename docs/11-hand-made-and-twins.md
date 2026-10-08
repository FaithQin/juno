# 11 · Hand-made tasks, Gradescope, and Canvas twins

A homework audit on 2026-09-24 found two ways juno would keep making second copies of work Faith
already had in Todoist. Both come from the same fact: juno knows a task *is* an assignment only
through a link (`item_links`, one row per source id → task id). Anything without a link looks new.

## 1. Tasks she wrote down before the assignment existed

Faith adds the quarter from the syllabi: `ENGR 40M: PSET 1 (Gradescope)` … `PSET 9`, the ENGR 40M
lab prelabs and write-ups, `CME 102: Pset2 (Gradescope)` … `Pset8`, `MATSCI 88Q: Pre-lab N` /
`Post-lab N (Gradescope)`. None of them can carry a Gradescope link, because the assignment
doesn't exist yet. After the Gradescope first run, `plan_sync` makes a task for every unlinked
Gradescope assignment, so each of these would have been twinned the day it was published.

Title matching can't simply be switched on: the research (and `adopt_by_title`'s docstring) is
clear that title matches break on renames and lookalikes, and Faith decided matches are proposed,
never applied silently. So the fix is a question.

**`matching.py` decides what is worth asking about.** A task and an assignment are "plausibly the
same" when, in the same course:

| must agree | how | example |
|---|---|---|
| the numbers | digits in the name, course code removed, leading zeros dropped | `PSET 1`, `Pset1`, `Problem Set 1`, `HW 1` → `1`; `Lab 2A` → `2a` |
| the kind words | `pre`, `post`, `lab`, `pset`, `quiz`, `exam`, ... after spelling aliases | `Pre-lab 1` and `Lab 1: Pre Lab` → {pre, lab}; never pairs with a post-lab |
| the due date | within 2 days (her dates are often inferred from a syllabus) | Thu 11:59pm vs Fri 5pm: still hers |
| …or her deadline | the Todoist deadline field counts as a date too; the closer one decides (§4) | planned Fri, deadline Mon, Gradescope Mon: hers |

No number, no guess (`Final Project Proposal` is not matched to `Final Project presentation`).
Each task is offered once, to the assignment with the closest due date.

**The Gradescope job asks, one question at a time.** When a new unlinked assignment plausibly
matches an unlinked task (one no sync follows), the job holds the assignment back from the plan
and proposes through the usual slot (`proposal_slot` / `propose_job`, kind `gradescope_match`):

```
gradescope: a new assignment looks like a task you already have:
- Lab 2: Pre Lab → MATSCI 88Q: Pre-lab 2 (Gradescope) (both due mon oct 5 12:00pm)
reply yes to link them (i'll tick it when you submit and follow gradescope's date changes), or no to add it as a new task
```

- **Yes** records the link (`adopted=True`). Her title, notes and date stay as they are (her
  standing decision: adopted tasks change date only when the *source* changes it); if the dates
  differ, the reply says so. From then on a Gradescope date change moves the task and a
  submission ticks it.
- **No** makes the Gradescope task right away, as juno did before, and remembers the pair so it is
  never asked again.
- While another job's question is out, the assignment simply waits (no twin in the meantime);
  `sync_now` says what it's waiting on.
- If the question becomes moot before she answers (Canvas linked the same assignment by id, see
  below), it is withdrawn and the sync text says "no need to answer my question about …".

An exact-title hand-made task goes through the question too. `adopt_same_title` (from doc 10) now
only shares a task that another sync already follows; that was its purpose, twins between the two
syncs, and it keeps working for it.

## 2. One assignment, posted twice

MATSCI 88Q and CME 102 put every Gradescope assignment on Canvas as well, as an external-tool
assignment. The Canvas sync saw "Pre-lab 1" (Canvas 828789), the Gradescope sync saw "Lab 1: Pre
Lab" (Gradescope 8676496), and each made a task. With Faith's own, Lab 1 had three.

The names differ, and the first idea was to match them fuzzily (same number, due within minutes).
Reading the Canvas API instead showed something better: the external tool's launch parameters
name the Gradescope assignment exactly.

```json
"external_tool_tag_attributes": {
  "url": "https://lti.int.turnitin.com/launch/gs-proxy",
  "custom_params": {"custom_gradescope_resource_id": "assignment-8676496"}
}
```

That is identity, not a guess, so no question is needed (`twins.py`):

- `CanvasItem.gradescope_id` carries the id (`canvas_client.gradescope_id_of`).
- The Canvas sync remembers every pairing it sees in `kv["gradescope_twins"]`, because the
  Gradescope job never talks to Canvas.
- `link_twins` runs in both syncs before any title logic: an unlinked item whose other half
  already has a task is linked to that task, and the sync text says "linked 1 to tasks you
  already had". Whichever half appears first makes (or adopts) the task; the second joins it.
- An undated Canvas half (CME 102's "Pset1") is linked too, so a due date added later can't
  make a twin.

## 3. The copies that already exist

The duplicate check (doc 10) now sees twins by id as well, so each MATSCI Lab 1 triple is one
group. Which task stays: the one a sync ticks on submission. A Gradescope link now outranks the
Canvas half of a Gradescope assignment (Canvas shows no submission for those, only grades later);
an ordinary Canvas link still outranks both. Before a copy is deleted, notes Faith wrote on it
(anything more than a sync's one-line link) are appended to the kept task, logged so `undo` can
take them back after the copies. Nothing is deleted without her yes.

## 4. Planned work: the deadline is the date that counts (2026-10-08)

Two misses had one cause. On 2026-10-06 the sync made "EE 160A: Homework 2 (Gradescope)" next to
her "EE 160A: HW2 (Gradescope) (check date)"; on 2026-10-03 it made "ENGR 40M: Prelab 1
(Gradescope)" next to her "ENGR 40M: Lab 1 prelab (Gradescope)". The titles were never the problem
(`HW2` and `Homework 2` both read as `(2, {pset})`). The dates were:

| her task | its due date | its Todoist deadline | Gradescope | gap the matcher saw |
|---|---|---|---|---|
| HW2 (check date) | Fri Oct 16 11:59pm (the syllabus) | Mon Oct 19 (the website) | Mon Oct 19 11:59pm | 3 days |
| Lab 1 prelab | Sat Oct 3 5:40pm (a work block) | Mon Oct 5 | Mon Oct 5 6:00pm | 2 days 20 min |

Since 2026-10-03 juno reads a task with a Todoist deadline as **planned work**: the due date is when
she'll do it, the deadline is when it's due (`tasks.py`, doc 12 §4). The matcher predates that and
measured only the due date, so both times it compared Gradescope's deadline with her *plan* and
missed by a little. The prelab miss happened 55 seconds after she moved the block to that evening.

The fix is in `matching.due_gap`: the deadline is one more date to compare, and the closer of the
two decides. A task with only a deadline now counts as dated. Gradescope's exact time against a
deadline (a day) compares by day, like a date-only task. The question then shows the deadline, so
she can see why juno thinks they match:

```
- Homework 2 → EE 160A: HW2 (Gradescope) (check date) (gradescope: mon oct 19 11:59pm, yours: fri oct 16 11:59pm, deadline mon oct 19)
```

`_same_instant` ("both due …", and the heads-up after a yes) still compares the due date only: a
deadline is a day, not a time, so it can't be "the same instant".

The duplicate check (doc 10) doesn't catch these pairs afterwards either: the titles normalize
differently (`hw2checkdate`, `homework2`) and her task links the course's homework page, not the
Gradescope assignment. Pairs already made stay until she says what to do with them.

## Reading the code

1. `canvas_client.py` — `gradescope_id_of`, `CanvasItem.gradescope_id`.
2. `twins.py` — `twins_in`, `record_twins`, `load_twins`, `link_twins`.
3. `matching.py` — `signature`, `same_work`, `due_gap` (due date or deadline), `plausible_matches`.
4. `gradescope_sync.py` — `run` (after the first run), `_ask_about_matches`, `approve_match`.
5. `sync.py` — `run_sync` (twins before exact titles), `task_title`.
6. `duplicates.py` — twins in `find_duplicates`, `hand_written`, `_carry_notes`.
7. Tests: `tests/test_matching.py`, the new sections at the end of `tests/test_gradescope_job.py`,
   `tests/test_sync_projects.py`, `tests/test_duplicates.py`, `tests/test_canvas_client.py`.
