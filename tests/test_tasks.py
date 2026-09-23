"""Todoist helpers: course inference, DueTask conversion, fuzzy task matching."""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from assistant.tasks import due_task_from, match_tasks, normalize_course

TZ = ZoneInfo("America/Los_Angeles")
COURSES = ["ENGR 40M", "CS 106B", "CME 102", "MATSCI 88Q", "EE 310", "EE 100"]
SECTIONS = {"S1": "ENGR 40M", "S2": "CS 106B", "S3": "CME 102"}


@dataclass
class FakeDue:
    date: object
    string: str = ""
    timezone: str | None = None


@dataclass
class FakeTask:
    id: str
    content: str
    due: FakeDue | None = None
    priority: int = 1
    section_id: str | None = None
    project_id: str = "P"
    created_at: datetime = field(default_factory=lambda: datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc))
    description: str = ""


def test_normalize_course_is_forgiving():
    assert normalize_course("cme102", COURSES) == "CME 102"
    assert normalize_course("CME-102", COURSES) == "CME 102"
    assert normalize_course("engr 40m", COURSES) == "ENGR 40M"
    assert normalize_course("cs106b", COURSES) == "CS 106B"
    assert normalize_course("matsci88q", COURSES) == "MATSCI 88Q"
    assert normalize_course("ee100", COURSES) == "EE 100"
    assert normalize_course("physics", COURSES) is None


def test_due_task_with_time_in_utc():
    t = FakeTask("T1", "ENGR 40M quizzes 2–8", FakeDue(datetime(2026, 9, 26, 6, 59, tzinfo=timezone.utc)), section_id="S1")
    d = due_task_from(t, tz=TZ, sections=SECTIONS)
    assert d.task_id == "T1" and d.course == "ENGR 40M" and d.has_time is True
    assert d.due_at == datetime(2026, 9, 26, 6, 59, tzinfo=timezone.utc)
    assert d.created_at == t.created_at and d.priority == 1


def test_due_task_with_floating_local_time():
    t = FakeTask("T2", "CS 106B: Assignment 1", FakeDue(datetime(2026, 10, 5, 23, 59)), section_id="S2", priority=4)
    d = due_task_from(t, tz=TZ, sections=SECTIONS)
    assert d.due_at == datetime(2026, 10, 5, 23, 59, tzinfo=TZ)
    assert d.has_time is True and d.priority == 4 and d.course == "CS 106B"


def test_due_task_date_only_is_end_of_local_day():
    t = FakeTask("T3", "ENGR 40M: Lab safety training", FakeDue(date(2026, 9, 28)), section_id="S1")
    d = due_task_from(t, tz=TZ, sections=SECTIONS)
    assert d.due_at == datetime(2026, 9, 28, 23, 59, tzinfo=TZ) and d.has_time is False


def test_task_without_due_is_skipped():
    assert due_task_from(FakeTask("T4", "someday"), tz=TZ, sections=SECTIONS) is None


def test_match_tasks_by_words_and_course():
    tasks = [
        FakeTask("T1", "CS 106B: Assignment 1 (Paperless)", section_id="S2"),
        FakeTask("T2", "CS 106B: Assignment 2 (Paperless)", section_id="S2"),
        FakeTask("T3", "CME 102: Find HW due dates on Gradescope", section_id="S3"),
    ]
    assert [t.id for t in match_tasks("assignment 1", tasks, sections=SECTIONS)] == ["T1"]
    assert [t.id for t in match_tasks("cs106b assignment", tasks, sections=SECTIONS)] == ["T1", "T2"]
    assert [t.id for t in match_tasks("hw due dates", tasks, sections=SECTIONS)] == ["T3"]
    assert match_tasks("physics lab", tasks, sections=SECTIONS) == []
