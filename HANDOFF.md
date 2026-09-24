# Handoff — state as of 2026-09-24 (night, Pacific)

Read `AGENTS.md` for the rules. This file is the live snapshot: what is running, what is pending,
what to do next. **Update it at the end of every working session.**

## What is live (all verified on the server, deployed 2026-09-24 ~14:30 PDT)
| Piece | Cadence | Notes |
|---|---|---|
| Canvas → Todoist sync | hourly | adopted 52 hand-made tasks on 2026-09-22; batches same-day quizzes; retries transient errors |
| Gradescope → Todoist | every 3 h | via saved browser login; first run approved 2026-09-24; proposals asked once |
| Canvas events → Stanford calendar | hourly | first-run proposal **re-asked once** at the next run (see Pending) |
| Nudges: 8pm the evening before, 2h before | scan every 10 min | late ones say "i was offline"; a Todoist blip skips one scan quietly |
| Morning brief | 07:00 daily | every dated Todoist task + calendars Stanford/TA/primary/StartX/Cal.com; waits ~10 min through a Todoist outage, then says so |
| Telegram chat (`gpt-6-sol`, low reasoning) | on message | tasks, events, web, browser, Ed, `sync_now`, undo, **photos**, `answer_proposal`, `/status` (now with today's token use and cache share) |
| Completion tracking | with each sync | submitted work ticks the task; quizzes done inside a batch get a ✅ on their checklist line |
| Real browser (Playwright) | on demand | logins: gradescope, paperless (cs198), ed. **Canvas is never browsed** (API only); `browser_submit` asks first |

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
- **Calendar first-run proposal.** The old record (no question text) was cleared at deploy; the
  hourly job re-asks **once** at its next run (~15:30 PDT 2026-09-24): 9 SystemX seminar dates
  matched to hand-made "EE 310" events plus Nov 26 as new. Faith replies yes/no right away, or
  later with "yes to the calendar thing" (juno uses `answer_proposal`). If Nov 26 is cancelled:
  "delete the nov 26 systemx seminar".
- **Faith to decide: history window.** Still 24 h (`ChatSession.window`). With caching and
  compaction it is much cheaper than before; shortening to ~6 h would cut a little more at the
  cost of juno forgetting the morning by evening. Recommendation: leave it, check `/status` for a
  few days first.
- **Faith to decide: Outlook meetings → Google Calendar** (her ask; not started). Scoping questions:
  1. Access path. (A) Microsoft Graph with her own OAuth consent (device-code flow, delegated
     `Mail.Read`/`Calendars.Read`); needs an app registration, and Stanford's tenant may block
     consent to unverified apps. (B) An Outlook rule that forwards meeting invites to a Gmail
     address juno reads via the Gmail API (same OAuth style as the calendar; no Microsoft admin
     involved). (C) The browser with a saved outlook.office.com login (SSO session cookies; would
     expire like Canvas). Recommend trying A, falling back to B.
  2. Which meetings: new invites addressed to her (the ask as written), or everything on her
     Outlook calendar (then it's a mirror, not an inbox check)?
  3. Which Google calendar they land on (primary?), and whether juno should also accept the
     invite in Outlook or only copy it.
  4. Cadence (every 10 min like nudges?) and whether declined invites are remembered by id.
- **Mac main checkout is behind.** This session pushed from a worktree; run `git pull` in
  `Second Brain/1 - Projects/Personal AI Agent` before the next session there.

## Infrastructure
- Server: DigitalOcean droplet `165.232.146.165` (SFO), Ubuntu 24.04, Docker, project at `/opt/juno`.
  Image: `mcr.microsoft.com/playwright/python:v1.63.0-noble`. 1 GB RAM (container ≈380 MiB, host ≈210 MB free);
  resize to 2 GB is pre-approved if needed. Plan: move to Hetzner when it outgrows the $6 box.
- Deploy: `scripts/deploy.sh root@165.232.146.165`. **Run it from a checkout that has `.env`**: it rsyncs with
  `--delete`, so a checkout without `.env` would delete the server's copy. Copies `data/browser/*.json` if present.
  `data/assistant.sqlite3` on the server is the source of truth (links, nudge ledger, history, facts, usage counters).
- Secrets: Mac `.env` and server `/opt/juno/.env` only. Keys present: Canvas, Todoist, OpenAI, Telegram
  token + chat id. Google OAuth client at `data/google_credentials.json`, token at `data/google_token.json`
  (scopes: calendar read + events write). Ed uses the session token inside `data/browser/ed.json`.
- Accounts: OpenAI on Faith's personal account (not Stanford Edu). GitHub `FaithQin/juno`, private.
- Usage counters in `kv`: `requests:<day>`, `tokens_in:<day>`, `tokens_cached:<day>`, `tokens:<day>`.

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
1. Outlook → Google Calendar (questions above).
2. History window (above); a `/help` command listing what juno can do.
3. CS 106B course-site scrape (site was "under construction" on 2026-09-23).
4. iMessage via Photon: needs a Node sidecar (Photon has no HTTP send API) or a Python path.
5. Public repo: scrub Faith's email (assistant.yaml), ids (courses.yaml), personal details (RESEARCH/DECISIONS).
6. Chromium sandbox hardening; narrow the nudge rule.

## How to pick this up in a fresh session
1. `uv sync && uv run pytest` (expect 167 passing).
2. Read this file, then `DECISIONS.md`, then `docs/07-hardening.md`.
3. Check the server: `ssh root@165.232.146.165 'cd /opt/juno && docker compose ps && docker compose logs --tail=20 juno'`,
   and send `/status` in Telegram to see the cache share.
4. Ask Faith what's next; don't start a phase without her answers to its scoping questions.
