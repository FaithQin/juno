"""Telegram adapter: allowlist, setup mode, reply plumbing, long-message splitting."""

from types import SimpleNamespace

import pytest

from assistant.channels.telegram import TelegramChannel, split_message

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeMessage:
    def __init__(self, text):
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text):
        self.replies.append(text)


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.actions: list[int] = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))

    async def send_chat_action(self, chat_id, action):
        self.actions.append(chat_id)


def update_for(chat_id, text):
    msg = FakeMessage(text)
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id), message=msg), msg


def make_channel(allowed, on_message=None):
    async def default(text):
        return f"echo: {text}"

    ch = TelegramChannel.__new__(TelegramChannel)
    ch.allowed_chat_ids = set(allowed)
    ch.on_message = on_message or default
    ch.bot = FakeBot()
    ch.ignored = []
    return ch


async def test_allowed_chat_gets_a_reply_and_a_typing_indicator():
    ch = make_channel([42])
    update, msg = update_for(42, "what's due")
    await ch._on_text(update, None)
    assert msg.replies == ["echo: what's due"]
    assert ch.bot.actions == [42]


async def test_unknown_chat_is_ignored_silently():
    calls = []

    async def spy(text):
        calls.append(text)
        return "should not happen"

    ch = make_channel([42], spy)
    update, msg = update_for(999, "hi")
    await ch._on_text(update, None)
    assert msg.replies == [] and calls == [] and ch.ignored == [999]


async def test_setup_mode_start_reveals_the_chat_id_when_no_allowlist():
    ch = make_channel([])
    update, msg = update_for(777, "/start")
    await ch._on_start(update, None)
    assert msg.replies and "777" in msg.replies[0] and "TELEGRAM_CHAT_IDS" in msg.replies[0]
    update, msg = update_for(777, "hello")
    await ch._on_text(update, None)
    assert msg.replies == []            # still ignored until the id is in .env


async def test_send_goes_to_every_allowed_chat_in_chunks():
    ch = make_channel([1, 2])
    await ch.send("x" * 5000)
    assert [c for c, _ in ch.bot.sent] == [1, 1, 2, 2]
    assert all(len(t) <= 4096 for _, t in ch.bot.sent)


def test_split_message_prefers_line_boundaries():
    text = "\n".join(f"line {i} " + "y" * 100 for i in range(60))
    parts = split_message(text, limit=1000)
    assert len(parts) > 1
    assert all(len(p) <= 1000 for p in parts)
    assert "\n".join(parts) == text            # nothing lost, split only at newlines
    assert split_message("short", limit=1000) == ["short"]


async def test_reply_with_blank_lines_arrives_as_separate_bubbles():
    async def multi(text):
        return "twelve things today. bold.\n\nfirst up: 8:50am bike to gates\n\n- a\n- b"

    ch = make_channel([42], multi)
    ch.bubble_delay = 0
    update, msg = update_for(42, "what's due")
    await ch._on_text(update, None)
    assert msg.replies == ["twelve things today. bold.", "first up: 8:50am bike to gates", "- a\n- b"]
    assert ch.bot.actions == [42, 42, 42]        # typing indicator before each bubble


async def test_send_also_splits_on_blank_lines():
    ch = make_channel([1])
    ch.bubble_delay = 0
    await ch.send("one\n\ntwo")
    assert [t for _, t in ch.bot.sent] == ["one", "two"]


def test_bubbles_helper():
    from assistant.channels.telegram import bubbles
    assert bubbles("a\n\n\n  b  \n\nc") == ["a", "b", "c"]
    assert bubbles("single\nline list") == ["single\nline list"]
    assert bubbles("   ") == []


async def test_status_command_answers_allowed_chat_only():
    ch = make_channel([42])
    ch.status = lambda: "running on juno-droplet (docker) since wed 10:45am"
    update, msg = update_for(42, "/status")
    await ch._on_status(update, None)
    assert msg.replies == ["running on juno-droplet (docker) since wed 10:45am"]
    update, msg = update_for(999, "/status")
    await ch._on_status(update, None)
    assert msg.replies == [] and ch.ignored == [999]


# -- photos --------------------------------------------------------------------------------------

class FakeFile:
    def __init__(self, data: bytes):
        self.data = data

    async def download_as_bytearray(self):
        return bytearray(self.data)


class FakePhotoBot(FakeBot):
    def __init__(self):
        super().__init__()
        self.files = {"small": b"tiny", "big": b"\xff\xd8 big jpeg"}
        self.fetched: list[str] = []

    async def get_file(self, file_id):
        self.fetched.append(file_id)
        return FakeFile(self.files[file_id])


def photo_update_for(chat_id, caption):
    msg = FakeMessage(None)
    msg.caption = caption
    msg.photo = [SimpleNamespace(file_id="small", width=90), SimpleNamespace(file_id="big", width=1280)]
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id), message=msg), msg


async def test_a_photo_reaches_the_brain_as_an_image_with_its_caption():
    from pydantic_ai.messages import BinaryContent

    seen: list = []

    async def on_message(text, images=None):
        seen.append((text, images))
        return "i see two section times"

    ch = make_channel([42], on_message)
    ch.bot = FakePhotoBot()
    update, msg = photo_update_for(42, "which of these fit?")
    await ch._on_photo(update, None)
    assert msg.replies == ["i see two section times"]
    assert ch.bot.fetched == ["big"]                                   # the largest rendition only
    text, images = seen[0]
    assert text == "which of these fit?"
    assert len(images) == 1 and isinstance(images[0], BinaryContent)
    assert images[0].data == b"\xff\xd8 big jpeg" and images[0].media_type == "image/jpeg"


async def test_a_photo_without_a_caption_still_goes_through():
    seen: list = []

    async def on_message(text, images=None):
        seen.append(text)
        return "got it"

    ch = make_channel([42], on_message)
    ch.bot = FakePhotoBot()
    update, msg = photo_update_for(42, None)
    await ch._on_photo(update, None)
    assert seen == [""] and msg.replies == ["got it"]


async def test_photos_from_unknown_chats_are_ignored():
    ch = make_channel([42])
    ch.bot = FakePhotoBot()
    update, msg = photo_update_for(999, "hi")
    await ch._on_photo(update, None)
    assert msg.replies == [] and ch.bot.fetched == [] and ch.ignored == [999]
