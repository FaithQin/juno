"""`assistant check`: what it reports about Classes and each course's sub-project (2026-09-24)."""

from assistant.cli import check_report
from assistant.config import CoursesConfig
from fakes import FakeTask, FakeTodoist


def cfg(courses):
    return CoursesConfig.model_validate({"todoist": {"project_id": "CLASSES"}, "courses": courses})


def test_check_reports_each_course_sub_project_and_active_tasks_across_all_of_them():
    todoist = FakeTodoist(
        [FakeTask("T1", "general"), FakeTask("T2", "ENGR 40M: lab", project_id="P-ENGR"),
         FakeTask("T3", "CS 106B: A1", project_id="P-CS")],
        projects=[("CLASSES", "Classes", None), ("P-ENGR", "ENGR 40M", "CLASSES"), ("P-CS", "CS 106B", "CLASSES")],
    )
    lines = check_report(todoist, cfg([{"code": "ENGR 40M", "project_id": "P-ENGR"},
                                       {"code": "CS 106B", "project_id": "P-CS"}]))
    assert "todoist project: Classes (CLASSES)" in lines
    assert "ENGR 40M: sub-project ENGR 40M (P-ENGR) ok" in lines
    assert "CS 106B: sub-project CS 106B (P-CS) ok" in lines
    assert "active tasks: 3 (Classes + 2 course sub-projects)" in lines
    assert not any("will be created" in l for l in lines)


def test_check_flags_a_missing_sub_project_and_one_not_under_classes():
    todoist = FakeTodoist([], projects=[("CLASSES", "Classes", None), ("P-X", "EE 100", "SOMEWHERE_ELSE")])
    lines = check_report(todoist, cfg([{"code": "EE 100", "project_id": "P-X"},
                                       {"code": "EE 310", "project_id": "P-GONE"}]))
    assert "EE 100: sub-project EE 100 (P-X) is not under Classes" in lines
    assert "EE 310: sub-project P-GONE NOT FOUND" in lines


def test_check_still_reports_legacy_sections_for_courses_without_a_project():
    todoist = FakeTodoist([], sections={"CLASSES": {"CME 102": "S3"}})
    lines = check_report(todoist, cfg([{"code": "CME 102"}, {"code": "EE 100"}]))
    assert "CME 102: section CME 102 in Classes (legacy)" in lines
    assert "sections that will be created on first sync: EE 100" in lines
