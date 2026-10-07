# 12 · Replies, colors, planned work, sources, and her class changes

Faith, 2026-10-03, after a week of use: understand a reply to an earlier message, set colors on
calendar events, tell "due dates" apart from scheduled work blocks, don't attach sources unless
asked, and make sure juno knows about her class changes. Each part below is small; together they
are the difference between juno sounding like it remembers the conversation and not.

## 1. Answering an earlier message

**Telegram replies.** When she uses Telegram's reply on a message, the update carries
`reply_to_message` (and `quote` if she highlighted part of it). `channels/telegram.reply_of`
turns that into a `Reply` (text, whether juno sent it, when), and `ChatSession` puts it in front of
her words: `[sat oct 3, 2:10pm] (replying to your message from fri 8:00pm: "due tomorrow 11:59pm:
CME 102: Pset 2") push it to sunday`. The model knows which task "it" is.

**juno's own texts are part of the conversation.** Nudges, the brief, sync notes and proposals
are sent by scheduled jobs, outside any chat turn, so the model never saw them: "done" after a
nudge meant nothing to it. Now every proactive text goes through `notify` in `app.py`, which sends
it and records it as one of juno's lines (`record_sent`) in a second stream, `telegram:outbox`.
`ChatSession._history` reads both streams in the order they were saved; pydantic-ai folds juno's
back-to-back lines into one turn, so the history stays valid. The outbox lives in its own stream
on purpose: whether a proposal is "fresh" (a bare yes answers it) asks whether *chat* happened
after it, and a nudge in between shouldn't change that.

**Replying yes/no to a proposal answers it,** however old. Normally a bare "yes" answers a job's
proposal only while it is the last thing said (`docs/07-hardening.md` §2). A reply to the
proposal's own message is unambiguous, so `_proposal_reply` answers it directly.

**…but only the question that is waiting now (fixed 2026-10-04).** A job replaces its own question
when what it found changes (`Store.proposal_slot` returns "free" for a new digest): the Sep 28
duplicates question (Breakfast, CME Pset1 work blocks) was replaced on Oct 3 by one about ENGR 40M
and EE 160A. Questions of one kind share lines: every duplicates question starts "todoist: 2 pairs
look like duplicates." and ends "reply yes to delete the copies…". Matching on text alone, a yes to
a line quoted from the *old* message would have deleted the tasks in the *new* one. So the reply
is placed in time first: Telegram stamps every message (`Reply.sent_at`), and the job's `asked_at`
says when the waiting question went out (the job stamps it just before sending, so its own
message is never earlier; `CLOCK_SKEW`, 30 s, covers the two clocks disagreeing).

| her reply is to… | `_proposal_reply` | a bare yes/no | anything else |
|---|---|---|---|
| the waiting question's message (shares its text, sent at or after `asked_at`) | `current` | answers it, in code | the model, which may answer it |
| an older juno message that shares a line with it (an earlier version) | `replaced` | "nothing done: that question was replaced on …", then the current question as its own message, in code | the model, but `answer_proposal` is shut for this turn |
| any other message from before `asked_at` | `earlier` | the model, `answer_proposal` shut | the model, `answer_proposal` shut |
| a message with no timestamp | `None` | the model asks | the model |

The out-of-date answer never reaches the model, so it can't be read as a yes to the new question
(Faith chose this, 2026-10-04). The current question is resent as its own bubble so that replying
to it lands in the first row. The gate on `answer_proposal` (`_answer_from_model`) is the same idea
for everything the code can't decide: a reply is about the message it replies to, and a message
from before the question was asked can't be answering it; the tool tells the model so, and the
model tells her nothing was done.

## 2. Sources only when she asks

OpenAI's web search glues citations onto answers: ` ([medlineplus.gov](https://…?utm_source=openai))`.
Telegram shows them raw. `tidy_reply` removes them from what she reads, unless her message asks for
sources ("sources?", "link?", "where did you get that"), in which case they become plain links. The
`utm_source=openai` marker is what makes this safe: a sign-up link she asked for has no such marker
and is never touched. The stored history keeps the original text, so a later "sources?" can be
answered from it.

## 3. Event colors

Google has eleven event colors addressed by id; the names (Flamingo, Grape, Tomato…) exist only in
its UI. `colors.color_id` accepts those names and plain words ("pink", "green", "default").

Her scheme, read from her Stanford calendar that day: classes and sections Flamingo, audited
classes Grape, exams Tomato. She chose to have juno apply it automatically, so `ColorScheme.pick`
reads the kind of event from its title (an exam word first, then an audited course code or the
word "audit", then a graded course code) and `add_event` uses it unless she names a color. It
lives in `assistant.yaml` (`calendar.colors`). Against her next 30 days of events it agreed on
107 of 109; the two misses were social events she colored Banana by hand, which the scheme leaves
alone. Synced copies (Canvas, Outlook) keep the calendar default.

*Update 2026-10-06 (`docs/15-classes-and-holds.md`):* auditing ended, so there is no audit color any
more, and `HOLD: <Name> (<Org>)` events are Graphite and never recolored.

`color_event` recolors one occurrence, or with `all_occurrences` the whole series: an occurrence
carries `recurringEventId`, and patching that id changes every occurrence. Setting the default
sends `colorId: null`, which Google's patch semantics treat as "clear". Undo restores the old color;
a deleted event comes back with its color.

## 4. Planned work vs deadlines

Todoist's due date is overloaded: for an assignment it's the deadline, for "CME 102 Pset 2: work
block" it's when she'll work. Her account already says which: 149 of 280 tasks carry a duration and
42 carry Todoist's own deadline field (the planning convention her other assistants use). So
`tasks.due_task_from` sorts every task, in this order:

1. Todoist deadline field set → **planned**: she said where the deadline is, so the due date is her plan.
2. tracked by a sync (Canvas/Gradescope) → **due**: an assignment's date is a deadline.
3. a duration, or "block" in the title → **planned**. Anything else → **due**.

`DueTask` carries `kind`, `duration_min` and `deadline`, and everything downstream uses them:

- **Nudges** (her choice): planned work with a start time gets one heads-up 10 minutes before
  ("starting 3:00pm: CME 102 Pset 2: work block (1h · deadline thu)") instead of "due tomorrow" and
  "due in 2h". Its key includes the date, so a recurring block gets one each time it recurs.
- **Brief**: "due today" (deadlines, including planned work whose Todoist deadline is today),
  "planned today", "due tomorrow", and overdue items labelled "(planned fri)" when they were plans.
- **Chat** `get_tasks`: separate due and planned lists; the persona says "planned for 3pm", never "due".
- **Creating a block**: `add_task` takes `duration_minutes` and `deadline`, so a block juno
  schedules is recognisable as one.

## 5. Her class changes

`courses.yaml` now says everything: graded classes (ENGR 40M, CME 102, EE 100, CS 106B, and EE 160A,
added), audits (`audit: true`: EE 227 with alias CS 227A, EE 260A, AA 274A with alias AA 174A) and a
`dropped:` list (MATSCI 88Q, EE 310). Audits are known for chat, Ed and their Todoist projects, but
`by_canvas_id()` and the Gradescope sync skip them and `nudge_tasks()` leaves them out; the brief tags
their tasks "(audit)". The context block tells the model which is which, and aliases resolve ("cs 227a"
→ EE 227).

*Update 2026-10-06 (`docs/15-classes-and-holds.md`):* the audits ended; EE 227, EE 260A and AA 274A
moved to `dropped:` with `audit: true`, and EE 160A got its Canvas site (231155) and the aliases
AA 174A and CS 137A.

A YAML lesson on the way: the dropped date was first written `on: 2026-09-30`, and PyYAML read the key
`on` as the boolean `true` (YAML 1.1 treats on/off/yes/no as booleans). The field is `dropped_on`.

**The class check** (`course_watch.py`, daily 9:30) is what would have caught this drift: it compares
Canvas enrollments and the projects under Classes with `courses.yaml` and texts once about each
difference (a course Canvas lists that juno doesn't know, a Todoist class project no course owns, a
synced course Canvas no longer lists). juno can't edit its own configuration, so the text says where
the list lives. Against her real accounts after this change it finds nothing.

## Reading the code

1. `chat.py` — `Reply`, `tidy_reply`, `record_sent`, `ChatSession.note_sent / _reply_note / _proposal_reply / _out_of_date / _answer_from_model`.
2. `channels/telegram.py` — `reply_of`. `app.py` — `notify`, `course_kwargs`, `color_scheme`, the class check job.
3. `colors.py`; `chat_ops.add_event / color_event` and the `color_event` undo.
4. `tasks.due_task_from`, `reminders.plan_nudges` (the `start` kind), `brief.format_brief`, `jobs.run_brief_job`.
5. `config.py` (`audit`, `aliases`, `DroppedCourse`), `course_watch.py`.
6. Tests: `test_replies.py`, `test_colors.py`, `test_blocks.py`, `test_classes.py`.
