import json
import tarfile

import pytest


def paper(root, pid, status="ok", references=True):
    folder = root / "data/corpus" / pid.replace(".", "-")
    (folder / "v1").mkdir(parents=True)
    metadata = dict(arxiv_id=pid, title="Example", authors=["Ada"],
                    submission_date="2026-04-01T00:00:00Z", revised_dates=[],
                    num_versions=1, venue=None, doi=None)
    (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf8")
    if references:
        (folder / "references.json").write_text(json.dumps(dict(status="ok", references=[])), encoding="utf8")
    files = []
    if status == "ok":
        (folder / "v1/main.tex").write_text("Hello", encoding="utf8")
        files = ["main.tex"]
    return dict(arxiv_id=pid, version=1, status=status, files=files)


def test_pack_batch_preserves_empty_versions_and_checksums(tmp_path):
    from src.benchmark.batch_archives import pack_batch, verify_batch

    local = tmp_path / "local"
    ids = ["2604.20535", "2604.20536"]
    records = [paper(local, ids[0]), paper(local, ids[1], "unavailable")]
    target = tmp_path / "batch.tar.gz"
    result = pack_batch(local, ids, records, target, provenance={"run_id": "example"})
    assert result["papers"] == 2
    manifest = verify_batch(target, expected_sha256=result["sha256"])
    assert manifest["ids"] == ids
    assert manifest["versions"][1]["status"] == "unavailable"
    with tarfile.open(target) as archive:
        assert archive.getmember("data/corpus/2604-20536/v1").isdir()
        assert archive.extractfile("data/corpus/2604-20535/v1/main.tex").read() == b"Hello"
    target.write_bytes(target.read_bytes()[:-20])
    with pytest.raises(ValueError, match="checksum"):
        verify_batch(target, expected_sha256=result["sha256"])


@pytest.mark.parametrize("problem", ["references", "figure", "duplicate"])
def test_pack_batch_refuses_incomplete_or_unfiltered_payload(tmp_path, problem):
    from src.benchmark.batch_archives import pack_batch

    ids = ["2604.20535"]
    record = paper(tmp_path, ids[0], references=problem != "references")
    if problem == "figure":
        (tmp_path / "data/corpus/2604-20535/v1/figure.png").write_bytes(b"image")
    if problem == "duplicate":
        ids *= 2
    target = tmp_path / "batch.tar.gz"
    with pytest.raises(ValueError):
        pack_batch(tmp_path, ids, [record], target, provenance={})
    assert not target.exists()


def setup_checkpoint(tmp_path, count=3):
    local, remote = tmp_path / "local", tmp_path / "drive"
    ids = [f"2604.{20535 + i}" for i in range(count)]
    (local / "work").mkdir(parents=True)
    manifest = dict(config=dict(run_id="archive", archive_batch_size=2), required_ids=ids,
                    code_revision="abc", snapshot_sha256="snapshot")
    (local / "work/manifest.json").write_text(json.dumps(manifest), encoding="utf8")
    return local, remote, ids


def test_archive_checkpoint_roundtrip_partial_then_complete(tmp_path):
    from src.benchmark.archive_checkpoints import ArchiveCheckpoints

    local, remote, ids = setup_checkpoint(tmp_path)
    record = paper(local, ids[0], "unavailable", references=False)
    journal = local / "work/versions.jsonl"
    journal.write_text(json.dumps(record) + "\n")
    index = ArchiveCheckpoints(local, remote).save(ids, phase="periodic")
    assert index["versions"] == 1
    assert not (remote / "data/corpus").exists()
    assert index["batches"][0]["complete"] is False
    restored = tmp_path / "restored"
    ArchiveCheckpoints(restored, remote).restore()
    assert (restored / "data/corpus/2604-20535/v1").is_dir()
    assert not (restored / "data/corpus/2604-20536").exists()
    (restored / "data/corpus/2604-20535/references.json").write_text('{"status":"not_found"}')
    rows = [record, paper(restored, ids[1]), paper(restored, ids[2])]
    (restored / "work/versions.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    index = ArchiveCheckpoints(restored, remote).save(ids, phase="final")
    assert [b["papers"] for b in index["batches"]] == [2, 1]
    assert all(b["complete"] for b in index["batches"])
    final = tmp_path / "final"
    ArchiveCheckpoints(final, remote).restore()
    assert (final / "data/corpus/2604-20536/v1/main.tex").read_text() == "Hello"
    assert (final / "data/corpus/2604-20535/v1").is_dir()


def test_archive_checkpoint_keeps_previous_generation_on_upload_failure(tmp_path, monkeypatch):
    from src.benchmark.archive_checkpoints import ArchiveCheckpoints
    local, remote, ids = setup_checkpoint(tmp_path, count=1)
    row = paper(local, ids[0])
    (local / "work/versions.jsonl").write_text(json.dumps(row) + "\n")
    cp = ArchiveCheckpoints(local, remote)
    cp.save(ids)
    original = (remote / "INDEX.json").read_bytes()
    (local / "work/new.log").write_text("new")
    monkeypatch.setattr(cp, "_publish_archive", lambda *args: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(OSError, match="offline"):
        cp.save(ids)
    assert (remote / "INDEX.json").read_bytes() == original
    ArchiveCheckpoints(tmp_path / "restored", remote).restore()


def test_archive_checkpoint_rejects_corrupt_archive(tmp_path):
    from src.benchmark.archive_checkpoints import ArchiveCheckpoints
    local, remote, ids = setup_checkpoint(tmp_path, count=1)
    row = paper(local, ids[0])
    (local / "work/versions.jsonl").write_text(json.dumps(row) + "\n")
    index = ArchiveCheckpoints(local, remote).save(ids)
    (remote / index["batches"][0]["path"]).write_bytes(b"broken")
    with pytest.raises(ValueError, match="checksum"):
        ArchiveCheckpoints(tmp_path / "restored", remote).restore()


def test_runner_selects_archive_backend_and_preserves_old_run_identity(tmp_path):
    from src.benchmark.archive_checkpoints import ArchiveCheckpoints
    from src.benchmark.runner import BenchmarkConfig, checkpoint_backend, prepare_run
    local, remote, _ = setup_checkpoint(tmp_path)
    assert isinstance(checkpoint_backend(local, remote), ArchiveCheckpoints)
    saved = prepare_run(BenchmarkConfig("old", "partition", ("dang",), count=1),
                        tmp_path / "runs", "abc", resume=False)
    assert "archive_batch_size" not in saved["config"]
    cfg = BenchmarkConfig("new", "partition", ("dang",), count=1, archive_batch_size=100)
    saved = prepare_run(cfg, tmp_path / "runs", "abc", resume=False)
    assert saved["config"]["archive_batch_size"] == 100


def test_archive_timing_rows_exclude_post_sampler_publication(tmp_path):
    from src.benchmark.archive_checkpoints import archive_timing_rows
    work = tmp_path / "work"
    work.mkdir()
    rows = [dict(generation="one", phase="post-chunk", packing_verify_s=2, upload_verify_s=3),
            dict(generation="two", phase="evidence-publication", packing_verify_s=7, upload_verify_s=8)]
    (work / "archive_events.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    result = {row["metric"]: row["value"] for row in archive_timing_rows([work])}
    assert result["archive_packing_verify_time"] == 2
    assert result["archive_upload_verify_time"] == 3
    assert result["archive_evidence_publication_time"] == 15


def test_archive_checkpoint_refuses_journal_omitting_source_file(tmp_path):
    from src.benchmark.archive_checkpoints import ArchiveCheckpoints
    local, remote, ids = setup_checkpoint(tmp_path, count=1)
    row = paper(local, ids[0])
    row["files"] = []
    (local / "work/versions.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="file list"):
        ArchiveCheckpoints(local, remote).save(ids)
    assert not (remote / "INDEX.json").exists()
