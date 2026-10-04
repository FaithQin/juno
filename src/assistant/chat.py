"""One conversation: load the last 24 hours, run the agent, save what's new, count tokens."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dataclasses import replace

from pydantic_ai import (
    Agent, DeferredToolRequests, DeferredToolResults, ModelMessagesTypeAdapter, ToolDenied, UsageLimits,
)
from pydantic_ai.messages import (
    BinaryContent, ModelMessage, ModelRequest, ModelResponse, RetryPromptPart, SystemPromptPart, TextPart, ToolCallPart,
    ToolReturnPart, UserPromptPart,
)

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


KEEP_IMAGES = 3        # photos stay attached to the last few messages that carried one; older ones become a note
IMAGE_NOTE = "[photo she sent, no longer attached]"


def _has_image(p) -> bool:
    return isinstance(p, UserPromptPart) and isinstance(p.content, list) and any(isinstance(c, BinaryContent) for c in p.content)


def compact_previous_turns(messages: list[ModelMessage], *, keep_images: int = KEEP_IMAGES) -> list[ModelMessage]:
    """Earlier turns come back as conversation only: what she said and what juno answered.

    Every request re-sends the whole history, and most of it was never the conversation: tool
    calls, tool output and the model's own encrypted reasoning from turns that are over. Those
    were the bulk of a 56k-token request. Dropping them costs nothing the model can't fetch again
    with one tool call. A response whose tool call is still waiting on her yes/no is kept whole,
    because the provider needs that call, and the reasoning that led to it, exactly as it was.
    Kept text loses its provider id so it is replayed as plain text rather than by reference."""
    answered = {
        p.tool_call_id
        for m in messages if isinstance(m, ModelRequest)
        for p in m.parts if isinstance(p, (ToolReturnPart, RetryPromptPart)) and p.tool_call_id
    }
    with_images = [(mi, pi) for mi, m in enumerate(messages) if isinstance(m, ModelRequest)
                   for pi, p in enumerate(m.parts) if _has_image(p)]
    thin = set(with_images[:-keep_images]) if keep_images else set(with_images)
    out: list[ModelMessage] = []
    for mi, m in enumerate(messages):
        if isinstance(m, ModelRequest):
            parts = []
            for pi, p in enumerate(m.parts):
                if not isinstance(p, (UserPromptPart, SystemPromptPart)):
                    continue
                if (mi, pi) in thin:
                    p = replace(p, content=[IMAGE_NOTE if isinstance(c, BinaryContent) else c for c in p.content])
                parts.append(p)
        elif isinstance(m, ModelResponse):
            if any(isinstance(p, ToolCallPart) and p.tool_call_id not in answered for p in m.parts):
                out.append(m)
                continue
            parts = [replace(p, id=None) for p in m.parts if isinstance(p, TextPart)]
        else:
            out.append(m)
            continue
        if parts:
            out.append(replace(m, parts=parts))
    return out


DEFAULT_RUN_TIMEOUT = timedelta(seconds=180)   # whole turn, all tool calls included
CLOCK_SKEW = timedelta(seconds=30)             # Telegram's clock vs ours, when placing a message after a question

@dataclass(frozen=True)
class Reply:
    """The message she answered with Telegram's reply: its text (or the part she quoted), whether
    juno sent it, and when. Juno's own texts from scheduled jobs are replies too: a nudge, the brief."""
    text: str
    from_juno: bool
    sent_at: datetime | None = None


# OpenAI's web search appends citations like " ([medlineplus.gov](https://…?utm_source=openai))".
# Faith wants sources only when she asks (2026-10-03), so they are taken out of what she reads;
# the stored history keeps them, so "sources?" in a later message can still be answered.
_OPENAI_URL = r"https?://[^\s)]*utm_source=openai[^\s)]*"
CITATION_RE = re.compile(r" ?\(\[([^\]]+)\]\((" + _OPENAI_URL + r")\)\)")
INLINE_CITATION_RE = re.compile(r"\[([^\]]+)\]\((" + _OPENAI_URL + r")\)")
SOURCES_ASK_RE = re.compile(
    r"\b(sources?|cite|citations?|links?|urls?|references?|where (did|do) you (get|find|read)|how do you know)\b", re.I)
REPLY_SNIPPET = 600


def _clean_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "utm_source"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def asks_for_sources(text: str) -> bool:
    return bool(SOURCES_ASK_RE.search(text or ""))


def tidy_reply(text: str, *, keep_sources: bool) -> str:
    """Web-search citations out (or, when she asked for sources, turned into plain links).
    Links that aren't search citations, like a sign-up page she asked for, are left alone."""
    if keep_sources:
        text = CITATION_RE.sub(lambda m: f" ({_clean_url(m[2])})", text)
        text = INLINE_CITATION_RE.sub(lambda m: f"{m[1]} ({_clean_url(m[2])})", text)
    else:
        text = CITATION_RE.sub("", text)
        text = INLINE_CITATION_RE.sub(lambda m: m[1], text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip()


def record_sent(store: Store, text: str, *, at: datetime, conversation_id: str = "telegram") -> None:
    """Keep a text juno sent on its own (nudge, brief, sync note, proposal) as one of juno's lines in
    the conversation's outbox stream, so her answer to it makes sense to the model."""
    if not text.strip():
        return
    message = ModelResponse(parts=[TextPart(text[:2000])], timestamp=at)
    store.save_messages(f"{conversation_id}:outbox", ModelMessagesTypeAdapter.dump_json([message]), at=at)


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
        self.outbox_id = f"{conversation_id}:outbox"    # texts juno sent on its own, kept beside the chat
        self.window = window
        self.usage_limits = usage_limits
        self.run_timeout = run_timeout
        self.pending: PendingApproval | None = None
        self.job_handlers: dict = {}      # kind → async (payload, approved) -> reply text
        self._reply_predates_job = False   # this turn replies to a message sent before the pending question
        ops.answer_job = self._answer_from_model   # the answer_proposal tool lands here

    # -- proposals from scheduled jobs (e.g. the Gradescope first run) --------

    def propose_job(self, kind: str, payload: dict, question: str) -> None:
        self.store.propose_job(kind, payload, question, at=self.ops.now())

    async def _answer_job(self, approved: bool) -> str:
        job = self.store.pending_job()
        if job is None:
            return "there's no proposal waiting"
        self.store.kv_delete("pending_job")
        handler = self.job_handlers.get(job["kind"])
        if handler is None:
            return f"i lost the handler for {job['kind']}; nothing done"
        return await handler(job["payload"], approved)

    async def _answer_from_model(self, approved: bool) -> str:
        if self._reply_predates_job:   # a reply is about the message it replies to, which came before this question
            return ("not done: she's replying to a message from before this question was asked, so it isn't her "
                    "answer to it. tell her nothing was done; if she meant this question, show it to her to answer")
        return await self._answer_job(approved)

    def _out_of_date(self) -> str:
        """Her yes/no to a question that has since been replaced: nothing happens, and the current
        question comes again as its own message, so a reply to it is unambiguous."""
        job = self.store.pending_job()
        text = (f"nothing done: that question was replaced on {self._stamp(datetime.fromisoformat(job['asked_at']))}. "
                f"here's the current one, reply yes or no to it:\n\n{job['question']}")
        self.note_sent(text)
        return text

    def _job_is_fresh(self) -> bool:
        """A bare yes/no answers a job's proposal only while that proposal is the last thing said.
        Once other chat has happened, 'ok' means whatever it means in that chat; the proposal stays
        in the model's context and the answer_proposal tool takes it from there."""
        job = self.store.pending_job()
        if job is None or not job.get("asked_at"):
            return False
        return not self.store.has_messages_after(self.conversation_id, job["asked_at"])

    def note_sent(self, text: str, *, at: datetime | None = None) -> None:
        """Record a text juno sent on its own (a nudge, the brief, a sync note, a proposal) as one of
        juno's lines, so her answer to it, with or without Telegram's reply, makes sense to the model.
        Kept in its own stream so it doesn't count as chat when deciding whether a proposal is fresh."""
        record_sent(self.store, text, at=at or self.ops.now(), conversation_id=self.conversation_id)

    def _history(self, now):
        history = []
        for blob in self.store.load_messages([self.conversation_id, self.outbox_id], since=now - self.window):
            history.extend(ModelMessagesTypeAdapter.validate_json(blob))
        return compact_previous_turns(history)

    def _reply_note(self, reply: Reply) -> str:
        who = "your message" if reply.from_juno else "her own earlier message"
        when = f" from {self._stamp(reply.sent_at)}" if reply.sent_at else ""
        quoted = " ".join(reply.text.split())
        if len(quoted) > REPLY_SNIPPET:
            quoted = quoted[:REPLY_SNIPPET].rstrip() + "…"
        return f'(replying to {who}{when}: "{quoted}")'

    def _stamp(self, now) -> str:
        """The clock rides on her message ("[wed sep 23, 10:00am] hi"), not in the instructions:
        the instructions then stay identical from one request to the next, which is what lets the
        provider serve the persona, tools and history from its prompt cache."""
        return now.astimezone(self.ops.tz).strftime("%a %b %-d, %-I:%M%p").lower()

    def _bump(self, key: str, n: int) -> None:
        self.store.kv_set(key, str(int(self.store.kv_get(key) or 0) + n))

    async def _run(self, text: str | None, *, images: list[BinaryContent] | None = None, reply_to: Reply | None = None,
                   deferred=None):
        now = self.ops.now()
        if text is not None and reply_to is not None:
            text = f"{self._reply_note(reply_to)} {text}"
        prompt = f"[{self._stamp(now)}] {text}" if text is not None else None
        if images:
            prompt = [prompt or f"[{self._stamp(now)}]", *images]
        result = await asyncio.wait_for(
            self.agent.run(prompt, deps=self.ops, message_history=self._history(now),
                           deferred_tool_results=deferred, usage_limits=self.usage_limits),
            timeout=self.run_timeout.total_seconds(),
        )
        self.store.save_messages(self.conversation_id, result.new_messages_json(), at=now)
        usage = result.usage() if callable(result.usage) else result.usage
        day = now.astimezone(self.ops.tz).date().isoformat()
        for key, attr in (("tokens", "total_tokens"), ("tokens_in", "input_tokens"),
                          ("tokens_cached", "cache_read_tokens"), ("requests", "requests")):
            self._bump(f"{key}:{day}", int(getattr(usage, attr, 0) or 0))
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

    def _proposal_reply(self, reply: Reply | None) -> str | None:
        """How her Telegram reply relates to the pending proposal.
        "current": the question's own message (its text, sent after it was asked), so a yes/no answers
        it however much chat happened since. "replaced": one of juno's messages from before it was asked
        that shares a line with it, i.e. an older question of the same kind ("reply yes to delete the
        copies…" ends every duplicates question). "earlier": any other message from before it was asked.
        Neither of the last two may answer it. None: no proposal, not a reply, or Telegram didn't say
        when the message was sent (then the model asks)."""
        job = self.store.pending_job()
        if reply is None or reply.sent_at is None or job is None or not job.get("question") or not job.get("asked_at"):
            return None
        quoted, question = " ".join(reply.text.split()), " ".join(job["question"].split())
        sent = reply.sent_at if reply.sent_at.tzinfo else reply.sent_at.replace(tzinfo=timezone.utc)
        if sent >= datetime.fromisoformat(job["asked_at"]) - CLOCK_SKEW:
            return "current" if len(quoted) >= 12 and quoted in question else None
        lines = (" ".join(line.split()) for line in job["question"].splitlines())
        shared = (len(quoted) >= 12 and quoted in question) or any(len(line) >= 12 and line in quoted for line in lines)
        return "replaced" if reply.from_juno and shared else "earlier"

    async def handle(self, text: str, *, images: list[BinaryContent] | None = None, reply_to: Reply | None = None) -> str:
        answer = _norm(text) if not images else ""       # a photo is never a yes or a no
        if self.pending is not None:                     # a tool waiting on her yes is always the latest question
            if answer in YES:
                return self._finish(await self._resume(True))
            if answer in NO:
                return self._finish(await self._resume(False))
            skipped = self.pending.description
            await self._resume(False)                    # close the dangling tool call, then move on
            reply = self._finish(await self._run(text, images=images, reply_to=reply_to))
            return f"skipped the pending {skipped}.\n\n{self._tidy(reply, text)}"
        which = self._proposal_reply(reply_to)
        if answer in YES or answer in NO:
            if which == "current" or (reply_to is None and self._job_is_fresh()):
                return await self._answer_job(answer in YES)
            if which == "replaced":
                return self._out_of_date()
        # anything else: normal chat; a pending proposal keeps waiting and stays visible to the model
        self._reply_predates_job = which in ("replaced", "earlier")
        try:
            return self._tidy(self._finish(await self._run(text, images=images, reply_to=reply_to)), text)
        finally:
            self._reply_predates_job = False

    def _tidy(self, reply: str, asked: str) -> str:
        if self.pending is not None:                     # an approval question: nothing to tidy
            return reply
        return tidy_reply(reply, keep_sources=asks_for_sources(asked))
