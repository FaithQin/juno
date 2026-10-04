# 10 · Duplicate tasks

Faith, 2026-09-24, late: "juno should also check to make sure there are no duplicate tasks in
todoist." A scan of her account that night found exactly two pairs, and they explained themselves:

| made by the Canvas sync (Sep 24) | made by the Gradescope sync (Sep 23) |
|---|---|
| MATSCI 88Q: Pre-lab 1 | MATSCI 88Q: Pre-lab 1 (Gradescope) |
| MATSCI 88Q: Post-lab 1 | MATSCI 88Q: Post-lab 1 (Gradescope) |

Same assignment, seen from two sides. The Gradescope job created the task first (the assignment
was on Gradescope before the instructor published it on Canvas); a day later the Canvas sync
saw an external-tool assignment with no Canvas link on any task and made its own. Each sync was
correct on its own terms. Neither knew about the other.

## 1. Stop making twins: `adopt_same_title`

Both syncs already adopt hand-made tasks that carry the item's link (`adopt_links`). Now they
also adopt a task whose title is *exactly* the item's name once the course code and a trailing
"(Gradescope)" are ignored, in the same course. Exact equality only: the research warned that
looser title matching duplicates on renames, and the Gradescope first run still proposes fuzzy
matches for confirmation instead. When a match is adopted the sync report says so ("linked 1 to
tasks you already had"), because every write, even to juno's own link table, is reported.

## 2. Find the ones that exist: `duplicates.py`

"Duplicate" is deliberately narrow. Two active tasks are copies when they are in the same project
and either their titles normalise to the same string (course prefix, source suffix, case and
punctuation ignored) with due dates no more than a day apart (a weekly "reading" task a week apart
is a series, not a copy), or their descriptions point at the same Canvas or Gradescope assignment
*and* their names agree. (Narrowed on 2026-10-03; see §4 for exactly how and why.)
A union-find groups them, so three copies make one group. The kept task is the one a sync tracks
(a Canvas link outranks a Gradescope one), else the older one.

The check runs right after every hourly Canvas sync, which is the moment a twin would appear, and
on demand ("check for duplicates" → `find_duplicates`). It is silent when it finds nothing.

## 3. Nothing is deleted without a yes

Findings become one proposal, asked once, through the same one-question-at-a-time slot as every
other job: "todoist: 2 pairs look like duplicates … reply yes to delete the copies (undoable), or
no to keep them all". Yes deletes the copies, each with the same undo snapshot `delete_task` in
chat uses, and moves any sync link from the copy to the kept task, so a Gradescope submission
still ticks the task that survived. No remembers those exact pairs and never asks about them
again; a new pair is still asked about.

## 4. Narrowed after a wrong question (2026-10-03)

On Sep 28 juno asked:

```
todoist: 2 pairs look like duplicates.
- Breakfast looks like a copy of Breakfast (due wed sep 30 8:15am vs tue sep 29 8:15am)
- CME 102 Pset1: work block (Tue night) looks like a copy of CME 102: Pset1 (Gradescope) (...)
- CME 102 Pset1: work block (Wed AM) looks like a copy of CME 102: Pset1 (Gradescope) (...)
- CME 102 Pset1: finish + submit looks like a copy of CME 102: Pset1 (Gradescope) (...)
```

A yes would have deleted a breakfast and her plan for the problem set. Two rules were too loose:

- **"Same title, due within a day."** The day of slack is for a date she guessed from a syllabus
  next to the real one. Two tasks at *exactly the same clock time* on different days are the
  opposite: a habit she repeats. So `_close_enough` now says no when both have a time, the times
  match and the days don't. (11:59pm Thursday vs 12:00am Friday still counts as a copy.)
- **"Same assignment link."** Her work blocks carry the assignment's link so she can open it from
  any of them. A shared link says the tasks are *about* the same assignment, not that they *are*
  it. Now a shared link counts only when the names agree too: either the same normalised title,
  or both names are just the assignment's name worded differently. `assignment_named` drops the
  course code (from `courses.yaml`, or any leading "EE 160A:"-style code) and anything in
  brackets, then reads the name with `matching.signature`:

  | name | `assignment_named` |
  |---|---|
  | ENGR 40M: Prelab 1 (Gradescope) | (1, {pre, lab}) |
  | ENGR 40M: Lab 1 prelab (Gradescope) | (1, {pre, lab}): the same, so a copy |
  | EE 160A: HW1 (due Fri Oct 9, week 3) | (1, {pset}) |
  | CME 102 Pset1: work block (Tue night) | None: "work block" says more than the assignment |
  | Breakfast | None: no number, no guess |

Faith picked this over the simpler "identical titles only". A read-only run over her 280 live tasks
showed that the simpler rule would have missed two real pairs that very night (the Canvas-made
"Prelab 1 (Gradescope)" next to her "Lab 1 prelab"; two EE 160A HW1 tasks). The chosen rule finds
exactly those two and nothing else.

**A question that no longer applies withdraws itself.** Questions go out one at a time
(`Store.proposal_slot`), so the unanswered Sep 28 question held up every Outlook and Gradescope
question for five days, long after all six tasks were done. The check already replaced its own
question when the findings changed. Now, when it finds nothing, it drops a pending duplicates
question and says so: "todoist: no need to answer my duplicates question, it's out of date (nothing
was deleted)". The Gradescope match question already worked this way.

## Reading the code

1. `sync.py` — `_title_key`, `adopt_same_title`, `Report.adopted`; called from `run_sync` and `GradescopeSync.run`.
2. `duplicates.py` — `normalize_title`, `assignment_named`, `_close_enough`, `find_duplicates`, `DuplicateCheck.run` / `approve`.
3. `app.py` — the check hangs off `sync_job`; `ChatOps.find_duplicates` is the chat entry.
4. `tests/test_duplicates.py`, and the twin tests in `tests/test_sync.py`, `tests/test_sync_projects.py`, `tests/test_gradescope_job.py`.
