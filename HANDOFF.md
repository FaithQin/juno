# Handoff — state as of 2026-09-24 (late evening, Pacific)

Read `AGENTS.md` for the rules. This file is the live snapshot: what is running, what is pending,
what to do next. **Update it at the end of every working session.**

## What is live (all verified on the server)
| Piece | Cadence | Notes |
|---|---|---|
| Canvas → Todoist sync | hourly | adopted 52 hand-made tasks on 2026-09-22; batches same-day quizzes |
| Gradescope → Todoist | every 3 h | via saved browser login; first run approved 2026-09-24 |
| Canvas events → Stanford calendar | hourly | first run **proposal pending in Telegram** (see below) |
| Nudges: 8pm the evening before, 2h before | scan every 10 min | late ones say "i was offline" |
| Morning brief | 07:00 daily | every dated Todoist task + calendars Stanford/TA/primary/StartX/Cal.com |
| Telegram chat (`gpt-6-sol`, low reasoning) | on message | tasks, events, web, browser, Ed, `sync_now`, undo, `/status` |
| Completion tracking | with each sync | submitted work ticks the task; quizzes done inside a batch get a ✅ on their checklist line (first one marked 2026-09-24: "3. Current + KCL") |
| Real browser (Playwright) | on demand | logins: gradescope, paperless (cs198), ed, canvas; `browser_submit` asks first |

## Pending right now
- **Calendar first-run proposal** sent to Telegram 2026-09-24: 9 SystemX seminar dates matched to
  hand-made "EE 310" events, plus Nov 26 (Thanksgiving) as new. Faith replies yes/no in Telegram.
  If yes and the Nov 26 seminar is actually cancelled: "delete the nov 26 systemx seminar".
- Nothing else pending.

## Infrastructure
- Server: DigitalOcean droplet `165.232.146.165` (SFO), Ubuntu 24.04, Docker, project at `/opt/juno`.
  Image: `mcr.microsoft.com/playwright/python:v1.63.0-noble`. 1 GB RAM (≈470 MB free with Chromium up);
  resize to 2 GB is pre-approved if needed. Plan: move to Hetzner when it outgrows the $6 box.
- Deploy: `scripts/deploy.sh root@165.232.146.165` from Faith's Mac. Copies `.env` and `data/browser/*.json`.
  `data/assistant.sqlite3` on the server is the source of truth (links, nudge ledger, history, facts).
- Secrets: Mac `.env` and server `/opt/juno/.env` only. Keys present: Canvas, Todoist, OpenAI, Telegram
  token + chat id. Google OAuth client at `data/google_credentials.json`, token at `data/google_token.json`
  (scopes: calendar read + events write). Ed uses the session token inside `data/browser/ed.json`.
- Accounts: OpenAI on Faith's personal account (not Stanford Edu). GitHub `FaithQin/juno`, private.

## Standing rules added today
- **Every edit is reported.** Chat writes echo; scheduled and manual syncs text. `assistant sync` texts unless `--quiet`.
- **Session end:** update this file, add a `CHANGELOG.md` line, push (see `AGENTS.md`).

## Known warts
- One-shot `assistant chat` *inside the container* prints a harmless "Event loop is closed" notice
  after the answer (py3.12 finalizer order). The always-on process never shows it.
- Chromium runs as root without its sandbox in the container. Hardening (unprivileged user + seccomp) is a todo.
- The p1/p2-anywhere rule pulls long capstone/application tasks into the nudges; Faith may want to narrow it.
- Ed's API is undocumented; the `x-token` header and endpoints are what the web app uses. Could change.

## Next candidates (Faith decides)
1. CS 106B course-site scrape (site was still "under construction" on 2026-09-23).
2. iMessage via Photon: needs a Node sidecar (Photon has no HTTP send API) or a Python path.
3. Public repo: scrub Faith's email (assistant.yaml), ids (courses.yaml), personal details (RESEARCH/DECISIONS).
4. Chromium sandbox hardening; narrow the nudge rule; a `/help` command listing what juno can do.

## How to pick this up in a fresh session
1. `uv sync && uv run pytest` (expect 141 passing).
2. Read this file, then `DECISIONS.md`, then the latest `docs/0N-*.md`.
3. Check the server: `ssh root@165.232.146.165 'cd /opt/juno && docker compose ps && docker compose logs --tail=20 juno'`.
4. Ask Faith what's next; don't start a phase without her answers to its scoping questions.
