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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .agent import build_agent
from .chat import ChatSession
from .chat_ops import ChatOps
from .config import AppConfig, CoursesConfig, Settings, load_app_config, load_courses, project_root
from .db import Store
from .gcal import GoogleCalendar
from .jobs import run_brief_job, run_nudges_job, run_sync_job
from .todoist_client import TodoistClient

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
    )
    agent = build_agent(app_cfg.agent.chat_model, persona=load_persona)   # loader: persona.md is re-read per message
    session = ChatSession(agent, ops, store, conversation_id=conversation_id)
    return Runtime(settings, app_cfg, courses_cfg, store, todoist, calendar, ops, session)


async def serve(rt: Runtime) -> None:
    """Telegram polling plus the scheduler, until SIGINT/SIGTERM."""
    from .channels.telegram import TelegramChannel
    from .scheduler import build_scheduler
    from .sync import run_sync

    if not rt.settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is empty in .env (create a bot with @BotFather, see README)")

    channel = TelegramChannel(rt.settings.telegram_bot_token, rt.settings.allowed_chat_ids, rt.session.handle)
    if not rt.settings.allowed_chat_ids:
        log.warning("TELEGRAM_CHAT_IDS is empty: setup mode. Send /start to the bot to learn your chat id.")

    async def sync_job():
        await run_sync_job(run=lambda: run_sync(rt.settings, rt.courses_cfg), send=channel.send)

    async def nudges_job():
        await run_nudges_job(rt.ops, rt.store, send=channel.send)

    async def brief_job():
        await run_brief_job(rt.ops, send=channel.send)

    sched = build_scheduler(rt.app_cfg, rt.settings.tz, sync=sync_job, nudges=nudges_job, brief=brief_job)

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
