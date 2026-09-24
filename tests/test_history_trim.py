"""Old tool output is shrunk before each model request so browsing turns don't blow the token budget."""

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from assistant.chat import trim_old_tool_returns


def convo(n_tools: int, size: int = 2000):
    msgs = [ModelRequest(parts=[UserPromptPart("hi")])]
    for i in range(n_tools):
        msgs.append(ModelResponse(parts=[ToolCallPart("browse", {"url": f"https://x/{i}"}, tool_call_id=f"c{i}")]))
        msgs.append(ModelRequest(parts=[ToolReturnPart("browse", "x" * size, tool_call_id=f"c{i}")]))
    msgs.append(ModelResponse(parts=[TextPart("done")]))
    return msgs


def returns(msgs):
    return [p for m in msgs if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart)]


def test_keeps_the_last_three_tool_returns_and_shrinks_older_ones():
    out = trim_old_tool_returns(convo(5))
    lens = [len(p.content) for p in returns(out)]
    assert lens[-3:] == [2000, 2000, 2000]
    assert all(l < 400 for l in lens[:-3])
    assert "[older tool output trimmed" in returns(out)[0].content
    assert [len(p.content) for p in returns(convo(5))] == [2000] * 5   # input untouched


def test_small_or_recent_output_is_left_alone():
    out = trim_old_tool_returns(convo(2))
    assert [len(p.content) for p in returns(out)] == [2000, 2000]
    out = trim_old_tool_returns(convo(6, size=100))
    assert [len(p.content) for p in returns(out)] == [100] * 6


# -- previous turns are re-sent as just the conversation: no tool traffic, no reasoning ----------

from pydantic_ai.messages import ThinkingPart

from assistant.chat import compact_previous_turns


def test_compact_previous_turns_keeps_only_what_she_and_juno_said():
    msgs = [
        ModelRequest(parts=[UserPromptPart("hi")]),
        ModelResponse(parts=[ThinkingPart("", id="rs_1", signature="sig"), ToolCallPart("get_tasks", {}, tool_call_id="c1")]),
        ModelRequest(parts=[ToolReturnPart("get_tasks", "3 tasks", tool_call_id="c1")]),
        ModelResponse(parts=[ThinkingPart("", id="rs_2"), TextPart("three things today", id="msg_1")]),
    ]
    out = compact_previous_turns(msgs)
    assert [type(p).__name__ for m in out for p in m.parts] == ["UserPromptPart", "TextPart"]
    assert out[1].parts[0].content == "three things today" and out[1].parts[0].id is None   # replayed as plain text, not by id
    assert len(msgs) == 4 and isinstance(msgs[1].parts[0], ThinkingPart)                    # input untouched


def test_compact_previous_turns_leaves_a_tool_call_still_waiting_on_her_alone():
    pending = ModelResponse(parts=[ThinkingPart("", id="rs_9"), ToolCallPart("browser_submit", {"ref": 3}, tool_call_id="c9")])
    out = compact_previous_turns([ModelRequest(parts=[UserPromptPart("sign me up")]), pending])
    assert out[1] is pending
