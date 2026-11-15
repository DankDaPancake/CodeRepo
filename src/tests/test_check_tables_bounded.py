import pyarrow.parquet as pq
import pytest

from src.parser.run import Options, run
from src.parser.writer import to_table
from src.qa.check_tables_bounded import check_paper, check_run, validate_partition
from src.tests.test_m2_pipeline import corpus  # noqa: F401


def test_partition_rejects_rows_moved_across_shards(corpus, tmp_path):  # noqa: F811
    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    validate_partition(out, work / "shards.jsonl")
    source = out / "shard-00000" / "elements.parquet"
    target = out / "shard-00001" / "elements.parquet"
    rows = pq.read_table(target).to_pylist() + pq.read_table(source).to_pylist()[:1]
    pq.write_table(to_table("elements", rows), target)
    with pytest.raises(ValueError, match="wrong shard"):
        validate_partition(out, work / "shards.jsonl")


def test_partition_rejects_cross_paper_parent(corpus, tmp_path):  # noqa: F811
    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    path = out / "shard-00000" / "hierarchy.parquet"
    rows = pq.read_table(path).to_pylist()
    rows[0]["parent_id"] = "2606-00002#bad"
    pq.write_table(to_table("hierarchy", rows), path)
    with pytest.raises(ValueError, match="parent ownership"):
        validate_partition(out, work / "shards.jsonl")


def test_paper_checks_detect_cycles_and_missing_roots():
    elements = {"p#1": "document", "p#2": "section", "p#3": "section"}
    edges = [(1, "p#1", "p"), (1, "p#2", "p#3"), (1, "p#3", "p#2")]
    errors = check_paper("p", elements, edges, [], {1, 2})
    assert any("unreachable" in item for item in errors)
    assert any("root" in item for item in errors)


def test_paper_checks_reject_multiple_parents_and_unexpected_version():
    elements = {"p#root": "document", "p#a": "section", "p#b": "section", "p#x": "section"}
    edges = [
        (1, "p#root", "p"),
        (1, "p#a", "p#root"),
        (1, "p#b", "p#root"),
        (1, "p#x", "p#a"),
        (1, "p#x", "p#b"),
        (2, "p#root", "p"),
    ]
    errors = check_paper("p", elements, edges, [], {1})
    assert any("multiple parents" in item for item in errors)
    assert any("unexpected version" in item for item in errors)


def test_shared_leaf_under_two_parents_is_valid():
    elements = {"p#root": "document", "p#a": "section", "p#b": "section", "p#x": "sentence"}
    edges = [
        (1, "p#root", "p"),
        (1, "p#a", "p#root"),
        (1, "p#b", "p#root"),
        (1, "p#x", "p#a"),
        (1, "p#x", "p#b"),
    ]
    assert check_paper("p", elements, edges, [], {1}) == []


def test_paper_rejects_non_document_root_and_leaf_parent():
    elements = {"p#root": "sentence", "p#child": "sentence"}
    edges = [(1, "p#root", "p"), (1, "p#child", "p#root")]
    problems = check_paper("p", elements, edges, [], {1})
    assert any("root kind" in item for item in problems)
    assert any("leaf parent" in item for item in problems)


def test_bounded_run_checks_all_papers_and_caps_rows(corpus, tmp_path):  # noqa: F811
    from src.qa.check_tables import check

    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    report = check_run(out, work / "shards.jsonl", max_shard_rows=10000)
    assert report["ok"] and report["papers"] == 3 and report["versions"] == 5
    assert report["elements_by_kind"] == check(out)["elements_by_kind"]
    assert report == check(out)
    with pytest.raises(ValueError, match="row limit"):
        check_run(out, work / "shards.jsonl", max_shard_rows=1)


def test_run_reports_each_completed_shard(corpus, tmp_path):  # noqa: F811
    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    events, validation = [], []
    check_run(
        out,
        work / "shards.jsonl",
        on_progress=lambda *event: events.append(event),
        on_validation=lambda *event: validation.append(event),
    )
    assert events == [(1, 3), (2, 3), (3, 3)]
    assert validation == events


def test_partition_reports_progress_for_each_shard(corpus, tmp_path):  # noqa: F811
    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    events = []
    validate_partition(out, work / "shards.jsonl", on_progress=lambda *x: events.append(x))
    assert events == [(1, 3), (2, 3), (3, 3)]


def test_resume_refuses_changed_input_identity(corpus, tmp_path):  # noqa: F811
    out, work, checkpoint = tmp_path / "out", tmp_path / "work", tmp_path / "qa"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)

    def interrupt(done, total):
        if done == 1:
            raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        check_run(
            out,
            work / "shards.jsonl",
            checkpoint_dir=checkpoint,
            identity={"revision": "abc"},
            on_progress=interrupt,
        )
    resumed = check_run(
        out, work / "shards.jsonl", checkpoint_dir=checkpoint, identity={"revision": "abc"}
    )
    assert resumed["ok"] and resumed["papers"] == 3
    with pytest.raises(ValueError, match="identity"):
        check_run(
            out, work / "shards.jsonl", checkpoint_dir=checkpoint, identity={"revision": "changed"}
        )


def test_resume_refuses_changed_shard(corpus, tmp_path):  # noqa: F811
    out, work, checkpoint = tmp_path / "out", tmp_path / "work", tmp_path / "qa"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    check_run(out, work / "shards.jsonl", checkpoint_dir=checkpoint, identity={"revision": "abc"})
    path = out / "shard-00000" / "bibtex.parquet"
    table = pq.read_table(path)
    pq.write_table(table, path, compression="NONE")
    with pytest.raises(ValueError, match="Checkpoint input changed"):
        check_run(
            out, work / "shards.jsonl", checkpoint_dir=checkpoint, identity={"revision": "abc"}
        )


def test_resume_refuses_changed_journal(corpus, tmp_path):  # noqa: F811
    out, work, checkpoint = tmp_path / "out", tmp_path / "work", tmp_path / "qa"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    journal = work / "shards.jsonl"
    check_run(out, journal, checkpoint_dir=checkpoint, identity={"revision": "abc"})
    text = journal.read_text(encoding="utf8")
    journal.write_text(text.replace('"elapsed_s":', '"elapsed_s" :', 1), encoding="utf8")
    with pytest.raises(ValueError, match="identity"):
        check_run(out, journal, checkpoint_dir=checkpoint, identity={"revision": "abc"})


def test_checker_refuses_changed_shard_before_first_check(corpus, tmp_path):  # noqa: F811
    from src.benchmark.m2_sync import _tree_hashes

    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    hashes = {p.name: _tree_hashes(p) for p in out.glob("shard-*")}
    path = out / "shard-00000/bibtex.parquet"
    table = pq.read_table(path)
    pq.write_table(table, path, compression="NONE")
    with pytest.raises(ValueError, match="hash mismatch"):
        check_run(out, work / "shards.jsonl", expected_hashes=hashes)


def test_checker_rejects_unknown_journal_version_status(corpus, tmp_path):  # noqa: F811
    import json

    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    journal = work / "shards.jsonl"
    records = [json.loads(line) for line in journal.read_text(encoding="utf8").splitlines()]
    records[0]["papers"][0]["versions"][0]["status"] = "unexpected"
    journal.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf8")
    with pytest.raises(ValueError, match="version status"):
        check_run(out, journal)


def test_checker_reports_failed_papers(corpus, tmp_path):  # noqa: F811
    import json

    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    journal = work / "shards.jsonl"
    records = [json.loads(line) for line in journal.read_text(encoding="utf8").splitlines()]
    records[0]["papers"][0]["error"] = "paper failed"
    journal.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf8")
    report = check_run(out, journal)
    assert not report["ok"] and any("paper failed" in item for item in report["problems"])
