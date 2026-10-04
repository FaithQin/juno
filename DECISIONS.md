# Decisions

Everything below was chosen by Faith on 2026-09-22 unless marked **default (mine)**, which
means Claude picked a sensible default and it is one config line to change.

## What it is

A personal AI agent, built in Python, that starts as a school assistant and grows into a general
one. It watches Canvas, keeps Todoist and Google Calendar current, is reachable over iMessage,
sends proactive reminders and a morning brief, and later knows where you are.

## Accounts and channels

| Decision | Choice | Notes |
|---|---|---|
| Calendar | Google Calendar | Existing calendars: `Stanford` (classes), `TA` (office hours), `Todoist` (mirror of timed tasks) |
| Canvas | canvas.stanford.edu with a personal access token | Token creation is allowed |
| Text channel (v1) | iMessage via Photon | Inbound arrives by webhook, so the server needs a public HTTPS URL |
| Timezone | America/Los_Angeles | Store UTC, render Pacific, inject "now + tz" into every prompt |
| Hosting | Cheap VPS (Hetzner or DigitalOcean, $4-6/mo), Docker | Needed for the Photon and location webhooks |
| LLM provider | OpenAI: `gpt-6-sol` for chat, `gpt-6-luna` for background | Via Pydantic AI, so any role can switch to Claude by editing config |
| Location (later phase) | OwnTracks app, HTTP mode, geofences | Lateness alerts are not in v1 |
| Friend's repo | Not available; build from scratch | |
| Involvement | Teach me as we go | Smaller phases, a walkthrough doc per phase |
| Project folder | `Second Brain/1 - Projects/Personal AI Agent` | `.venv` and `data/` are gitignored; Obsidian ignores dot-folders |

## Scope of v1

1. Canvas → Todoist sync (this phase).
2. iMessage chat, due-date reminders, morning brief.

Later phases, in order: Canvas calendar events → Google Calendar and the CS 106B site scrape;
syllabus parsing with approval; OwnTracks location and running-late alerts; a Gradescope scraper
for unlinked courses (only if the Gradescope login is email + password, not SSO only).

## Where things live

- **Todoist holds anything you check off.** Project `Classes` (id in `courses.yaml`) under
  `Areas`, one section per course: ENGR 40M, CS 106B, CME 102, MATSCI 88Q, EE 310, EE 100.
  Task naming convention already in use: `COURSE: Title`, with the Canvas link in the description.
- **Google Calendar holds anything you go to at a time.** Classes, exams, office hours are already
  there by hand. Canvas timed events will be added in a later phase with duplicate detection
  against the hand-made ones.
- Assignments never go on the calendar directly; the Todoist calendar mirror already shows them.

## Sync behaviour

| Decision | Choice |
|---|---|
| Existing hand-made tasks | **Adopt.** Link them by the Canvas URLs in their descriptions; never duplicate; only change their due date when Canvas changes it |
| ENGR 40M quizzes (~50) | **One task per due date** with a checklist of links in the description, e.g. `ENGR 40M quizzes 2–8` |
| Non-Canvas assignments | Text them to the agent; also scrape the public CS 106B site (phase 2); Gradescope scraper as a later option |
| Gradescope assignments linked into Canvas | Sync automatically (they appear as Canvas external-tool assignments) |
| When a new Canvas assignment appears | **Create it, then text a summary.** Reply `undo` reverses it. Outward-facing actions always ask first |
| Submitted on Canvas | **default (mine):** tick the Todoist task (`COMPLETE_WHEN_SUBMITTED=true`). A batch completes only when every member is submitted |
| No due date | **default (mine):** skip, list in the report (`INCLUDE_UNDATED=false`) |
| Batching threshold | **default (mine):** 2 or more items in the same course, group and due time (`BATCH_MIN_SIZE=2`) |
| Removed or unpublished on Canvas | Never delete; note it in the report |
| Completed or deleted by you in Todoist | Never recreate |
| Task priority | **default (mine):** normal |

## Proactive behaviour (phase 2)

| Decision | Choice |
|---|---|
| Morning brief | 7:00 am: today's classes and events, due today and tomorrow, overdue |
| Due-date nudges | 24 hours and 2 hours before each item, keyed by assignment so they never repeat |
| Quiet hours | None |
| Personality | Casual, lowercase, brief. Mirrors your length. No emoji unless you use them. Name: not chosen yet (`AGENT_NAME` in `.env`) |

## Non-negotiables from the research

Silence is a valid output. One brief plus capped interrupts. Deterministic sync with no LLM in the
loop. Identity by Canvas id, never title. Confirm side effects with a verbatim draft; thumbs-up
means yes. Untrusted content (syllabi, Canvas descriptions, emails) is data, not instructions.
Secrets in `.env` with 600 permissions, never committed. Daily token budget once the LLM arrives.

## Phase 2 decisions (2026-09-22, evening)

| Decision | Choice |
|---|---|
| Channel | **Telegram now; Photon iMessage later.** Photon has no HTTP send API (Node SDK over gRPC only), so a pure-Python juno can't send through it yet. Telegram is free, needs no public URL, and the channel is a thin adapter |
| Name and voice | **juno.** Casual, lowercase, brief; task names and course codes keep their case |
| Chat writes | add, complete, reschedule, snooze. **Act then echo**, `undo` reverses. Ambiguous match → "which one?". Unknown course → ask |
| Other Telegram chats | ignored silently; one allowlisted chat id |
| Conversation context | last 24 hours |
| Facts memory | yes: `remember` / `forget`, stored in SQLite, injected every prompt |
| First nudge | **8:00pm the evening before** (a literal 24h would land at midnight for 11:59pm deadlines) |
| Second nudge | 2 hours before, only for tasks with a clock time |
| Date-only tasks | eve nudge only |
| Missed nudges (juno offline) | **send anyway, say it was offline and when** |
| Nudges cover | Classes project plus p1/p2 tasks anywhere |
| Morning brief | 7:00 every day; calendars Stanford, TA, primary, StartX, Cal.com; deterministic, no LLM |
| Google scope | read all calendars + write events now, so phase 3 needs no re-consent; token kept in `data/` |
| Calendar read | full OAuth (not iCal URLs) |
| Models | OpenAI gpt-6-sol for chat via pydantic-ai; gpt-6-luna reserved for background |
| Replies | ~~one message per reply~~ → changed 2026-09-23: **Poke-style bubbles**. juno writes short messages separated by blank lines; the channel sends each as its own text with a typing pause |
| Phase 1 real run | done 2026-09-22: 52 hand-made tasks adopted, 1 task added |
| Brief task lists | **every dated task in Todoist** (not just school or p1/p2); overdue shows the **last 7 days** only |

## Phase 2.5 decisions (2026-09-23)

| Decision | Choice |
|---|---|
| Opening links | **`read_link` tool**: public pages as readable text; Canvas links via the API with her token. Content is framed as untrusted data; private/local addresses are refused |
| Web search | **OpenAI native web search** (Responses API), Stanford as the user location, low context size; `agent.web_search` in assistant.yaml. No per-call cap on OpenAI, so the per-message request limit (8) is the ceiling |
| Autonomy for reading | juno opens links found in messages and tasks **without asking**; reading never changes anything |
| Full browser (Playwright) | **next phase, soon**: behind-login sites (Gradescope, Paperless, SSO forms) and form filling |
| Hosting order | finish web tools → **VPS deploy next**, so juno answers while the Mac is closed |
| Host | **DigitalOcean** first ($6 droplet, SFO); move to Hetzner when it runs out of room. Docker so the move is one command |
| Deploy flow | rsync from the Mac (`scripts/deploy.sh`), including `.env`; `data/` copied only on the first deploy; one juno instance at a time |

## Phase 3 decisions (2026-09-23): the browser

| Decision | Choice |
|---|---|
| Scope | **Read and act**: open, click, type, select, submit |
| Logins | **One-time login on the Mac** (`browser-login <site>`), storage state shipped by `deploy.sh`; juno asks for a re-login when a snapshot lands on a login page. No passwords anywhere in juno |
| Sites | Gradescope, Paperless (CS 106B), Ed Discussion, Canvas web pages |
| Submitting | **Always asks first** (`requires_approval` on `browser_submit`); yes/no over Telegram; any other message cancels the pending click |
| Reading and filling | autonomous, no confirmation |
| Memory | one Chromium, one context per site, one page, closed after 10 idle minutes; **resize the droplet to 2 GB if it runs out** |
| Sandbox | Chromium runs as root without its sandbox inside the container (accepted for now; hardening later) |
| Per-message limits | raised to 14 model requests / 120k tokens so multi-step browsing fits |

## Phase 4 decisions (2026-09-24): Gradescope sync and Ed

| Decision | Choice |
|---|---|
| Gradescope cadence | every 3 hours, through the saved browser login, no model involved |
| First run | **propose over Telegram, wait for yes**: title matches to hand-made tasks plus the new items; a "no" is remembered by fingerprint |
| Submitted on Gradescope | tick the Todoist task (same as Canvas) |
| Naming | `COURSE: Name (Gradescope)`, matching the existing convention |
| Ed | **official-ish API with a personal token** (`ED_API_TOKEN`); `ed_announcements` tool; browsing Ed stays available |
| "Too many steps" | fixed by trimming old tool output from history before each model request (keep the last 3 in full); per-turn ceiling raised to 24 requests / 250k tokens as a backstop |
| Editing tasks | new `edit_task` tool: title, notes, priority; undoable |

## Phase 5 decisions (2026-09-24): calendar

| Decision | Choice |
|---|---|
| Deletes | **act, then echo, undoable**; only on her explicit ask; syncs never delete |
| Canvas events target | the **Stanford** calendar |
| First calendar run | **propose over Telegram, wait for yes** (matches by same day + within an hour + course code or shared title word) |
| Chat calendar tools | add / move / delete events with undo; new events go to Stanford (classes, exams), TA (office hours), or personal, per the persona |
| Cadence | hourly, via the Canvas API (no browser) |

## Phase 6 decisions (2026-09-24, late): completions

| Decision | Choice |
|---|---|
| Completed work | syncs tick the Todoist task when Canvas/Gradescope show a submission (already true); **quizzes finished inside a batch get a ✅ on their checklist line** and a "progress" note |
| On demand | `sync_now` tool: "i finished quiz 3" → juno checks Canvas/Gradescope right then and reports |
| Every edit is reported | **standing rule**: any write by juno or a sync (add, complete, move, edit, link, delete) is echoed in chat or texted by the sync. No silent changes |

## 2026-09-24 (night): after a day of real use

Faith's message that evening: $5 of OpenAI in one day, Canvas re-login, photos ignored, juno
browsing Canvas for the calendar, "can it learn my preferences", and Outlook invites → Google
Calendar. All of the following are **default (mine)** except where marked; each is one line to change.

| Decision | Choice |
|---|---|
| Unanswered proposals | **asked once**; repeated only if Canvas/Gradescope changes what's proposed |
| A bare yes/no after other chat | goes to normal chat; the proposal stays visible to the model and `answer_proposal` handles a clear answer |
| Transient upstream errors | retried with backoff; the brief waits ~10 min then says it's skipping; nudges/sync retry twice |
| Cost | clock moves out of the instructions onto her message (cacheable prefix); previous turns re-sent as conversation only; reasoning context `current_turn`; cache key `juno`. **History window stays 24 h** (Faith to decide whether to shorten; see HANDOFF) |
| Photos | **on**: sent to the model as images; the last 3 photo messages stay attached, older ones become a note |
| Canvas in the browser | **never**: the API token covers tasks, events and links; no Canvas re-logins |
| Learning preferences | persona rule: corrections are saved with `remember` unprompted; the fact list is in every prompt |
| Outlook → Google Calendar | **not started**: needs Faith's answers (see HANDOFF → scoping questions) |

## Phase 7 decisions (2026-09-24, night): Outlook meetings → Google Calendar

Faith's answers, in her words where possible.

| Decision | Choice |
|---|---|
| Access | **Published Outlook calendar link (ICS)**; "Publish a calendar" is available in her Stanford Outlook. URL in `.env` as `OUTLOOK_ICS_URL`, nowhere else |
| Which meetings | **Everything new on the Outlook calendar, including tentative invites** |
| Target | **Stanford** calendar |
| Confirmation | every new item is proposed over Telegram; yes copies it with all details; no is remembered by id |
| Cadence | **default (mine):** every 10 minutes |
| Attendees | never invited on Google (that would email them); not in the feed anyway |
| Cancellations | never deleted; a vanished meeting is reported once, she says "delete it" if she wants |
| Canvas browsing | **stays off**; Faith will name the Canvas pages she still needs (grades? modules? files?) and they become API tools |

## Per-course Todoist sub-projects (2026-09-24, night)

Faith, from the Stanford session: "i want each class as a separate subproject under class not to be
shoved all underneath classes". Asked how to handle juno, she chose **update both** (Todoist and juno).

| Decision | Choice |
|---|---|
| Layout | **each class is its own sub-project under Classes** (ENGR 40M, CS 106B, CME 102, MATSCI 88Q, EE 100, EE 310); ids in `courses.yaml` |
| General class tasks | stay in the Classes root with no section (add/drop and withdrawal deadlines) |
| Old sections | tasks moved (same ids) into the sub-projects, then the empty sections removed |
| New work | Canvas, Gradescope and chat-added course tasks go into the course sub-project, no section |
| A course without `project_id` | **default (mine):** keeps the old layout (a section inside Classes), so an old config still works |

## Duplicates (2026-09-24, late night)

Faith: "juno should also check to make sure there are no duplicate tasks in todoist." Defaults (mine), one line each to change:

| Decision | Choice |
|---|---|
| What counts | same project and (same title once course prefix, "(Gradescope)"-style suffix, case and punctuation are ignored, due dates ≤ 1 day apart) **or** the same Canvas/Gradescope assignment link in the descriptions |
| Which one stays | the task a sync tracks (Canvas link over Gradescope link), else the older one |
| When | after every hourly Canvas sync, and on demand ("check for duplicates") |
| Removal | **proposed, never automatic**; yes deletes the copies with undo snapshots and moves their sync links to the kept task; no is remembered per pair |
| Prevention | both syncs adopt an existing task with the exact same title in the same course instead of creating a twin (reported as "linked … to tasks you already had") |

## Hand-made tasks vs Gradescope, and Canvas/Gradescope twins (2026-09-24, late night)

From the homework audit that night (Faith's instructions, marked; the rest **default (mine)**). Walkthrough: `docs/11-hand-made-and-twins.md`.

| Decision | Choice |
|---|---|
| New Gradescope assignment that plausibly is a task she wrote herself | **ask once over Telegram, one question at a time; never link silently** (Faith). The assignment is held back (no twin) until she answers |
| What "plausibly" means | same course, same numbers (PSET 1 = Pset1 = Problem Set 1), same pre/post/lab/pset kind words, due dates within ~2 days (Faith); no number, no guess (mine) |
| Yes | link recorded (`adopted`), so Gradescope's later date changes move it and a submission ticks it (Faith). Her title, notes and **current date are left alone**, and the reply says if the dates differ (mine, from the 2026-09-22 rule that adopted tasks change date only when the source changes it) |
| No | the Gradescope task is created right away, as before (Faith); that pair is never asked about again (mine) |
| Several matches at once | one question lists them all; yes/no answers all of them (mine; same as the first-run question) |
| A question that became moot (Canvas linked it by id) | withdrawn, and the sync text says so (mine) |
| Exact-title hand-made task, Gradescope side | **asked like any other match** (follows "never link silently"); `adopt_same_title` now only shares tasks another sync already follows. **Open:** the Canvas sync still adopts an exact-title hand-made task without asking (texts afterwards), from the duplicates change earlier tonight. Ask Faith whether that should ask too |
| Canvas external tool that is a Gradescope assignment | **the same work: both ids linked to one task** (Faith). Identified **by id** (`custom_gradescope_resource_id` in the Canvas launch parameters), not by name and due time: no guess, so no question (mine) |
| Which copy the duplicate check keeps | **the task linked to the source that ticks on submission** (Faith): a Gradescope link outranks the Canvas half of a Gradescope assignment; a plain Canvas link still outranks both (mine) |
| Notes on a deleted copy | **carried over to the kept task** (Faith), logged so undo can take them back (mine) |
| Faith's existing duplicates | **not deleted by the agent**; listed and proposed, she decides (Faith) |

## Duplicates, narrowed after a wrong question (2026-10-03)

The Sep 28 duplicates question was wrong (her "Breakfast" on Tue and Wed at 8:15am; her three "CME 102 Pset1: work
block / finish + submit" tasks as copies of "CME 102: Pset1 (Gradescope)" because they carried its link), and it
blocked every other question for five days. Walkthrough: `docs/10-duplicates.md` §4.

| Decision | Choice |
|---|---|
| Same title, a day apart | still copies (a hand-made date vs the real one), **except at the same clock time on different days**: a daily habit, not a copy (mine, from the Breakfast pair) |
| Same assignment link, different titles | **copies only when both names are just the assignment's name, worded differently** (Faith, 2026-10-03, picked over "identical titles only"): course code and anything in brackets dropped, then the same numbers and assignment words (pre/post/lab/pset/hw/quiz, any spelling) and no other words. "Lab 1 prelab" = "Prelab 1"; "HW1 (due Fri Oct 9, week 3)" = "HW1 (Gradescope)"; "Pset1: work block (Tue night)" says more than the assignment, so it is a step, never a copy. No number, no guess (as in `matching.py`). Identical titles (after course code / source suffix / case / punctuation) still count too |
| Why not "identical titles only" | checked read-only against her 280 live tasks on 2026-10-03: it would have missed two real pairs that night (the Canvas-made "ENGR 40M: Prelab 1 (Gradescope)" next to her "Lab 1 prelab (Gradescope)"; two "EE 160A: HW1" tasks). The chosen rule finds exactly those two and nothing else |
| A pending duplicates question the check no longer finds (tasks done, deleted, or no longer alike) | **withdrawn**, with a one-line text ("no need to answer my duplicates question, it's out of date (nothing was deleted)"), so it can't block the queue (mine; same as the Gradescope match question) |
| Date-only tasks with the same title a day apart | **unchanged: still asked about** (mine, the minimal change). If a date-only daily habit shows up, narrow this the same way |

## Replies, colors, planned work, sources, classes (2026-10-03, night)

Faith's message: understand replies to earlier messages, set event colors, tell due dates from scheduled work blocks,
no sources unless asked, and make juno aware of her class changes. Walkthrough: `docs/12-replies-colors-planned-classes.md`.

| Decision | Choice |
|---|---|
| Telegram replies | the replied-to text (or the quoted part) rides on her message; a reply yes/no to a proposal's message answers that proposal however old (mine) |
| juno's own texts | nudges, brief, sync notes and proposals are kept in the conversation (a separate outbox stream) so "done" or "push it" right after one makes sense (mine) |
| Sources | **only when she asks** (Faith): web-search citations (`utm_source=openai`) are stripped from replies; when she asks for sources they become plain links; other links are untouched |
| Event colors | **juno matches her scheme automatically** (Faith): classes and sections Flamingo, audits Grape, exams Tomato, else default; a color she names wins; `color_event` recolors one occurrence or a whole series, undoable. Synced Canvas/Outlook copies stay default (mine) |
| Planned vs due | Todoist deadline field → planned (the due date is her plan); tracked by a sync → due; duration or "block" in the title → planned; else due (mine, from her Todoist: 149 tasks with durations, 42 with deadlines) |
| Work-block reminders | **one heads-up 10 minutes before a planned block with a start time** (Faith); no "due tomorrow" / "due in 2h" for planned work; blocks without a time only in the brief |
| Classes | **EE 160A graded** (Faith: "actively taking and getting graded on"); **EE 227 (CS 227A), EE 260A, AA 274A audits** (Faith: "leave them as for audit"; AA 274A is labelled audit on her calendar): known for chat/Ed/Todoist, no Canvas/Gradescope sync, no nudges, "(audit)" in the brief. MATSCI 88Q and EE 310 listed as dropped |
| CS 106B's Canvas site | not synced: it is empty, and its assignments come from Paperless/Gradescope (mine) |
| Class check | daily 9:30: texts once about a Canvas course or Todoist class project juno doesn't know, or a synced course Canvas no longer lists (mine) |

