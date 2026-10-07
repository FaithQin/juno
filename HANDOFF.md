# Handoff — state as of 2026-10-06 (~17:45 PDT, after Outlook auto-add and tasks outside classes)

Read `AGENTS.md` for the rules. This file is the live snapshot: what is running, what is pending,
what to do next. **Update it at the end of every working session.**

## What is live (verified on the server; last deploy `2f7ca39`, 2026-10-06 17:17 PDT)
| Piece | Cadence | Notes |
|---|---|---|
| Canvas → Todoist sync | hourly | adopted 52 hand-made tasks on 2026-09-22; batches same-day quizzes; retries transient errors |
| Gradescope → Todoist | every 3 h | via saved browser login; first run approved 2026-09-24; proposals asked once. **New:** an assignment that plausibly is a hand-made task (same course + number + pre/post/lab/pset words + due within 2 days) is **asked about** (`gradescope_match`), held back until she answers; yes links, no creates. `docs/11-hand-made-and-twins.md` |
| **Canvas ↔ Gradescope twins** | with both syncs | a Canvas external tool names its Gradescope assignment (`custom_gradescope_resource_id`); both ids now link to one task, whichever side comes first. Pairings kept in `kv["gradescope_twins"]` (written by the Canvas sync) |
| Canvas events → Stanford calendar | hourly | first-run proposal **re-asked once** at the next run (see Pending) |
| Nudges: 8pm the evening before, 2h before | scan every 10 min | late ones say "i was offline"; a Todoist blip skips one scan quietly. **Planned work** (a Todoist deadline field, a duration, or "block" in the title) gets **one heads-up 10 min before a timed start** instead ("starting 3:00pm: … (1h · deadline thu)"). **Audited classes get none.** |
| Morning brief | 07:00 daily | every dated Todoist task + calendars Stanford/TA/primary/StartX/Cal.com; waits ~10 min through a Todoist outage, then says so. Sections: **due today** (incl. planned work whose Todoist deadline is today) / **planned today** / due tomorrow / overdue ("planned fri" for missed plans); audit tasks tagged "(audit)" |
| Telegram chat (`gpt-6-sol`, low reasoning) | on message | tasks, events, web, browser, Ed, `sync_now`, undo, photos, `answer_proposal`, `/status`. **Since 2026-10-03:** a Telegram reply carries the quoted message; a reply yes/no to a proposal's message answers it, **only if that message was sent after the waiting question was asked** (a reply to an older, replaced question gets "nothing done: that question was replaced on …" + the current one, in code; 2026-10-04); every text juno sends on its own is kept in the conversation (`telegram:outbox` stream); web citations stripped unless she asks for sources; `get_tasks` lists due and planned separately; `add_task` takes `duration_minutes` + `deadline` for work blocks, and (2026-10-06) a `project` for tasks outside her classes ("one-off tasks", "ssig"; without one it asks which); `color_event` and `add_event(color=)` with her scheme applied automatically |
| Completion tracking | with each sync | submitted work ticks the task; quizzes done inside a batch get a ✅ on their checklist line |
| Real browser (Playwright) | on demand | logins: gradescope, paperless (cs198, refreshed 2026-10-02), ed. **Canvas is never browsed** (API only); `browser_submit` asks first |
| **Outlook → Stanford calendar** | every 10 min | published Outlook ICS link in `.env`. **Since 2026-10-06:** new items (incl. tentative invites) are **added without asking** and juno texts what it added or linked; items she said no to before stay off; ended meetings skipped; **heads-up 30 min before each Outlook meeting** (read from Google, so series and her own copies work). Never waits on another question. `sync_now("outlook")`; `assistant outlook --print`. `docs/13-outlook-auto-add-and-projects.md` |
| **Duplicate check** | after every hourly Canvas sync + "check for duplicates" | proposed for deletion (undoable, links and **her notes** move to the kept task); keeps the task that ticks on submission. **Narrowed 2026-10-03:** same title in a project with due dates ≤ 1 day apart, *except* the same clock time on different days (a habit); a shared assignment link only with the same title or both names just the assignment's name reworded (`assignment_named`: "Lab 1 prelab" = "Prelab 1", work blocks never); Canvas-Gradescope twins by id. A pending duplicates question it no longer finds withdraws itself. `docs/10-duplicates.md` §4, `docs/11-…` |
| **Classes** (`courses.yaml`, 2026-10-03) | — | **Graded:** ENGR 40M, CME 102, EE 100 (synced from Canvas), CS 106B (Paperless/Gradescope; its Canvas site is empty), **EE 160A** (added; no Canvas/Gradescope/Ed site yet). **Audits** (`audit: true`: known for chat/Ed/Todoist, never synced, never nudged): EE 227 (alias CS 227A), EE 260A, AA 274A (alias AA 174A, no Todoist project). **Dropped:** MATSCI 88Q (Sep 30), EE 310 (Oct 2; its archived project still holds 3 open tasks, invisible to juno). Each class's tasks live in its sub-project under Classes (`6cXPJPmRH6GF2MPr`). After the deploy: `assistant check` 7 sub-projects ok + AA 274A "audit, no Todoist project", 95 active class tasks; dry-run sync read only the 3 graded Canvas courses, "nothing to change" |
| **Class check** | daily 09:30 | texts once about a Canvas course or a Todoist project under Classes that `courses.yaml` doesn't know, or a synced course Canvas no longer lists; quiet when nothing changed (it found nothing on 2026-10-03). `course_watch.py`; state `kv["course_watch_seen"]` |
| **Event colors** | when juno adds an event | her scheme from `assistant.yaml` `calendar.colors`: classes/sections flamingo, audits grape, exams tomato, else default; agreed with 107 of her next 109 Stanford events (the 2 misses: social events she colored banana by hand). Canvas/Outlook copies stay default |

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
- **2026-10-06 incident: the Human Capital interview (Tue Oct 6, 1:45pm, a tentative Outlook invite) never reached Faith.**
  The Outlook job could only *ask*, and its question had waited silently behind an unanswered duplicates question since
  Sep 28; the brief and nudges never read Outlook. Fixed in code (auto-add + 30-min heads-up, Faith's choice); see
  `docs/13-outlook-auto-add-and-projects.md`. **Deployed `2f7ca39` 2026-10-06 17:17 PDT** and redeployed with the fix below. **First live adds, 17:18 PDT**,
  came from her chat "check everywhere" (`sync_now("all")`, a quiet run): copied the two ChemE colloquiums (Oct 12, Oct 19),
  linked "Faith Qin and Monroe Kennedy" → her "ARMLab interview" and "Faith + Nathan // Intro Call" → her own
  "Faith + Nathan // Intro Call (Andrews Cooper)" (made on Google that afternoon). The model never relayed that list, so
  adds and moves are now **always texted**, quiet or not (`run()`); 315 tests.
  First run after deploy (read-only preview at ~17:20 PDT): links "Faith Qin and Monroe Kennedy" (Wed Oct 7 2pm) to her
  "ARMLab interview: Prof. Kennedy (ME 191)", adds "ChemE Colloquium…" Mon Oct 12 and Mon Oct 19 4:30pm (tentative).
  "Faith + Nathan // Intro Call" (Wed Oct 7 1:30pm): she had said no to it in an earlier batch; on 2026-10-06 she asked
  for it, so its uid was taken off `outlook_declined` (10 → 9) just before the deploy and the first run copies it too.
- **"Try out Instinct"** was added to One-Off Tasks (due Oct 6) by hand via the Todoist MCP, at her request; juno had
  answered "which course is that for?" twice that morning.
- **Duplicates question still waiting** (replaced again 2026-10-04 21:39Z, now 1 pair): "EE 160A: HW1 (due Fri Oct 9,
  week 3)" as a copy of "EE 160A: HW1 (Gradescope)". Gradescope-match and Canvas-calendar questions still queue behind
  it **silently** (Outlook no longer does). The ENGR 40M prelab pair from Oct 3 is gone from it (resolved by hand?).
  **Unchecked:** why `gradescope_match` didn't ask about her "Lab 1 prelab" before the Gradescope twin was made on Oct 3.
- **Reply gap closed (2026-10-04, `05d654c`, deployed):** a Telegram reply answers the waiting question only if the
  replied-to message was sent at or after its `asked_at`; a yes/no to an older version gets "nothing done: that question
  was replaced on …" plus the current one; any reply to an earlier message can't call `answer_proposal`. Faith asked
  about the cost of that wide block on 2026-10-06 and chose to keep it.
- **Verify on the next proactive text** (e.g. the 07:00 brief on Sun Oct 4): rows appear in `messages` with
  `conversation_id = 'telegram:outbox'`, and a reply to that text in Telegram arrives as "(replying to your message from …)".
  Both are covered by tests; neither has happened live yet. First planned-work heads-up expected Sun Oct 4 10:50am
  ("ENGR 40M: Lab 1 prelab", planned 11am, deadline Mon).
- The progress-line note from 2026-10-02 is resolved: only `sync --dry-run` labelled a batch by task id (real syncs
  always fetched the title); dry runs now read the title too. The ENGR 40M batch's progress was applied by a real sync.
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
  Copies `data/browser/*.json` if present, **with `--update` since 2026-10-03**: juno rewrites the server's
  `gradescope.json` as it browses, so the Mac copy is usually older and must not replace it.
  `data/assistant.sqlite3` on the server is the source of truth (links, nudge ledger, history, facts, usage counters).
  The host has no `sqlite3` CLI: read the database with `docker compose exec -T juno python -c "import sqlite3; …"`.
- Deploy hiccup 2026-10-04: the first `deploy.sh` run hung >10 min in the code rsync (ssh connected, the remote rsync
  never started, nothing changed on the server). Killed and re-run, it finished in ~30 s. If it happens again, check
  `ps` on the server for `rsync --server`; none means it's safe to kill and retry.
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
0. **No silent queue.** Gradescope-match and Canvas-calendar questions still wait without a word behind another
   question; at least the brief should say "a question is waiting since …" (the Outlook incident's second cause).
1. Let juno change its own class list from chat ("add EE 101A as a class"); color Canvas/Outlook copies with her scheme.
2. The Canvas-side exact-title question (Pending, older notes).
3. A mixed answer to a multi-item question ("yes to the first, no to the second"); today it's all or nothing.
4. Canvas API tools for the pages she names (grades, modules, files).
5. History window; a `/help` command listing what juno can do.
6. CS 106B course-site scrape; iMessage via Photon; public-repo scrub; Chromium sandbox hardening; narrow the nudge rule.

## How to pick this up in a fresh session
1. `uv sync && uv run pytest` (expect 315 passing).
2. Read this file, then `DECISIONS.md`, then `docs/07-hardening.md`, `docs/08-outlook.md`, `docs/09-per-course-projects.md`, `docs/10-duplicates.md`, `docs/11-hand-made-and-twins.md` and `docs/12-replies-colors-planned-classes.md`.
3. Check the server: `ssh root@165.232.146.165 'cd /opt/juno && docker compose ps && docker compose logs --tail=20 juno'`,
   and send `/status` in Telegram to see the cache share.
4. Ask Faith what's next; don't start a phase without her answers to its scoping questions.
