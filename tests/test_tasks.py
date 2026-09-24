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


# --- per-course sub-projects: project first, then legacy section, else none --------------

PROJECTS = {"P-ENGR": "ENGR 40M", "P-CS": "CS 106B", "P-CME": "CME 102"}   # sub-project id → code


def test_course_of_prefers_the_sub_project_then_the_legacy_section_else_none():
    from assistant.tasks import course_of

    in_project = FakeTask("T1", "Lab 1", project_id="P-CME")
    in_section = FakeTask("T2", "Lab 2", project_id="CLASSES", section_id="S1")
    both = FakeTask("T3", "Lab 3", project_id="P-CS", section_id="S1")        # a section she made inside the sub-project
    general = FakeTask("T4", "Add/drop deadline", project_id="CLASSES")
    elsewhere = FakeTask("T5", "Groceries", project_id="INBOX")
    assert course_of(in_project, projects=PROJECTS, sections=SECTIONS) == "CME 102"
    assert course_of(in_section, projects=PROJECTS, sections=SECTIONS) == "ENGR 40M"
    assert course_of(both, projects=PROJECTS, sections=SECTIONS) == "CS 106B"
    assert course_of(general, projects=PROJECTS, sections=SECTIONS) is None
    assert course_of(elsewhere, projects=PROJECTS, sections=SECTIONS) is None
    assert course_of(in_section, sections=SECTIONS) == "ENGR 40M"           # legacy callers pass sections only


def test_due_task_and_match_use_the_sub_project_for_the_course():
    t = FakeTask("T1", "Assignment 1 (Paperless)", FakeDue(date(2026, 10, 5)), project_id="P-CS")
    assert due_task_from(t, tz=TZ, sections=SECTIONS, projects=PROJECTS).course == "CS 106B"
    assert due_task_from(t, tz=TZ, sections=SECTIONS).course is None       # without the map it is general
    tasks = [t, FakeTask("T2", "Pset 1", project_id="P-CME"), FakeTask("T3", "CS 106B: Assignment 2", section_id="S2")]
    assert [x.id for x in match_tasks("cs106b assignment", tasks, sections=SECTIONS, projects=PROJECTS)] == ["T1", "T3"]
