# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
import csv

from src.benchmark.m2_benchmark import folder_size, main
from src.tests.test_m2_pipeline import corpus  # noqa: F401  (fixture)


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_benchmark_runs_the_parser_and_writes_the_three_measures(corpus, tmp_path):  # noqa: F811
    report = tmp_path / "bench"
    code = main(
        [
            "--data-root", str(corpus), "--out-dir", str(tmp_path / "out"),
            "--work-dir", str(tmp_path / "work"), "--report", str(report),
            "--interval", "0.05", "--", "--workers", "1",
        ]
    )  # fmt: skip
    assert code == 0
    summary = {r["metric"]: r for r in read(report / "m2_benchmark_summary.csv")}
    assert float(summary["wall_time_e2e"]["value"]) > 0
    assert summary["papers"]["value"] == "3" and summary["versions"]["value"] == "5"
    assert float(summary["output_size"]["value"]) > 0
    assert float(summary["time_per_paper"]["value"]) > 0
    assert float(summary["ram_max"]["value"]) >= 0
    series = read(report / "m2_resource_timeseries.csv")
    assert series and set(series[0]) == {"t_sec", "rss_total_mb", "disk_mb"}
    assert (report / "environment.json").exists() and (report / "m2_papers.csv").exists()
    assert folder_size(tmp_path / "out") > 0
