# Changelog

## 2026-09-24
- Phase 5: Canvas events → Stanford calendar (first run proposes, matches hand-made events by day/time/course);
  chat tools add_event, move_event, delete_event, delete_task, all undoable.
- Phase 4: Gradescope → Todoist sync via the saved browser login (first run proposed and approved);
  Ed announcements through Ed's API using the web session token; `edit_task`.
- Fixed "too many steps": old tool output is trimmed from history before each model request.
- Browser: start lock (no double Chromium), continuous session save in `browser-login`, cs198 host for Paperless.

## 2026-09-23
- Phase 3: real browser (Playwright) with numbered-ref snapshots; `browser_submit` gated by approval;
  saved logins for Gradescope, Paperless, Ed, Canvas made on the Mac and shipped by deploy.
- Phase 2.5: `read_link` (public pages + Canvas via API, untrusted-data framing) and OpenAI native web search.
- Deployed to a DigitalOcean droplet in Docker; `/status` command; persona hot-reload; Poke-style bubbles.
- Phase 2 live: Telegram chat, nudges (8pm eve, 2h), 07:00 brief, facts memory, undo; Google Calendar OAuth.

## 2026-09-22
- Research on Poke, OpenClaw, student tools, channels, architecture → `RESEARCH.md`; 20 scoping decisions → `DECISIONS.md`.
- Phase 1: Canvas → Todoist sync, idempotent by Canvas id, adopting 52 hand-made tasks; 12 tests.
- Phase 2 built (Telegram, nudges, brief) pending accounts.
