"""Ride out upstream hiccups. Todoist answered 503 at 07:00 one morning and the brief never went
out; a 502 ten minutes later killed a nudge scan. Neither is worth a traceback: wait and try again.

`is_transient` says whether an error is the kind that goes away by itself (5xx, rate limits,
dropped connections). `retrying` runs a blocking call on a worker thread and, on such errors,
sleeps through the given delays before giving up. Real errors (401, 404, a bug) raise at once.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable, TypeVar

import httpx
import requests
from canvasapi.exceptions import CanvasException, RateLimitExceeded

T = TypeVar("T")
log = logging.getLogger(__name__)

TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}
DELAYS: tuple[float, ...] = (5, 20, 60, 180, 300)     # about ten minutes in all: long enough for a Todoist blip
STATUS_IN_MESSAGE = re.compile(r"status code (\d{3})")   # canvasapi folds 5xx into a generic CanvasException


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in TRANSIENT_STATUS
    if isinstance(exc, (httpx.TransportError, requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, RateLimitExceeded):
        return True
    if isinstance(exc, CanvasException):
        m = STATUS_IN_MESSAGE.search(str(exc))
        return bool(m) and int(m[1]) in TRANSIENT_STATUS
    return isinstance(exc, (ConnectionError, TimeoutError))


def describe_briefly(exc: BaseException) -> str:
    """'503 Service Unavailable' or the exception's class name: enough for a log line or a text."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{exc.response.status_code} {exc.response.reason_phrase}".strip()
    return type(exc).__name__


async def retrying(fn: Callable[[], T], *, label: str, delays: tuple[float, ...] = DELAYS,
                   sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> T:
    """Run `fn` on a worker thread; on a transient error, wait through `delays` and try again."""
    for attempt, delay in enumerate(delays, start=1):
        try:
            return await asyncio.to_thread(fn)
        except Exception as e:
            if not is_transient(e):
                raise
            log.warning("%s: %s; retry %d in %ss", label, describe_briefly(e), attempt, delay)
            await sleep(delay)
    return await asyncio.to_thread(fn)
