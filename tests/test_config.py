"""Phase 2 config: assistant.yaml plus the new .env keys."""

from pathlib import Path

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
    assert cfg.outlook.target == "Stanford" and cfg.outlook.every_minutes == 10
    monkeypatch.setenv("CANVAS_TOKEN", "x")
    monkeypatch.setenv("TODOIST_TOKEN", "y")
    assert Settings(_env_file=None).outlook_ics_url == ""
