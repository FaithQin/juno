"""Answering an earlier message, and keeping web-search citations out of replies (Faith, 2026-10-03).

- A Telegram reply carries the message she replied to; juno sees it with her text.
- Texts juno sent on its own (nudges, the brief, sync notes) are part of the conversation, so she
  can answer them with or without Telegram's reply.
- Replying yes/no to a proposal's message answers that proposal, however long ago it was asked;
  a reply to an older question it replaced never does (2026-10-04).
- Web-search citations are stripped from replies unless she asks for sources.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from assistant.agent import build_agent
from assistant.channels.telegram import reply_of
from assistant.chat import ChatSession, Reply, asks_for_sources, tidy_reply
from test_chat_ops import NOW, SAMPLE, make_ops

models.ALLOW_MODEL_REQUESTS = False
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# -- telegram: what the quoted message was ------------------------------------------------------

def test_reply_of_reads_the_quoted_message_and_who_sent_it():
    sent = datetime(2026, 9, 23, 3, 0, tzinfo=timezone.utc)
    juno_msg = SimpleNamespace(text="due tomorrow 11:59pm: CME 102: Pset 2", caption=None, photo=None,
                               from_user=SimpleNamespace(is_bot=True), date=sent)
    msg = SimpleNamespace(text="push it to sunday", reply_to_message=juno_msg, quote=None)
    assert reply_of(msg) == Reply("due tomorrow 11:59pm: CME 102: Pset 2", from_juno=True, sent_at=sent)

    msg.quote = SimpleNamespace(text="CME 102: Pset 2")                       # she highlighted part of it
    assert reply_of(msg).text == "CME 102: Pset 2"

    photo = SimpleNamespace(text=None, caption=None, photo=[object()], from_user=SimpleNamespace(is_bot=False), date=sent)
    assert reply_of(SimpleNamespace(reply_to_message=photo, quote=None)) == Reply("[a photo]", from_juno=False, sent_at=sent)
    assert reply_of(SimpleNamespace(text="hi", reply_to_message=None, quote=None)) is None


async def test_the_telegram_handler_passes_the_reply_along():
    from test_telegram import FakeBot, FakeMessage, make_channel

    seen = []

    async def on_message(text, reply_to=None):
        seen.append((text, reply_to))
        return "moved it"

    ch = make_channel([42], on_message)
    msg = FakeMessage("push it to sunday")
    msg.reply_to_message = SimpleNamespace(text="due tomorrow: CME 102: Pset 2", caption=None, photo=None,
                                           from_user=SimpleNamespace(is_bot=True), date=None)
    msg.quote = None
    await ch._on_text(SimpleNamespace(effective_chat=SimpleNamespace(id=42), message=msg), None)
    assert seen == [("push it to sunday", Reply("due tomorrow: CME 102: Pset 2", from_juno=True, sent_at=None))]
    assert msg.replies == ["moved it"]


# -- the session: the quote rides on her message --------------------------------------------------

def prompts(messages):
    return [p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, UserPromptPart)]


async def test_her_message_carries_the_message_she_replied_to(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="p")
    seen = []

    def fn(messages, info: AgentInfo):
        seen.append(messages)
        return ModelResponse(parts=[TextPart("on it")])

    session = ChatSession(agent, ops, store, conversation_id="tg:1")
    nudge = Reply("due tomorrow 11:59pm: CME 102: Pset 2", from_juno=True, sent_at=NOW - timedelta(hours=14))
    with agent.override(model=FunctionModel(fn)):
        await session.handle("push it to sunday", reply_to=nudge)
        await session.handle("and this one too", reply_to=Reply("CME 102: Find HW due dates", from_juno=False, sent_at=None))
    assert prompts(seen[0])[-1] == ('[wed sep 23, 10:00am] (replying to your message from tue sep 22, 8:00pm: '
                                    '"due tomorrow 11:59pm: CME 102: Pset 2") push it to sunday')
    assert prompts(seen[1])[-1] == '[wed sep 23, 10:00am] (replying to her own earlier message: "CME 102: Find HW due dates") and this one too'


async def test_replying_yes_to_an_old_proposal_answers_it(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="p")
    session = ChatSession(agent, ops, store, conversation_id="tg:1")
    answers = []

    async def on_outlook(payload, approved):
        answers.append(approved)
        return "linked 6 existing events, nothing new to add"

    session.job_handlers["outlook_new"] = on_outlook
    question = "outlook: 6 upcoming meetings aren't on your google calendar yet.\n- Faith <> Tim (fri sep 25 9:00am) → Tim intro"
    store.propose_job("outlook_new", {"digest": "d"}, question, at=NOW - timedelta(days=2))
    store.save_messages("tg:1", b"[]", at=NOW - timedelta(days=1))          # lots of chat since: a bare yes wouldn't count

    with agent.override(model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("chat reply")]))):
        assert await session.handle("yes", reply_to=Reply("some other message", from_juno=True, sent_at=None)) == "chat reply"
        assert answers == []
        reply = await session.handle("yes", reply_to=Reply(question, from_juno=True, sent_at=NOW - timedelta(days=2)))
    assert reply == "linked 6 existing events, nothing new to add" and answers == [True]
    assert store.pending_job() is None


OLD_DUPES = ("todoist: 2 pairs look like duplicates.\n- Breakfast looks like a copy of Breakfast (both due sun sep 28)\n"
             "- CME 102: Pset1 work block looks like a copy of CME 102: Pset1 work block\n"
             "reply yes to delete the copies (undoable), or no to keep them all")
NEW_DUPES = ("todoist: 2 pairs look like duplicates.\n"
             "- ENGR 40M: Lab 1 prelab (Gradescope) looks like a copy of ENGR 40M: Prelab 1 (Gradescope)\n"
             "- EE 160A: HW1 (due Fri Oct 9, week 3) looks like a copy of EE 160A: HW1 (Gradescope)\n"
             "reply yes to delete the copies (undoable), or no to keep them all")


async def test_a_reply_to_a_replaced_question_does_not_answer_the_new_one(tmp_path):
    """Every duplicates question shares its first and last lines. A yes to a line quoted from an older
    question, since replaced, must not delete the tasks the new question is about (2026-10-04)."""
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="p")
    session = ChatSession(agent, ops, store, conversation_id="tg:1")
    answers = []

    async def handler(payload, approved):
        answers.append(approved)
        return "deleted 2 copies"

    session.job_handlers["duplicates"] = handler
    asked = NOW - timedelta(hours=1)
    store.propose_job("duplicates", {"digest": "new"}, NEW_DUPES, at=asked)
    old_sent = NOW - timedelta(days=6)

    out_of_date = ("nothing done: that question was replaced on wed sep 23, 9:00am. "
                   f"here's the current one, reply yes or no to it:\n\n{NEW_DUPES}")
    with agent.override(model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("chat reply")]))):
        for quoted in ("reply yes to delete the copies (undoable), or no to keep them all",
                       "todoist: 2 pairs look like duplicates."):
            assert await session.handle("yes", reply_to=Reply(quoted, from_juno=True, sent_at=old_sent)) == out_of_date
        assert await session.handle("no", reply_to=Reply(OLD_DUPES, from_juno=True, sent_at=old_sent)) == out_of_date
        assert answers == [] and store.pending_job() is not None

        # when Telegram doesn't say when the message was sent, a yes can't be placed: the model asks
        await session.handle("yes", reply_to=Reply("todoist: 2 pairs look like duplicates.", from_juno=True, sent_at=None))
        assert answers == []

        # the new question's own message (Telegram's clock a few seconds behind juno's is fine)
        reply = await session.handle("yes", reply_to=Reply(NEW_DUPES, from_juno=True, sent_at=asked - timedelta(seconds=5)))
    assert reply == "deleted 2 copies" and answers == [True]


async def test_the_model_cannot_approve_a_question_from_a_reply_to_the_one_it_replaced(tmp_path):
    """More than a bare yes ("yes delete them") goes to the model; answer_proposal is shut for that turn,
    and for any reply to a message sent before the question was asked."""
    from pydantic_ai.messages import ToolCallPart, ToolReturnPart

    ops, store, _ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="p")
    session = ChatSession(agent, ops, store, conversation_id="tg:1")
    answers = []

    async def handler(payload, approved):
        answers.append(approved)
        return "deleted 2 copies"

    session.job_handlers["duplicates"] = handler
    store.propose_job("duplicates", {"digest": "new"}, NEW_DUPES, at=NOW - timedelta(hours=1))

    def via_tool(messages, info: AgentInfo) -> ModelResponse:
        ret = next((p for p in messages[-1].parts if isinstance(p, ToolReturnPart)), None)
        if ret is None:
            return ModelResponse(parts=[ToolCallPart("answer_proposal", {"approved": True})])
        return ModelResponse(parts=[TextPart(ret.content)])

    with agent.override(model=FunctionModel(via_tool)):
        reply = await session.handle("yes delete them", reply_to=Reply(OLD_DUPES, from_juno=True, sent_at=NOW - timedelta(days=6)))
        assert reply.startswith("not done: she's replying to a message from before this question was asked")
        brief = Reply("good morning. due today: CME 102: Pset 2", from_juno=True, sent_at=NOW - timedelta(hours=3))
        assert await session.handle("yes", reply_to=brief) == reply                     # not a question: the model, shut out
        assert answers == [] and store.pending_job() is not None
        # the next message isn't a reply to the old one: the model can answer again
        assert await session.handle("yes go ahead and delete the engr and ee copies") == "deleted 2 copies"
    assert answers == [True]


# -- texts juno sent on its own are part of the conversation ----------------------------------------

async def test_texts_juno_sent_on_its_own_are_in_the_conversation(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="p")
    seen = []

    def fn(messages, info: AgentInfo):
        seen.append(messages)
        return ModelResponse(parts=[TextPart("nice, ticked it")])

    session = ChatSession(agent, ops, store, conversation_id="tg:1")
    session.note_sent("due tomorrow 11:59pm: CME 102: Pset 2 (thu 11:59pm)", at=NOW - timedelta(hours=1))
    with agent.override(model=FunctionModel(fn)):
        await session.handle("done with that one")
    said = [p.content for m in seen[0] if isinstance(m, ModelResponse) for p in m.parts if isinstance(p, TextPart)]
    assert said == ["due tomorrow 11:59pm: CME 102: Pset 2 (thu 11:59pm)"]


async def test_a_text_juno_sent_on_its_own_does_not_make_a_proposal_stale(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="p")
    session = ChatSession(agent, ops, store, conversation_id="tg:1")
    answers = []

    async def handler(payload, approved):
        answers.append(approved)
        return "done"

    session.job_handlers["duplicates"] = handler
    store.propose_job("duplicates", {"digest": "d"}, "todoist: 1 pair looks like duplicates.", at=NOW - timedelta(minutes=30))
    session.note_sent("starting 10:15am: CME 102 Pset 2: work block (1h)", at=NOW - timedelta(minutes=10))
    with agent.override(model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("chat")]))):
        assert await session.handle("yes") == "done"
    assert answers == [True]


# -- sources only when she asks -------------------------------------------------------------------------

CITED = ("sip some water and sit down. ([medlineplus.gov](https://www.medlineplus.gov/ency/article/003093.htm?utm_source=openai))"
         "\n\nper [nih.gov](https://www.nih.gov/x?a=1&utm_source=openai), rest helps.\n\nsignups: https://cs198.stanford.edu/signups")


def test_tidy_reply_drops_web_citations_but_keeps_links_she_asked_for():
    assert tidy_reply(CITED, keep_sources=False) == (
        "sip some water and sit down.\n\nper nih.gov, rest helps.\n\nsignups: https://cs198.stanford.edu/signups")
    assert tidy_reply(CITED, keep_sources=True) == (
        "sip some water and sit down. (https://www.medlineplus.gov/ency/article/003093.htm)"
        "\n\nper nih.gov (https://www.nih.gov/x?a=1), rest helps.\n\nsignups: https://cs198.stanford.edu/signups")


def test_asks_for_sources():
    assert asks_for_sources("what are your sources?") and asks_for_sources("link?") and asks_for_sources("where did you get that")
    assert not asks_for_sources("what's due today") and not asks_for_sources("i feel woozy")


async def test_the_session_strips_citations_unless_she_asked(tmp_path):
    ops, store, _ = make_ops(tmp_path, SAMPLE)
    agent = build_agent("test", persona="p")
    session = ChatSession(agent, ops, store, conversation_id="tg:1")
    with agent.override(model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart(CITED)]))):
        assert "utm_source" not in await session.handle("i feel woozy")
        assert "https://www.medlineplus.gov/ency/article/003093.htm" in await session.handle("sources?")
