"""Gradescope pages → assignments. Fixtures mirror the real markup (button rows before submission,
link rows after; <time datetime> for due dates; a second <time> for the late due date)."""

from datetime import datetime, timezone

from assistant.gradescope import GsAssignment, GsCourse, match_courses, parse_course, parse_dashboard

DASHBOARD = """<html><body>
<a class="courseBox" href="/courses/1341356"><h3 class="courseBox--shortname" title="Aut26-CS-106B">Aut26-CS-106B</h3>
  <div class="courseBox--name">Programming Abstractions in C++</div><div class="courseBox--assignments"><div class="left">0 assignments</div></div></a>
<a class="courseBox" href="/courses/1359455"><h3 class="courseBox--shortname">F26-CME-102-01/ENGR-155A-01</h3>
  <div class="courseBox--name">Ordinary Differential Equations for Engineers</div></a>
<a class="courseBox" href="/courses/1399426"><h3 class="courseBox--shortname">MATSCI 88Q A26</h3><div class="courseBox--name">Edible Materials</div></a>
<a class="courseBox" href="/courses/1278740"><h3 class="courseBox--shortname">Sp26-CME-100-01/ENGR-154-01</h3><div class="courseBox--name">Vector Calculus</div></a>
<a class="courseBox courseBox-new js-enrollInCourse" href="#"><div class="courseBox--buttonLabel">Enroll in Course</div></a>
</body></html>"""

COURSE = """<html><body><table id="assignments-student-table"><thead><tr><th>Name</th><th>Status</th><th>Released Due ( PDT )</th></tr></thead><tbody>
<tr><th class="table--primaryLink"><button class="js-submitAssignment" data-assignment-id="8709892" data-assignment-title="Pset1">Pset1</button></th>
  <td class="submissionStatus"><div class="submissionStatus--text">No Submission</div></td>
  <td><time class="submissionTimeChart--releaseDate" datetime="2026-09-22 23:58:00 -0700">Sep 22 at 11:58PM</time>
      <time class="submissionTimeChart--dueDate" datetime="2026-10-01 23:59:00 -0700">Oct 01 at 11:59PM</time>
      <time class="submissionTimeChart--dueDate" datetime="2026-10-02 23:59:00 -0700">Late Due Date: Oct 02 at 11:59PM</time></td></tr>
<tr><th class="table--primaryLink"><a href="/courses/1359455/assignments/8700001/submissions/415727256">Pre-Lab 1</a></th>
  <td class="submissionStatus"><div class="submissionStatus--text">Submitted</div></td>
  <td><time class="submissionTimeChart--dueDate" datetime="2026-09-28 12:00:00 -0700">Sep 28 at 12:00PM</time></td></tr>
<tr><th class="table--primaryLink"><a href="/courses/1359455/assignments/8700002/submissions/415727257">Quiz 0</a></th>
  <td class="submissionStatus"><div class="submissionStatus--score">9.0 / 10.0</div></td>
  <td><time class="submissionTimeChart--dueDate" datetime="2026-09-20 23:59:00 -0700">Sep 20 at 11:59PM</time></td></tr>
<tr><th class="table--primaryLink"><a href="/courses/1359455/assignments/8700003/submissions/415727258">Midterm</a></th>
  <td class="submissionStatus"><div class="submissionStatus--text">Submitted</div></td><td></td></tr>
</tbody></table></body></html>"""


def test_parse_dashboard_lists_real_courses_only():
    courses = parse_dashboard(DASHBOARD)
    assert [(c.id, c.shortname) for c in courses] == [
        (1341356, "Aut26-CS-106B"), (1359455, "F26-CME-102-01/ENGR-155A-01"), (1399426, "MATSCI 88Q A26"), (1278740, "Sp26-CME-100-01/ENGR-154-01"),
    ]
    assert courses[1].name == "Ordinary Differential Equations for Engineers"


def test_match_courses_by_squashed_code():
    gs = parse_dashboard(DASHBOARD)
    matched = match_courses(gs, ["ENGR 40M", "CS 106B", "CME 102", "MATSCI 88Q", "EE 100"])
    assert {code: c.id for code, c in matched.items()} == {"CS 106B": 1341356, "CME 102": 1359455, "MATSCI 88Q": 1399426}
    # CME 100 (last spring) must not be mistaken for CME 102


def test_parse_course_rows():
    rows = parse_course(COURSE, course_id=1359455)
    by_name = {a.name: a for a in rows}
    pset = by_name["Pset1"]
    assert pset == GsAssignment(
        id=8709892, course_id=1359455, name="Pset1", submitted=False, status="No Submission",
        due_at=datetime(2026, 10, 2, 6, 59, tzinfo=timezone.utc), late_due_at=datetime(2026, 10, 3, 6, 59, tzinfo=timezone.utc),
        released_at=datetime(2026, 9, 23, 6, 58, tzinfo=timezone.utc),
        url="https://www.gradescope.com/courses/1359455/assignments/8709892",
    )
    assert by_name["Pre-Lab 1"].submitted and by_name["Pre-Lab 1"].id == 8700001 and by_name["Pre-Lab 1"].late_due_at is None
    assert by_name["Quiz 0"].submitted and by_name["Quiz 0"].status == "9.0 / 10.0"
    assert by_name["Midterm"].due_at is None and by_name["Midterm"].submitted
