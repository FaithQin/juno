"""Assemble the real thing: clients, ChatOps, agent, Telegram, scheduler.

`build_runtime()` is the one place that knows about real network clients.
Everything it wires together was tested with fakes; this file is deliberately
thin so there is little here to get wrong.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .agent import build_agent
from .browser import BrowserSession
from .chat import ChatSession
from .chat_ops import ChatOps
from .config import AppConfig, CoursesConfig, Settings, load_app_config, load_courses, project_root
from .db import Store
from .gcal import GoogleCalendar
from .jobs import run_brief_job, run_nudges_job, run_sync_job
from .status import describe_runtime
from .todoist_client import TodoistClient
from .web import WebReader
from . import __version__

log = logging.getLogger(__name__)
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Runtime:
    settings: Settings
    app_cfg: AppConfig
    courses_cfg: CoursesConfig
    store: Store
    todoist: TodoistClient
    calendar: GoogleCalendar | None
    ops: ChatOps
    session: ChatSession


def load_persona() -> str:
    path = project_root() / "persona.md"
    return path.read_text(encoding="utf-8") if path.exists() else "you are a brief, lowercase personal assistant."


def build_runtime(*, conversation_id: str = "telegram") -> Runtime:
    settings = Settings()
    app_cfg = load_app_config()
    courses_cfg = load_courses()
    if settings.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)

    store = Store(settings.db_path)
    todoist = TodoistClient(settings.todoist_token)
    project = todoist.project(project_id=courses_cfg.todoist.project_id, name=courses_cfg.todoist.project_name)
    sections = {name: s.id for name, s in todoist.sections(project.id).items()}

    # Lazy: nothing is read until the first calendar lookup, so finishing `gcal-auth` needs no restart.
    calendar: GoogleCalendar | None = GoogleCalendar(settings.google_credentials_path, settings.google_token_path)
    if not settings.google_token_path.exists():
        log.warning("no Google token yet; the brief and schedule will have no calendar events until you run: uv run assistant gcal-auth")

    ops = ChatOps(
        store=store, todoist=todoist, calendar=calendar, tz=settings.tz,
        courses=[c.code for c in courses_cfg.courses], sections=sections,
        classes_project_id=project.id, calendar_names=app_cfg.brief.calendars, now=now_utc,
        web=WebReader(canvas_url=settings.canvas_url, canvas_token=settings.canvas_token),
        browser=BrowserSession(data_dir=project_root() / "data", headless=True),   # starts on first use
    )
    agent = build_agent(app_cfg.agent.chat_model, persona=load_persona,   # loader: persona.md is re-read per message
                        web_search=app_cfg.agent.web_search)
    session = ChatSession(agent, ops, store, conversation_id=conversation_id)
    return Runtime(settings, app_cfg, courses_cfg, store, todoist, calendar, ops, session)


async def with_cleanup(ops, coro):
    """Await one piece of work, then stop the browser (if one was started) before the loop closes."""
    try:
        return await coro
    finally:
        browser = getattr(ops, "browser", None)
        if browser is not None:
            try:
                await browser.stop()
            except Exception:
                pass
        import gc

        gc.collect()   # finalize Playwright's driver transport while the loop is still open (py3.12 prints a warning otherwise)
        await asyncio.sleep(0)


async def serve(rt: Runtime) -> None:
    """Telegram polling plus the scheduler, until SIGINT/SIGTERM."""
    from .channels.telegram import TelegramChannel
    from .scheduler import build_scheduler
    from .sync import run_sync

    if not rt.settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is empty in .env (create a bot with @BotFather, see README)")

    started_at = now_utc()

    def status_text() -> str:
        last_scan = rt.store.kv_get("last_scan")
        sync = rt.store.last_run("sync")
        return describe_runtime(
            hostname=socket.gethostname(), in_docker=Path("/.dockerenv").exists(), version=__version__,
            started_at=started_at, now=now_utc(), tz=rt.settings.tz,
            last_scan=datetime.fromisoformat(last_scan) if last_scan else None,
            last_sync_at=sync[0] if sync else None, last_sync_ok=sync[1] if sync else None,
        )

    channel = TelegramChannel(rt.settings.telegram_bot_token, rt.settings.allowed_chat_ids, rt.session.handle,
                              status=status_text)
    if not rt.settings.allowed_chat_ids:
        log.warning("TELEGRAM_CHAT_IDS is empty: setup mode. Send /start to the bot to learn your chat id.")

    async def sync_job():
        await run_sync_job(run=lambda: run_sync(rt.settings, rt.courses_cfg), send=channel.send)

    async def nudges_job():
        await run_nudges_job(rt.ops, rt.store, send=channel.send)

    async def brief_job():
        await run_brief_job(rt.ops, send=channel.send)

    async def browser_idle_job():
        if rt.ops.browser is not None and await rt.ops.browser.close_idle(600):
            log.info("closed the idle browser page")

    sched = build_scheduler(rt.app_cfg, rt.settings.tz, sync=sync_job, nudges=nudges_job, brief=brief_job,
                            browser_idle=browser_idle_job)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await channel.start()
    sched.start()
    log.info("%s is up: telegram polling + %d scheduled jobs", rt.app_cfg.agent.name, len(sched.get_jobs()))
    try:
        await stop.wait()
    finally:
        sched.shutdown(wait=False)
        await channel.stop()
        if rt.ops.browser is not None:
            await rt.ops.browser.stop()
