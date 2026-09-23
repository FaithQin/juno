# Walkthrough 1: the Canvas → Todoist sync

Read this next to the code. It explains *why* each piece is shaped the way it is, and ends with
things to try so you can change it with confidence.

## What one run does

```
uv run assistant sync
      │
      ├─ config.py        read .env and courses.yaml
      ├─ todoist_client   fetch the Classes project, its sections, all active tasks
      ├─ canvas_client    for each course in courses.yaml: assignments (+ your submission), quizzes
      ├─ sync.adopt_links any active task whose description links a Canvas item becomes its record
      ├─ sync.plan_sync   PURE: items + memory → Plan (creates / joins / due updates / completes / skips)
      ├─ sync.apply_plan  the only place Todoist is written; records every link in SQLite
      └─ format_report    the text you'll later receive as an iMessage
```

The split between `plan_sync` and `apply_plan` is the single most important design choice.
A plan is just data, so `--dry-run` prints exactly what would happen, and `tests/test_sync.py`
can exercise every rule in under a second without touching either API.

## The three questions the sync answers for every Canvas item

1. **Do I already know this item?** Lookup by `(kind, canvas_id)` in the `item_links` table.
   Never by title: the research found sync tools that duplicated tasks whenever an instructor
   renamed something.
2. **Is it alone or part of a batch?** `batch_key()` groups items that share a course, an
   assignment group, and a due time. Two or more together become one task with a checklist,
   which is how the ENGR 40M quizzes were already organised by hand.
3. **Has Canvas changed since last time?** Each link remembers the due date Canvas reported at
   the last sync. If it differs now, the task's due date is updated. Your own edits in Todoist
   are never compared against, so nothing you change by hand gets "corrected".

## Adoption, and why the first run is safe

`adopt_links()` runs before planning. It scans every active task in `Classes` for URLs like
`canvas.stanford.edu/courses/231533/assignments/823749` and records "this task represents that
assignment". The Canvas due date is recorded from the live item at the same moment, so the first
plan sees no difference and leaves your hand-set dates alone. If a link points at an item the sync
didn't fetch (say, a course not in `courses.yaml`), the due date is stored as unknown, and an
unknown due date never triggers an update.

One consequence worth knowing: because hand-made tasks are adopted, the sync will never rename
them. It only manages titles on tasks it created itself.

## What the sync refuses to do

- Delete a task. Something removed from Canvas is mentioned in the report and left alone.
- Recreate a task you completed or deleted in Todoist. A task that disappears from the active
  list is marked completed in the database and forgotten about.
- Create anything that Canvas already shows as submitted.
- Un-tick a batch task while any member is still open.
- Call Canvas in parallel. Canvas charges a pre-flight penalty for concurrent requests; a steady
  sequential stream is never throttled.

## Reading the code, in order

1. `config.py` — `Settings` reads `.env`; `CoursesConfig` reads `courses.yaml`. Everything else
   takes these as arguments rather than reading files itself.
2. `canvas_client.py` — turns two Canvas object types into one `CanvasItem`. Look at
   `_is_submitted` and `is_gradescope`: Gradescope assignments an instructor linked into Canvas
   arrive as `submission_types == ("external_tool",)` with a gradescope URL.
3. `db.py` — two tables that matter, `item_links` and `tasks`, plus a `runs` log. Plain sqlite3.
4. `sync.py` — top to bottom: helpers, naming, the `Plan` dataclasses, `plan_sync`, adoption,
   `apply_plan`, `format_report`, and `run_sync` which strings them together.
5. `cli.py` — argparse, three commands.

## Things to try

- Change `BATCH_MIN_SIZE` to 3 in `.env`, run `--dry-run`, and watch pairs of quizzes become
  separate tasks. Change it back.
- Add a course to `courses.yaml` with a made-up `section:` name, run `--dry-run`, then `check`:
  it tells you the section will be created on the first real run.
- In `tests/test_sync.py`, copy `test_quizzes_same_week_become_one_task_with_checklist` and make
  two of the three quizzes submitted. Predict what the plan contains, then run `uv run pytest`.
- Read `format_report` and change the wording. This is the text phase 2 sends over iMessage.

## What phase 2 adds

A scheduler runs this every hour and pipes `format_report` into an iMessage when anything
changed. The same `Store` gets a `reminders_sent` table keyed by `(assignment, kind)` so the 24h
and 2h nudges fire exactly once. The chat agent gets read-only tools over the same database
plus one write tool, `add_task`, for the Gradescope and Paperless assignments you text it.
