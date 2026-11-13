# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
import csv
import json

from src.benchmark.m2_benchmark import folder_size, main
from src.tests.test_m2_pipeline import corpus  # noqa: F401  (fixture)


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def command(corpus, tmp_path, *extra):  # noqa: F811
    return [
        "--data-root", str(corpus), "--out-dir", str(tmp_path / "out"),
        "--work-dir", str(tmp_path / "work"), "--report", str(tmp_path / "bench"),
        "--interval", "0.05", "--", *extra,
    ]  # fmt: skip


def test_benchmark_runs_the_parser_and_writes_the_measures(corpus, tmp_path):  # noqa: F811
    code = main(command(corpus, tmp_path, "--workers", "1"))
    assert code == 0
    summary = {r["metric"]: r for r in read(tmp_path / "bench" / "m2_benchmark_summary.csv")}
    assert float(summary["wall_time_e2e"]["value"]) > 0
    assert summary["papers"]["value"] == "3" and summary["versions"]["value"] == "5"
    assert summary["sessions"]["value"] == "1"
    assert float(summary["output_size"]["value"]) > 0 and float(summary["input_size"]["value"]) > 0
    assert float(summary["disk_max"]["value"]) >= float(summary["input_size"]["value"])
    assert float(summary["time_per_paper"]["value"]) > 0
    series = read(tmp_path / "bench" / "m2_resource_timeseries.csv")
    assert series and set(series[0]) == {"session_id", "t_sec", "rss_total_mb", "disk_mb"}
    assert (tmp_path / "bench" / "environment.json").exists()
    assert folder_size(tmp_path / "out") > 0


def test_a_second_session_is_added_to_the_first(corpus, tmp_path):  # noqa: F811
    main(command(corpus, tmp_path, "--limit", "1"))
    main(command(corpus, tmp_path))  # the same command resumes: only the rest is parsed
    sessions = [
        json.loads(line)
        for line in (tmp_path / "bench" / "m2_sessions.jsonl").read_text().splitlines()
    ]
    assert [s["session_id"] for s in sessions] == [1, 2]
    summary = {r["metric"]: r for r in read(tmp_path / "bench" / "m2_benchmark_summary.csv")}
    assert summary["sessions"]["value"] == "2" and summary["papers"]["value"] == "3"
    total = sum(s["wall_s"] for s in sessions)
    assert abs(float(summary["wall_time_e2e"]["value"]) - total) < 0.05
    series = read(tmp_path / "bench" / "m2_resource_timeseries.csv")
    assert {r["session_id"] for r in series} == {"1", "2"}


def test_several_data_roots_are_passed_to_the_runner(corpus, tmp_path):  # noqa: F811
    other = tmp_path / "other"
    other.mkdir()
    args = command(corpus, tmp_path)
    args[args.index("--data-root") : args.index("--data-root")] = ["--data-root", str(other)]
    assert main(args) == 0  # an empty second run is fine: the papers come from the first
    summary = {r["metric"]: r for r in read(tmp_path / "bench" / "m2_benchmark_summary.csv")}
    assert summary["papers"]["value"] == "3"


def test_failed_session_report_write_preserves_previous_session(corpus, tmp_path, monkeypatch):  # noqa: F811
    import pytest

    import src.benchmark.m2_benchmark as bm

    report = tmp_path / "report"
    report.mkdir()
    old = {"session_id": 1, "wall_s": 1, "output_mb": 0, "returncode": 0, "command": []}
    sessions = report / "m2_sessions.jsonl"
    original = json.dumps(old) + "\n"
    sessions.write_text(original, encoding="utf8")
    dumps = bm.json.dumps

    def fail_on_new(value, *args, **kwargs):
        if isinstance(value, dict) and value.get("session_id") == 1:
            raise RuntimeError("interrupted report")
        return dumps(value, *args, **kwargs)

    monkeypatch.setattr(bm.json, "dumps", fail_on_new)
    result = {"wall": 1, "returncode": 0, "started_at": "now", "cmd": [], "samples": []}
    with pytest.raises(RuntimeError, match="interrupted report"):
        bm.write_report(result, report, tmp_path / "work", tmp_path / "out", [corpus])
    assert sessions.read_text(encoding="utf8") == original


def test_benchmark_shows_parser_progress(corpus, tmp_path, capfd):  # noqa: F811
    assert main(command(corpus, tmp_path, "--workers", "1")) == 0
    output = capfd.readouterr().err
    assert "paper" in output
    assert "3/3" in output
