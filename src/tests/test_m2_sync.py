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


def test_sync_snapshot_excludes_a_shard_committed_while_copying(corpus, tmp_path, monkeypatch):  # noqa: F811
    import json

    import src.benchmark.m2_sync as sync

    out, work, report = dirs(tmp_path, "a")
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1, limit=1)
    remote = tmp_path / "drive"
    copy_shard = sync._copy_shard

    def copy_and_commit(src, dst):
        copy_shard(src, dst)
        run(corpus, out, work, options=Options(), progress=False, shard_papers=1, limit=2)

    monkeypatch.setattr(sync, "_copy_shard", copy_and_commit)
    sync_to_drive(out, work, report, remote)
    records = [json.loads(x) for x in (remote / "work/shards.jsonl").read_text().splitlines()]
    assert all((remote / "out" / f"shard-{r['shard']:05d}").is_dir() for r in records)


def test_sync_refuses_corrupt_existing_remote_shard(corpus, tmp_path):  # noqa: F811
    out, work, report = dirs(tmp_path, "a")
    run(corpus, out, work, options=Options(), progress=False, limit=1)
    remote = tmp_path / "drive"
    sync_to_drive(out, work, report, remote)
    shard_file = remote / "out/shard-00000/elements.parquet"
    shard_file.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        sync_to_drive(out, work, report, remote)


def test_restore_rejects_corrupt_remote_shard(corpus, tmp_path):  # noqa: F811
    out, work, report = dirs(tmp_path, "a")
    run(corpus, out, work, options=Options(), progress=False, limit=1)
    remote = tmp_path / "drive"
    sync_to_drive(out, work, report, remote)
    (remote / "out/shard-00000/elements.parquet").write_bytes(b"corrupt")
    out2, work2, report2 = dirs(tmp_path, "b")
    with pytest.raises(ValueError, match="integrity"):
        restore_from_drive(remote, out2, work2, report2)


def test_restore_rejects_corruption_during_copy(corpus, tmp_path, monkeypatch):  # noqa: F811
    import src.benchmark.m2_sync as sync

    out, work, report = dirs(tmp_path, "a")
    run(corpus, out, work, options=Options(), progress=False, limit=1)
    remote = tmp_path / "drive"
    sync_to_drive(out, work, report, remote)
    original = sync.shutil.copytree

    def corrupt_copy(src, dst):
        result = original(src, dst)
        (dst / "elements.parquet").write_bytes(b"corrupt")
        return result

    monkeypatch.setattr(sync.shutil, "copytree", corrupt_copy)
    out2, work2, report2 = dirs(tmp_path, "b")
    with pytest.raises(ValueError, match="integrity"):
        restore_from_drive(remote, out2, work2, report2)


def test_restore_uses_one_journal_snapshot_when_drive_changes(corpus, tmp_path, monkeypatch):  # noqa: F811
    import json

    import src.benchmark.m2_sync as sync

    out, work, report = dirs(tmp_path, "a")
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1, limit=1)
    remote = tmp_path / "drive"
    sync_to_drive(out, work, report, remote)
    original = sync.shutil.copytree
    changed = False

    def copy_and_sync(src, dst):
        nonlocal changed
        result = original(src, dst)
        if not changed:
            changed = True
            run(corpus, out, work, options=Options(), progress=False, shard_papers=1, limit=2)
            sync_to_drive(out, work, report, remote)
        return result

    monkeypatch.setattr(sync.shutil, "copytree", copy_and_sync)
    out2, work2, report2 = dirs(tmp_path, "b")
    restore_from_drive(remote, out2, work2, report2)
    rows = [json.loads(x) for x in (work2 / "shards.jsonl").read_text().splitlines()]
    assert all((out2 / f"shard-{row['shard']:05d}").is_dir() for row in rows)


def test_sync_restores_corpus_and_bbl_identities(corpus, tmp_path):  # noqa: F811
    out, work, report = dirs(tmp_path, "a")
    run(corpus, out, work, options=Options(), progress=False, limit=1)
    (work / "corpus-input-identity.json").write_text('{"sha256":"a"}', encoding="utf8")
    (work / "bbl-input-identity.json").write_text('{"journal_sha256":"b"}', encoding="utf8")
    remote = tmp_path / "drive"
    sync_to_drive(out, work, report, remote)
    out2, work2, report2 = dirs(tmp_path, "b")
    restore_from_drive(remote, out2, work2, report2)
    assert (work2 / "corpus-input-identity.json").is_file()
    assert (work2 / "bbl-input-identity.json").is_file()


def test_external_bbl_survives_verified_drive_resume(corpus, tmp_path):  # noqa: F811
    import hashlib
    import json

    from src.parser.run import main as parser_main
    from src.qa.check_tables import read_table

    recovery = tmp_path / "recovery"
    file = recovery / "files/2606-00002/v2/main.bbl"
    file.parent.mkdir(parents=True)
    content = b"\\bibitem{outside} A. Author. Title. 2020."
    file.write_bytes(content)
    record = {
        "arxiv_id": "2606.00002",
        "version": 2,
        "status": "recovered",
        "files": [
            {
                "path": "files/2606-00002/v2/main.bbl",
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    (recovery / "versions.jsonl").write_text(json.dumps(record) + "\n", encoding="utf8")
    out, work, report = dirs(tmp_path, "a")
    common = [
        "--data-root",
        str(corpus),
        "--bbl-recovery-dir",
        str(recovery),
        "--no-progress",
        "--shard-papers",
        "1",
        "--workers",
        "2",
    ]
    assert (
        parser_main([*common, "--out-dir", str(out), "--work-dir", str(work), "--limit", "1"]) == 0
    )
    remote = tmp_path / "drive"
    sync_to_drive(out, work, report, remote)
    out2, work2, report2 = dirs(tmp_path, "b")
    restore_from_drive(remote, out2, work2, report2)
    assert parser_main([*common, "--out-dir", str(out2), "--work-dir", str(work2)]) == 0
    refs = read_table(out2, "bibtex")
    assert any(r["citation_key"] == "outside" for r in refs)
    assert check(out2)["ok"]


def test_sync_can_skip_live_report_until_parser_exits(corpus, tmp_path):  # noqa: F811
    out, work, report = dirs(tmp_path, "a")
    run(corpus, out, work, options=Options(), progress=False, limit=1)
    report.mkdir(parents=True)
    (report / "m2_sessions.jsonl").write_text("partial", encoding="utf8")
    remote = tmp_path / "drive"
    sync_to_drive(out, work, report, remote, include_report=False)
    assert not (remote / "report/m2_sessions.jsonl").exists()
