"""Canvas client: tolerate courses where an endpoint is disabled."""

from canvasapi.exceptions import ResourceDoesNotExist

from assistant.canvas_client import CanvasClient


class FakeAssignment:
    id = 823749
    name = "2 SI Prefixes"
    due_at = "2026-09-26T06:59:00Z"
    html_url = "https://canvas.stanford.edu/courses/231533/assignments/823749"
    submission_types = ["online_quiz"]
    assignment_group_id = 10
    published = True
    submission = {"workflow_state": "unsubmitted"}


class FakeGroup:
    id = 10
    name = "Online Quizzes"


class FakeCourse:
    def get_assignment_groups(self):
        return [FakeGroup()]

    def get_assignments(self, **kwargs):
        return [FakeAssignment()]

    def get_quizzes(self, **kwargs):
        raise ResourceDoesNotExist("Not Found")


class FakeApi:
    def get_course(self, course_id):
        return FakeCourse()


def test_course_with_quizzes_disabled_still_returns_its_assignments():
    client = CanvasClient("https://canvas.example.edu", "token")
    client.api = FakeApi()
    items = client.items_for_course(231533)
    assert [(i.kind, i.canvas_id, i.group_name, i.submitted) for i in items] == [("assignment", 823749, "Online Quizzes", False)]


class GradescopeTool(FakeAssignment):
    id = 828789
    name = "Pre-lab 1"
    submission_types = ["external_tool"]
    external_tool_tag_attributes = {"url": "https://lti.int.turnitin.com/launch/gs-proxy", "new_tab": True,
                                    "custom_params": {"tii_app_key": "gs-proxy", "custom_gradescope_resource_id": "assignment-8676496"}}


class HypothesisTool(FakeAssignment):
    id = 826592
    name = "Reading 1 - Viscosity (Chapter 5.1)"
    submission_types = ["external_tool"]
    external_tool_tag_attributes = {"url": "https://lms.hypothes.is/lti_launches", "custom_params": {}}


def test_a_gradescope_external_tool_carries_its_gradescope_assignment_id():
    class Course(FakeCourse):
        def get_assignments(self, **kwargs):
            return [GradescopeTool(), HypothesisTool(), FakeAssignment()]

    class Api:
        def get_course(self, course_id):
            return Course()

    client = CanvasClient("https://canvas.example.edu", "token")
    client.api = Api()
    got = {i.canvas_id: (i.gradescope_id, i.is_gradescope) for i in client.items_for_course(232193)}
    assert got == {828789: (8676496, True), 826592: (None, False), 823749: (None, False)}
