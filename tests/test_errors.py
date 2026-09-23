"""Model/API failures become one honest sentence in juno's voice, never a traceback."""

from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded

from assistant.errors import describe_error


def test_no_credits_is_explained_plainly():
    e = ModelHTTPError(status_code=429, model_name="gpt-6-sol",
                       body={"code": "credit_balance_exhausted", "message": "You have no credits remaining."})
    assert describe_error(e) == "openai says the account has no credits left. add some at platform.openai.com → billing and try again"


def test_rate_limit_and_auth_and_unknown():
    assert describe_error(ModelHTTPError(status_code=429, model_name="m", body={"code": "rate_limit_exceeded"})) == \
        "openai is rate-limiting me right now. try again in a minute"
    assert describe_error(ModelHTTPError(status_code=401, model_name="m", body={})) == \
        "openai rejected the api key. check OPENAI_API_KEY in .env"
    assert describe_error(UsageLimitExceeded("too many")) == "that took more steps than i allow per message. try asking in a smaller piece"
    assert describe_error(RuntimeError("boom")) == "something broke on my end (RuntimeError). try again in a sec"


def test_timeout_is_explained():
    assert describe_error(TimeoutError()) == "that took too long and i gave up. try again, maybe in smaller pieces"
