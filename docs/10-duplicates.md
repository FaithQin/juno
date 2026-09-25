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
is a series, not a copy), or their descriptions point at the same Canvas or Gradescope assignment.
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

## Reading the code

1. `sync.py` — `_title_key`, `adopt_same_title`, `Report.adopted`; called from `run_sync` and `GradescopeSync.run`.
2. `duplicates.py` — `normalize_title`, `find_duplicates`, `DuplicateCheck.run` / `approve`.
3. `app.py` — the check hangs off `sync_job`; `ChatOps.find_duplicates` is the chat entry.
4. `tests/test_duplicates.py`, and the twin tests in `tests/test_sync.py`, `tests/test_sync_projects.py`, `tests/test_gradescope_job.py`.
