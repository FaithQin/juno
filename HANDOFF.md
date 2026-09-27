# Handoff — state as of 2026-09-24 (~22:50 PDT, after hand-made matching and Canvas/Gradescope twins)

Read `AGENTS.md` for the rules. This file is the live snapshot: what is running, what is pending,
what to do next. **Update it at the end of every working session.**

## What is live (verified on the server; last deploy `ad55a1c`, 2026-09-24 ~22:38 PDT)
| Piece | Cadence | Notes |
|---|---|---|
| Canvas → Todoist sync | hourly | adopted 52 hand-made tasks on 2026-09-22; batches same-day quizzes; retries transient errors |
| Gradescope → Todoist | every 3 h | via saved browser login; first run approved 2026-09-24; proposals asked once. **New:** an assignment that plausibly is a hand-made task (same course + number + pre/post/lab/pset words + due within 2 days) is **asked about** (`gradescope_match`), held back until she answers; yes links, no creates. `docs/11-hand-made-and-twins.md` |
| **Canvas ↔ Gradescope twins** | with both syncs | a Canvas external tool names its Gradescope assignment (`custom_gradescope_resource_id`); both ids now link to one task, whichever side comes first. Pairings kept in `kv["gradescope_twins"]` (written by the Canvas sync) |
| Canvas events → Stanford calendar | hourly | first-run proposal **re-asked once** at the next run (see Pending) |
| Nudges: 8pm the evening before, 2h before | scan every 10 min | late ones say "i was offline"; a Todoist blip skips one scan quietly |
| Morning brief | 07:00 daily | every dated Todoist task + calendars Stanford/TA/primary/StartX/Cal.com; waits ~10 min through a Todoist outage, then says so |
| Telegram chat (`gpt-6-sol`, low reasoning) | on message | tasks, events, web, browser, Ed, `sync_now`, undo, **photos**, `answer_proposal`, `/status` (now with today's token use and cache share) |
| Completion tracking | with each sync | submitted work ticks the task; quizzes done inside a batch get a ✅ on their checklist line |
| Real browser (Playwright) | on demand | logins: gradescope, paperless (cs198, refreshed 2026-09-27 12:40 PDT), ed. **Canvas is never browsed** (API only); `browser_submit` asks first |
| **Outlook → Stanford calendar** | every 10 min | published Outlook ICS link in `.env`; new items (incl. tentative invites) proposed, yes copies with all details; `sync_now("outlook")`; `assistant outlook --print` |
| **Duplicate check** | after every hourly Canvas sync + "check for duplicates" | same-title / same-link / **Canvas-Gradescope twin** copies proposed for deletion (undoable, links move to the kept task, **her notes on a copy move to the kept task**). Keeps the task that ticks on submission (Gradescope over the Canvas half of a Gradescope assignment). The Canvas sync adopts exact-title matches; the Gradescope sync only shares tasks another sync follows. `docs/10-duplicates.md`, `docs/11-…` |
| **Todoist layout: one sub-project per class** | — | deployed `03aba64` ~16:30 PDT. Classes (`6cXPJPmRH6GF2MPr`) holds only the 2 university deadlines; each course's tasks live in its sub-project (`project_id` in `courses.yaml`). The 6 old sections are deleted. `assistant check` shows all 6 "ok"; a dry-run sync after the move said "nothing to change" |

## Todoist move (2026-09-24, ~17:00 PDT, done)
- Faith asked for each class as its own sub-project under Classes. 68 open tasks and the 5 completed tasks
  that were still in the old sections moved by id (same task ids, so juno's links held). Then the 6 empty sections
  were deleted. Server check afterwards: 70 active tasks, 0 legacy sections, dry-run sync "nothing to change"
  (same as before the move). Details: `docs/09-per-course-projects.md`.
- The Todoist MCP's `update-tasks` reports "not found (404)" when it moves a *completed* task, but the move
  goes through (the activity log and `fetch-object` confirm it). Don't retry, just verify.

## What changed tonight and why (Faith's evening message)
- **Cost.** 2.5M tokens on 2026-09-24; the last request was 56k input tokens, $0.14, 0 read from
  cache. Cause: the `now:` line in the instructions changed every minute, ahead of the whole
  history, so OpenAI's prompt cache never hit. Fixed: the clock rides on each user message,
  earlier turns are re-sent without tool traffic or reasoning, reasoning context `current_turn`,
  prompt cache key. Measured right after on the Mac: **73% of input tokens from cache**. Expect
  tomorrow's spend to be a fraction of today's; `/status` shows the cache share live.
- **Photos** now reach the model (verified with a rendered section-times table).
- **Canvas re-login**: Stanford SSO only issues session cookies, so the Canvas browser login was
  always going to die daily. juno no longer browses Canvas at all; the API token never expires.
- **"Why do you keep sending that"**: the calendar proposal was re-sent hourly. Proposals are now
  asked once, and a stray "ok" hours later can't approve one.
- Details and reasoning: `docs/07-hardening.md`; decisions: `DECISIONS.md` (2026-09-24 night).

## Pending right now
- **Proposals queue, one at a time** (a bare yes/no answers the one that is out while it is the last
  thing said; otherwise "yes to the outlook one" etc. via `answer_proposal`). As of 22:50 PDT:
  1. **Outlook: waiting on Faith.** 6 upcoming meetings, all matched to hand-made events on her
     Google calendars; yes = link + tag, nothing created.
  2. **Duplicates: proposed with the first hourly Canvas sync after she answers Outlook.** Previewed on the
     server (read-only, 22:40) with the new twin logic. Two groups, MATSCI 88Q Lab 1:
     - keep `6hcV4XxhmGFjMXhJ` "Lab 1: Pre Lab (Gradescope)" (Gradescope-linked); delete Canvas copy `6hcX66cWvjqV6FcJ`
       and her hand-made `6hc6W9fgcqQ8G3qJ` (its notes move onto the kept task).
     - keep `6hcV4XrqpGvXj2xr` "Lab 1: Post Lab (Gradescope)"; delete `6hcX66fMPgMwPfPJ` and `6hc6W9jCPxcrJGVr` (notes move).
     Faith was also asked in the Claude session (the agent deleted nothing). *Correction:* the previous handoff said yes
     would delete the "(Gradescope)" copies. Under the old code that meant her hand-made tasks (with notes), and the
     Gradescope-made copies would have survived. Fixed before it was ever asked.
     Her post-lab note says "juno also added two copies of this assignment (Gradescope + Canvas)". It will be stale
     once the copies are gone; she may want to trim it.
  3. **Gradescope match questions start Fri Sep 25**, when ENGR 40M PSET 1 is released (ENGR 40M's Gradescope course
     1395437 is on the dashboard, empty tonight). A read-only simulation against her real tasks paired PSET 1/2,
     Lab 0/1/2A prelab and write-ups, CME Pset2/Pset6, MATSCI Lab 2 pre/post correctly; "Final Project Proposal" is not guessed.
- **Next hourly Canvas sync will text one line**: "linked 1 to tasks you already had: Pset1 → CME 102: Pset1 (Gradescope)"
  (Canvas 833182, undated, is the same assignment as Gradescope 8709892). Seen in the dry run.
- **Faith to decide: should the Canvas sync ask too?** It still adopts a hand-made task whose title is exactly the
  Canvas name (e.g. Canvas "Pre-lab 2" → her "MATSCI 88Q: Pre-lab 2 (Gradescope)") and texts afterwards, per the
  duplicates change earlier tonight. The Gradescope side now always asks. See DECISIONS.md (2026-09-24, late night).
- **Faith to answer: which Canvas pages she still needs** (grades? modules? files?). Canvas
  browsing stays off; those become API tools.
- **Faith to decide: history window.** Still 24 h (`ChatSession.window`). Recommendation: leave it, check `/status`.
- **Paperless will log out again** (Stanford SSO session cookies, roughly a day). juno says so when
  it happens; refresh with `uv run assistant browser-login paperless` on the Mac, then ship
  `data/browser/` (deploy.sh does it from a checkout that has that folder).

- **Re-login routine (any saved site; Paperless needs it about daily):** on the Mac, in the project folder,
  `uv run assistant browser-login paperless` (log in, close the window), then ship just that file and restart:
  `rsync -az data/browser/paperless.json root@165.232.146.165:/opt/juno/data/browser/ && ssh root@165.232.146.165 'cd /opt/juno && docker compose restart juno'`.
  Lighter and safer than `deploy.sh`, which also ships code and would revert the server from a checkout that isn't pulled.

## Infrastructure
- Server: DigitalOcean droplet `165.232.146.165` (SFO), Ubuntu 24.04, Docker, project at `/opt/juno`.
  Image: `mcr.microsoft.com/playwright/python:v1.63.0-noble`. 1 GB RAM (container ≈380 MiB, host ≈210 MB free);
  resize to 2 GB is pre-approved if needed. Plan: move to Hetzner when it outgrows the $6 box.
- Deploy: `scripts/deploy.sh root@165.232.146.165`. **Run it from a checkout that has `.env`**: it rsyncs with
  `--delete`, so a checkout without `.env` would delete the server's copy. Excludes `.claude/` (local worktrees).
  Copies `data/browser/*.json` if present.
  `data/assistant.sqlite3` on the server is the source of truth (links, nudge ledger, history, facts, usage counters).
- Secrets: Mac `.env` and server `/opt/juno/.env` only. Keys present: Canvas, Todoist, OpenAI, Telegram
  token + chat id. Google OAuth client at `data/google_credentials.json`, token at `data/google_token.json`
  (scopes: calendar read + events write). Ed uses the session token inside `data/browser/ed.json`.
- Accounts: OpenAI on Faith's personal account (not Stanford Edu). GitHub `FaithQin/juno`, private.
- Usage counters in `kv`: `requests:<day>`, `tokens_in:<day>`, `tokens_cached:<day>`, `tokens:<day>`.
- Matching state in `kv`: `gradescope_twins` ({gradescope id: canvas assignment id}, never pruned),
  `gradescope_match_declined` (["gs id:task id"] she said no to), `duplicates_declined`.
- Outlook: `OUTLOOK_ICS_URL` in both `.env`s (the published-calendar link; a secret). Job state in `kv`:
  `outlook_declined`, `outlook_gone`; links in `item_links` with kind `outlook_event`, `task_id` = `calendar_id|event_id`.
  The link was pasted into a Claude chat once; if Faith wants a fresh secret, unpublish and republish the calendar in Outlook
  and update both `.env`s.

## Standing rules
- **Every edit is reported.** Chat writes echo; scheduled and manual syncs text. `assistant sync` texts unless `--quiet`.
- **Corrections become facts.** When Faith corrects how juno works, juno saves it with `remember` unprompted (persona rule).
- **Session end:** update this file, add a `CHANGELOG.md` line, push (see `AGENTS.md`).

## Known warts
- Paperless (cs198) is an SSO-only login like Canvas was; it will expire on its own schedule and juno will ask for
  `browser-login paperless`. Gradescope has a year-long remember-me. Ed uses its stored token.
- One-shot `assistant chat` *inside the container* prints a harmless "Event loop is closed" notice after the answer.
- Chromium runs as root without its sandbox in the container. Hardening (unprivileged user + seccomp) is a todo.
- The p1/p2-anywhere rule pulls long capstone/application tasks into the nudges; Faith may want to narrow it.
- Ed's API is undocumented; the `x-token` header and endpoints are what the web app uses. Could change.
- `data/browser/canvas.json` still exists on the Mac and server; unused now, harmless.

## Next candidates (Faith decides)
1. The Canvas-side exact-title question (above).
2. A mixed answer to a multi-item match question ("yes to the first, no to the second"); today it's all or nothing.
3. Canvas API tools for the pages she names (grades, modules, files).
4. History window (above); a `/help` command listing what juno can do.
5. CS 106B course-site scrape (site was "under construction" on 2026-09-23).
6. iMessage via Photon: needs a Node sidecar (Photon has no HTTP send API) or a Python path.
7. Public repo: scrub Faith's email (assistant.yaml), ids (courses.yaml), personal details (RESEARCH/DECISIONS).
8. Chromium sandbox hardening; narrow the nudge rule.

## How to pick this up in a fresh session
1. `uv sync && uv run pytest` (expect 265 passing).
2. Read this file, then `DECISIONS.md`, then `docs/07-hardening.md`, `docs/08-outlook.md`, `docs/09-per-course-projects.md`, `docs/10-duplicates.md` and `docs/11-hand-made-and-twins.md`.
3. Check the server: `ssh root@165.232.146.165 'cd /opt/juno && docker compose ps && docker compose logs --tail=20 juno'`,
   and send `/status` in Telegram to see the cache share.
4. Ask Faith what's next; don't start a phase without her answers to its scoping questions.
