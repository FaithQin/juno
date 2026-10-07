# 08 · Outlook meetings → Google Calendar

> **Changed 2026-10-06:** new items are now added without asking, and a heads-up goes out 30 minutes
> before each Outlook meeting. Why and how: `docs/13-outlook-auto-add-and-projects.md`.

Faith's ask, verbatim: "check if a meeting has been sent to my outlook, ask me to confirm it,
and if I confirm, populate the meeting with all the information onto my gcal."

## The access path, and why it isn't the Microsoft API

Three ways to see an Outlook calendar from outside: the Microsoft Graph API (needs an app
registration and a consent Stanford's tenant may refuse, plus tokens that expire), the browser
with a saved login (Stanford SSO session cookies die within a day, as Canvas taught us), or the
**published calendar link**: Outlook web → gear → Calendar → Shared calendars → Publish a
calendar → an ICS URL. The last one is a plain HTTPS GET, needs no registration and never
expires; the URL itself is the secret, so it lives in `.env` as `OUTLOOK_ICS_URL` and nowhere
else. Faith checked that Stanford allows publishing; that settled it.

One fact makes the feed enough: Outlook puts an invite on the calendar as *tentative* the moment
it arrives. So "a meeting was sent to me" and "a meeting is on my Outlook calendar" are the same
thing in the feed, distinguished by `X-MICROSOFT-CDO-BUSYSTATUS` (TENTATIVE vs BUSY vs FREE).
Attendees are not in a published feed; that's fine, because Google would *email* attendees of a
copied event, and this copy is hers alone.

## Parsing the feed (`parse_ics`)

The `icalendar` library does the heavy lifting: line folding, escaping, and the Windows
timezone names Outlook uses ("Pacific Standard Time", "Eastern Standard Time") via the VTIMEZONE
blocks in the feed. Every time is converted to Faith's timezone at parse time; the absolute
instant is what matters, and Google gets `America/Los_Angeles`.

Three shapes come out of one feed:

- **A single event.** UID, title, start, end, location, description (Teams/Zoom links live
  there), busy status.
- **A series master** with an `RRULE` and possibly `EXDATE`s. The rule is copied to Google as
  is, with `UNTIL` normalised to UTC the way Google requires.
- **An occurrence Outlook moved**: a second VEVENT with the same UID and a `RECURRENCE-ID`. It
  becomes a stand-alone event (`uid#original-start`) and the master gets an `EXDATE` for the
  original slot. An occurrence edited but *not* moved (notes changed, same time) is dropped:
  the series still covers it.

`in_window` keeps the next 120 days plus yesterday. A series stays as long as it hasn't ended,
however long ago it began; her calendar feed has a year of history and 185 events, of which 8
were upcoming the night this shipped.

## Proposing, matching, copying (`OutlookSync`)

Same protocol as the Canvas calendar job: nothing is written until she says yes.

1. Every run fetches the feed, then handles what is already linked: a changed title or time is
   patched on Google and texted ("moved 1: …"); a single event that vanished from Outlook is
   reported once and left on Google (syncs never delete).
2. Unlinked, undeclined items are matched against her existing Google events across the brief's
   calendars, with the same narrow matcher the Canvas job uses (same day, within an hour, a
   shared title word). A series is matched before its occurrences, so her hand-made weekly copy
   links to the series rather than to one moved instance. On the first real run 6 of 6 upcoming
   items matched hand-made events: she had been copying them by hand.
3. What remains is one proposal: "looks like ones you already have: …" and "new (i'd add to
   Stanford): …", asked once (same digest → silence) until she answers. **Yes** links the
   matches (and tags the hand-made events with the Outlook UID) and creates the new ones on the
   Stanford calendar with title, time, location, description, recurrence and a "from outlook"
   note. **No** remembers those UIDs; only genuinely new meetings are asked about afterwards.

Identity is the Outlook UID, hashed to a 60-bit integer because `item_links` keys on ints. The
link's `task_id` is `calendar_id|event_id`, since a match can live on any of her calendars.

## In chat

"check outlook" → `sync_now(source="outlook")` runs the job immediately and returns the
proposal text. The yes/no goes through the same `answer_proposal` path as every other job.

## Reading the code

1. `outlook_sync.py` — `parse_ics`, `in_window`, `outlook_body`, `OutlookSync.run` / `approve`.
2. `app.py` — `build_outlook_sync`: the one real GET; the job is registered only when the URL is set.
3. `tests/test_outlook.py` — an Outlook-shaped fixture with two timezones, a series, a moved occurrence, an all-day event.
4. `uv run assistant outlook --print` — run it once by hand and read the proposal before letting the scheduler text it.
