# 07 · A day of real use: what broke, what it cost, what juno couldn't see

Phase 6 shipped late on 2026-09-24. Faith used juno all day. This walkthrough covers the fixes
that day of use asked for. None of them is a new feature in the product sense; all of them are
the difference between a demo and an assistant you keep.

## 1. "why do you keep sending that": proposals are asked once

The calendar sync's first run proposes instead of writing: "9 events look like ones you already
have, 1 is new, yes or no?" It ran hourly, and every hour it sent the question again, because
nothing remembered that the question was already out. Same shape in the Gradescope job.

Now `Store.propose_job` records the question and when it was asked, `Store.pending_job` reads it
back, and both jobs check first: same proposal (same digest of the item ids) already pending →
say nothing. Canvas adds an event → the digest changes → a new question, once.

## 2. A stray "ok" is not an answer to a 20-hour-old question

`ChatSession.handle` used to check the pending proposal before anything else, so any bare
"yes", "ok", "sure", "wait" or "please", hours later, in the middle of an unrelated chat, would
have linked ten calendar events. The rule now: a bare yes/no answers a job's proposal only while
that proposal is the last thing said (`Store.has_messages_after`). After other chat, the proposal
stays pending, its text is quoted in the model's context, and a new tool, `answer_proposal`, lets
juno act when Faith clearly means it ("yes go ahead with the canvas calendar thing"). A tool
waiting on approval (`browser_submit`) is always the most recent question, so it is checked first.

## 3. Todoist answered 503 at 07:00 and the brief never went out

Both the morning brief and the nudge scan crashed on transient Todoist errors (503, then 502).
`retry.py` is small: `is_transient` recognises 5xx, 429, dropped connections and canvasapi's
folded-in status codes; `retrying` runs a blocking call on a worker thread and sleeps through a
list of delays on those errors only. The brief waits about ten minutes (5s, 20s, 1m, 3m, 5m), then
texts one line saying Todoist is down; a nudge scan retries twice and quietly leaves it for the
next scan; the hourly sync retries twice. A 401 or a bug still raises at once: those need a human.

## 4. $5 in a day: what a request actually contained

The numbers from the server's own records, for the last request of 2026-09-24:

| | |
|---|---|
| input tokens | 56,360 |
| written to OpenAI's cache | 56,292 |
| read from the cache | 0 |
| cost of that one request | $0.14 |

Every request wrote the whole prompt to the prompt cache and never read it back. The reason was
one line: the live context block started with `now: thu sep 24, 2:05pm`, which changes every
minute, and instructions come *before* the history in the prompt. A cache hit needs an identical
prefix, so the minute rolling over invalidated persona, tools and the whole day's history.

Three changes, in order of effect:

1. **The clock rides on her message.** Each user message is stored as `[thu sep 24, 2:05pm] hi`.
   The instructions (persona, timezone, courses, facts) no longer change from one request to the
   next. Measured on the Mac right after the change: 73% of input tokens served from the cache
   across four requests, including the second request of the very first turn.
2. **Previous turns are re-sent as conversation only.** `compact_previous_turns` strips tool
   calls, tool output and the model's encrypted reasoning from turns that are over; only what she
   said and what juno answered remain. Reasoning was the largest single part of stored history
   (77 KB of 134 KB), and the provider replays and bills it. A response whose tool call is still
   waiting on her yes/no is kept whole, because the provider needs that call and the reasoning
   that led to it, byte for byte. Kept text loses its provider id so it is replayed as plain text.
3. **Two model settings.** `openai_reasoning_context="current_turn"` tells OpenAI not to carry
   earlier turns' reasoning forward at all; `openai_prompt_cache_key="juno"` groups requests so
   the shared prefix is routed to the same cache.

`/status` now ends with `model today: N requests, X tokens in, Y% from cache`, so the effect is
visible without opening the OpenAI dashboard. What is *not* changed: the 24-hour history window
and the last-three-tool-outputs rule inside a turn. Shortening the window is a product choice
(see DECISIONS).

## 5. Photos

Telegram photos were silently dropped: there was no handler. Now `filters.PHOTO` routes to
`_on_photo`, which downloads the largest rendition and hands the brain the caption plus a
`BinaryContent` image. `ChatSession.handle(text, images=...)` sends both as one user message.
In history, the last three photo-bearing messages keep their pixels ("compare the pictures
above"); older photos become the note `[photo she sent, no longer attached]`. Verified against
the real model with a rendered section sign-up table: juno listed the three rows back.

## 6. Canvas through the API, never the browser

Faith had to log in to Canvas again the next day. The saved Canvas login is Stanford SSO's
session cookies (`canvas_session`, `__Host-shib_idp_session`): they last until Canvas or the IdP
decides they don't, roughly a day. Gradescope stays logged in because it sets a year-long
`remember_me`. juno never needed the Canvas web pages: the API token feeds `get_tasks`,
`get_schedule` and `read_link`. `ChatOps.browse` now sends any Canvas URL through `read_link`
(assignments, pages, quizzes, discussions) or answers with a pointer to the right tool, and the
persona says so. No more Canvas re-logins, and no more "checking Canvas" for the calendar.
Paperless is the other SSO-only login and will expire the same way; juno asks for a re-login
when it does.

## Reading the code

1. `retry.py` — `is_transient`, `describe_briefly`, `retrying`; used by `jobs.py`.
2. `db.py` — `pending_job`, `propose_job`, `has_messages_after`.
3. `chat.py` — `compact_previous_turns`, `_stamp`, `_job_is_fresh`, `handle(text, images=)`.
4. `channels/telegram.py` — `_on_photo`, `_handle`.
5. `chat_ops.py` — `browse` (Canvas branch), `answer_proposal`, `context_block`.
6. `tests/test_retry.py`, `tests/test_history_trim.py`, the photo tests in `tests/test_telegram.py` and `tests/test_agent.py`.
