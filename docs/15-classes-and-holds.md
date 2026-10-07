# 15 · Audits end, EE 160A gets its sites, and holds stay graphite

Faith, 2026-10-06: "im done auditing lectures so there will be no more of that." The same day she
set a new calendar convention: a time held for a meeting that isn't confirmed yet is an event titled
`HOLD: <Name> (<Org>)`, colored Graphite, so it reads differently from confirmed meetings (Banana).
Her graded load is now 20 units: CS 106B, CME 102, ENGR 40M, EE 100, EE 160A.

This phase is mostly configuration, but three of the changes needed code, and the reasons are worth
knowing because they come from how the outside sites name a cross-listed class.

## 1. Ended audits become history, not deleted lines

`courses.yaml` had EE 227 (alias CS 227A), EE 260A and AA 274A as `audit: true`. Deleting them outright
would have had a side effect: the daily class check (`course_watch.py`, `docs/12` §5) texts her about
any Canvas course or Todoist class project that `courses.yaml` doesn't know. Their Todoist projects
are archived now (10 open tasks between them, which juno can no longer see, the same as EE 310's), but
a Canvas site that lingers would have produced a "juno doesn't know this class" text.

So they moved to the `dropped:` list with a new flag, `audit: true`, and their aliases:

```yaml
  - code: "EE 227"
    aliases: ["CS 227A"]
    dropped_on: 2026-10-06
    audit: true
```

`DroppedCourse.audit` is there so juno says the right thing. The context block the model reads every
turn now has two lines instead of one:

```
dropped: MATSCI 88Q (sep 30), EE 310 (oct 2)
stopped auditing (no more audits): EE 227 / CS 227A (oct 6), EE 260A (oct 6), AA 274A (oct 6)
```

"You dropped EE 227" would have been wrong: she never enrolled in it.

The audit machinery itself (`Course.audit`, no nudges, the "(audit)" tag in the brief) is still in the
code, dormant: no course uses it. If she audits again in another quarter, it's one line in
`courses.yaml`. The audit color is gone from `assistant.yaml`, and its default is now `None`, so the
word "audit" in a title no longer turns an event Grape.

## 2. EE 160A: one class, three codes

The Canvas link on her EE 160A calendar event points at course 231155. Checked read-only against the
APIs before trusting it:

| Site | What it calls the class | How juno finds it |
|---|---|---|
| Canvas 231155 | "F26-AA-174A-01..." (Principles of Robot Autonomy I, Bansal & Pavone); sections AA 174A, CS 137A, **EE 160A**, and her enrollment is the EE 160A section | `canvas_id: 231155` |
| Gradescope 1396967 | already matched by code: the live sync linked "Homework 2" from it | by course code, nothing to add |
| Ed 106110 | "AA 174A 01" | the alias (below) |

The class is cross-listed: one Canvas site, one Ed forum, three course codes. Canvas names the site
after its first listing and cuts it short, and Ed uses AA 174A too. Two consequences:

- **The class check matched Canvas courses by code only.** "F26-AA-174A-01..." contains no "EE 160A",
  so it would have texted "canvas lists AA 174A, which juno doesn't know as a class" about her own
  graded class. `find_changes` now treats a Canvas course whose id is a configured `canvas_id` as known,
  whatever code Canvas shows.
- **Ed matched by code only too.** `ed_announcements("EE 160A")` would have said "i can't find EE 160A
  on ed". EE 160A now has `aliases: ["AA 174A", "CS 137A"]`, and the Ed lookup tries the code, then
  each alias. The aliases also help elsewhere: "aa 174a" in chat resolves to EE 160A, an event titled
  "AA 174A Section 3" gets the class color, and the context's `courses:` line shows them
  (`EE 160A (also AA 174A, CS 137A)`) so the model knows they're one class.

Ed also lists "AA 274A 01" (course 106894), the graduate listing of the same lectures. That's one of
the ended audits; the alias doesn't touch it because "aa174a" isn't in "aa274a01".

## 3. Assignments yes, calendar not yet: `canvas_events`

One `canvas_id` drives two jobs: the hourly Canvas → Todoist sync (assignments) and the hourly Canvas
→ Google Calendar sync (calendar events). Before adding it I checked both, read-only:

- **Assignments:** Canvas has one, "Skilling Document Upload" (Sep 24), already submitted, so the sync
  skips it. Nothing changes in Todoist today; future Canvas assignments will sync like her other classes.
- **Calendar events:** 55 in the next 120 days: every lecture, CA office hours, both section groups
  (she's in one), homework releases. The calendar sync's first run finished long ago, so on the next
  deploy it would have *added all 55 to her Stanford calendar without asking*, next to any lecture
  events she already made by hand. None of her other classes puts events there (only an old course has
  linked Canvas events).

She asked for assignments to sync, not for 55 calendar events, so a new per-course switch keeps them
off until she says otherwise:

```yaml
    canvas_events: false
```

`CoursesConfig.calendar_courses()` is `by_canvas_id()` minus those courses, and the calendar sync and
its Canvas query read that instead. Flip it to `true` (or delete the line) to turn them on.

## 4. Holds stay graphite

Two places in juno decide an event's color:

1. **Her scheme** (`ColorScheme.pick`), used by `add_event` when she doesn't name a color. A title
   starting `HOLD:` (any case, spaces allowed before the colon) now beats every other kind, so
   "HOLD: CME 102 midterm review (TA)" is Graphite, not Tomato or Flamingo. "Holden's birthday" and
   "Placeholder: …" aren't holds: the rule wants `hold` as the first word, followed by a colon.
   The color is configurable (`calendar.colors.hold: graphite`).
2. **`color_event`**, the chat tool. "Never recolors a hold" is a code gate here, not a line in the
   prompt: if the event's title is a hold and the requested color isn't the hold color, it changes
   nothing and says so ("…once it's confirmed, take 'HOLD:' out of its title and i can recolor it").
   Setting a hold *to* Graphite is still allowed, so a hold she made in the wrong color can be fixed.

Nothing else in juno writes colors: the Canvas and Outlook syncs create events with the calendar
default and only ever patch times, titles and a private tag. An explicit color in `add_event` still
wins, because that's her own words at creation, not a recolor.

No `HOLD:` events existed on her Stanford calendar yet (Sep–Dec, checked read-only), so the rule
follows her stated format.

## Reading the code

1. `courses.yaml`, `assistant.yaml` (`calendar.colors`).
2. `config.py`: `Course.canvas_events`, `DroppedCourse.audit / aliases`, `CoursesConfig.calendar_courses`.
3. `course_watch.find_changes` (the `configured` ids); `calendar_sync.CalendarSync._course_for`; `app.build_calendar_sync`.
4. `colors.py`: `HOLD_RE`, `is_hold`, `ColorScheme.pick`; `chat_ops.color_event` (the hold gate), `chat_ops.ed_announcements` (aliases), `chat_ops.context_block`.
5. `app.course_kwargs` (`ended_audits`), `app.color_scheme`.
6. Tests: `test_classes.py` (2026-10-06 section), `test_colors.py`, `test_calendar_sync.py`, `test_config.py`.
