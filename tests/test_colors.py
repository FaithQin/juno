"""Event colors (Faith, 2026-10-03): by name in chat, and her scheme applied to events juno adds.

Her Stanford calendar, read that day: classes and sections Flamingo, audited classes Grape, exams Tomato.
2026-10-06: auditing is over (Grape unused), and HOLD markers ("HOLD: <Name> (<Org>)") are Graphite, set
apart from confirmed meetings (Banana); juno never recolors a hold.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from assistant.brief import Event
from assistant.colors import ColorScheme, color_id, color_name
from test_chat_ops import make_ops

TZ = ZoneInfo("America/Los_Angeles")
SCHEME = ColorScheme(klass="flamingo", exam="tomato", hold="graphite",
                     courses=["ENGR 40M", "CME 102", "EE 100", "CS 106B", "EE 160A", "AA 174A", "CS 137A"])
AUDITING = ColorScheme(klass="flamingo", audit="grape", exam="tomato", courses=["EE 160A"], audits=["EE 227", "CS 227A"])


def test_color_id_takes_google_names_plain_words_and_default():
    assert color_id("Flamingo") == "4" and color_id("pink") == "4" and color_id("green") == "10" and color_id("4") == "4"
    assert color_id("light green") == "2" and color_id("grey") == "8"
    assert color_id("default") == "" and color_id("no color") == ""
    assert color_id("chartreuse") is None and color_id("12") is None
    assert color_name("11") == "tomato" and color_name(None) == "default"


def test_the_scheme_reads_the_kind_of_event_from_its_title():
    assert SCHEME.pick("MIDTERM 1 — CME 102") == "11"
    assert SCHEME.pick("EE 260A Midterm (only if enrolled)") == "11"                 # exams first, whatever the course
    assert SCHEME.pick("CS 106B Section") == "4" and SCHEME.pick("EE 160A") == "4" and SCHEME.pick("cs106b review") == "4"
    assert SCHEME.pick("AA 174A lecture") == "4"                                     # EE 160A's cross-listed code
    assert SCHEME.pick("Lunch with Alanood") is None and SCHEME.pick("Final Cut Pro workshop") is None


def test_no_audit_color_once_auditing_is_over():
    assert SCHEME.pick("CS 227A (audit) — Robot Perception, Shuran Song") is None
    assert SCHEME.pick("EE 160A lecture (audit row)") == "4"                         # the word alone no longer means grape
    assert AUDITING.pick("CS 227A (audit) — Robot Perception") == "3" and AUDITING.pick("EE 227 lecture") == "3"   # still works if she audits again


def test_a_hold_is_graphite_whatever_else_its_title_says():
    assert SCHEME.pick("HOLD: Nathan (Andrews Cooper)") == "8"
    assert SCHEME.pick("HOLD: CME 102 midterm review (TA)") == "8"                   # not tomato, not flamingo
    assert SCHEME.pick("hold: Prof. Kennedy (ARMLab)") == "8" and SCHEME.pick("  HOLD : Isha (StartX)") == "8"
    assert SCHEME.pick("Holden's birthday") is None and SCHEME.pick("Placeholder: EE 100 reading") == "4"
    assert ColorScheme(hold=None).pick("HOLD: Nathan (Andrews Cooper)") is None


def test_the_repo_config_colors_holds_graphite_and_has_no_audit_color():
    from pathlib import Path

    from assistant.app import color_scheme
    from assistant.config import load_app_config, load_courses

    root = Path(__file__).resolve().parents[1]
    app_cfg = load_app_config(root / "assistant.yaml")
    assert (app_cfg.calendar.colors.hold, app_cfg.calendar.colors.audit) == ("graphite", None)
    scheme = color_scheme(app_cfg, load_courses(root / "courses.yaml"))
    assert scheme.pick("HOLD: Nathan (Andrews Cooper)") == "8"
    assert scheme.pick("AA 174A Lecture 6 - Trajectory Tracking") == "4" and scheme.pick("EE 227 lecture") is None


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


def hold(day=24, hour=13, color="8"):
    return Event("HOLD: Nathan (Andrews Cooper)", datetime(2026, 9, day, hour, 30, tzinfo=TZ), datetime(2026, 9, day, hour + 1, 0, tzinfo=TZ),
                 None, False, "Stanford", id=f"hold{day}", calendar_id="cal-stanford", color_id=color)


def test_add_event_makes_a_hold_graphite(tmp_path):
    ops, store, cal = ops_with(tmp_path)
    assert ops.add_event("HOLD: Nathan (Andrews Cooper)", "2026-09-24T13:30", end="2026-09-24T14:00", calendar="Stanford") == \
        "added: HOLD: Nathan (Andrews Cooper), thu sep 24 1:30–2:00pm (Stanford, graphite)"
    (body,) = cal.bodies.values()
    assert body["colorId"] == "8"


def test_color_event_never_recolors_a_hold(tmp_path):
    ops, store, cal = ops_with(tmp_path, {date(2026, 9, 24): [hold(24, 13)]})
    for color in ("banana", "default", "tomato"):
        assert ops.color_event("nathan", color) == ("nothing changed: HOLD: Nathan (Andrews Cooper) is a hold, and holds stay graphite. "
                                                    "once it's confirmed, take 'HOLD:' out of its title and i can recolor it")
    assert cal.patches == [] and store.last_undoable() is None
    assert next(iter(cal.events.values())).color_id == "8"


def test_color_event_may_still_set_a_hold_to_graphite(tmp_path):
    ops, store, cal = ops_with(tmp_path, {date(2026, 9, 24): [hold(24, 13, color=None)]})
    assert ops.color_event("nathan", "grey") == "colored HOLD: Nathan (Andrews Cooper) graphite (thu sep 24 1:30–2:00pm)"
    assert cal.patches[-1] == ("cal-stanford", "hold24", {"colorId": "8"})
