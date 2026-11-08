# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
import pytest

from src.benchmark.m2_benchmark import main as benchmark_main
from src.benchmark.m2_sync import restore_from_drive, sync_to_drive
from src.parser.run import Options, run
from src.qa.check_tables import check
from src.tests.test_m2_pipeline import corpus  # noqa: F401  (fixture)


def dirs(tmp_path, name):
    return tmp_path / name / "out", tmp_path / name / "work", tmp_path / name / "report"


def test_sync_copies_new_shards_then_the_journal_and_is_incremental(corpus, tmp_path):  # noqa: F811
    out, work, report = dirs(tmp_path, "a")
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1, limit=2)
    remote = tmp_path / "drive" / "m2-01"
    first = sync_to_drive(out, work, report, remote)
    assert first["shards"] == 2 and (remote / "work" / "shards.jsonl").is_file()
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    second = sync_to_drive(out, work, report, remote)
    assert second["shards"] == 1  # only the shard written since
    assert not list((remote / "out").glob(".part-*"))  # no temporary leftovers


def test_resume_on_a_fresh_runtime_gives_the_same_tables(corpus, tmp_path):  # noqa: F811
    out, work, report = dirs(tmp_path, "a")
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1, limit=2)
    remote = tmp_path / "drive" / "m2-01"
    sync_to_drive(out, work, report, remote)

    # the runtime is lost: a new one restores from Drive and runs the same command
    out2, work2, report2 = dirs(tmp_path, "b")
    restored = restore_from_drive(remote, out2, work2, report2)
    assert restored["shards"] == 2
    summary = run(corpus, out2, work2, options=Options(), progress=False, shard_papers=1)
    assert summary["papers_this_run"] == 1 and summary["papers_committed_total"] == 3
    report_ = check(out2)
    assert report_["ok"] and report_["papers"] == 3


def test_a_shard_on_drive_that_the_journal_does_not_mention_is_dropped_on_resume(
    corpus,  # noqa: F811
    tmp_path,
):
    out, work, report = dirs(tmp_path, "a")
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1, limit=1)
    remote = tmp_path / "drive" / "m2-01"
    sync_to_drive(out, work, report, remote)
    (remote / "out" / "shard-00007").mkdir()  # copied, but the journal never learned of it
    (remote / "out" / "shard-00007" / "elements.parquet").write_bytes(b"half")
    out2, work2, report2 = dirs(tmp_path, "b")
    restore_from_drive(remote, out2, work2, report2)
    run(corpus, out2, work2, options=Options(), progress=False, shard_papers=1)
    assert not (out2 / "shard-00007").exists() and check(out2)["ok"]


def test_restore_refuses_to_overwrite_a_run_or_to_resume_nothing(corpus, tmp_path):  # noqa: F811
    out, work, report = dirs(tmp_path, "a")
    remote = tmp_path / "drive" / "m2-01"
    with pytest.raises(FileNotFoundError):
        restore_from_drive(remote, out, work, report)
    run(corpus, out, work, options=Options(), progress=False, limit=1)
    sync_to_drive(out, work, report, remote)
    with pytest.raises(FileExistsError):
        restore_from_drive(remote, out, work, report)


def test_the_report_with_the_session_log_travels_too(corpus, tmp_path):  # noqa: F811
    out, work, report = dirs(tmp_path, "a")
    benchmark_main(
        ["--data-root", str(corpus), "--out-dir", str(out), "--work-dir", str(work),
         "--report", str(report), "--interval", "0.05", "--", "--limit", "1"]
    )  # fmt: skip
    remote = tmp_path / "drive" / "m2-01"
    sync_to_drive(out, work, report, remote)
    out2, work2, report2 = dirs(tmp_path, "b")
    restore_from_drive(remote, out2, work2, report2)
    assert (report2 / "m2_sessions.jsonl").is_file()
    benchmark_main(
        ["--data-root", str(corpus), "--out-dir", str(out2), "--work-dir", str(work2),
         "--report", str(report2), "--interval", "0.05"]
    )  # fmt: skip
    assert len((report2 / "m2_sessions.jsonl").read_text().splitlines()) == 2
