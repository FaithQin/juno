# Walkthrough 6: the calendar, both directions

Until now juno only read Google Calendar. This phase adds writing: Canvas events flow onto
your Stanford calendar on a schedule, and you can add, move, and delete events (and delete
tasks) by text.

## Canvas events → Stanford calendar

Canvas's calendar holds instructor-posted events: exams, review sessions, seminars. For
your courses this quarter that's the weekly EE 310 SystemX seminar. `calendar_sync.py`
fetches them hourly through the Canvas API and mirrors them onto the Stanford calendar,
with the Canvas event id stored as a private property on the Google event and in
`item_links` (kind `canvas_event`). Same rules as every sync here: identity by id, never
delete, a moved Canvas event moves the Google one.

**The first run proposes.** You entered exams and classes by hand, so a naive sync would
duplicate "EE 310 Thursday 4:30" with "SystemX: … Seminar Thursday 4:30".
`match_existing` links a Canvas event to a hand-made one only when all three hold: same
day, starts within an hour, and either your course code is in the hand-made title or the
titles share a real word. The first run texts the proposed links and the genuinely new
events, and your yes records the links (and tags the hand-made events so they're
recognised later). A no is remembered until Canvas adds something.

## Calendar and delete tools for chat

`add_event`, `move_event`, `delete_event`, `delete_task`. All act immediately and are
undoable: an added event is deleted, a moved one is moved back, a deleted event or task is
recreated from the snapshot juno kept (with a new id). Event lookup covers the next two
weeks across your calendars and asks "which one?" on ambiguity, like tasks.

Where a new event goes is a persona rule, not code: classes and exams on Stanford, office
hours and help sessions on TA, everything else on your personal calendar. Change
`persona.md` if you'd rather.

Deletes exist only because you ask for them in chat; the syncs still never delete.

## Reading the code

1. `gcal.py` — `event_body`, `events_in_window`, the write methods; `Event` now carries ids.
2. `calendar_sync.py` — `match_existing` and `CalendarSync.run` / `approve`.
3. `chat_ops.py` — `_pick_event`, `add_event`, `move_event`, `delete_event`, `delete_task`, and their `undo` branches.
4. `tests/fakes.py` — `FakeCalendar` is now an in-memory Google Calendar with ids.
