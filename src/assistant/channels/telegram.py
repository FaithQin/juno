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

from pydantic_ai.messages import BinaryContent
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from ..chat import Reply
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


def reply_of(message) -> Reply | None:
    """What she replied to: the part she quoted if she highlighted some, else the whole message."""
    target = getattr(message, "reply_to_message", None)
    if target is None:
        return None
    quote = getattr(message, "quote", None)
    text = (getattr(quote, "text", None) if quote is not None else None) or getattr(target, "text", None) \
        or getattr(target, "caption", None)
    if not text:
        text = "[a photo]" if getattr(target, "photo", None) else "[a message with no text]"
    sender = getattr(target, "from_user", None)
    return Reply(text, from_juno=bool(getattr(sender, "is_bot", False)), sent_at=getattr(target, "date", None))


class TelegramChannel:
    bubble_delay = 0.6   # seconds between bubbles, so several messages read like typing, not a burst

    def __init__(self, token: str, allowed_chat_ids: set[int], on_message: Callable[[str], Awaitable[str]],
                 status: Callable[[], str] | None = None):
        self.allowed_chat_ids = set(allowed_chat_ids)
        self.on_message = on_message
        self.status = status
        self.ignored: list[int] = []
        self.app = Application.builder().token(token).build()
        self.bot = self.app.bot
        self.app.add_handler(CommandHandler("start", self._on_start))
        self.app.add_handler(CommandHandler("status", self._on_status))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        self.app.add_handler(MessageHandler(filters.PHOTO, self._on_photo))

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

    async def _on_status(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if chat_id not in self.allowed_chat_ids:
            self.ignored.append(chat_id)
            return
        await update.message.reply_text(self.status() if self.status else "no status available")

    def _allowed(self, chat_id: int) -> bool:
        if chat_id in self.allowed_chat_ids:
            return True
        self.ignored.append(chat_id)
        log.info("ignored message from chat %s", chat_id)
        return False

    async def _on_text(self, update, context) -> None:
        await self._handle(update, update.message.text, None)

    async def _on_photo(self, update, context) -> None:
        """A photo (a screenshot of section times, a syllabus page) goes to the brain as an image
        plus its caption. Telegram offers several renditions; the largest is the readable one."""
        if not self._allowed(update.effective_chat.id):
            return
        best = max(update.message.photo, key=lambda ph: ph.width)
        blob = await self.bot.get_file(best.file_id)
        data = bytes(await blob.download_as_bytearray())
        await self._handle(update, update.message.caption or "", [BinaryContent(data, media_type="image/jpeg")])

    async def _handle(self, update, text: str, images: list[BinaryContent] | None) -> None:
        chat_id = update.effective_chat.id
        if not self._allowed(chat_id):
            return
        await self.bot.send_chat_action(chat_id, ChatAction.TYPING)
        extra: dict = {}
        if images:
            extra["images"] = images
        quoted = reply_of(update.message)
        if quoted is not None:
            extra["reply_to"] = quoted
        try:
            reply = await self.on_message(text, **extra)
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
