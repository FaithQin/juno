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
