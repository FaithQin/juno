"""The Todoist wrapper, against a stub SDK: reads across Classes and the course sub-projects,
and the fake used everywhere else must accept exactly what the real client accepts."""

import inspect
from types import SimpleNamespace

from assistant.todoist_client import TodoistClient
from fakes import FakeTask, FakeTodoist


class StubAPI:
    """Pages, like the SDK: every list call yields lists."""

    def __init__(self, tasks=(), projects=()):
        self._tasks = list(tasks)
        self._projects = list(projects)
        self.calls: list = []
        self.added: list = []

    def get_tasks(self, project_id=None):
        self.calls.append(("get_tasks", project_id))
        yield [t for t in self._tasks if project_id is None or t.project_id == project_id]

    def get_projects(self):
        yield list(self._projects)

    def add_task(self, content, **kwargs):
        self.added.append((content, kwargs))
        return SimpleNamespace(id="NEW", content=content, **kwargs)


def client(api) -> TodoistClient:
    c = TodoistClient.__new__(TodoistClient)
    c.api = api
    return c


def test_tasks_in_reads_each_project_parent_first_and_lists_each_task_once():
    api = StubAPI([FakeTask("T1", "general"), FakeTask("T2", "lab", project_id="P-EE"), FakeTask("T3", "pset", project_id="P-CS")])
    got = client(api).tasks_in(["CLASSES", "P-EE", "P-CS", "P-EE"])
    assert [t.id for t in got] == ["T1", "T2", "T3"]
    assert api.calls == [("get_tasks", "CLASSES"), ("get_tasks", "P-EE"), ("get_tasks", "P-CS")]


def test_tasks_in_dedupes_a_task_seen_in_two_places_while_it_moves():
    moving = FakeTask("T1", "lab")
    api = StubAPI([moving])

    def get_tasks(project_id=None):          # the move lands between the two reads
        api.calls.append(("get_tasks", project_id))
        yield [moving]
    api.get_tasks = get_tasks
    assert [t.id for t in client(api).tasks_in(["CLASSES", "P-EE"])] == ["T1"]


def test_projects_lists_every_project_with_its_parent():
    api = StubAPI(projects=[SimpleNamespace(id="CLASSES", name="Classes", parent_id="AREAS"),
                            SimpleNamespace(id="P-EE", name="EE 100", parent_id="CLASSES")])
    assert [(p.id, p.parent_id) for p in client(api).projects()] == [("CLASSES", "AREAS"), ("P-EE", "CLASSES")]


def test_add_task_into_a_sub_project_needs_no_section():
    api = StubAPI()
    client(api).add_task(content="EE 100: Lab 1", project_id="P-EE")
    assert api.added == [("EE 100: Lab 1", {"description": "", "project_id": "P-EE", "section_id": None, "priority": 1})]


def _params(fn):
    return {name: (p.kind, p.default) for name, p in inspect.signature(fn).parameters.items() if name != "self"}


def test_fake_and_real_writes_take_the_same_arguments():
    for name in ("add_task", "update_task"):
        assert _params(getattr(FakeTodoist, name)) == _params(getattr(TodoistClient, name)), name


def test_update_can_never_move_a_task():
    for cls in (TodoistClient, FakeTodoist):
        params = _params(cls.update_task)
        assert "project_id" not in params and "section_id" not in params
    assert not hasattr(TodoistClient, "move_task")      # moves are the orchestrator's job, never juno's


def test_tasks_in_is_strict_by_default_and_can_skip_an_unreadable_project():
    api = StubAPI([FakeTask("T1", "general"), FakeTask("T2", "lab", project_id="P-EE")])
    real = api.get_tasks

    def get_tasks(project_id=None):
        if project_id == "P-GONE":
            raise RuntimeError("404")
        return real(project_id)
    api.get_tasks = get_tasks
    import pytest
    with pytest.raises(RuntimeError):
        client(api).tasks_in(["CLASSES", "P-GONE", "P-EE"])                       # syncs: never skip
    assert [t.id for t in client(api).tasks_in(["CLASSES", "P-GONE", "P-EE"], strict=False)] == ["T1", "T2"]


def test_fake_tasks_in_takes_the_same_arguments_as_the_real_one():
    assert _params(FakeTodoist.tasks_in) == _params(TodoistClient.tasks_in)


def test_lenient_tasks_in_still_raises_when_the_parent_cant_be_read():
    """A failing Classes read is Todoist being down, not one bad sub-project: the nudges and the
    brief must see the outage (they wait and retry) instead of an empty list."""
    api = StubAPI([FakeTask("T2", "lab", project_id="P-EE")])
    real = api.get_tasks

    def get_tasks(project_id=None):
        if project_id == "CLASSES":
            raise RuntimeError("503")
        return real(project_id)
    api.get_tasks = get_tasks
    import pytest
    with pytest.raises(RuntimeError):
        client(api).tasks_in(["CLASSES", "P-EE"], strict=False)
