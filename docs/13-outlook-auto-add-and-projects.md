# 13 · Outlook meetings added on their own, and tasks outside her classes

Faith, 2026-10-06: "I almost missed my interview with Human Capital today. This is a huge issue."
And: juno couldn't add "Try out Instinct" to her One-Off Tasks project. Both failures came from
how juno was designed, not from a crash, so they're worth understanding.

## 1. What went wrong with Outlook

"Faith / Sean [Human Capital]" (Tue Oct 6, 1:45pm) was on her Outlook calendar as *tentative*:
an invite she hadn't answered yet. The Outlook job read it every 10 minutes and did nothing
she could see, for three reasons stacked on top of each other:

1. **One question at a time.** Jobs that need her yes share a single slot (`Store.proposal_slot`),
   so a bare "yes" can never land on the wrong question (`docs/07-hardening.md`). A duplicates
   question had held that slot since Sep 28 (replaced twice, never answered).
2. **Waiting was silent.** A job that found the slot taken returned "…once you've answered the
   duplicates proposal" to `sync_now` callers and sent nothing. So for over a week, no new
   Outlook meeting reached her at all.
3. **Outlook only ever asked.** Even with the slot free, a meeting went onto Google only after a
   yes. And the morning brief and the nudges read Google Calendar and Todoist, never Outlook,
   so a meeting that lived only in Outlook appeared nowhere.

Any one of these alone would have been survivable. Together they hid an interview.

## 2. The fix: add, then tell her

Faith chose (2026-10-06): **every new Outlook item, tentative invites included, goes straight onto
her Stanford calendar; juno texts what it added; 30 minutes before each Outlook meeting it texts
a heads-up.** Meetings she said "no" to back when juno asked stay off.

`OutlookSync.run` now:

- finds the items that aren't linked yet, aren't in `outlook_declined`, and haven't ended
  (a meeting that's already over isn't worth copying);
- links the ones she already put on Google by hand (`match_existing`, as before) and copies the
  rest (`_copy`). A copy Google refuses is logged and left unlinked, so the next run tries again;
- texts one message: "outlook: added 2 to your Stanford calendar: … already on your calendar, now
  linked: … i'll text you 30 min before each meeting. to take one off google, say delete and which one".

**Always texted, whoever started it.** The first adds after the deploy came from her own chat ("check
everywhere" → `sync_now("all")`), which runs the sync *quietly* and hands its report to the model.
The model answered about psets and never mentioned the two meetings it had just put on her calendar.
So an add, a link or a move is now always texted through `send`, and a quiet run's return value is
marked "(already texted her this)" so the model doesn't need to repeat it.

It never touches the question slot, so a question waiting elsewhere can't block it again. If a
question from the old ask-first days is still out, it's dropped once its meetings are added.

**Why not "undo"?** juno's undo takes back the *last* action in the action log. If a background job
put its adds there, "undo" after her own chat action ("add a task… undo") would delete a meeting
instead. So she takes a meeting off with "delete the colloquium" (`delete_event`, which *is*
undoable). A deleted copy stays linked, so it isn't added back.

## 3. The heads-up

`OutlookSync.heads_up` runs right after each Outlook sync (every 10 minutes) but reads **Google**,
not the Outlook feed:

- the feed times out now and then (`ReadTimeout` a few times a day in the logs); the reminder
  shouldn't depend on it;
- Google already expands a series into its occurrences (`recurring_id` points at the series she
  linked), and has her own title and room if she linked a hand-made copy.

An event gets a heads-up if its id (or its series id) is an Outlook link, it isn't all-day, and it
starts within the next 30 minutes. The nudge ledger (`nudges_sent`, key
`outlook-heads-up:<event id>:<start>`) makes it once per meeting time; a meeting that moves gets
a new one. With a 10-minute scan the text says "in 25 min: …" or similar.

## 4. Tasks outside her classes

`add_task` only knew courses: no course meant "which course is that for?". Her Todoist is
organised beyond classes (Inbox, One-Off Tasks, Areas → Clubs → SSIG, Health, Research…).

Faith chose (2026-10-06): **juno always asks which project, unless she names one.** So:

- `add_task(..., project="one-off tasks")` resolves the name against her projects outside the
  Classes tree (`_other_projects`): an exact match ignoring case and punctuation wins, else a
  unique partial match ("ssig", "health"); several matches → "which project? Clubs, Energy Club";
  none → the list of her projects.
- No course and no project → "which project is that for? a class (…) or one of: …", which the
  model turns into a question for her. The persona tells it never to pick a project itself.
- A class named as the project ("cme 102") still goes to the class, with its course prefix.
- The task keeps her words as the title (no course prefix) and is undoable like any chat add.

**Finding a task to complete, move or edit** used to search only class tasks plus p1/p2 ones
(`ChatOps._candidates`), so "done with try out instinct" couldn't find a p4 task in One-Off Tasks.
Faith chose (2026-10-06) that juno sees every project for these: `_pick` now matches against
`todoist.all_tasks()`. With ~280 tasks a vague name gets "which one?" more often; that's the
trade. "What's due" (`get_tasks`) still lists class tasks plus p1/p2, as before.

One detail in the heads-up: when Outlook links her own *weekly* event, the id it links is the
occurrence Google listed (`<series>_<time>`). `heads_up` also accepts the series part of such an
id, so every week of her copy gets its reminder, not only the first.

## Reading the code

1. `outlook_sync.py` — `OutlookSync.run`, `_copy`, `_added_text`, `heads_up`; `approve` for a
   question still out from before.
2. `app.py` — `outlook_job` runs `run()` then `heads_up()`, each on its own.
3. `chat_ops.py` — `_other_projects`, `_project`, `add_task(project=)`; `agent.py` — the tool's
   `project` argument; `persona.md` — the "which project" rule and what juno does with Outlook.
4. Tests: `test_outlook.py` (adding, declines, ended meetings, failed copies, never waiting,
   heads-ups for single meetings, series and her own weekly copy), `test_chat_ops.py` (`HER_PROJECTS`,
   finding tasks in any project).
