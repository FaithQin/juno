# Walkthrough 5: Gradescope sync and Ed announcements

Two integrations with opposite shapes. Gradescope has no API, so juno's browser visits
it every few hours and a parser reads the page. Ed has an API, so a single request
replaces a five-page browser trip.

## Gradescope: the same engine, one new rule

`gradescope.py` turns two pages into data: the dashboard (course cards, matched to your
course codes by comparing "CME 102" with "F26-CME-102-01/ENGR-155A-01" after stripping
punctuation) and a course page (the assignments table). Before you submit, a row is a
`<button data-assignment-id>`; after, it's a link to your submission. Due dates come from
`<time datetime>` elements; a second one is the late deadline.

Each assignment becomes the same `CanvasItem` the Canvas sync uses, with `kind="gradescope"`,
and goes through the same `plan_sync` → `apply_plan` engine: identity by Gradescope id,
update never recreate, tick the task when Gradescope shows a submission, and the naming
convention already in your Classes project: `CME 102: Pset1 (Gradescope)`.

**The first run is a proposal.** Your hand-made Gradescope tasks have no link to match on,
and the research was clear that matching by title silently creates duplicates on renames.
So the first run matches by course plus title, then texts you:

```
gradescope: i found 3 open assignments across 2 courses.
looks like tasks you already have:
- Pset1 → CME 102: Pset 1 (Gradescope)
new (i'd add these to todoist):
- MATSCI 88Q: Pre-Lab 2 (Gradescope), due mon oct 5 12:00pm
reply yes to link and add, or no to skip
```

Your "yes" records the links and creates the new tasks; from then on the job creates and
texts, like Canvas. A "no" is remembered by a fingerprint of what was proposed, so juno
only asks again when Gradescope actually changes. Any other message leaves the proposal
waiting; it's answered by the next yes or no.

The plumbing for that is `ChatSession.propose_job` / `job_handlers`: a scheduled job
leaves a proposal in the store, and the next yes/no in chat routes to the job's
`approve()`. It's separate from the browser_submit approval, which pauses a model run.

If Gradescope logs juno out, the job texts the re-login command once a day and does
nothing else until the session is refreshed.

## Ed: the API is undocumented but stable

`ed.py` calls the two endpoints the Ed web app itself uses: `GET /api/user` for your
courses and `GET /api/courses/<id>/threads` for posts. Posts are stored as XML-ish markup
(`<document><paragraph>…`), flattened to text with link targets kept. The
`ed_announcements` tool returns announcements and pinned posts, newest first, with links,
and the persona tells juno to try it before browsing Ed.

Token: Stanford's SSO setup hides Ed's API-token page, so juno uses the token the Ed web
app itself stores in browser local storage, which `browser-login ed` captures in
`data/browser/ed.json`. That token is sent as an `x-token` header (a settings-page token
would use `Bearer`). Re-running `browser-login ed` refreshes it. `ED_API_TOKEN` in `.env`
is only for the case where the settings page does offer a token.

## Reading the code

1. `gradescope.py` — parsers with fixtures modeled on the real markup (`tests/test_gradescope.py`).
2. `sync.py` — `links_in` now knows Gradescope URLs; `adopt_by_title` is the first-run matcher.
3. `gradescope_sync.py` — the job: fetch, adopt, propose or sync, approve.
4. `chat.py` — `propose_job`, `_answer_job`, `job_handlers`.
5. `ed.py` — client, `document_to_text`, `format_announcements`.
