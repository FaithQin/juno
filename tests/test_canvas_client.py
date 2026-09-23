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
