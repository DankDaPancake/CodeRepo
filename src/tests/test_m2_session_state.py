import json

from src.benchmark.m2_session_state import begin_session, finish_session


def test_interrupted_session_is_marked_incomplete_when_resumed(tmp_path):
    state = tmp_path / "session_state.json"
    first = begin_session(state)
    second = begin_session(state, previous_session_stopped=True)
    assert first != second
    data = json.loads(state.read_text(encoding="utf8"))
    assert data["measurement_complete"] is False
    assert data["sessions"][0]["status"] == "interrupted"
    finish_session(state, second, 0)
    data = json.loads(state.read_text(encoding="utf8"))
    assert data["sessions"][-1]["status"] == "complete"
    assert data["measurement_complete"] is False


def test_successful_session_is_marked_complete(tmp_path):
    state = tmp_path / "session_state.json"
    session = begin_session(state)
    finish_session(state, session, 0)
    data = json.loads(state.read_text(encoding="utf8"))
    assert data["measurement_complete"] is True
    assert data["sessions"][0]["status"] == "complete"


def test_active_session_requires_explicit_stopped_confirmation(tmp_path):
    import pytest

    state = tmp_path / "session_state.json"
    begin_session(state)
    with pytest.raises(RuntimeError, match="still be running"):
        begin_session(state)


def test_incomplete_session_labels_summary_as_lower_bound(tmp_path):
    import csv

    from src.benchmark.m2_session_state import annotate_report

    state = tmp_path / "state.json"
    begin_session(state)
    session = begin_session(state, previous_session_stopped=True)
    finish_session(state, session, 0)
    report = tmp_path / "report"
    report.mkdir()
    summary = report / "m2_benchmark_summary.csv"
    summary.write_text(
        "metric,value,unit,tool\nwall_time_e2e,12,s,perf_counter\n"
        "time_per_paper,1,s,wall / papers\n",
        encoding="utf8",
    )
    annotate_report(state, report)
    with summary.open(encoding="utf8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert all("lower bound" in row["tool"] for row in rows)
    assert (
        json.loads((report / "measurement_audit.json").read_text())["measurement_complete"] is False
    )


def test_running_session_is_not_marked_measurement_complete(tmp_path):
    state = tmp_path / "state.json"
    begin_session(state)
    assert json.loads(state.read_text(encoding="utf8"))["measurement_complete"] is False
