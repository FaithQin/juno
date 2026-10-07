"""Command line entry point: `uv run assistant <command>`."""

from __future__ import annotations

import argparse
import sys

from .config import Settings, load_courses, project_root


def run_one_shot(coro):
    """asyncio.run, named for what it's used for. `with_cleanup` (app.py) stops the browser and
    collects garbage before the loop closes, which is what keeps Playwright's driver from
    printing an 'Event loop is closed' notice at exit on Python 3.12."""
    import asyncio

    return asyncio.run(coro)


def load_settings() -> Settings:
    try:
        return Settings()
    except Exception as e:  # pydantic ValidationError: a required token is missing
        missing = [w for w in ("canvas_token", "todoist_token") if w in str(e)]
        if missing:
            names = ", ".join(m.upper() for m in missing)
            sys.exit(
                f"missing {names} in {project_root() / '.env'}\n"
                "  cp .env.example .env && chmod 600 .env   then paste the tokens in (see README.md)"
            )
        raise


def cmd_courses(_args) -> int:
    from .canvas_client import CanvasClient

    settings = load_settings()
    cfg = load_courses()
    mapped = cfg.by_canvas_id()
    canvas = CanvasClient(settings.canvas_url, settings.canvas_token)
    print("active Canvas courses (id · code · name · courses.yaml?)")
    for cid, code, name in canvas.active_courses():
        tag = f"→ {mapped[cid].code}" if cid in mapped else "(not in courses.yaml)"
        print(f"  {cid} · {code} · {name} {tag}")
    return 0


def check_report(todoist, cfg) -> list[str]:
    """What `assistant check` prints: the parent project (Classes), each course's own
    sub-project (found, and under Classes?) or, for a course without one, its legacy section,
    and the active tasks juno reads across all of them."""
    project = todoist.project(project_id=cfg.todoist.project_id, name=cfg.todoist.project_name)
    sections = todoist.sections(project.id)
    by_id = {p.id: p for p in todoist.projects()}
    lines = [f"todoist project: {project.name} ({project.id})"]
    missing_sections = []
    for c in cfg.courses:
        if c.project_id:
            sub = by_id.get(c.project_id)
            if sub is None:
                lines.append(f"{c.code}: sub-project {c.project_id} NOT FOUND")
            elif getattr(sub, "parent_id", None) != project.id:
                lines.append(f"{c.code}: sub-project {sub.name} ({sub.id}) is not under {project.name}")
            else:
                lines.append(f"{c.code}: sub-project {sub.name} ({sub.id}) ok")
        elif c.section_name in sections:
            lines.append(f"{c.code}: section {c.section_name} in {project.name} (legacy)")
        elif c.audit:   # never synced, so no section is ever made for it
            lines.append(f"{c.code}: audit, no Todoist project (that's fine: juno syncs nothing for it)")
        else:
            missing_sections.append(c.section_name)
    read_ids = [pid for pid in cfg.class_project_ids(project.id) if pid == project.id or pid in by_id]
    n_sub = len(read_ids) - 1
    tasks = todoist.tasks_in(read_ids)
    lines.append(f"active tasks: {len(tasks)} ({project.name} + {n_sub} course sub-project{'s' if n_sub != 1 else ''})")
    if missing_sections:
        lines.append(f"sections that will be created on first sync: {', '.join(missing_sections)}")
    return lines


def cmd_check(_args) -> int:
    from .todoist_client import TodoistClient

    settings = load_settings()
    todoist = TodoistClient(settings.todoist_token)
    for line in check_report(todoist, load_courses()):
        print(line)
    print(f"timezone: {settings.timezone}")
    return 0


def telegram_notify(settings, text: str) -> bool:
    """Send a text to Faith's allowlisted chats. Every edit juno makes must reach her, even from a manual run."""
    import asyncio

    if not settings.telegram_bot_token or not settings.allowed_chat_ids:
        return False
    from telegram import Bot

    async def go():
        async with Bot(settings.telegram_bot_token) as bot:
            for chat_id in sorted(settings.allowed_chat_ids):
                await bot.send_message(chat_id, text)

    asyncio.run(go())
    from datetime import datetime, timezone

    from .chat import record_sent
    from .db import Store

    record_sent(Store(settings.db_path), text, at=datetime.now(timezone.utc))   # her answer to it should make sense to juno
    return True


def cmd_sync(args) -> int:
    from .sync import format_report, run_sync

    settings = load_settings()
    cfg = load_courses()
    report = run_sync(settings, cfg, dry_run=args.dry_run, verbose=args.verbose)
    text = format_report(report)
    print(text)
    if not args.dry_run and not args.quiet and report.changed:
        print("(texted)" if telegram_notify(settings, text) else "(no telegram configured; not texted)")
    return 1 if report.errors else 0


def cmd_run(_args) -> int:
    import asyncio
    import logging

    from .app import build_runtime, serve

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    rt = build_runtime()
    asyncio.run(serve(rt))
    return 0


def cmd_chat(args) -> int:
    """Talk to juno from the terminal (same brain as Telegram, separate conversation)."""
    import asyncio

    from .app import build_runtime

    from .errors import describe_error

    rt = build_runtime(conversation_id="cli")
    try:
        print(asyncio.run(rt.session.handle(" ".join(args.text))))
    except Exception as e:
        print(describe_error(e))
        return 1
    return 0


def cmd_brief(args) -> int:
    import asyncio

    from .app import build_runtime, with_cleanup
    from .jobs import run_brief_job

    rt = build_runtime()

    async def show(text):
        print(text)

    run_one_shot(with_cleanup(rt.ops, run_brief_job(rt.ops, send=show)))
    return 0


def cmd_nudges(args) -> int:
    """Show which nudges would fire right now (never sends, never records)."""
    from .app import build_runtime, now_utc
    from .reminders import format_nudges, plan_nudges

    rt = build_runtime()
    now = now_utc()
    nudges = plan_nudges(rt.ops.nudge_tasks(), now=now, tz=rt.settings.tz, sent=rt.store.sent_nudges(), snoozes=rt.store.snoozes())
    print(format_nudges(nudges, now=now, tz=rt.settings.tz, offline_since=None) or "no nudges due right now")
    return 0


def cmd_gcal_auth(_args) -> int:
    from .gcal import GoogleCalendar

    settings = load_settings()
    cal = GoogleCalendar(settings.google_credentials_path, settings.google_token_path)
    cal.authorize()
    names = sorted(cal.calendar_ids())
    print(f"authorized. token saved to {settings.google_token_path}")
    print("calendars visible: " + ", ".join(names))
    return 0


def cmd_gradescope(args) -> int:
    """Run the Gradescope sync once, now. Messages go to Telegram (or the console with --print)."""
    from .app import build_runtime, now_utc, with_cleanup
    from .gradescope_sync import GradescopeSync

    rt = build_runtime()

    async def to_console(text):
        print(text)

    async def to_telegram(text):
        from telegram import Bot

        print(text)
        async with Bot(rt.settings.telegram_bot_token) as bot:
            for chat_id in sorted(rt.settings.allowed_chat_ids):
                await bot.send_message(chat_id, text)
        rt.session.note_sent(text)              # her answer to it should make sense to juno

    send = to_console if args.print or not rt.settings.telegram_bot_token else to_telegram
    job = GradescopeSync(browser=rt.ops.browser, todoist=rt.todoist, store=rt.store, courses_cfg=rt.courses_cfg,
                         project_id=rt.project_id, sections=rt.sections, tz=rt.settings.tz, send=send, now=now_utc,
                         complete_when_submitted=rt.settings.complete_when_submitted)

    async def go():
        await job.run()
        print("(nothing to report)" if not job.store.kv_get("pending_job") else "(proposal sent; answer it in telegram)")

    run_one_shot(with_cleanup(rt.ops, go()))
    return 0


def cmd_calendar(args) -> int:
    """Run the Canvas events → Google Calendar sync once, now."""
    from .app import build_calendar_sync, build_runtime, with_cleanup

    rt = build_runtime()

    async def to_console(text):
        print(text)

    async def to_telegram(text):
        from telegram import Bot

        print(text)
        async with Bot(rt.settings.telegram_bot_token) as bot:
            for chat_id in sorted(rt.settings.allowed_chat_ids):
                await bot.send_message(chat_id, text)
        rt.session.note_sent(text)              # her answer to it should make sense to juno

    send = to_console if args.print or not rt.settings.telegram_bot_token else to_telegram
    job = build_calendar_sync(rt, send)

    async def go():
        await job.run()
        print("(proposal sent; answer it in telegram)" if rt.store.kv_get("pending_job") else "(nothing to report)")

    run_one_shot(with_cleanup(rt.ops, go()))
    return 0


def cmd_browser_login(args) -> int:
    """Open a real browser window on this Mac, let Faith log in (Duo and all), save the session."""
    import asyncio

    from .config import project_root
    from .sites import SITES, looks_like_login, session_path

    site = SITES.get(args.site)
    if site is None:
        sys.exit(f"unknown site {args.site!r}. choose one of: {', '.join(SITES)}")
    path = session_path(project_root() / "data", site)
    path.parent.mkdir(parents=True, exist_ok=True)

    async def run():
        import threading

        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context(storage_state=str(path) if path.exists() else None,
                                                viewport={"width": 1280, "height": 900})
            page = await context.new_page()
            await page.goto(site.login_url)
            print(f"a browser window opened at {site.login_url}")
            print(f"log in to {site.name} there (Duo included). when you're in, press Enter here or just close the window.")

            loop = asyncio.get_running_loop()
            done = asyncio.Event()
            page.on("close", lambda _: loop.call_soon_threadsafe(done.set))
            browser.on("disconnected", lambda _: loop.call_soon_threadsafe(done.set))
            if sys.stdin.isatty():   # launched from a terminal: Enter also finishes
                threading.Thread(target=lambda: (input(), loop.call_soon_threadsafe(done.set)), daemon=True).start()

            # save every couple of seconds while the window is open, so closing it loses nothing
            last_url = page.url
            while not done.is_set():
                try:
                    await context.storage_state(path=str(path))
                    path.chmod(0o600)
                    last_url = page.url
                except Exception:
                    break
                try:
                    await asyncio.wait_for(done.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
            try:
                await context.storage_state(path=str(path))
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass

        if looks_like_login(last_url, site):
            print(f"warning: the last page seen was still a login page ({last_url}); if you didn't finish logging in, run this again")
        print(f"saved {path}")
        print("ship it to the server with: scripts/deploy.sh root@SERVER_IP")

    run_one_shot(run())
    return 0


def cmd_browser_check(_args) -> int:
    """For every saved session, open the site and report whether it's still logged in."""
    import asyncio

    from .browser import BrowserSession
    from .config import project_root
    from .sites import SITES, session_path

    data = project_root() / "data"

    async def run():
        session = BrowserSession(data_dir=data, headless=True)
        try:
            for key, site in SITES.items():
                if not session_path(data, site).exists():
                    print(f"{key}: no saved session (run: uv run assistant browser-login {key})")
                    continue
                try:
                    snap = await session.open(site.home_url)
                    print(f"{key}: {'LOGIN NEEDED' if snap.login_required else 'logged in'} ({snap.title or snap.url})")
                except Exception as e:
                    print(f"{key}: error {type(e).__name__}: {e}")
        finally:
            await session.stop()

    run_one_shot(run())
    return 0


def cmd_outlook(args) -> int:
    """Run the Outlook → Google Calendar sync once, now."""
    from .app import build_outlook_sync, build_runtime, with_cleanup

    rt = build_runtime()

    async def to_console(text):
        print(text)

    async def to_telegram(text):
        from telegram import Bot

        print(text)
        async with Bot(rt.settings.telegram_bot_token) as bot:
            for chat_id in sorted(rt.settings.allowed_chat_ids):
                await bot.send_message(chat_id, text)
        rt.session.note_sent(text)              # her answer to it should make sense to juno

    send = to_console if args.print or not rt.settings.telegram_bot_token else to_telegram
    job = build_outlook_sync(rt, send)
    if job is None:
        print("OUTLOOK_ICS_URL is empty in .env (Outlook web → Calendar → Shared calendars → Publish a calendar)")
        return 1

    async def go():
        if not await job.run():                 # what it added or moved was already printed or texted
            print("(nothing to report)")

    run_one_shot(with_cleanup(rt.ops, go()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assistant", description="Faith's personal assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("courses", help="list active Canvas courses and whether courses.yaml maps them")
    sub.add_parser("check", help="verify Todoist access, the Classes project and its sections")

    p_sync = sub.add_parser("sync", help="sync Canvas assignments into Todoist")
    p_sync.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    p_sync.add_argument("-v", "--verbose", action="store_true")
    p_sync.add_argument("--quiet", action="store_true", help="don't text Faith about changes made by this manual run")

    sub.add_parser("run", help="start juno: Telegram polling + hourly sync + nudges + morning brief")
    p_chat = sub.add_parser("chat", help="one message to juno from the terminal")
    p_chat.add_argument("text", nargs="+")
    sub.add_parser("brief", help="print today's morning brief")
    sub.add_parser("nudges", help="show which nudges would fire right now")
    sub.add_parser("gcal-auth", help="one-time Google Calendar authorization")
    p_login = sub.add_parser("browser-login", help="log in to a site in a real browser window and save the session")
    p_login.add_argument("site", help="gradescope | paperless | ed | canvas")
    sub.add_parser("browser-check", help="report which saved sessions are still logged in")
    p_gs = sub.add_parser("gradescope", help="run the Gradescope → Todoist sync once, now")
    p_gs.add_argument("--print", action="store_true", help="print instead of texting")
    p_cal = sub.add_parser("calendar", help="run the Canvas events → Google Calendar sync once, now")
    p_cal.add_argument("--print", action="store_true", help="print instead of texting")
    p_ol = sub.add_parser("outlook", help="run the Outlook → Google Calendar sync once, now")
    p_ol.add_argument("--print", action="store_true", help="print instead of texting")

    args = parser.parse_args(argv)
    handlers = {"courses": cmd_courses, "check": cmd_check, "sync": cmd_sync, "run": cmd_run, "chat": cmd_chat,
                "brief": cmd_brief, "nudges": cmd_nudges, "gcal-auth": cmd_gcal_auth,
                "browser-login": cmd_browser_login, "browser-check": cmd_browser_check, "gradescope": cmd_gradescope, "calendar": cmd_calendar,
                "outlook": cmd_outlook}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
