"""One-shot commands must shut the browser down before the event loop closes."""

import pytest

from assistant.app import with_cleanup

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeBrowser:
    stopped = False

    async def stop(self):
        self.stopped = True


class FakeOps:
    def __init__(self):
        self.browser = FakeBrowser()


async def test_with_cleanup_stops_the_browser_even_when_the_work_fails():
    ops = FakeOps()

    async def work():
        return "answer"

    assert await with_cleanup(ops, work()) == "answer"
    assert ops.browser.stopped

    ops = FakeOps()

    async def boom():
        raise RuntimeError("model down")

    with pytest.raises(RuntimeError):
        await with_cleanup(ops, boom())
    assert ops.browser.stopped
