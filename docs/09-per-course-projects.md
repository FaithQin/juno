# 09 — One Todoist sub-project per class

**What changed.** Until 2026-09-24 every class lived in one Todoist project, *Classes*, as a section
(ENGR 40M, CME 102, ...). Faith wanted each class to be its own project, so now each one is a
**sub-project under Classes**. General class tasks (the add/drop and withdrawal deadlines) stay in
the Classes root with no section.

```
Classes                      ← todoist.project_id (parent)
├── ENGR 40M                 ← courses[].project_id
├── CS 106B
├── CME 102
├── MATSCI 88Q
├── EE 100
└── EE 310
```

## Config

`courses.yaml` keeps the parent under `todoist.project_id` and gives each course a `project_id`.
A course **without** one keeps the old layout (a section named after it inside Classes). That makes
the change safe to deploy before any task moves, and keeps an old config working. A misspelled key
(`projectid:`) is rejected at load: silently ignoring it would send the course back to sections.

## Reading: the union, by id

The Canvas sync, the Gradescope sync and chat all read **Classes plus every course sub-project**
(`CoursesConfig.class_project_ids`, `TodoistClient.tasks_in`). This is the lesson that matters:
the sync remembers tasks **by id**, and treats a remembered task that is no longer active as
completed. If juno read only Classes, moving a task into a sub-project would look like completing
it. Todoist keeps a task's id when it moves, so reading the union makes a move invisible.

Guards:
- **Parent first.** A task moved from Classes to a sub-project *while* juno reads is seen in one
  place or both (folded by id), never neither.
- **Strict for the syncs.** If a project can't be read, the sync raises instead of carrying on:
  skipping it would make every task in it look completed.
- **Lenient for chat and nudges.** They skip a sub-project that can't be read (logged), so one
  archived or mistyped sub-project doesn't silence every class. The parent failing still raises:
  that is Todoist being down, and the nudges and brief wait and retry.
- **Completed stays completed.** A row juno remembers as done stays done even if the task shows up
  open again: that is Faith reopening it. (An earlier draft re-opened such rows to heal a missed
  read; review showed it would re-tick tasks she reopened on purpose, so it was dropped. Deploying
  before the move is what prevents missed reads.)

## Writing: only creates choose a place

New Canvas/Gradescope items and chat-added course tasks go into the course's sub-project with no
section (`sync._destination`, `ChatOps.add_task`). Updates (due date, completion, progress) address
tasks by id and never send a project or section, so juno never moves a task back. Undo restores a
deleted task where it was, or into its course's sub-project if it was deleted from an old section
that has since been removed.

## Attributing a task to a course

`tasks.course_of`: the task's sub-project first, then its legacy section, else none (general). The
section fallback matters mid-migration, when some tasks still sit in the old sections.

## `assistant check`

Prints the parent, each course's sub-project (`ok`, `NOT FOUND`, or not under Classes), any legacy
section, and the active task count across all of them.

## Migration order (what was done on 2026-09-24)

1. Create the six sub-projects under Classes (empty; old code ignores them).
2. Ship this code with the ids in `courses.yaml` (reads the union; nothing moves yet).
3. Move every open task from each section into its sub-project (same ids).
4. Remove the empty sections.
5. `assistant sync --dry-run -v` on the server: expect no creates and nothing newly completed.
