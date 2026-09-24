"""Ed Discussion via its API: one request for a course's announcements instead of a browser trip.

The API isn't officially documented; the endpoints below are the ones the Ed web
app itself uses and that community clients (edapi) have relied on for years.
Token: edstem.org/us/settings/api-tokens → ED_API_TOKEN in .env.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

API_BASE = "https://us.edstem.org/api"
WEB_BASE = "https://edstem.org/us"

Fetch = Callable[[str, dict], tuple[int, str]]


@dataclass(frozen=True)
class EdCourse:
    id: int
    code: str
    name: str
    status: str
    year: str
    session: str


@dataclass(frozen=True)
class EdThread:
    id: int
    number: int
    type: str            # announcement | post | question
    title: str
    text: str
    category: str
    is_pinned: bool
    created_at: datetime
    url: str


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def document_to_text(document: str) -> str:
    """Ed stores posts as XML-ish markup; keep paragraph breaks and link targets."""
    if not document:
        return ""
    doc = re.sub(r'<link[^>]*href="([^"]+)"[^>]*>(.*?)</link>', r"\2 (\1)", document, flags=re.S)
    doc = re.sub(r"</paragraph>|</heading>|</list-item>|<break\s*/?>", "\n", doc)
    doc = re.sub(r"<[^>]+>", "", doc)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in doc.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def ed_token_from_session(path: Path) -> str | None:
    """The Ed web app keeps its auth token in browser local storage; the saved login
    (`browser-login ed`) captures it, so no separate API token is needed."""
    try:
        state = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    for origin in state.get("origins", []):
        if "edstem" not in origin.get("origin", ""):
            continue
        for item in origin.get("localStorage", []):
            if item.get("name") == "authToken" and item.get("value"):
                return item["value"]
    return None


def default_fetch(url: str, headers: dict) -> tuple[int, str]:
    r = httpx.get(url, headers=headers, timeout=20)
    return r.status_code, r.text


class EdClient:
    def __init__(self, token: str, fetch: Fetch = default_fetch, *, scheme: str = "bearer"):
        self.token = token
        self.fetch = fetch
        self.scheme = scheme     # "bearer" for a token from Ed's settings page; "x-token" for the web app's session token

    def _headers(self) -> dict:
        auth = {"x-token": self.token} if self.scheme == "x-token" else {"Authorization": f"Bearer {self.token}"}
        return {**auth, "Accept": "application/json"}

    def _get(self, path: str) -> dict:
        status, body = self.fetch(f"{API_BASE}/{path}", self._headers())
        if status != 200:
            raise RuntimeError(f"ed api {path} → HTTP {status}")
        return json.loads(body)

    def courses(self) -> list[EdCourse]:
        out = []
        for entry in self._get("user").get("courses", []):
            c = entry.get("course") or {}
            out.append(EdCourse(int(c["id"]), c.get("code", ""), c.get("name", ""), c.get("status", ""), str(c.get("year", "")), c.get("session", "")))
        return out

    def threads(self, course_id: int, *, limit: int = 30, sort: str = "new") -> list[EdThread]:
        data = self._get(f"courses/{course_id}/threads?limit={limit}&offset=0&sort={sort}")
        out = []
        for t in data.get("threads", []):
            created = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
            out.append(EdThread(
                id=int(t["id"]), number=int(t.get("number", 0)), type=t.get("type", "post"), title=t.get("title", ""),
                text=document_to_text(t.get("document", "")), category=t.get("category", ""),
                is_pinned=bool(t.get("is_pinned")), created_at=created,
                url=f"{WEB_BASE}/courses/{course_id}/discussion/{t['id']}",
            ))
        return out


def match_course(courses: list[EdCourse], code: str) -> EdCourse | None:
    key = _squash(code)
    hits = sorted((c for c in courses if key and key in _squash(c.code)), key=lambda c: c.id, reverse=True)
    active = [c for c in hits if c.status == "active"]
    return (active or hits or [None])[0]


def format_announcements(threads: list[EdThread], *, course_code: str, tz: ZoneInfo, limit: int = 5) -> str:
    picked = [t for t in threads if t.type == "announcement" or t.is_pinned]
    picked.sort(key=lambda t: t.created_at, reverse=True)
    picked = picked[:limit]
    if not picked:
        return f"no announcements or pinned posts in {course_code} right now"
    lines = [f"{course_code} announcements and pinned posts (newest first):"]
    for t in picked:
        tags = [t.type] if t.type == "announcement" else []
        if t.is_pinned:
            tags.append("pinned")
        day = t.created_at.astimezone(tz).strftime("%a %b %-d").lower()
        lines.append(f"- {day} · {t.title} [{', '.join(tags)}]")
        body = t.text.replace("\n", " ").strip()
        if body:
            lines.append("  " + (body[:400] + "…" if len(body) > 400 else body))
        lines.append(f"  {t.url}")
    return "\n".join(lines)
