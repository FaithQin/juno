"""One conversation: load the last 24 hours, run the agent, save what's new, count tokens."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from pydantic_ai import Agent, ModelMessagesTypeAdapter, UsageLimits

from .chat_ops import ChatOps
from .db import Store

DEFAULT_LIMITS = UsageLimits(request_limit=8, total_tokens_limit=40_000)
DEFAULT_RUN_TIMEOUT = timedelta(seconds=120)   # whole turn, all tool calls included


class ChatSession:
    def __init__(self, agent: Agent[ChatOps, str], ops: ChatOps, store: Store, *, conversation_id: str,
                 window: timedelta = timedelta(hours=24), usage_limits: UsageLimits = DEFAULT_LIMITS,
                 run_timeout: timedelta = DEFAULT_RUN_TIMEOUT):
        self.agent = agent
        self.ops = ops
        self.store = store
        self.conversation_id = conversation_id
        self.window = window
        self.usage_limits = usage_limits
        self.run_timeout = run_timeout

    async def handle(self, text: str) -> str:
        now = self.ops.now()
        history = []
        for blob in self.store.load_messages(self.conversation_id, since=now - self.window):
            history.extend(ModelMessagesTypeAdapter.validate_json(blob))

        result = await asyncio.wait_for(
            self.agent.run(text, deps=self.ops, message_history=history, usage_limits=self.usage_limits),
            timeout=self.run_timeout.total_seconds(),
        )

        self.store.save_messages(self.conversation_id, result.new_messages_json(), at=now)
        usage = result.usage() if callable(result.usage) else result.usage
        total = int(getattr(usage, "total_tokens", 0) or 0)
        key = f"tokens:{now.astimezone(self.ops.tz).date().isoformat()}"
        self.store.kv_set(key, str(int(self.store.kv_get(key) or 0) + total))
        return result.output
