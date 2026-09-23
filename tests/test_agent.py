"""The language-model layer: tools are wired to ChatOps, and history round-trips through SQLite.

No network: pydantic-ai's TestModel and FunctionModel stand in for OpenAI.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic_ai import capture_run_messages, models
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from assistant.agent import build_agent
from assistant.chat import ChatSession
from test_chat_ops import SAMPLE, make_ops

models.ALLOW_MODEL_REQUESTS = False
pytestmark = pytest.mark.anyio

EXPECTED_TOOLS = {
    "get_tasks", "get_schedule", "add_task", "complete_task", "reschedule_task",
    "snooze_reminder", "remember", "forget", "undo",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_agent_exposes_exactly_the_agreed_tools(tmp_path):
    ops, *_ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="be brief")
    model = TestModel(call_tools=[], custom_output_text="hi")
    with agent.override(model=model):
        result = await agent.run("hello", deps=ops)
    assert result.output == "hi"
    assert {t.name for t in model.last_model_request_parameters.function_tools} == EXPECTED_TOOLS


async def test_persona_and_live_context_reach_the_model(tmp_path):
    ops, *_ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="you are juno. lowercase, brief.")
    seen: dict = {}

    def fn(messages, info: AgentInfo) -> ModelResponse:
        seen["instructions"] = messages[0].instructions
        return ModelResponse(parts=[TextPart("ok")])

    with agent.override(model=FunctionModel(fn)):
        await agent.run("hi", deps=ops)
    assert "you are juno" in seen["instructions"]
    assert "now: wed sep 23, 10:00am" in seen["instructions"]
    assert "courses: ENGR 40M" in seen["instructions"]


async def test_tool_call_reaches_chat_ops_and_result_returns_to_model(tmp_path):
    ops, *_ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="p")

    def fn(messages, info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("get_tasks", {"scope": "today"})])
        return ModelResponse(parts=[TextPart("two things today")])

    with agent.override(model=FunctionModel(fn)), capture_run_messages() as messages:
        result = await agent.run("what's due today?", deps=ops)
    assert result.output == "two things today"
    returns = [p for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]
    assert returns and returns[0].content.startswith("due today:")
    assert "Sign up for a lab section" in returns[0].content


async def test_write_tool_acts_immediately_and_is_undoable(tmp_path):
    ops, store, todoist = make_ops(tmp_path)
    agent = build_agent("test", persona="p")

    def fn(messages, info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("add_task", {"title": "hw1", "due": "2026-09-24T23:59", "course": "cme102"})])
        return ModelResponse(parts=[TextPart("added it")])

    with agent.override(model=FunctionModel(fn)):
        await agent.run("add cme102 hw1 due thu 11:59", deps=ops)
    assert [t.content for t in todoist.tasks("CLASSES")] == ["CME 102: hw1"]
    assert store.last_undoable().kind == "add_task"


async def test_chat_session_persists_and_reloads_recent_history(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="p")
    counts: list[int] = []

    def fn(messages, info: AgentInfo) -> ModelResponse:
        counts.append(len(messages))
        return ModelResponse(parts=[TextPart(f"reply {len(counts)}")])

    session = ChatSession(agent, ops, store, conversation_id="tg:1")
    with agent.override(model=FunctionModel(fn)):
        assert await session.handle("hi") == "reply 1"
        assert await session.handle("again") == "reply 2"
    assert counts == [1, 3]                      # second run saw request+response of the first, plus its own
    assert len(store.load_messages("tg:1", since=ops.now() - timedelta(hours=24))) == 2
    assert int(store.kv_get("tokens:2026-09-23") or 0) >= 0   # usage is recorded per day


def test_agent_uses_low_reasoning_effort_and_no_sampling_params():
    agent = build_agent("openai:gpt-6-sol", persona="p")
    settings = dict(agent.model_settings or {})
    assert settings.get("openai_reasoning_effort") == "low"
    assert "temperature" not in settings
    assert settings.get("timeout") == 60


async def test_chat_session_gives_up_after_the_run_timeout(tmp_path):
    import anyio
    from datetime import timedelta as _td

    ops, store, _ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="p")

    async def slow(messages, info: AgentInfo) -> ModelResponse:
        await anyio.sleep(1)
        return ModelResponse(parts=[TextPart("late")])

    session = ChatSession(agent, ops, store, conversation_id="tg:1", run_timeout=_td(milliseconds=50))
    with agent.override(model=FunctionModel(slow)):
        with pytest.raises(TimeoutError):
            await session.handle("hi")


async def test_persona_is_reloaded_every_run_when_given_a_loader(tmp_path):
    ops, *_ = make_ops(tmp_path, SAMPLE)
    persona = {"text": "version one"}
    agent = build_agent("test", persona=lambda: persona["text"])   # a loader, not a string
    seen: list[str] = []

    def fn(messages, info: AgentInfo) -> ModelResponse:
        seen.append(messages[0].instructions)
        return ModelResponse(parts=[TextPart("ok")])

    with agent.override(model=FunctionModel(fn)):
        await agent.run("hi", deps=ops)
        persona["text"] = "version two"
        await agent.run("hi", deps=ops)
    assert "version one" in seen[0] and "version two" in seen[1]
    assert seen[1].index("version two") < seen[1].index("now:")   # persona before live context
