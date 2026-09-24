"""Configuration.

Two sources:
  * `.env`          secrets and behaviour flags (loaded by pydantic-settings)
  * `courses.yaml`  which courses to sync, the parent Todoist project (Classes) and
                    each course's own sub-project under it (docs/09-per-course-projects.md)

Everything is relative to the project folder. `uv run assistant ...` from that
folder just works; on a server set ASSISTANT_HOME to point at it.
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
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
    outlook_ics_url: str = ""              # Outlook web → Calendar → Shared calendars → Publish a calendar (a secret URL)

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
    # A misspelled key (`projectid:`) must fail loudly: ignored, it would quietly send the
    # course back to the legacy section path and re-create a section Faith removed.
    model_config = ConfigDict(extra="forbid")

    code: str                      # "ENGR 40M"; also the legacy section name
    canvas_id: int | None = None   # None for courses that don't live on Canvas
    project_id: str | None = None  # the course's own Todoist sub-project under Classes
    section: str | None = None     # legacy (no project_id): override the section name inside Classes
    website: str | None = None     # public course site to scrape (phase 2)

    @property
    def section_name(self) -> str:
        return self.section or self.code


class TodoistConfig(BaseModel):
    """The parent project (Classes). General class tasks live here with no section,
    and so does every course that has no `project_id` of its own (one section each)."""

    project_id: str | None = None
    project_name: str = "Classes"


class CoursesConfig(BaseModel):
    todoist: TodoistConfig = Field(default_factory=TodoistConfig)
    courses: list[Course] = Field(default_factory=list)

    @model_validator(mode="after")
    def _distinct_projects(self) -> "CoursesConfig":
        seen: dict[str, str] = {}
        for c in self.courses:
            if c.project_id is None:
                continue
            if c.project_id == self.todoist.project_id:
                raise ValueError(f"{c.code}: project_id is the parent project; give it its own sub-project")
            if c.project_id in seen:
                raise ValueError(f"{c.code} and {seen[c.project_id]} share project_id {c.project_id}")
            seen[c.project_id] = c.code
        return self

    def by_canvas_id(self) -> dict[int, Course]:
        return {c.canvas_id: c for c in self.courses if c.canvas_id is not None}

    def course_projects(self) -> dict[str, str]:
        """Course code → its sub-project id (courses with one)."""
        return {c.code: c.project_id for c in self.courses if c.project_id}

    def course_by_project(self) -> dict[str, str]:
        """Sub-project id → course code. The parent is never in here: its tasks are general."""
        return {pid: code for code, pid in self.course_projects().items()}

    def class_project_ids(self, parent_id: str) -> list[str]:
        """Every project that holds class tasks: the parent first, then each course's sub-project.

        Built from *all* courses, not just Canvas ones (CS 106B has no canvas_id). The parent
        comes first so a task moved from Classes into a sub-project mid-read is still seen once.
        The parent id is an argument because `todoist.project_id` may be None (found by name).
        """
        out = [parent_id]
        for c in self.courses:
            if c.project_id and c.project_id not in out:
                out.append(c.project_id)
        return out

    def course_sections(self, section_ids: dict[str, str]) -> dict[str, str]:
        """Course code → id of its legacy section in the parent, from Todoist's {name: id}.

        Covers every course, with or without a project: mid-migration some tasks still sit in
        the old sections and must be attributed to their course.
        """
        return {c.code: section_ids[c.section_name] for c in self.courses if c.section_name in section_ids}


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


class CalendarSyncConfig(BaseModel):
    target: str = "Stanford"        # Google calendar that receives Canvas events
    every_minutes: int = 60


class OutlookConfig(BaseModel):
    target: str = "Stanford"        # Google calendar that receives confirmed Outlook meetings
    every_minutes: int = 10


class AppConfig(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    brief: BriefConfig = Field(default_factory=BriefConfig)
    nudges: NudgesConfig = Field(default_factory=NudgesConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    gradescope: GradescopeConfig = Field(default_factory=GradescopeConfig)
    calendar: CalendarSyncConfig = Field(default_factory=CalendarSyncConfig)
    outlook: OutlookConfig = Field(default_factory=OutlookConfig)


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
