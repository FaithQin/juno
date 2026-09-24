"""Submitting a form pauses the run and waits for Faith's yes or no."""

import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from assistant.agent import build_agent
from assistant.browser import Element, Snapshot
from assistant.chat import ChatSession
from test_chat_ops import SAMPLE, make_ops

models.ALLOW_MODEL_REQUESTS = False
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeBrowser:
    def __init__(self):
        self.submitted: list[int] = []
        self.snap = Snapshot(url="https://forms.example.com/lab", title="Lab section sign-up", login_required=False,
                             text="Pick a section", elements=[Element(3, "button", "Sign up", kind="submit")])

    async def open(self, url):
        return self.snap

    async def submit(self, ref):
        self.submitted.append(ref)
        return Snapshot(url=self.snap.url, title="Thanks", login_required=False, text="You're signed up", elements=[])

    def describe_ref(self, ref):
        return f'"Sign up" on Lab section sign-up'


def submit_then_answer(messages, info: AgentInfo) -> ModelResponse:
    if len(messages) == 1:
        return ModelResponse(parts=[ToolCallPart("browser_submit", {"ref": 3})])
    return ModelResponse(parts=[TextPart("done, you're signed up")])


async def test_submit_waits_for_yes(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    ops.browser = FakeBrowser()
    agent = build_agent("test", persona="p")
    session = ChatSession(agent, ops, store, conversation_id="tg:1")
    with agent.override(model=FunctionModel(submit_then_answer)):
        reply = await session.handle("sign me up for the tuesday lab")
        assert reply == 'about to click "Sign up" on Lab section sign-up. reply yes to go ahead or no to skip'
        assert ops.browser.submitted == []                      # nothing happened yet
        reply = await session.handle("yes")
    assert reply == "done, you're signed up"
    assert ops.browser.submitted == [3]
    assert session.pending is None


async def test_submit_can_be_declined(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    ops.browser = FakeBrowser()
    agent = build_agent("test", persona="p")
    session = ChatSession(agent, ops, store, conversation_id="tg:1")

    def fn(messages, info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("browser_submit", {"ref": 3})])
        return ModelResponse(parts=[TextPart("ok, skipped it")])

    with agent.override(model=FunctionModel(fn)):
        await session.handle("sign me up")
        reply = await session.handle("no")
    assert reply == "ok, skipped it" and ops.browser.submitted == []


async def test_new_message_while_pending_cancels_the_pending_submit(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    ops.browser = FakeBrowser()
    agent = build_agent("test", persona="p")
    session = ChatSession(agent, ops, store, conversation_id="tg:1")
    calls = []

    def fn(messages, info: AgentInfo) -> ModelResponse:
        calls.append(len(messages))
        if len(calls) == 1:
            return ModelResponse(parts=[ToolCallPart("browser_submit", {"ref": 3})])
        return ModelResponse(parts=[TextPart("fine")])

    with agent.override(model=FunctionModel(fn)):
        await session.handle("sign me up")
        reply = await session.handle("actually what's due today")
    assert ops.browser.submitted == [] and session.pending is None
    assert reply.startswith("skipped the pending click")


async def test_background_job_proposal_is_approved_or_declined_over_chat(tmp_path):
    """A scheduled job can leave a proposal in the store; the next yes/no in chat answers it."""
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="p")
    session = ChatSession(agent, ops, store, conversation_id="tg:1")
    seen: list = []

    async def on_gradescope(payload, approved):
        seen.append((payload, approved))
        return "linked 1, added 2" if approved else "ok, skipped gradescope for now"

    session.job_handlers["gradescope_first_run"] = on_gradescope
    session.propose_job("gradescope_first_run", {"link": [1], "new": [2, 3]}, "gradescope found 3 things. reply yes or no")
    assert store.kv_get("pending_job") is not None

    with agent.override(model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("chat reply")]))):
        assert await session.handle("yes") == "linked 1, added 2"
        assert seen == [({"link": [1], "new": [2, 3]}, True)]
        assert store.kv_get("pending_job") is None
        assert await session.handle("hello") == "chat reply"          # nothing pending: normal chat

        session.propose_job("gradescope_first_run", {"x": 1}, "again?")
        assert await session.handle("no") == "ok, skipped gradescope for now"
        session.propose_job("gradescope_first_run", {"x": 2}, "again?")
        reply = await session.handle("what's due today")                # unrelated message: proposal stays pending
        assert reply == "chat reply" and store.kv_get("pending_job") is not None
