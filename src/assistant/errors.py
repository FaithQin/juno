"""Turn exceptions into one sentence juno can say. Used by the CLI and the Telegram handler."""

from __future__ import annotations

from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "that took too long and i gave up. try again, maybe in smaller pieces"
    if isinstance(exc, ModelHTTPError):
        body = exc.body if isinstance(exc.body, dict) else {}
        code = str(body.get("code") or body.get("type") or "")
        if exc.status_code == 429 and ("credit" in code or "insufficient_quota" in code):
            return "openai says the account has no credits left. add some at platform.openai.com → billing and try again"
        if exc.status_code == 429:
            return "openai is rate-limiting me right now. try again in a minute"
        if exc.status_code in (401, 403):
            return "openai rejected the api key. check OPENAI_API_KEY in .env"
        return f"openai returned an error ({exc.status_code}). try again in a sec"
    if isinstance(exc, UsageLimitExceeded):
        return "that took more steps than i allow per message. try asking in a smaller piece"
    return f"something broke on my end ({type(exc).__name__}). try again in a sec"
