# Changelog

## 2026-10-02
- Dropped courses removed from `courses.yaml`: MATSCI 88Q (dropped Sep 30) and EE 310 (dropped Oct 2). Their Canvas
  courses no longer sync, so nothing gets written to the EE 310 sub-project, which is now archived in Todoist.
  `test_config` asserts neither code is in the repo config (test written first, failed, then passed). 263 passed,
  2 skipped. Not deployed yet.
- Paperless (cs198) login refreshed by Faith from the terminal and shipped (rsync one file + restart).

## 2026-09-27
- Paperless (cs198) login refreshed and shipped; HANDOFF records the re-login routine (rsync one file + restart, not a full deploy).

## 2026-09-24 (late night, last)
- Gradescope: a new assignment that plausibly is a task Faith wrote herself (same course, number, pre/post/lab/pset
  words, due within 2 days; "PSET 1" = "Pset1" = "Problem Set 1") is asked about once over Telegram and held back
  meanwhile; yes links it (her title/notes/date kept, date differences mentioned), no creates it as before. Exact-title
  hand-made matches are asked too; `adopt_same_title` on the Gradescope side only shares tasks another sync follows.
- Canvas external tools that open a Gradescope assignment (MATSCI 88Q, CME 102) are linked to the same task by id
  (`custom_gradescope_resource_id`), from either side; no more Canvas/Gradescope twins.
- Duplicate check sees those twins, keeps the Gradescope-linked task, and carries notes from a deleted copy onto it.
  Before this, the queued proposal would have deleted her hand-made Lab 1 tasks (with notes) and kept a twin.
- `deploy.sh` excludes `.claude/`. `docs/11-hand-made-and-twins.md`. 265 tests. Deployed `ad55a1c`; check ok,
  dry-run sync: only the CME 102 Pset1 twin link.

## 2026-09-24 (late night, later still)
- Duplicate tasks: after every Canvas sync (and on "check for duplicates") juno finds same-title / same-link twins in a
  project and proposes deleting the copies (undoable; links move to the kept task). Both syncs now adopt an existing
  task with the exact same title instead of creating a twin, which is how the two MATSCI 88Q pairs happened.
  `docs/10-duplicates.md`.

## 2026-09-24 (night, latest)
- Each class is now its own Todoist sub-project under Classes (Faith's ask). juno reads class tasks from Classes plus
  every course sub-project (task ids survive a move, so nothing is re-created or wrongly closed; syncs read strictly, chat and
  nudges skip one unreadable sub-project but still see a Todoist outage), files new Canvas/Gradescope/chat tasks into the course sub-project with no
  section, attributes a task's course by sub-project first and old section second, and `assistant check` reports each
  sub-project. A course without `project_id` keeps the old section layout. Gradescope's legacy section is now created
  once, not once per run. Undo of a delete from an old section restores into the course sub-project.
  Reviewed by three agents; a draft "heal" rule was dropped because it would re-tick reopened tasks.
  `docs/09-per-course-projects.md`. 230 tests.
- Deployed `03aba64` and moved Faith's Todoist over: 68 open + 5 completed class tasks into their sub-projects (same ids),
  6 old sections deleted. Server check afterwards: 70 active tasks, 0 legacy sections, dry-run sync "nothing to change".

## 2026-09-24 (night, later)
- Phase 7: Outlook meetings → Google Calendar from a published Outlook calendar link (ICS), every 10 min: new items
  (incl. tentative invites) proposed over Telegram, matched against hand-made events, series copied with their rules,
  moves patched, disappearances reported once; `sync_now(source="outlook")`; `uv run assistant outlook --print`.
  `docs/08-outlook.md`. One proposal at a time across jobs (the second waits). Paperless login refreshed and shipped.

## 2026-09-24 (night)
- Cost: the clock moved from the instructions onto each user message so OpenAI's prompt cache hits (measured 73% of
  input from cache right after); previous turns are re-sent without tool traffic or reasoning; `openai_reasoning_context`
  current_turn and a prompt cache key; `/status` shows today's requests, input tokens and cache share.
- Proposals (calendar, gradescope) are asked once instead of every run; a stale bare "ok" no longer approves one;
  `answer_proposal` tool and the pending question in the model's context.
- Transient Todoist/Canvas errors are retried (`retry.py`); the morning brief waits ~10 min then texts one line.
- Telegram photos reach the model as images (older photos thin out of history).
- Canvas links go through the API, never the browser (no more daily Canvas re-logins); persona: learn from corrections.
- Docs: `docs/07-hardening.md`. Tests: 167.

## 2026-09-24
- Phase 6: completion tracking inside batch tasks (✅ per submitted quiz, "progress" notes), `sync_now` chat tool
  ("i finished quiz 3" → check Canvas/Gradescope now), manual `assistant sync` texts its changes; standing rule that
  every edit is reported. Cross-tool context files: AGENTS.md, HANDOFF.md, CHANGELOG.md.
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
