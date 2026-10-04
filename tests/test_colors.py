"""Event colors (Faith, 2026-10-03): by name in chat, and her scheme applied to events juno adds.

Her Stanford calendar, read that day: classes and sections Flamingo, audited classes Grape, exams Tomato.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from assistant.brief import Event
from assistant.colors import ColorScheme, color_id, color_name
from test_chat_ops import make_ops

TZ = ZoneInfo("America/Los_Angeles")
SCHEME = ColorScheme(klass="flamingo", audit="grape", exam="tomato",
                     courses=["ENGR 40M", "CME 102", "EE 100", "CS 106B", "EE 160A"],
                     audits=["EE 227", "CS 227A", "EE 260A", "AA 274A", "AA 174A"])


def test_color_id_takes_google_names_plain_words_and_default():
    assert color_id("Flamingo") == "4" and color_id("pink") == "4" and color_id("green") == "10" and color_id("4") == "4"
    assert color_id("light green") == "2" and color_id("grey") == "8"
    assert color_id("default") == "" and color_id("no color") == ""
    assert color_id("chartreuse") is None and color_id("12") is None
    assert color_name("11") == "tomato" and color_name(None) == "default"


def test_the_scheme_reads_the_kind_of_event_from_its_title():
    assert SCHEME.pick("MIDTERM 1 — CME 102") == "11"
    assert SCHEME.pick("EE 260A Midterm (only if enrolled)") == "11"                 # exams first, whatever the course
    assert SCHEME.pick("CS 227A (audit) — Robot Perception, Shuran Song") == "3"
    assert SCHEME.pick("AA 274A lecture") == "3"
    assert SCHEME.pick("CS 106B Section") == "4" and SCHEME.pick("EE 160A") == "4" and SCHEME.pick("cs106b review") == "4"
    assert SCHEME.pick("Lunch with Alanood") is None and SCHEME.pick("Final Cut Pro workshop") is None


def sections(month, day):
    """One weekly CS 106B section occurrence; juno looks two weeks ahead of Wed Sep 23."""
    return Event("CS 106B Section", datetime(2026, month, day, 15, 30, tzinfo=TZ), datetime(2026, month, day, 16, 20, tzinfo=TZ),
                 "Gates B12", False, "Stanford", id=f"sec_{month}{day}", calendar_id="cal-stanford", color_id="4", recurring_id="sec")


def ops_with(tmp_path, events=None):
    ops, store, _ = make_ops(tmp_path, [], events or {})
    ops.colors = SCHEME
    return ops, store, ops.calendar


def test_add_event_colors_by_her_scheme_unless_she_names_a_color(tmp_path):
    ops, store, cal = ops_with(tmp_path)
    assert ops.add_event("CS 106B Section", "2026-09-24T15:30", end="2026-09-24T16:20", calendar="Stanford") == \
        "added: CS 106B Section, thu sep 24 3:30–4:20pm (Stanford, flamingo)"
    assert ops.add_event("Coffee with Isha", "2026-09-24T10:00", color="green") == "added: Coffee with Isha, thu sep 24 10:00–11:00am (personal calendar, basil)"
    assert ops.add_event("Lunch", "2026-09-24T12:00") == "added: Lunch, thu sep 24 12:00–1:00pm (personal calendar)"
    colors = {cal.events[i].title: cal.bodies[i].get("colorId") for i in cal.bodies}
    assert colors == {"CS 106B Section": "4", "Coffee with Isha": "10", "Lunch": None}
    assert ops.add_event("x", "2026-09-24T12:00", color="chartreuse").startswith("error: color must be one of")
    assert len(cal.events) == 3


def test_color_event_recolors_one_occurrence_or_the_whole_series_with_undo(tmp_path):
    ops, store, cal = ops_with(tmp_path, {date(2026, 9, 24): [sections(9, 24)], date(2026, 10, 1): [sections(10, 1)]})
    assert ops.color_event("cs 106b section", "tomato") == "which one?\n- CS 106B Section (thu sep 24 3:30–4:20pm)\n- CS 106B Section (thu oct 1 3:30–4:20pm)"
    assert ops.color_event("cs 106b section", "tomato", all_occurrences=True) == "colored every CS 106B Section tomato"
    assert {e.color_id for e in cal.events.values()} == {"11"}
    assert cal.patches[-1] == ("cal-stanford", "sec", {"colorId": "11"})            # the series, not one instance
    assert ops.undo() == "undone: every CS 106B Section is flamingo again"
    assert {e.color_id for e in cal.events.values()} == {"4"}


def test_color_event_on_a_single_event_and_back_to_default(tmp_path):
    lunch = Event("Lunch with Alanood", datetime(2026, 9, 24, 12, 0, tzinfo=TZ), datetime(2026, 9, 24, 13, 0, tzinfo=TZ), None,
                  False, "Stanford", id="lunch", calendar_id="cal-stanford")
    ops, store, cal = ops_with(tmp_path, {date(2026, 9, 24): [lunch]})
    assert ops.color_event("lunch", "banana") == "colored Lunch with Alanood banana (thu sep 24 12:00–1:00pm)"
    assert ops.color_event("lunch", "default") == "colored Lunch with Alanood default (thu sep 24 12:00–1:00pm)"
    assert cal.patches[-1] == ("cal-stanford", "lunch", {"colorId": None})          # null clears it in Google's patch
    assert ops.undo() == "undone: Lunch with Alanood is banana again"


def test_a_deleted_event_comes_back_with_its_color(tmp_path):
    ops, store, cal = ops_with(tmp_path, {date(2026, 10, 1): [sections(10, 1)]})
    ops.delete_event("cs 106b section")
    ops.undo()
    (back,) = cal.events.values()
    assert back.color_id == "4"
