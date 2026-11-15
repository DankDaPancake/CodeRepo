import json

import pytest

from src.qa.qa_inputs import (
    inspect_run,
    prepare_qa,
    read_assignments,
    restore_shards,
    verify_checkpoint,
    verify_shard,
)


def test_assignments_reject_paper_in_two_shards_without_changing_journal(tmp_path):
    path = tmp_path / "shards.jsonl"
    original = (
        "\n".join(json.dumps({"shard": n, "papers": [{"arxiv_id": "2606.00001"}]}) for n in (0, 1))
        + "\n"
    )
    path.write_text(original, encoding="utf8")
    with pytest.raises(ValueError, match="Duplicate paper"):
        read_assignments(path)
    assert path.read_text(encoding="utf8") == original


def test_assignments_reject_incomplete_journal(tmp_path):
    path = tmp_path / "shards.jsonl"
    path.write_text('{"shard": 1', encoding="utf8")
    with pytest.raises(ValueError, match="incomplete"):
        read_assignments(path)


def test_verify_shard_detects_modified_and_extra_files(tmp_path):
    import hashlib

    shard = tmp_path / "shard-00000"
    shard.mkdir()
    path = shard / "elements.parquet"
    path.write_bytes(b"original")
    expected = {"elements.parquet": hashlib.sha256(b"original").hexdigest()}
    verify_shard(shard, expected)
    path.write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash"):
        verify_shard(shard, expected)
    path.write_bytes(b"original")
    (shard / "extra").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="files"):
        verify_shard(shard, expected)


def test_checkpoint_rejects_extra_shard_and_preserves_inputs(tmp_path):
    import hashlib

    out = tmp_path / "out"
    shard = out / "shard-00000"
    shard.mkdir(parents=True)
    (shard / "elements.parquet").write_bytes(b"a")
    journal = tmp_path / "shards.jsonl"
    journal.write_text(
        json.dumps({"shard": 0, "papers": [{"arxiv_id": "2606.00001"}]}) + "\n",
        encoding="utf8",
    )
    hashes = {"shard-00000": {"elements.parquet": hashlib.sha256(b"a").hexdigest()}}
    assert verify_checkpoint(out, journal, hashes) == {"2606.00001": 0}
    (out / "shard-00001").mkdir()
    with pytest.raises(ValueError, match="shards"):
        verify_checkpoint(out, journal, hashes)
    assert (out / "shard-00001").exists()


def test_restore_reuses_verified_shard_and_refuses_changed_local(tmp_path):
    import hashlib

    remote = tmp_path / "remote"
    local = tmp_path / "local"
    (remote / "shard-00000").mkdir(parents=True)
    (remote / "shard-00000" / "x").write_bytes(b"one")
    hashes = {"shard-00000": {"x": hashlib.sha256(b"one").hexdigest()}}
    assert restore_shards(remote, local, hashes) == {"copied": 1, "reused": 0}
    assert restore_shards(remote, local, hashes) == {"copied": 0, "reused": 1}
    (local / "shard-00000" / "x").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        restore_shards(remote, local, hashes)
    assert (local / "shard-00000" / "x").read_bytes() == b"changed"


def test_restore_does_not_publish_corrupt_source(tmp_path):
    import hashlib

    remote, local = tmp_path / "remote", tmp_path / "local"
    (remote / "shard-00000").mkdir(parents=True)
    (remote / "shard-00000" / "x").write_bytes(b"bad")
    hashes = {"shard-00000": {"x": hashlib.sha256(b"good").hexdigest()}}
    with pytest.raises(ValueError, match="hash mismatch"):
        restore_shards(remote, local, hashes)
    assert not (local / "shard-00000").exists()
    assert (remote / "shard-00000" / "x").read_bytes() == b"bad"


def test_restore_checks_available_disk_before_copying(tmp_path, monkeypatch):
    import hashlib
    import shutil

    remote, local = tmp_path / "remote", tmp_path / "local"
    (remote / "shard-00000").mkdir(parents=True)
    (remote / "shard-00000/x").write_bytes(b"abc")
    hashes = {"shard-00000": {"x": hashlib.sha256(b"abc").hexdigest()}}
    monkeypatch.setattr(shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(100, 99, 1))
    with pytest.raises(OSError, match="free space"):
        restore_shards(remote, local, hashes)
    assert not (local / "shard-00000").exists()


def test_inspect_run_pins_identity_and_rejects_incomplete_run(tmp_path):
    root = tmp_path / "run"
    (root / "work").mkdir(parents=True)
    (root / "out" / "shard-00000").mkdir(parents=True)
    (root / "M2_MANIFEST.json").write_text(
        json.dumps({"m2_run_id": "run", "code_revision": "abc", "expected_ids": 1}), encoding="utf8"
    )
    (root / "SESSION_STATE.json").write_text(
        json.dumps({"sessions": [{"status": "complete", "returncode": 0}]}), encoding="utf8"
    )
    (root / "work" / "run_summary.json").write_text(
        json.dumps({"interrupted": False, "papers_committed_total": 1}), encoding="utf8"
    )
    (root / "work" / "shards.jsonl").write_text(
        json.dumps({"shard": 0, "papers": [{"arxiv_id": "2606.00001"}]}) + "\n", encoding="utf8"
    )
    (root / "work" / "shard-hashes.json").write_text(
        json.dumps({"shard-00000": {}}), encoding="utf8"
    )
    identity, hashes = inspect_run(root, "run", "qa-sha")
    assert identity["parser_revision"] == "abc" and identity["qa_revision"] == "qa-sha"
    assert len(identity["journal_sha256"]) == 64 and len(hashes) == 1
    with pytest.raises(ValueError, match="shard count"):
        inspect_run(root, "run", "qa-sha", expected_shards=2)
    (root / "work" / "run_summary.json").write_text(
        json.dumps({"interrupted": True, "papers_committed_total": 1}), encoding="utf8"
    )
    with pytest.raises(ValueError, match="incomplete"):
        inspect_run(root, "run", "qa-sha")


def test_prepare_qa_preserves_source_and_rejects_changed_identity(tmp_path):
    root = tmp_path / "run"
    (root / "work").mkdir(parents=True)
    (root / "out" / "shard-00000").mkdir(parents=True)
    (root / "M2_MANIFEST.json").write_text(
        json.dumps({"m2_run_id": "run", "code_revision": "abc"}), encoding="utf8"
    )
    (root / "SESSION_STATE.json").write_text(
        json.dumps({"sessions": [{"status": "complete", "returncode": 0}]}), encoding="utf8"
    )
    (root / "work/run_summary.json").write_text(
        json.dumps({"interrupted": False, "papers_committed_total": 1}), encoding="utf8"
    )
    journal = root / "work/shards.jsonl"
    journal.write_text(
        json.dumps({"shard": 0, "papers": [{"arxiv_id": "2606.00001"}]}) + "\n", encoding="utf8"
    )
    (root / "work/shard-hashes.json").write_text(json.dumps({"shard-00000": {}}), encoding="utf8")
    qa = root / "qa" / "qa-01"
    identity, hashes = prepare_qa(root, "run", "qa-01", "sha1")
    assert qa.joinpath("identity.json").is_file()
    assert identity["qa_revision"] == "sha1" and hashes == {"shard-00000": {}}
    assert prepare_qa(root, "run", "qa-01", "sha1")[0] == identity
    with pytest.raises(ValueError, match="identity"):
        prepare_qa(root, "run", "qa-01", "sha2")
    assert journal.read_text(encoding="utf8").endswith("\n")
    with pytest.raises(ValueError, match="QA run ID"):
        prepare_qa(root, "run", "../bad", "sha1")


def test_full_run_checks_assigned_ids_not_just_count(tmp_path, monkeypatch):
    import src.parser.run as runner

    root = tmp_path / "run"
    (root / "work").mkdir(parents=True)
    (root / "out/shard-00000").mkdir(parents=True)
    (root / "M2_MANIFEST.json").write_text(
        json.dumps(
            {"m2_run_id": "run", "run_mode": "full", "expected_ids": 1, "code_revision": "x"}
        ),
        encoding="utf8",
    )
    (root / "SESSION_STATE.json").write_text(
        json.dumps({"sessions": [{"status": "complete", "returncode": 0}]}), encoding="utf8"
    )
    (root / "work/run_summary.json").write_text(
        json.dumps({"interrupted": False, "papers_committed_total": 1}), encoding="utf8"
    )
    (root / "work/shards.jsonl").write_text(
        json.dumps({"shard": 0, "papers": [{"arxiv_id": "2606.00001"}]}) + "\n", encoding="utf8"
    )
    (root / "work/shard-hashes.json").write_text(json.dumps({"shard-00000": {}}), encoding="utf8")
    monkeypatch.setattr(runner, "assigned_folders", lambda: {"2606-00002"})
    with pytest.raises(ValueError, match="assigned IDs"):
        inspect_run(root, "run", "qa-sha")
