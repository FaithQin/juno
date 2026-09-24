"""Configuration.

Two sources:
  * `.env`          secrets and behaviour flags (loaded by pydantic-settings)
  * `courses.yaml`  which Canvas courses to sync and where they go in Todoist

Everything is relative to the project folder. `uv run assistant ...` from that
folder just works; on a server set ASSISTANT_HOME to point at it.
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def project_root() -> Path:
    return Path(os.environ.get("ASSISTANT_HOME", Path.cwd())).resolve()


class Settings(BaseSettings):
    """Values from `.env` (or real environment variables, which win)."""

    model_config = SettingsConfigDict(
        env_file=project_root() / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    canvas_url: str = "https://canvas.stanford.edu"
    canvas_token: str
    todoist_token: str
    timezone: str = "America/Los_Angeles"

    # Sync behaviour. Defaults are the ones recorded in DECISIONS.md.
    complete_when_submitted: bool = True   # tick the Todoist task once Canvas shows it submitted
    include_undated: bool = False          # create tasks for assignments with no due date
    batch_min_size: int = 2                # same course + same due time + same group → one task

    # Phase 2
    telegram_bot_token: str = ""
    telegram_chat_ids: str = ""            # comma-separated; empty = setup mode (/start reveals your id)
    openai_api_key: str = ""               # pydantic-ai reads OPENAI_API_KEY from the environment too
    ed_api_token: str = ""                 # edstem.org/us/settings/api-tokens

    @property
    def allowed_chat_ids(self) -> set[int]:
        return parse_chat_ids(self.telegram_chat_ids)

    @property
    def google_credentials_path(self) -> Path:
        return project_root() / "data" / "google_credentials.json"

    @property
    def google_token_path(self) -> Path:
        return project_root() / "data" / "google_token.json"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def db_path(self) -> Path:
        return project_root() / "data" / "assistant.sqlite3"


class Course(BaseModel):
    code: str                      # "ENGR 40M" — also the default Todoist section name
    canvas_id: int | None = None   # None for courses that don't live on Canvas
    section: str | None = None     # override the Todoist section name
    website: str | None = None     # public course site to scrape (phase 2)

    @property
    def section_name(self) -> str:
        return self.section or self.code


class TodoistConfig(BaseModel):
    project_id: str | None = None
    project_name: str = "Classes"


class CoursesConfig(BaseModel):
    todoist: TodoistConfig = Field(default_factory=TodoistConfig)
    courses: list[Course] = Field(default_factory=list)

    def by_canvas_id(self) -> dict[int, Course]:
        return {c.canvas_id: c for c in self.courses if c.canvas_id is not None}


def parse_chat_ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(";", ",").split(",") if x.strip()}


class AgentConfig(BaseModel):
    name: str = "juno"
    chat_model: str = "openai:gpt-6-sol"
    background_model: str = "openai:gpt-6-luna"
    web_search: bool = True                 # provider-native web search (OpenAI: ~$0.01/search)


class BriefConfig(BaseModel):
    time: str = "07:00"
    calendars: list[str] = Field(default_factory=list)

    @property
    def hour_minute(self) -> tuple[int, int]:
        h, m = self.time.split(":")
        return int(h), int(m)


class NudgesConfig(BaseModel):
    scan_minutes: int = 10


class SyncConfig(BaseModel):
    every_minutes: int = 60


class GradescopeConfig(BaseModel):
    every_hours: int = 3


class AppConfig(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    brief: BriefConfig = Field(default_factory=BriefConfig)
    nudges: NudgesConfig = Field(default_factory=NudgesConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    gradescope: GradescopeConfig = Field(default_factory=GradescopeConfig)


def load_app_config(path: Path | None = None) -> AppConfig:
    path = path or project_root() / "assistant.yaml"
    if not path.exists():
        return AppConfig()
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig.model_validate(raw)


def load_courses(path: Path | None = None) -> CoursesConfig:
    path = path or project_root() / "courses.yaml"
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return CoursesConfig.model_validate(raw)
