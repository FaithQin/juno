"""Ed Discussion through its (undocumented but stable) API: courses, threads, announcements text."""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from assistant.ed import EdClient, document_to_text, format_announcements, match_course

TZ = ZoneInfo("America/Los_Angeles")

USER = {"courses": [
    {"course": {"id": 70001, "code": "CS 106B", "name": "Programming Abstractions", "year": "2026", "session": "Autumn", "status": "active"}},
    {"course": {"id": 60001, "code": "CS 106B", "name": "Programming Abstractions", "year": "2025", "session": "Autumn", "status": "archived"}},
    {"course": {"id": 70002, "code": "ENGR 40M", "name": "An Intro to Making", "year": "2026", "session": "Autumn", "status": "active"}},
]}
THREADS = {"threads": [
    {"id": 9001, "number": 12, "type": "announcement", "title": "Section sign-ups open Thursday", "category": "Logistics",
     "is_pinned": True, "created_at": "2026-09-23T15:04:05Z",
     "document": "<document version=\"2.0\"><paragraph>Sign-ups open <bold>Thu 12pm</bold> at <link href=\"https://cs198.stanford.edu/section/signup\">the portal</link>.</paragraph><paragraph>Sections start week 2.</paragraph></document>"},
    {"id": 9002, "number": 13, "type": "question", "title": "Help with A0", "category": "Assignments", "is_pinned": False,
     "created_at": "2026-09-23T16:00:00Z", "document": "<document><paragraph>How do I…</paragraph></document>"},
    {"id": 9003, "number": 11, "type": "post", "title": "Welcome!", "category": "General", "is_pinned": True,
     "created_at": "2026-09-20T10:00:00Z", "document": "<document><paragraph>Welcome to the course.</paragraph></document>"},
]}


def fake_fetch(url, headers):
    assert headers["Authorization"] == "Bearer tok"
    if url.endswith("/api/user"):
        return 200, json.dumps(USER)
    if "/api/courses/70001/threads" in url:
        return 200, json.dumps(THREADS)
    return 404, "{}"


def test_document_to_text_flattens_ed_markup_and_keeps_links():
    doc = THREADS["threads"][0]["document"]
    assert document_to_text(doc) == "Sign-ups open Thu 12pm at the portal (https://cs198.stanford.edu/section/signup).\nSections start week 2."


def test_courses_and_active_match():
    ed = EdClient("tok", fetch=fake_fetch)
    courses = ed.courses()
    assert [(c.id, c.code, c.status) for c in courses] == [(70001, "CS 106B", "active"), (60001, "CS 106B", "archived"), (70002, "ENGR 40M", "active")]
    assert match_course(courses, "cs106b").id == 70001          # the active one, not last year's
    assert match_course(courses, "physics") is None


def test_threads_and_announcement_formatting():
    ed = EdClient("tok", fetch=fake_fetch)
    threads = ed.threads(70001)
    assert [t.id for t in threads] == [9001, 9002, 9003]
    assert threads[0].url == "https://edstem.org/us/courses/70001/discussion/9001"
    assert threads[0].created_at == datetime(2026, 9, 23, 15, 4, 5, tzinfo=timezone.utc)
    text = format_announcements(threads, course_code="CS 106B", tz=TZ, limit=5)
    lines = text.splitlines()
    assert lines[0] == "CS 106B announcements and pinned posts (newest first):"
    assert lines[1] == "- wed sep 23 · Section sign-ups open Thursday [announcement, pinned]"
    assert lines[2] == "  Sign-ups open Thu 12pm at the portal (https://cs198.stanford.edu/section/signup). Sections start week 2."
    assert lines[3] == "  https://edstem.org/us/courses/70001/discussion/9001"
    assert "Welcome!" in text and "Help with A0" not in text          # questions aren't announcements
