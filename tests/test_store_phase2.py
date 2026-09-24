"""Phase 2 tables: facts memory, conversation history, nudge ledger, undo log, key-value."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assistant.db import Store

NOW = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)


def make_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "t.sqlite3")


def test_facts_remember_list_forget(tmp_path):
    s = make_store(tmp_path)
    fid = s.remember("ENGR 40M lab is Tuesday 3-6 in Packard 051", now=NOW)
    assert [f.text for f in s.facts()] == ["ENGR 40M lab is Tuesday 3-6 in Packard 051"]
    assert s.facts()[0].id == fid
    assert [f.id for f in s.find_facts("lab")] == [fid]
    s.forget(fid)
    assert s.facts() == []


def test_history_returns_only_recent_turns_in_order(tmp_path):
    s = make_store(tmp_path)
    s.save_messages("c1", b'[{"n":1}]', at=NOW - timedelta(hours=30))
    s.save_messages("c1", b'[{"n":2}]', at=NOW - timedelta(hours=2))
    s.save_messages("c1", b'[{"n":3}]', at=NOW - timedelta(minutes=5))
    s.save_messages("c2", b'[{"n":9}]', at=NOW)
    blobs = s.load_messages("c1", since=NOW - timedelta(hours=24))
    assert [json.loads(b)[0]["n"] for b in blobs] == [2, 3]


def test_nudge_ledger_is_idempotent(tmp_path):
    s = make_store(tmp_path)
    assert s.sent_nudges() == set()
    s.mark_nudge("T1:24h", at=NOW)
    s.mark_nudge("T1:24h", at=NOW)  # second call is harmless
    assert s.sent_nudges() == {"T1:24h"}


def test_snoozes_round_trip(tmp_path):
    s = make_store(tmp_path)
    s.set_snooze("T1", NOW + timedelta(hours=3))
    assert s.snoozes() == {"T1": NOW + timedelta(hours=3)}
    s.clear_snooze("T1")
    assert s.snoozes() == {}


def test_action_log_supports_undo(tmp_path):
    s = make_store(tmp_path)
    assert s.last_undoable() is None
    a = s.log_action("add_task", {"task_id": "T1", "content": "x"}, at=NOW)
    b = s.log_action("complete_task", {"task_id": "T2"}, at=NOW + timedelta(minutes=1))
    last = s.last_undoable()
    assert last.id == b and last.kind == "complete_task" and last.payload == {"task_id": "T2"}
    s.mark_undone(b)
    assert s.last_undoable().id == a


def test_kv(tmp_path):
    s = make_store(tmp_path)
    assert s.kv_get("last_scan") is None
    s.kv_set("last_scan", NOW.isoformat())
    assert s.kv_get("last_scan") == NOW.isoformat()


def test_store_is_usable_from_worker_threads(tmp_path):
    # pydantic-ai runs sync tools on worker threads; APScheduler does the same for sync jobs
    from concurrent.futures import ThreadPoolExecutor

    s = make_store(tmp_path)
    s.remember("main thread fact", now=NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        texts = pool.submit(lambda: [f.text for f in s.facts()]).result()
        fid = pool.submit(lambda: s.remember("worker thread fact", now=NOW)).result()
    assert texts == ["main thread fact"] and fid > 0
    assert [f.text for f in s.facts()] == ["main thread fact", "worker thread fact"]


def test_last_run_reports_the_most_recent_finished_job(tmp_path):
    s = make_store(tmp_path)
    assert s.last_run("sync") is None
    r1 = s.start_run("sync"); s.finish_run(r1, ok=False, summary="crashed")
    r2 = s.start_run("sync"); s.finish_run(r2, ok=True, summary="added 1")
    s.start_run("sync")  # in progress, not finished: ignored
    finished_at, ok = s.last_run("sync")
    assert ok is True and finished_at.tzinfo is not None


def test_pending_job_round_trip(tmp_path):
    s = make_store(tmp_path)
    assert s.pending_job() is None
    s.propose_job("calendar_first_run", {"digest": "abc"}, "add 3 events?", at=NOW)
    job = s.pending_job()
    assert job["kind"] == "calendar_first_run" and job["payload"] == {"digest": "abc"}
    assert job["question"] == "add 3 events?" and job["asked_at"] == NOW.isoformat(timespec="seconds")
    s.kv_delete("pending_job")
    assert s.pending_job() is None
