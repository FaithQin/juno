"""One conversation: load the last 24 hours, run the agent, save what's new, count tokens."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import timedelta

from dataclasses import replace

from pydantic_ai import (
    Agent, DeferredToolRequests, DeferredToolResults, ModelMessagesTypeAdapter, ToolDenied, UsageLimits,
)
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart

from .chat_ops import ChatOps
from .db import Store

DEFAULT_LIMITS = UsageLimits(request_limit=24, total_tokens_limit=250_000)   # a ceiling; trimming keeps real turns far below
KEEP_FULL = 3          # most recent tool results stay intact
BIG = 600              # older results longer than this are shrunk
TRIM_NOTE = "\n… [older tool output trimmed; call the tool again if you need it]"


def trim_old_tool_returns(messages: list[ModelMessage]) -> list[ModelMessage]:
    """History processor: every model request re-sends the whole conversation, and a page
    snapshot is thousands of tokens, so all but the last few tool results are shrunk."""
    positions = [
        (mi, pi)
        for mi, m in enumerate(messages) if isinstance(m, ModelRequest)
        for pi, p in enumerate(m.parts) if isinstance(p, ToolReturnPart)
    ]
    to_trim = set(positions[:-KEEP_FULL]) if KEEP_FULL else set(positions)
    if not to_trim:
        return messages
    out: list[ModelMessage] = []
    for mi, m in enumerate(messages):
        if not (isinstance(m, ModelRequest) and any((mi, pi) in to_trim for pi in range(len(m.parts)))):
            out.append(m)
            continue
        parts = []
        for pi, p in enumerate(m.parts):
            if (mi, pi) in to_trim and isinstance(getattr(p, "content", None), str) and len(p.content) > BIG:
                parts.append(replace(p, content=p.content[: BIG // 2].rstrip() + TRIM_NOTE))
            else:
                parts.append(p)
        out.append(replace(m, parts=parts))
    return out
DEFAULT_RUN_TIMEOUT = timedelta(seconds=180)   # whole turn, all tool calls included

YES = {"yes", "y", "yep", "yeah", "yea", "ok", "okay", "go", "go ahead", "do it", "sure", "confirm", "👍", "please"}
NO = {"no", "n", "nope", "stop", "cancel", "don't", "dont", "skip", "nah", "wait"}


def _norm(text: str) -> str:
    return re.sub(r"[^\w👍' ]", "", text.strip().lower()).strip()


@dataclass
class PendingApproval:
    tool_call_id: str
    tool_name: str
    args: dict
    description: str


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
        self.pending: PendingApproval | None = None

    def _history(self, now):
        history = []
        for blob in self.store.load_messages(self.conversation_id, since=now - self.window):
            history.extend(ModelMessagesTypeAdapter.validate_json(blob))
        return history

    async def _run(self, text: str | None, *, deferred=None):
        now = self.ops.now()
        result = await asyncio.wait_for(
            self.agent.run(text, deps=self.ops, message_history=self._history(now),
                           deferred_tool_results=deferred, usage_limits=self.usage_limits),
            timeout=self.run_timeout.total_seconds(),
        )
        self.store.save_messages(self.conversation_id, result.new_messages_json(), at=now)
        usage = result.usage() if callable(result.usage) else result.usage
        total = int(getattr(usage, "total_tokens", 0) or 0)
        key = f"tokens:{now.astimezone(self.ops.tz).date().isoformat()}"
        self.store.kv_set(key, str(int(self.store.kv_get(key) or 0) + total))
        return result

    def _describe(self, call) -> str:
        args = dict(call.args_as_dict()) if hasattr(call, "args_as_dict") else dict(call.args or {})
        if call.tool_name == "browser_submit" and self.ops.browser is not None:
            return f"click {self.ops.browser.describe_ref(int(args.get('ref', 0)))}"
        return f"run {call.tool_name} with {args}"

    def _finish(self, result) -> str:
        """Either a plain answer, or a pause: remember what needs approval and ask."""
        if isinstance(result.output, DeferredToolRequests):
            call = result.output.approvals[0]
            args = dict(call.args_as_dict()) if hasattr(call, "args_as_dict") else dict(call.args or {})
            self.pending = PendingApproval(call.tool_call_id, call.tool_name, args, self._describe(call))
            return f"about to {self.pending.description}. reply yes to go ahead or no to skip"
        self.pending = None
        return result.output

    async def _resume(self, approved: bool):
        p = self.pending
        self.pending = None
        verdict = True if approved else ToolDenied("faith said no")
        return await self._run(None, deferred=DeferredToolResults(approvals={p.tool_call_id: verdict}))

    async def handle(self, text: str) -> str:
        if self.pending is not None:
            answer = _norm(text)
            if answer in YES:
                return self._finish(await self._resume(True))
            if answer in NO:
                return self._finish(await self._resume(False))
            skipped = self.pending.description
            await self._resume(False)                    # close the dangling tool call, then move on
            reply = self._finish(await self._run(text))
            return f"skipped the pending {skipped}.\n\n{reply}"
        return self._finish(await self._run(text))
