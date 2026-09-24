"""Command line entry point: `uv run assistant <command>`."""

from __future__ import annotations

import argparse
import sys

from .config import Settings, load_courses, project_root


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


def cmd_check(_args) -> int:
    from .todoist_client import TodoistClient

    settings = load_settings()
    cfg = load_courses()
    todoist = TodoistClient(settings.todoist_token)
    project = todoist.project(project_id=cfg.todoist.project_id, name=cfg.todoist.project_name)
    sections = todoist.sections(project.id)
    tasks = todoist.tasks(project.id)
    print(f"todoist project: {project.name} ({project.id})")
    print(f"sections: {', '.join(sorted(sections)) or '(none)'}")
    print(f"active tasks: {len(tasks)}")
    missing = [c.section_name for c in cfg.courses if c.section_name not in sections]
    if missing:
        print(f"sections that will be created on first sync: {', '.join(missing)}")
    print(f"timezone: {settings.timezone}")
    return 0


def cmd_sync(args) -> int:
    from .sync import format_report, run_sync

    settings = load_settings()
    cfg = load_courses()
    report = run_sync(settings, cfg, dry_run=args.dry_run, verbose=args.verbose)
    print(format_report(report))
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

    from .app import build_runtime
    from .jobs import run_brief_job

    rt = build_runtime()

    async def show(text):
        print(text)

    asyncio.run(run_brief_job(rt.ops, send=show))
    return 0


def cmd_nudges(args) -> int:
    """Show which nudges would fire right now (never sends, never records)."""
    from .app import build_runtime, now_utc
    from .reminders import format_nudges, plan_nudges

    rt = build_runtime()
    now = now_utc()
    nudges = plan_nudges(rt.ops.due_tasks(), now=now, tz=rt.settings.tz, sent=rt.store.sent_nudges(), snoozes=rt.store.snoozes())
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
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context(storage_state=str(path) if path.exists() else None,
                                                viewport={"width": 1280, "height": 900})
            page = await context.new_page()
            await page.goto(site.login_url)
            print(f"a browser window opened at {site.login_url}")
            print(f"log in to {site.name} there (Duo included). when you can see you're logged in, come back here and press Enter.")
            await asyncio.get_running_loop().run_in_executor(None, input)
            if looks_like_login(page.url, site):
                print(f"warning: the browser is still on a login page ({page.url}); saving anyway")
            await context.storage_state(path=str(path))
            path.chmod(0o600)
            await browser.close()
        print(f"saved {path}")
        print("ship it to the server with: scripts/deploy.sh root@SERVER_IP")

    asyncio.run(run())
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

    asyncio.run(run())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assistant", description="Faith's personal assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("courses", help="list active Canvas courses and whether courses.yaml maps them")
    sub.add_parser("check", help="verify Todoist access, the Classes project and its sections")

    p_sync = sub.add_parser("sync", help="sync Canvas assignments into Todoist")
    p_sync.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    p_sync.add_argument("-v", "--verbose", action="store_true")

    sub.add_parser("run", help="start juno: Telegram polling + hourly sync + nudges + morning brief")
    p_chat = sub.add_parser("chat", help="one message to juno from the terminal")
    p_chat.add_argument("text", nargs="+")
    sub.add_parser("brief", help="print today's morning brief")
    sub.add_parser("nudges", help="show which nudges would fire right now")
    sub.add_parser("gcal-auth", help="one-time Google Calendar authorization")
    p_login = sub.add_parser("browser-login", help="log in to a site in a real browser window and save the session")
    p_login.add_argument("site", help="gradescope | paperless | ed | canvas")
    sub.add_parser("browser-check", help="report which saved sessions are still logged in")

    args = parser.parse_args(argv)
    handlers = {"courses": cmd_courses, "check": cmd_check, "sync": cmd_sync, "run": cmd_run, "chat": cmd_chat,
                "brief": cmd_brief, "nudges": cmd_nudges, "gcal-auth": cmd_gcal_auth,
                "browser-login": cmd_browser_login, "browser-check": cmd_browser_check}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
