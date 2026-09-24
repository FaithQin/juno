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
