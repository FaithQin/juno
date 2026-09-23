"""Telegram, via long polling: no public URL, free, pushes any time.

Only chats listed in TELEGRAM_CHAT_IDS are answered; everything else is
logged and ignored (Faith's choice). With an empty allowlist the bot is in
setup mode: `/start` tells you your chat id so you can put it in `.env`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable

from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from ..errors import describe_error

TELEGRAM_LIMIT = 4096
log = logging.getLogger(__name__)


def bubbles(text: str) -> list[str]:
    """Blank lines separate bubbles, like texting: one thought per message, lists stay together."""
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split at line boundaries so lists don't get cut mid-item; hard-split only a single huge line."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        parts.append(current)
    return parts


class TelegramChannel:
    bubble_delay = 0.6   # seconds between bubbles, so several messages read like typing, not a burst

    def __init__(self, token: str, allowed_chat_ids: set[int], on_message: Callable[[str], Awaitable[str]]):
        self.allowed_chat_ids = set(allowed_chat_ids)
        self.on_message = on_message
        self.ignored: list[int] = []
        self.app = Application.builder().token(token).build()
        self.bot = self.app.bot
        self.app.add_handler(CommandHandler("start", self._on_start))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

    # -- inbound -------------------------------------------------------------

    async def _on_start(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self.allowed_chat_ids:
            await update.message.reply_text(
                f"hi. your chat id is {chat_id}. put TELEGRAM_CHAT_IDS={chat_id} in .env and restart me."
            )
        elif chat_id in self.allowed_chat_ids:
            await update.message.reply_text("hey. i'm here.")
        else:
            self.ignored.append(chat_id)

    async def _on_text(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if chat_id not in self.allowed_chat_ids:
            self.ignored.append(chat_id)
            log.info("ignored message from chat %s", chat_id)
            return
        await self.bot.send_chat_action(chat_id, ChatAction.TYPING)
        try:
            reply = await self.on_message(update.message.text)
        except Exception as e:
            log.exception("handling a message failed")
            reply = describe_error(e)
        for i, bubble in enumerate(bubbles(reply) or ["…"]):
            if i:
                await self.bot.send_chat_action(chat_id, ChatAction.TYPING)
                await asyncio.sleep(self.bubble_delay)
            for part in split_message(bubble):
                await update.message.reply_text(part)

    # -- outbound ------------------------------------------------------------

    async def send(self, text: str) -> None:
        for chat_id in sorted(self.allowed_chat_ids):
            for i, bubble in enumerate(bubbles(text)):
                if i:
                    await asyncio.sleep(self.bubble_delay)
                for part in split_message(bubble):
                    await self.bot.send_message(chat_id, part)

    # -- lifecycle (manual, so the scheduler can share the event loop) --------

    async def start(self) -> None:
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
