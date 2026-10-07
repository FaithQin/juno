"""Phase 2 config: assistant.yaml plus the new .env keys."""

from pathlib import Path

from datetime import date

from assistant.config import AppConfig, Settings, load_app_config, parse_chat_ids


def test_parse_chat_ids_accepts_commas_spaces_and_empty():
    assert parse_chat_ids("") == set()
    assert parse_chat_ids("123") == {123}
    assert parse_chat_ids("123, 456 ,789") == {123, 456, 789}


def test_load_app_config_defaults_and_overrides(tmp_path: Path):
    cfg = load_app_config(tmp_path / "missing.yaml")
    assert cfg.agent.name == "juno" and cfg.brief.time == "07:00" and cfg.nudges.scan_minutes == 10

    (tmp_path / "assistant.yaml").write_text(
        "agent:\n  name: pip\n  chat_model: openai:gpt-6-sol\nbrief:\n  time: '06:30'\n  calendars: [Stanford, TA]\nsync:\n  every_minutes: 30\n"
    )
    cfg = load_app_config(tmp_path / "assistant.yaml")
    assert cfg.agent.name == "pip" and cfg.brief.time == "06:30"
    assert cfg.brief.calendars == ["Stanford", "TA"] and cfg.sync.every_minutes == 30
    assert cfg.brief.hour_minute == (6, 30)


def test_settings_has_phase2_keys_with_safe_defaults(monkeypatch):
    monkeypatch.setenv("CANVAS_TOKEN", "x")
    monkeypatch.setenv("TODOIST_TOKEN", "y")
    s = Settings(_env_file=None)
    assert s.telegram_bot_token == "" and s.telegram_chat_ids == "" and s.openai_api_key == ""
    assert s.google_credentials_path.name == "google_credentials.json"


def test_outlook_config_and_setting_defaults(monkeypatch):
    cfg = AppConfig()
    assert cfg.outlook.target == "Stanford" and cfg.outlook.every_minutes == 10 and cfg.outlook.skip == []
    assert "ChemE" in load_app_config().outlook.skip                         # she left ChemE (2026-10-06)
    assert cfg.calendar.quarter_ends == []
    assert load_app_config().calendar.quarter_ends[:2] == [date(2026, 12, 11), date(2027, 3, 19)]   # where repeats stop
    monkeypatch.setenv("CANVAS_TOKEN", "x")
    monkeypatch.setenv("TODOIST_TOKEN", "y")
    assert Settings(_env_file=None).outlook_ics_url == ""


# --- per-course Todoist sub-projects (2026-09-24) ---------------------------------------

import pytest
from pydantic import ValidationError

from assistant.config import CoursesConfig, load_courses

REPO_COURSES = Path(__file__).resolve().parents[1] / "courses.yaml"


def _cfg(courses, parent="CLASSES"):
    return CoursesConfig.model_validate({"todoist": {"project_id": parent}, "courses": courses})


def test_course_project_id_parses_and_defaults_to_none():
    cfg = _cfg([{"code": "EE 100", "canvas_id": 232825, "project_id": "P-EE"}, {"code": "CME 102", "canvas_id": 232579}])
    assert cfg.courses[0].project_id == "P-EE"
    assert cfg.courses[1].project_id is None           # legacy: a section named after the course inside Classes


def test_class_project_ids_is_parent_first_then_every_course_project_including_non_canvas():
    cfg = _cfg([
        {"code": "EE 100", "canvas_id": 232825, "project_id": "P-EE"},
        {"code": "CME 102", "canvas_id": 232579},                        # legacy: no project to read
        {"code": "CS 106B", "canvas_id": None, "project_id": "P-CS"},    # not on Canvas, still read
    ])
    assert cfg.class_project_ids("CLASSES") == ["CLASSES", "P-EE", "P-CS"]


def test_course_by_project_and_course_projects():
    cfg = _cfg([{"code": "EE 100", "project_id": "P-EE"}, {"code": "CME 102"}, {"code": "CS 106B", "project_id": "P-CS"}])
    assert cfg.course_by_project() == {"P-EE": "EE 100", "P-CS": "CS 106B"}
    assert cfg.course_projects() == {"EE 100": "P-EE", "CS 106B": "P-CS"}


def test_course_sections_maps_live_section_ids_to_course_codes():
    cfg = _cfg([{"code": "EE 100", "project_id": "P-EE"}, {"code": "CME 102", "section": "CME"}, {"code": "MATSCI 88Q"}])
    live = {"EE 100": "S-EE", "CME": "S-CME", "General": "S-GEN"}          # section name → id, as Todoist lists them
    assert cfg.course_sections(live) == {"EE 100": "S-EE", "CME 102": "S-CME"}   # keyed by code; non-course sections ignored


def test_a_misspelled_course_key_fails_loudly_instead_of_falling_back_to_sections():
    with pytest.raises(ValidationError):
        _cfg([{"code": "EE 100", "projectid": "P-EE"}])


def test_duplicate_course_projects_and_a_course_pointing_at_the_parent_are_rejected():
    with pytest.raises(ValidationError):
        _cfg([{"code": "EE 100", "project_id": "P-X"}, {"code": "EE 310", "project_id": "P-X"}])
    with pytest.raises(ValidationError):
        _cfg([{"code": "EE 100", "project_id": "CLASSES"}])


def test_the_repo_courses_yaml_ships_every_course_with_its_sub_project():
    cfg = load_courses(REPO_COURSES)
    assert cfg.todoist.project_id == "6cXPJPmRH6GF2MPr"                # Classes stays the parent
    assert cfg.course_projects() == {
        "ENGR 40M": "6hcWWXF2wPQ63xGP",
        "CME 102": "6hcWWXF7PMmh57v2",
        "EE 100": "6hcWWXGX4RFgHc5C",
        "CS 106B": "6hcWWXHRpx3H2RvF",
        "EE 160A": "6hg9Mmh6R7Q68H7M",
    }                                                                   # EE 227 and EE 260A: audits ended 2026-10-06, projects archived
    assert {c.code: c.canvas_id for c in cfg.courses}["CS 106B"] is None
    # Dropped courses and ended audits stay out of the sync: MATSCI 88Q (Sep 30, 2026), EE 310 (Oct 2, 2026),
    # EE 227, EE 260A, AA 274A (Oct 6, 2026).
    assert not {"MATSCI 88Q", "EE 310", "EE 227", "EE 260A", "AA 274A"} & {c.code for c in cfg.courses}
