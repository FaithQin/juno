# Walkthrough 4: a real browser

`read_link` fetches a page the way `curl` does: no JavaScript, no login. That covers most
public pages and Canvas via the API, and nothing behind Stanford's login. This phase gives
juno an actual Chromium it can drive: open, read, click, type, select, submit.

## Logins are yours, not juno's

Stanford logins end in a Duo push to your phone, so a browser on a server can never log in
by itself. Instead, you log in once on your Mac and hand juno the result:

```bash
uv run assistant browser-login gradescope      # also: paperless, ed, canvas
```

A real browser window opens on the login page. You log in, Duo and all, then press Enter
in the terminal. Playwright saves the browser's *storage state* (cookies and local storage)
to `data/browser/gradescope.json`. `scripts/deploy.sh` ships those files to the server on
every deploy, and juno uses them until the site logs it out, at which point a snapshot
says "login needed" and juno tells you to run the command again. Between logins: weeks
for Gradescope and Ed, days for Canvas, it varies.

`uv run assistant browser-check` opens each site with its saved session and reports
"logged in" or "LOGIN NEEDED".

## How the model sees a page: snapshots and refs

The model never sees HTML. `BrowserSession.snapshot()` runs one piece of JavaScript in the
page that finds every visible interactive element (links, buttons, inputs, selects) and
tags each with a `data-juno-ref` number, then returns the page's visible text framed as
untrusted data plus a numbered list:

```
[1] link "Homework 1" → https://www.gradescope.com/courses/1/assignments/9
[2] textbox "Search"
[3] button "Submit" (submits)
```

The model acts by number: `browser_click(1)`, `browser_type(2, "hw1")`. Because the
number is written onto the element itself, a later click finds exactly that element even
if the page shifted. Every action returns a fresh snapshot, and refs are only valid until
the next one.

This is the same shape browser agents like Playwright MCP use, built from a hundred lines
we control rather than a dependency.

## The gate: submitting asks first

`browser_click` is free. `browser_submit` is declared with `requires_approval=True`, which
makes pydantic-ai *pause the run* and hand back a `DeferredToolRequests` instead of an
answer. `ChatSession` turns that into a text ("about to click "Sign up" on Lab section
sign-up. reply yes to go ahead or no to skip"), remembers the pending call, and on your
next message resumes the same run with an approval or a denial. Any other message denies
it and moves on. The tests in `tests/test_approval.py` walk through all three paths.

Two consequences: juno can fill an entire form autonomously and stop exactly at the
button, and nothing a web page says can make that button get pressed.

## Memory on a 1 GB server

One Chromium process, one browser context per site (so cookies don't mix), one page open
at a time. A scheduled job closes the page after ten idle minutes, which releases most of
Chromium's memory; contexts and cookies stay. If the droplet still runs out, the plan is
the 2 GB size.

The Docker image switched to Microsoft's Playwright image, which ships Chromium and its
system libraries; its tag must match the `playwright` version in `pyproject.toml`.

## What juno must never do in a browser

- Type a password. The persona forbids it, and no tool is needed to enforce it: your
  passwords are not in juno's context anywhere.
- Follow instructions found on a page. Same rule as `read_link`: page text is data.
- Open private network addresses. The same URL guard as `read_link` runs before every `browse`.

Chromium runs without its sandbox inside the container because the process is root
there. That's the standard trade-off for headless Chromium in Docker; a sandbox escape
from a web page into a container that holds your tokens is the risk being accepted. The
hardening step, running as an unprivileged user with a seccomp profile, is on the list.

## Reading the code

1. `sites.py` — the four site profiles and what a login URL looks like.
2. `browser.py` — `ELEMENTS_JS`, `render_snapshot`, `BrowserSession`.
3. `agent.py` — the six `browser_*` tools; note `requires_approval=True` on one of them.
4. `chat.py` — `PendingApproval`, `_finish`, `_resume`: the pause and the yes/no.
5. `tests/test_browser_real.py` — a real Chromium on a local page, no network.

## Known notice

Running the one-shot `assistant chat` command *inside the container* (Python 3.12) can print
"Exception ignored in BaseSubprocessTransport.__del__ … Event loop is closed" after the
answer. The browser has already been stopped by then; it's the interpreter finalizing
Playwright's driver pipe in an unlucky order. The always-on `run` process doesn't exit, so it
never shows this, and the same command on the Mac (Python 3.13) is clean. Ignore it.
