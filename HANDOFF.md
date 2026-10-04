# Handoff — state as of 2026-10-03 (~22:30 PDT, after replies, colors, planned work and the class changes)

Read `AGENTS.md` for the rules. This file is the live snapshot: what is running, what is pending,
what to do next. **Update it at the end of every working session.**

## What is live (verified on the server; last deploy `d59c991`, 2026-10-03 22:17 PDT)
| Piece | Cadence | Notes |
|---|---|---|
| Canvas → Todoist sync | hourly | adopted 52 hand-made tasks on 2026-09-22; batches same-day quizzes; retries transient errors |
| Gradescope → Todoist | every 3 h | via saved browser login; first run approved 2026-09-24; proposals asked once. **New:** an assignment that plausibly is a hand-made task (same course + number + pre/post/lab/pset words + due within 2 days) is **asked about** (`gradescope_match`), held back until she answers; yes links, no creates. `docs/11-hand-made-and-twins.md` |
| **Canvas ↔ Gradescope twins** | with both syncs | a Canvas external tool names its Gradescope assignment (`custom_gradescope_resource_id`); both ids now link to one task, whichever side comes first. Pairings kept in `kv["gradescope_twins"]` (written by the Canvas sync) |
| Canvas events → Stanford calendar | hourly | first-run proposal **re-asked once** at the next run (see Pending) |
| Nudges: 8pm the evening before, 2h before | scan every 10 min | late ones say "i was offline"; a Todoist blip skips one scan quietly. **Planned work** (a Todoist deadline field, a duration, or "block" in the title) gets **one heads-up 10 min before a timed start** instead ("starting 3:00pm: … (1h · deadline thu)"). **Audited classes get none.** |
| Morning brief | 07:00 daily | every dated Todoist task + calendars Stanford/TA/primary/StartX/Cal.com; waits ~10 min through a Todoist outage, then says so. Sections: **due today** (incl. planned work whose Todoist deadline is today) / **planned today** / due tomorrow / overdue ("planned fri" for missed plans); audit tasks tagged "(audit)" |
| Telegram chat (`gpt-6-sol`, low reasoning) | on message | tasks, events, web, browser, Ed, `sync_now`, undo, photos, `answer_proposal`, `/status`. **Since 2026-10-03:** a Telegram reply carries the quoted message; a reply yes/no to a proposal's message answers it; every text juno sends on its own is kept in the conversation (`telegram:outbox` stream); web citations stripped unless she asks for sources; `get_tasks` lists due and planned separately; `add_task` takes `duration_minutes` + `deadline` for work blocks; `color_event` and `add_event(color=)` with her scheme applied automatically |
| Completion tracking | with each sync | submitted work ticks the task; quizzes done inside a batch get a ✅ on their checklist line |
| Real browser (Playwright) | on demand | logins: gradescope, paperless (cs198, refreshed 2026-10-02), ed. **Canvas is never browsed** (API only); `browser_submit` asks first |
| **Outlook → Stanford calendar** | every 10 min | published Outlook ICS link in `.env`; new items (incl. tentative invites) proposed, yes copies with all details; `sync_now("outlook")`; `assistant outlook --print` |
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
- **Duplicates question for Faith (expected 2026-10-03 ~23:03 PDT, the first hourly check after the deploy).** The deployed
  rule finds exactly two pairs among her 280 active tasks (read-only check), and that question replaces the stale Sep 28
  one (Breakfast / CME Pset1 work blocks, all 6 tasks done). Both are pairs she chose to be asked about:
  - "ENGR 40M: Lab 1 prelab (Gradescope)" (hers, with notes, due Sun Oct 4 11am) as a copy of "ENGR 40M: Prelab 1
    (Gradescope)" (made 2026-10-03 17:28 PDT by a sync, linked to Gradescope 8769171, not adopted, due Mon Oct 5 6pm). Yes
    keeps the linked one and moves her notes onto it; her Sunday 11am date is lost (the kept task keeps Mon 6pm).
    **Unchecked:** why the Gradescope match question (`gradescope_match`) didn't ask about her "Lab 1 prelab" before
    this twin was made. Its rule (same number, pre+lab words, due within 2 days) should have paired them; her task was
    edited at 21:42 PDT, so its title or date may have been different at 17:28. Worth a look before the next lab.
  - "EE 160A: HW1 (due Fri Oct 9, week 3)" (made 2026-10-03 21:33 PDT, undated, with notes) as a copy of "EE 160A: HW1
    (Gradescope)" (Oct 1, due Fri Oct 9 11:59pm). Neither is synced (EE 160A has been in `courses.yaml` since the 2026-10-03
    22:17 deploy, but it has no Canvas or Gradescope site to sync from); the older is kept.
  Both pairs appeared within minutes of each other on Oct 3 ~21:30–21:42 PDT, while someone was editing these tasks
  (likely Faith or another assistant), so she may already be mid-cleanup. Outlook and Gradescope-match questions still
  queue behind this one until she answers.
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
0. Let juno change its own class list from chat ("add EE 101A as a class") instead of the class check pointing at
   `courses.yaml`; and color Canvas/Outlook copies with the scheme too, if she wants.
1. The Canvas-side exact-title question (above).
2. A mixed answer to a multi-item question ("yes to the first, no to the second"); today it's all or nothing, for
   match and duplicates questions alike (tonight's duplicates question has two pairs).
3. Canvas API tools for the pages she names (grades, modules, files).
4. History window (above); a `/help` command listing what juno can do.
5. CS 106B course-site scrape (site was "under construction" on 2026-09-23).
6. iMessage via Photon: needs a Node sidecar (Photon has no HTTP send API) or a Python path.
7. Public repo: scrub Faith's email (assistant.yaml), ids (courses.yaml), personal details (RESEARCH/DECISIONS).
8. Chromium sandbox hardening; narrow the nudge rule.

## How to pick this up in a fresh session
1. `uv sync && uv run pytest` (expect 303 passing).
2. Read this file, then `DECISIONS.md`, then `docs/07-hardening.md`, `docs/08-outlook.md`, `docs/09-per-course-projects.md`, `docs/10-duplicates.md`, `docs/11-hand-made-and-twins.md` and `docs/12-replies-colors-planned-classes.md`.
3. Check the server: `ssh root@165.232.146.165 'cd /opt/juno && docker compose ps && docker compose logs --tail=20 juno'`,
   and send `/status` in Telegram to see the cache share.
4. Ask Faith what's next; don't start a phase without her answers to its scoping questions.
