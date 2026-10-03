# Handoff — state as of 2026-10-02 (~23:40 PDT, after dropping MATSCI 88Q and EE 310)

Read `AGENTS.md` for the rules. This file is the live snapshot: what is running, what is pending,
what to do next. **Update it at the end of every working session.**

## What is live (verified on the server; last deploy `f10a52e`, 2026-10-02 ~23:28 PDT)
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
| Real browser (Playwright) | on demand | logins: gradescope, paperless (cs198, refreshed 2026-10-02), ed. **Canvas is never browsed** (API only); `browser_submit` asks first |
| **Outlook → Stanford calendar** | every 10 min | published Outlook ICS link in `.env`; new items (incl. tentative invites) proposed, yes copies with all details; `sync_now("outlook")`; `assistant outlook --print` |
| **Duplicate check** | after every hourly Canvas sync + "check for duplicates" | same-title / same-link / **Canvas-Gradescope twin** copies proposed for deletion (undoable, links move to the kept task, **her notes on a copy move to the kept task**). Keeps the task that ticks on submission (Gradescope over the Canvas half of a Gradescope assignment). The Canvas sync adopts exact-title matches; the Gradescope sync only shares tasks another sync follows. `docs/10-duplicates.md`, `docs/11-…` |
| **Todoist layout: one sub-project per class** | — | Classes (`6cXPJPmRH6GF2MPr`) holds only the 2 university deadlines; each course's tasks live in its sub-project (`project_id` in `courses.yaml`). **4 courses since 2026-10-02**: ENGR 40M, CME 102, EE 100, CS 106B. MATSCI 88Q (dropped Sep 30; its sub-project is empty) and EE 310 (dropped Oct 2; sub-project archived, 3 open tasks left there that Todoist leaves out of account-wide reads, so the brief and nudges don't see them) are out of `courses.yaml`. After the deploy: `assistant check` 4 × ok, 71 active tasks; dry-run sync read only the 4 sub-projects and the 3 Canvas courses, creates nothing |

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
- **Stale duplicates proposal blocking the queue (found 2026-10-02).** Asked 2026-09-28, never answered. It is wrong:
  it calls Faith's "Breakfast" tasks on consecutive days copies of each other, and her three "CME 102 Pset1: work
  block / finish + submit" tasks copies of "CME 102: Pset1 (Gradescope)" (they share the assignment link). All 6 task
  ids are no longer active. Proposals go one at a time, so nothing else (Outlook, Gradescope match questions) can be
  asked until it is answered. **Faith should reply "no to the duplicates one"** (records the pairs as declined, deletes
  nothing). The rule itself needs narrowing before it proposes again: a shared assignment link alone should not make
  two tasks copies, and same-title tasks on consecutive days are a daily habit, not a copy (`duplicates.find_duplicates`).
- **Next hourly sync will text a progress line labelled by task id** ("6hc6PpfWjfJMh5fr: 3/6 done (9. …, 10. Diodes,
  11. Solar Cells)") instead of the ENGR 40M quiz-batch title, seen in the 2026-10-02 dry run. Cosmetic.
- Sep 24 notes on the Outlook proposal, MATSCI 88Q duplicate groups and the CME Pset1 adoption line are superseded:
  MATSCI tasks are all gone, and 1 Outlook event is linked. Gradescope match-question status was not re-checked.
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
