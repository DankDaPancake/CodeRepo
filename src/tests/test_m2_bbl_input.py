import hashlib
import json

import pytest

from src.benchmark.m2_bbl_input import load_bbl_index


def make_run(root):
    data = b"example bibliography"
    path = root / "files/2604-20536/v1/main.bbl"
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    record = {
        "arxiv_id": "2604.20536",
        "version": 1,
        "status": "recovered",
        "files": [
            {
                "path": "files/2604-20536/v1/main.bbl",
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ],
    }
    (root / "versions.jsonl").write_text(json.dumps(record) + "\n", encoding="utf8")
    return path


def test_reads_verified_version_index(tmp_path):
    path = make_run(tmp_path)
    assert load_bbl_index(tmp_path) == {("2604.20536", 1): [path]}


def test_rejects_changed_file(tmp_path):
    path = make_run(tmp_path)
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        load_bbl_index(tmp_path)


def test_rejects_path_traversal(tmp_path):
    make_run(tmp_path)
    journal = tmp_path / "versions.jsonl"
    record = json.loads(journal.read_text(encoding="utf8"))
    record["files"][0]["path"] = "files/2604-20536/v1/../../outside.bbl"
    journal.write_text(json.dumps(record) + "\n", encoding="utf8")
    with pytest.raises(ValueError, match="Unsafe"):
        load_bbl_index(tmp_path)


def test_detects_same_size_content_change(tmp_path):
    path = make_run(tmp_path)
    path.write_bytes(b"X" * len(path.read_bytes()))
    with pytest.raises(ValueError, match="integrity"):
        load_bbl_index(tmp_path)


def test_same_size_recovery_change_is_rejected_on_resume(tmp_path):
    from src.benchmark.m2_bbl_input import verify_run_identity

    source = tmp_path / "recovery"
    source.mkdir()
    path = make_run(source)
    work = tmp_path / "work"
    verify_run_identity(source, work)
    path.write_bytes(b"X" * len(path.read_bytes()))
    with pytest.raises(ValueError, match="integrity"):
        verify_run_identity(source, work)


def test_rejects_invalid_path_type(tmp_path):
    make_run(tmp_path)
    journal = tmp_path / "versions.jsonl"
    record = json.loads(journal.read_text(encoding="utf8"))
    record["files"][0]["path"] = 17
    journal.write_text(json.dumps(record) + "\n", encoding="utf8")
    with pytest.raises(ValueError, match="Unsafe"):
        load_bbl_index(tmp_path)


def test_hashes_match_the_verified_journal(tmp_path):
    from src.benchmark.m2_bbl_input import load_bbl_hashes

    path = make_run(tmp_path)
    index = load_bbl_index(tmp_path)
    assert load_bbl_hashes(tmp_path, index)[path] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_complete_recovery_rejects_missing_candidate(tmp_path):
    from src.benchmark.m2_bbl_input import validate_recovery_complete

    make_run(tmp_path)
    candidates = [
        {"arxiv_id": "2604.20536", "version": 1},
        {"arxiv_id": "2604.20541", "version": 2},
    ]
    (tmp_path / "candidates.json").write_text(json.dumps(candidates), encoding="utf8")
    with pytest.raises(ValueError, match="candidate"):
        validate_recovery_complete(tmp_path)


def test_complete_recovery_rejects_unknown_status(tmp_path):
    from src.benchmark.m2_bbl_input import validate_recovery_complete

    make_run(tmp_path)
    journal = tmp_path / "versions.jsonl"
    record = json.loads(journal.read_text(encoding="utf8"))
    record["status"] = "recoveredd"
    journal.write_text(json.dumps(record) + "\n", encoding="utf8")
    (tmp_path / "candidates.json").write_text(
        json.dumps([{"arxiv_id": record["arxiv_id"], "version": 1}]), encoding="utf8"
    )
    with pytest.raises(ValueError, match="status"):
        validate_recovery_complete(tmp_path)
