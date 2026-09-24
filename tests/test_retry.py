"""Transient upstream errors (a Todoist 503, a dropped connection) are retried with backoff; real errors are not."""

import httpx
import pytest
import requests
from canvasapi.exceptions import CanvasException, ResourceDoesNotExist

from assistant.retry import describe_briefly, is_transient, retrying

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://api.todoist.com/api/v1/tasks")
    return httpx.HTTPStatusError("boom", request=req, response=httpx.Response(status, request=req))


def test_is_transient_recognises_upstream_hiccups_only():
    assert is_transient(http_error(503)) and is_transient(http_error(502)) and is_transient(http_error(429))
    assert not is_transient(http_error(404)) and not is_transient(http_error(401))
    assert is_transient(httpx.ConnectError("no route"))
    assert is_transient(requests.ConnectionError("reset"))
    assert is_transient(CanvasException("Encountered an error: status code 502"))
    assert not is_transient(ResourceDoesNotExist("Not Found"))
    assert not is_transient(ValueError("bad input"))


def test_describe_briefly_names_the_status():
    assert describe_briefly(http_error(503)) == "503 Service Unavailable"
    assert describe_briefly(httpx.ConnectError("x")) == "ConnectError"


async def test_retrying_waits_then_succeeds():
    calls, naps = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise http_error(503)
        return "ok"

    async def sleep(s):
        naps.append(s)

    assert await retrying(flaky, label="todoist", delays=(5, 20, 60), sleep=sleep) == "ok"
    assert naps == [5, 20]


async def test_retrying_gives_up_after_the_delays_and_never_retries_real_errors():
    naps = []

    async def sleep(s):
        naps.append(s)

    def always_503():
        raise http_error(503)

    with pytest.raises(httpx.HTTPStatusError):
        await retrying(always_503, label="todoist", delays=(1, 2), sleep=sleep)
    assert naps == [1, 2]

    def bad():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await retrying(bad, label="todoist", delays=(1, 2), sleep=sleep)
    assert naps == [1, 2]                        # no extra sleeps: it failed straight away
