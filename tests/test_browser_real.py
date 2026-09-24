"""Drive a real headless Chromium on a local page: no network, skipped if no browser is installed."""

import pytest

from assistant.browser import BrowserSession

pytestmark = pytest.mark.anyio

HTML = """<!doctype html><html><head><title>Lab sign-up</title></head><body>
<h1>Lab sign-up</h1><p>Pick a section and sign up.</p>
<form onsubmit="event.preventDefault(); document.body.innerHTML='<p>thanks '+document.getElementById('n').value+'</p>'">
  <label for="n">Your name</label><input id="n" type="text">
  <label for="s">Section</label>
  <select id="s"><option value="mon">Monday 1-4</option><option value="tue">Tuesday 3-6</option></select>
  <a href="https://example.com/rules">Lab rules</a>
  <button type="submit">Sign up</button>
</form>
<script>var secret = 1;</script>
</body></html>"""


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_snapshot_type_select_and_click_on_a_real_page(tmp_path):
    session = BrowserSession(data_dir=tmp_path, headless=True)
    try:
        await session.start()
    except Exception as e:
        pytest.skip(f"chromium not available: {e}")
    try:
        ctx = await session._context(None)
        session._page = await ctx.new_page()
        await session._page.set_content(HTML)
        snap = await session.snapshot()
        assert snap.title == "Lab sign-up" and snap.login_required is False
        assert "Pick a section and sign up." in snap.text and "secret" not in snap.text
        kinds = {(e.role, e.name) for e in snap.elements}
        assert {("textbox", "Your name"), ("combobox", "Section"), ("link", "Lab rules"), ("button", "Sign up")} <= kinds
        assert next(e for e in snap.elements if e.name == "Sign up").kind == "submit"

        ref = next(e.ref for e in snap.elements if e.name == "Your name")
        snap = await session.type(ref, "Faith")
        assert next(e for e in snap.elements if e.name == "Your name").value == "Faith"

        ref = next(e.ref for e in snap.elements if e.name == "Section")
        snap = await session.select(ref, "Tuesday 3-6")
        assert next(e for e in snap.elements if e.name == "Section").value == "Tuesday 3-6"

        assert session.describe_ref(next(e.ref for e in snap.elements if e.name == "Sign up")) == '"Sign up" on Lab sign-up'
        ref = next(e.ref for e in snap.elements if e.name == "Sign up")
        snap = await session.submit(ref)
        assert "thanks Faith" in snap.text
    finally:
        await session.stop()
