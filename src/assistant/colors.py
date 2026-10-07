"""Google Calendar event colors by name, and the scheme Faith uses for her own events.

Google has eleven event colors, addressed by id ("1".."11") with names only in its UI. Faith says
"make it green" or "the color I use for classes", so `color_id` takes Google's names and plain
words alike. Her scheme, read from her Stanford calendar on 2026-10-03: classes and sections
Flamingo, audited classes Grape, exams Tomato, everything else the calendar's default. juno uses
it for events it adds (her choice that day) unless she names a color; synced copies of Canvas
and Outlook events keep the default.

2026-10-06: auditing ended, so there is no audit color in her config any more; and her HOLD markers
("HOLD: <Name> (<Org>)", a time held for a meeting that isn't confirmed) are Graphite, to set them
apart from confirmed meetings. A hold beats every other kind, and juno never recolors one
(`ChatOps.color_event`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EVENT_COLORS = {"lavender": "1", "sage": "2", "grape": "3", "flamingo": "4", "banana": "5", "tangerine": "6",
                "peacock": "7", "graphite": "8", "blueberry": "9", "basil": "10", "tomato": "11"}
PLAIN_WORDS = {
    "light blue": "lavender", "periwinkle": "lavender", "light purple": "lavender",
    "light green": "sage", "mint": "sage", "purple": "grape", "violet": "grape",
    "pink": "flamingo", "salmon": "flamingo", "coral": "flamingo", "yellow": "banana", "orange": "tangerine",
    "teal": "peacock", "turquoise": "peacock", "cyan": "peacock", "aqua": "peacock",
    "gray": "graphite", "grey": "graphite", "blue": "blueberry", "dark blue": "blueberry",
    "green": "basil", "dark green": "basil", "red": "tomato",
}
DEFAULT_WORDS = {"default", "none", "no color", "calendar color", "calendar default", "reset", "clear", "normal"}
NAMES = ", ".join(EVENT_COLORS)
_BY_ID = {v: k for k, v in EVENT_COLORS.items()}
# "Final Cut Pro" is not an exam; "finals", "final exam", "midterm 1" are.
EXAM_RE = re.compile(r"\b(mid-?terms?|final exams?|finals|exams?|quiz(?:zes)?)\b", re.I)
HOLD_RE = re.compile(r"^\s*hold\s*:", re.I)      # "HOLD: Nathan (Andrews Cooper)"; not "Holden", not "Placeholder:"


def is_hold(title: str) -> bool:
    return bool(HOLD_RE.match(title or ""))


def color_id(name: str | None) -> str | None:
    """'Flamingo', 'pink' or '4' → '4'; 'default' → '' (clear the color); anything else → None."""
    key = " ".join((name or "").strip().lower().replace("colour", "color").split())
    if key in DEFAULT_WORDS:
        return ""
    if key in _BY_ID:
        return key
    return EVENT_COLORS.get(PLAIN_WORDS.get(key, key))


def color_name(cid: str | None) -> str:
    return _BY_ID.get(cid or "", "default")


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass(frozen=True)
class ColorScheme:
    """Color names per kind of event; `courses` are her graded course codes, `audits` the ones she
    audits (aliases included, e.g. AA 174A for EE 160A)."""
    klass: str | None = "flamingo"
    audit: str | None = None
    exam: str | None = "tomato"
    hold: str | None = "graphite"
    courses: tuple[str, ...] | list[str] = field(default_factory=tuple)
    audits: tuple[str, ...] | list[str] = field(default_factory=tuple)

    def pick(self, title: str) -> str | None:
        """The color id her scheme gives an event with this title, or None for the calendar default."""
        squashed = _squash(title)

        def mentions(codes) -> bool:
            return any(_squash(c) and _squash(c) in squashed for c in codes)

        if is_hold(title):
            kind = self.hold
        elif EXAM_RE.search(title):
            kind = self.exam
        elif self.audit and (re.search(r"\baudit\b", title, re.I) or mentions(self.audits)):
            kind = self.audit
        elif mentions(self.courses):
            kind = self.klass
        else:
            return None
        return color_id(kind) or None if kind else None
