# Research: what to learn from existing AI assistants

Compiled 2026-09-22 from five parallel research passes (Poke, messaging-first assistants and open-source frameworks, student/Canvas tools, location and channels, agent architecture). Items flagged *unverified* could not be confirmed against a primary source.

---

## 1. Landscape snapshot

### Poke (poke.com, Interaction Co., acquired by Cognition July 2026)
- Text-first assistant in Apple Messages (first Apple-approved AI agent on Messages for Business, June 2026), SMS, Telegram, RCS. Lost WhatsApp under Meta's general-purpose-chatbot ban.
- Core: Gmail/Outlook + Google/Outlook calendar. Plain-English "reminders" (cron triggers) and "automations" (event triggers). Shareable "recipes". Any MCP server as an integration. An inbound API (`POST /api/v1/inbound/api-message`) that drops arbitrary JSON into your thread, which is how one user built a running-late alert from iOS Shortcuts.
- Architecture (from a leaked system prompt and the OpenPoke reconstruction): a personality "Interaction Agent" is the only thing that talks to the user; it delegates to stateful execution agents with no personality. Inbound messages are tagged by type (user, automation, email, agent report, system). Rule: never act on automation or email content without prior human approval. A `wait` tool lets it silently discard low-value triggers. Texting style rules in the prompt: split on newlines into bubbles, mirror user length, no preamble, banned phrases.
- Cost to run was ~$50/user/month; pricing Free / $19 / $199.
- **Loved**: zero-friction, personality, morning brief, async multi-tasking, extensibility.
- **Hated**: timezone bugs (wrong weekday, reminders an hour late), noisy proactive pings (~7 in 10 useful), slow (15+ min for basic checks), multi-step chains ~60% success, no quiet hours, text thread as the only store, free tier exhausted in days.

### OpenClaw (open source, TypeScript, ~390k stars)
- Gateway daemon; channels for WhatsApp, Telegram, Signal, Discord, Slack, iMessage. Any LLM.
- Memory is plain Markdown: `SOUL.md` (persona), `USER.md` (dated preference directives, supersede in place), `MEMORY.md` (curated durable facts, loaded every session), `memory/YYYY-MM-DD.md` daily notes with hybrid search, a "dreaming" sweep that distills notes into MEMORY.md. Docs: reminders belong in the scheduler, not memory.
- Proactivity: cron for exact times; a "heartbeat" (default 30 min) runs a turn that replies `NO_REPLY` if nothing needs attention, with `activeHours`, light context, and flood guards.
- Went wrong: one-click RCE (CVE-2026-25253), ~21k exposed instances, plaintext credentials, 341 malicious marketplace skills, prompt-injection exfiltration demos, duplicate-delivery and DST bugs, $20 overnight on a heartbeat, $47 in 20 min from a group echo loop.

### Others
- **Martin**: SMS/WhatsApp/calls/Telegram; $21-49/mo; complaints about sign-in and calendar setup.
- **Dola → Toki**: WhatsApp channel killed by Meta's ban Feb 2026; now an app; ADHD users love that it phones you.
- **Lindy**: iMessage/SMS EA; draft-and-approve; documented silent failures ("confirmed as sent" emails that never went).
- **Catch, Pally, Notis, Arlo**: approval gates before anything big; chase unanswered threads.
- **ChatGPT Pulse** retired June 2026 into scheduled tasks; monitoring tasks notify only on change; tasks that send externally pause for approval. **Gemini scheduled actions**, **Claude scheduled tasks** (cloud runs while asleep), **Siri AI** (iOS 27, personal context, mostly pull).
- **nanobot** (Python, MIT, ~48k stars, ~4k-line core): Telegram/Discord/Slack/email, cron, memory, MCP. The best small Python codebase to study.
- **Khoj** (Python, AGPL): RAG second brain with scheduled automations.

### Student tools
- **Wick**: Canvas sync + twice-daily SMS; reviewers say the texts are the most useful feature and they rarely open the app; they add tasks by texting.
- **Coursicle** syllabus upload (editable preview before saving), **Dormway** (grading weights, late policy), **Shovel** (workload-fits-hours math), **MyStudyLife** (users want it to adapt automatically).
- GitHub: `scottquach/Canvas-Assignments-Transfer-For-Todoist` (dedups by title, so renames duplicate), `igcast648-rgb/Canvas-to-Notion-Sync` (stores Canvas ID and "reminders sent" in the target, 4/3/2/1h reminder ladder), `euntaek0127/canvas-notion-sync` (never un-checks manual completion), `vishalsachdev/canvas-mcp` (Python MCP server, 100+ tools, active), `X-isdoingreat/canvas-pilot` (scan → approve → execute gate). No Telegram/SMS Canvas bot with traction exists.
- Syllabus parsers: all LLM-based hobby repos; known failures are tables, missing year, rubric-vs-schedule duplicates, prose deadlines, scanned PDFs. Every credible tool has a review step before commit.

---

## 2. Patterns worth copying (ranked)

1. **Silence is a valid output.** Every good proactive system has a "nothing to say" path (OpenClaw `NO_REPLY`, Poke `wait`, ChatGPT monitoring tasks).
2. **One morning brief plus capped urgent interrupts.** Never push "new assignment" individually. Quiet hours in the user's timezone (Poke lacks them and users complain).
3. **Two schedulers.** Deterministic cron/APScheduler for sync and exact reminders (no LLM). A cheap, small-model "anything need attention?" check with a tiny state digest, skipped when the checklist is empty.
4. **Idempotent sync keyed on Canvas IDs.** Local table `canvas_id → todoist_id, gcal_id, content_hash`. Update, never recreate. Never un-check a task the user completed manually. Suppress submitted items. A `reminders_sent(idempotency_key)` ledger.
5. **Confirm side effects with a verbatim draft; treat 👍 as yes.** Auto-run read-only and self-owned task writes. Never act on content pulled from Canvas/email without approval.
6. **Separate the chat/personality agent from execution.** Keep tool noise out of the conversational context. Ack immediately, work in the background, post the result back to the same thread.
7. **Timezone discipline.** Store UTC, render local, inject "now + IANA tz" into the user turn (not the cached system prompt), test the DST week and day-of-week math.
8. **Memory as files plus SQLite.** `USER.md`-style dated directives (supersede, don't append), a daily log, a facts table with a `remember()` tool. Reminders live in the scheduler. No vector DB needed.
9. **Texting style in the prompt.** Short bubbles, mirror the user's length and case, no preamble, banned phrases, no emoji unless the user uses them.
10. **An inbound webhook.** Anything (Shortcuts, OwnTracks, GitHub Actions) can post into the assistant. This is how location gets in.
11. **Ship default recipes** so there is no blank canvas: morning brief, due-in-48h, exam week, leave-now.
12. **Model routing.** Cheap model for classification and heartbeat, strong model for chat and syllabus extraction. Poke's ~$50/user economics forced a sale.
13. **Syllabus parse with a mandatory review step.** Infer term/year, dedupe rubric vs schedule, show the list, then commit.
14. **Planner API as the primary Canvas feed** (cross-course to-do with submission status), ICS feed as the tokenless fallback.
15. **Name it.** A one-file persona and a name drive attachment more than any feature.

## 3. Things to avoid

- Title-based dedup; assuming token creation is allowed at your school; parallel Canvas calls (pre-flight throttling penalty); Todoist REST v2 samples (shut down Feb 2026).
- Google OAuth consent screen left in "Testing" (refresh tokens die after 7 days; set to "In production").
- WhatsApp Business API for a personal assistant (banned since Jan 2026).
- Frontier model on every poll; no spend cap; full-context heartbeats.
- Text thread as the system of record; Todoist and the calendar are truth.
- Plaintext secrets, anything bound beyond localhost, third-party skill marketplaces, a shell tool.
- Prompt injection via syllabi, Canvas descriptions, calendar invites, email: treat as untrusted data in delimited blocks; confirmation gates in code, not in the prompt.
- Silent wrong actions ("sent" that never sent); verify side effects and echo what was done.
- Anything that drafts or submits coursework.

---

## 4. Facts that shape the design

### Channels
| Channel | Push anytime | Cost | Friction | Notes |
|---|---|---|---|---|
| Telegram bot | Yes | Free | BotFather token; long polling needs no public URL | What hobbyists and OpenClaw docs recommend for v1 |
| iMessage via Photon | Yes | Free tier (shared number, up to 10 users); Pro $25/mo | Sign up, API key | Unofficial |
| iMessage via BlueBubbles | Yes | Free | Mac always on; macOS 26 issues | Uses your Apple ID |
| Twilio SMS (sole-prop 10DLC) | Yes | ~$0.012/segment + $1.15/mo number + ~$4 brand + $15 vetting + $2/mo | Campaign vetting days to weeks | Unregistered traffic blocked since 2023 |
| WhatsApp Cloud API | Templates only outside 24h | Per-conversation | Meta verification | General-purpose AI banned |
| Discord / Slack bot DM | Yes | Free | Low | Fine fallback |

### Location
| Method | Reliability | Battery | Notes |
|---|---|---|---|
| OwnTracks (HTTP mode, "significant" + geofences) | Good | Low | Open source; queues offline; iOS and Android |
| iOS Shortcuts automations | Weak alone | Low | Arrive/Leave/Time triggers; no periodic trigger; good redundant "left home" ping |
| Home Assistant Companion | Good | Low | Only if you run HA |
| Find My / Life360 / Maps Timeline | Fragile or dead | | Avoid |

Travel time: Mapbox Directions free to 100k req/mo with traffic; Google Routes if transit is needed (Pro tier 5k/mo free); Apple Maps Server API needs the $99 developer program.

Lateness logic used by Apple/Waze: within [start − 2h, start], take the latest fix, get ETA, alert once when now + ETA + buffer ≥ start, escalate once if still stationary 10 min later, suppress if already at the venue.

### Hosting
$4-6/mo VPS (Hetzner, DigitalOcean) is the student verdict. Mac at home with Cloudflare Tunnel or Tailscale Funnel is free but must stay awake. Railway Hobby $5 is the lowest-effort PaaS.

### Canvas API cheat sheet
- Token: Account → Settings → New Access Token (shown once). Institutions can restrict students; check first. Fallback: ICS feed URL from `GET /users/self/profile`.
- `GET /api/v1/planner/items?start_date&end_date&filter=incomplete_items`: cross-course feed with submission status and `planner_override.marked_complete`. Also `/users/self/todo`, `/users/self/upcoming_events`, `/users/self/missing_submissions`.
- `GET /courses/:id/assignments?include[]=submission&include[]=all_dates&bucket=upcoming&order_by=due_at`. `due_at` already reflects your section override.
- `GET /calendar_events?type=event|assignment&context_codes[]=course_N` (max 10 codes). Class meeting times exist only if the instructor set a timetable; otherwise enter manually or parse from the syllabus.
- `GET /courses/:id?include[]=syllabus_body` (HTML). PDFs via `/courses/:id/files?search_term=syllabus`. Syllabi often live in Modules/Pages instead.
- `GET /announcements?context_codes[]=course_1`.
- Pagination via `Link` headers (`canvasapi` 3.6.0 handles it). Throttling is cost-based; sequential calls are fine, parallel calls pay a pre-flight penalty.

### Todoist / Google Calendar
- Todoist unified API v1 only (`api.todoist.com/api/v1`); SDK `todoist-api-python` 4.0.0. No external-ID field: keep a local mapping table; optionally a `canvas:<id>` line in the description.
- Google Calendar: `extendedProperties.private.canvas_id` and `events.list?privateExtendedProperty=canvas_id=…`, or `events.import` with a deterministic `iCalUID`. Set the OAuth app to "In production".

### MCP servers that exist
Todoist official hosted (`https://ai.todoist.net/mcp`, OAuth) and local `@doist/todoist-mcp`; Google Calendar and Gmail official servers are Developer Preview only; Notion official hosted (GA); Canvas community `vishalsachdev/canvas-mcp` (Python, local). Tradeoff: the Anthropic MCP connector executes tools server-side, so your code loses the confirmation gate and audit log. Use plain Python tools for anything that writes.

### Framework
Thin loop on the Anthropic Python SDK tool runner (`@beta_tool` + `client.beta.messages.tool_runner`), SQLite, APScheduler 3.x, a Telegram adapter. LangGraph only for resumable multi-step workflows; Claude Agent SDK only if the agent should run scripts on your machine; OpenClaw is TypeScript and too large.

### Cost (Anthropic list prices, Sept 2026)
Assumptions: 40 messages/day, ~2.5 calls each, 48 heartbeats/day, hourly sync with no LLM.
| Design | ≈ $/month |
|---|---|
| Chat on Haiku 4.5 | ~12 |
| Chat on Sonnet 5 | ~25 |
| Chat on Opus 5 | ~60 |
| Heartbeats on Haiku/Sonnet, cached | 2-8 |
| Heartbeats on Opus, uncached | ~65 |

---

## 5. Security checklist
1. Secrets in the OS keychain (`keyring`) or a 600-perm `.env`, gitignored.
2. Narrowest OAuth scopes.
3. Canvas descriptions, syllabi, invites, emails are untrusted data in delimited blocks.
4. Operator instructions in `system`, never in user-turn text.
5. Confirmation gate for send/delete/message-someone implemented in code (tool-runner hook).
6. Allowlist one chat ID.
7. Nothing bound beyond localhost except the location webhook, which is authenticated.
8. No marketplace skills, no shell tool.
9. Audit-log every tool call.
10. Daily token budget and spend cap; log tokens per run.

---

## Sources (selected)
Poke: poke.com/docs, poke.com/docs/api, github.com/InteractionCo/mcp-server-template, shloked.com/writing/openpoke, techcrunch.com 2026-04-08 / 06-04 / 07-24, cognition.com/blog/interaction, blog.saner.ai/poke-reviews, agent-finder.co/reviews/poke, producthunt.com/products/poke-by-interaction-co.
OpenClaw: docs.openclaw.ai (heartbeat, memory, timezone, channels), en.wikipedia.org/wiki/OpenClaw, adversa.ai OpenClaw security 101, macstories.net Clawdbot story, github.com/openclaw/openclaw issues #72176 #88951 #125017 #146914.
Others: trymartin.com, toki.com, respond.io WhatsApp ban, usecarly.com Lindy review, catchagent.ai, pally.com, techcrunch.com ChatGPT Pulse, blog.google Gemini scheduled actions, xda-developers.com Claude scheduled tasks, apple.com/newsroom Siri AI, github.com/HKUDS/nanobot, github.com/khoj-ai/khoj.
Student: App Store pages for Wick and Shovel, coursicle.com syllabus posts, github repos listed above, canvas.instructure.com/doc/api (planner, assignments, calendar_events, throttling, pagination, oauth), developer.todoist.com/api/v1, groups.google.com Doist shutdown notice, developers.google.com OAuth2 and Calendar references.
Location/channels: owntracks.org/booklet, companion.home-assistant.io, support.apple.com Shortcuts and Time to Leave, support.google.com Waze planned drives, developers.google.com Routes pricing, docs.mapbox.com, twilio.com A2P 10DLC docs, photon.codes/pricing, loopmessage.com, sendblue.com, BlueBubbles issues #761 #776, developers.facebook.com WhatsApp pricing, core.telegram.org/bots/faq, hetzner/digitalocean/fly/railway pricing pages, tailscale.com Funnel, developers.cloudflare.com Tunnel.
Architecture: github.com/Doist/todoist-mcp, developers.google.com Calendar and Gmail MCP guides, github.com/vishalsachdev/canvas-mcp, platform.claude.com MCP connector and prompt caching, mem0.ai reminder-agent post, github.com/dominicci13/personal-ai-assistant, apscheduler docs, docs.slack.dev lazy listeners, oasis.security and esecurityplanet OpenClaw incidents, labs.cloudsecurityalliance.org indirect prompt injection note.
