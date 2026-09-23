# Personal AI Agent

juno: a school assistant that grows into a general one. Python 3.12+, managed with `uv`.

- `RESEARCH.md` — what Poke, OpenClaw, Wick and friends get right and wrong, and the API facts this design rests on.
- `DECISIONS.md` — every choice made before building, and the defaults you can flip.
- `docs/01-canvas-sync.md`, `docs/02-juno.md` — one walkthrough per phase, written to teach.
- `CLAUDE.md` — how to work in this repo (TDD, always).

## What runs

| Piece | When | Needs the LLM? |
|---|---|---|
| Canvas → Todoist sync | hourly | no |
| Due-date nudges (8pm the evening before, 2h before) | every 10 min | no |
| Morning brief (classes, events, due today/tomorrow, overdue) | 7:00 daily | no |
| Chat over Telegram: what's due, add/complete/move a task, snooze, remember, undo | when you text | yes (gpt-6-sol) |

## Setup, once

### 1. Canvas and Todoist (done)

```bash
cp .env.example .env && chmod 600 .env
```

`CANVAS_TOKEN`: Canvas → Account → Settings → *+ New Access Token*.
`TODOIST_TOKEN`: Todoist → Settings → Integrations → Developer.

### 2. OpenAI

platform.openai.com → API keys → create. Add a few dollars of credit. Paste as `OPENAI_API_KEY`.

### 3. Telegram

1. In Telegram, message **@BotFather**, send `/newbot`, pick a name (juno) and a username. Copy the token into `TELEGRAM_BOT_TOKEN`.
2. Leave `TELEGRAM_CHAT_IDS` empty and start juno:

```bash
uv run assistant run
```

3. Open your bot in Telegram and send `/start`. It replies with your chat id. Put that in `TELEGRAM_CHAT_IDS`, restart. Every other chat is ignored silently.

### 4. Google Calendar (read events for the brief; write comes in phase 3)

1. console.cloud.google.com → new project (any name) → *APIs & Services* → *Enable APIs* → **Google Calendar API**.
2. *OAuth consent screen* → External → fill the app name and your email → add yourself as a test user → **Publish** the app (so the token doesn't expire every 7 days; the "unverified app" warning is fine for personal use).
3. *Credentials* → *Create credentials* → **OAuth client ID** → Desktop app → download the JSON.
4. Save it as `data/google_credentials.json`, then:

```bash
uv run assistant gcal-auth
```

A browser opens once. The token is saved to `data/google_token.json` and refreshes itself.

### 5. Install and test

```bash
uv sync && uv run pytest
```

## Run

Everything together (Telegram polling, hourly sync, nudges, brief):

```bash
uv run assistant run
```

Useful on their own:

```bash
uv run assistant sync --dry-run -v     # what the sync would change
uv run assistant chat "what's due this week"   # talk to juno from the terminal
uv run assistant brief                 # print today's brief
uv run assistant nudges                # what would fire right now
uv run assistant check                 # Todoist connection and sections
```

Until the VPS (phase 7), `run` only works while this Mac is awake. Nudges missed while asleep are sent late with an honest note, never dropped.

## Layout

```
assistant.yaml          name, models, brief time, calendars, cadences
courses.yaml            Canvas courses → Todoist sections
persona.md              juno's voice (static; cacheable by the provider)
.env                    secrets (never committed)
data/                   sqlite db, Google token (never committed)
src/assistant/
  config.py             .env + yaml
  canvas_client.py      Canvas → CanvasItem
  todoist_client.py     thin wrapper over the official SDK
  gcal.py               Google Calendar OAuth + reads
  db.py                 SQLite: links, tasks, facts, history, nudges, undo
  sync.py               plan (pure) → apply → report          [phase 1]
  tasks.py              course inference, DueTask, fuzzy match
  reminders.py          nudge planner (pure)
  brief.py              morning brief (pure)
  chat_ops.py           what juno can do (act, echo, undo)
  agent.py              pydantic-ai tools over ChatOps
  chat.py               conversation persistence
  jobs.py               the three scheduled jobs
  scheduler.py          APScheduler wiring
  channels/telegram.py  allowlist, setup mode, send
  app.py                builds the real runtime
  cli.py                commands
tests/                  fakes for everything; no network
```

## Phases

1. Canvas → Todoist sync ✅
2. Telegram chat, add-task-by-text, nudges, morning brief, facts memory, undo ✅ (needs your OpenAI + Telegram + Google setup to go live)
3. Canvas calendar events → Google Calendar; CS 106B site scrape
4. Syllabus parsing with approval
5. OwnTracks location, running-late alerts
6. Gradescope scraper (if email + password login works)
7. Deploy: Docker on a VPS
8. iMessage channel via Photon (needs a Node sidecar or a Python send path)
