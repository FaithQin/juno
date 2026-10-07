# 14 · Repeating and all-day events

Faith, 2026-10-06, after juno told her "i can't create recurring events from here": "fix that next".
Her ask that hit the wall was a weekly all-day "[class] PSET DUE" event in tomato on Stanford, so
two things were missing, not one: `add_event` only took a start *time*, so it couldn't make an
all-day event either.

## 1. How Google does it

A repeating event in Google Calendar is **one** event with a rule attached (RFC 5545):

```
RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;UNTIL=20261212T075959Z
```

Google expands it into occurrences when you list events (`singleEvents=True`), and each occurrence
carries `recurringEventId`, the id of the series. So "every week" is never 10 copies: delete the
series id and every occurrence goes; delete an occurrence id and only that week goes.

An all-day event uses `{"date": "2026-10-08"}` instead of `{"dateTime": …}`, and Google's `end`
date is *exclusive*: a one-day event on Oct 8 ends on Oct 9. `gcal.event_body` hides that: give it a
`date` and an inclusive last day, and it writes the exclusive end itself.

## 2. The model never writes the rule

`recurrence.py` builds it from plain fields the model passes to `add_event`:

| field | example | notes |
|---|---|---|
| `repeat` | `"weekly"` | daily, weekly, monthly, yearly; anything else is an error back to the model |
| `every` | `2` | every other week |
| `days` | `["mon", "wed"]` | weekly only; "Wednesday", "weds", "we" all read as WE |
| `until` | `"2026-11-19"` | the last day it may happen, inclusive |
| `count` | `6` | instead of until, never both |

Checking fields in code, not trusting a model-written RRULE, is the same rule as everywhere in juno:
writes go through code gates. A typo ("FREQ=WEEKY") would otherwise be a silent failure or a
calendar full of wrong events.

Two details worth knowing:

- **UNTIL for a timed event is a UTC instant.** "Until Nov 19" means the end of Nov 19 where she is,
  11:59:59pm Pacific, which is `20261120T075959Z` (after daylight time ends). For an all-day event
  it's just the date, `20261211`.
- **The first occurrence is moved onto her weekdays.** Google counts the start itself as an occurrence
  even when it isn't one of the `days`, so "mon and wed, starting today (thu)" would put a stray event
  on thursday. `first_on` moves the start to the first matching day.

## 3. Every repeat ends

Faith chose (2026-10-06): **with no end given, a repeat stops at the end of the quarter.** The dates
live in `assistant.yaml` as `calendar.quarter_ends` (the last day of end-quarter exams, from
Stanford's 2026-27 academic calendar: Dec 11, Mar 19, Jun 9, Aug 14). `recurrence.finish` picks the
first one on or after the first occurrence, so an event starting in winter break runs to the end of
winter quarter. If juno doesn't know the quarter (next year, until someone adds the dates), it asks
"how long should it repeat?" rather than repeating forever. The echo says which: "every week until
fri dec 11, the end of the quarter".

## 4. Taking it back

- `undo` right after deletes the series (the id `add_event` logged is the series id).
- `delete_event(query, all_occurrences=True)` deletes the whole series. Before deleting, it reads the
  series' own body from Google (`get_event` on `recurringEventId`), keeps the fields that define it
  (summary, times, recurrence, color, …) and logs them, so `undo` recreates it, rule and all.
- Without `all_occurrences`, deleting removes one occurrence, as before. Deleting a one-off all-day
  event and undoing it now brings it back as all-day (it used to come back as midnight to 1am).

## Reading the code

1. `recurrence.py` — `plan`, `first_on`, `finish`, `rrule`, `describe`.
2. `gcal.event_body` — dates, the exclusive end, `recurrence`.
3. `chat_ops.add_event` (`_parse_point`, `_event_when`), `delete_event(all_occurrences=)`, the
   `delete_event` branch of `undo`. `agent.py` documents the new arguments for the model.
4. `config.py` (`CalendarSyncConfig.quarter_ends`), `assistant.yaml`, `app.py` passes them to `ChatOps`.
5. Tests: `test_recurring.py`.
