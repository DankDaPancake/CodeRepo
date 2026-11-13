import pytest

from src.benchmark.m2_inputs import verify_corpus_identity


def test_corpus_identity_rejects_same_size_edit(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    file = corpus / "main.tex"
    file.write_text("first", encoding="utf8")
    work = tmp_path / "work"
    verify_corpus_identity([corpus], work)
    file.write_text("other", encoding="utf8")
    with pytest.raises(ValueError, match="corpus input changed"):
        verify_corpus_identity([corpus], work)


def test_cached_checkpoint_rejects_a_different_generation(tmp_path):
    import json

    from src.benchmark.m2_inputs import verify_restored_checkpoint

    local = tmp_path / "local"
    local.mkdir()
    (local / ".checkpoint-head.json").write_text(
        json.dumps({"generation": "old", "files": {}, "directories": []})
    )
    index = {"generation": "new", "files": {}, "directories": []}
    with pytest.raises(ValueError, match="checkpoint"):
        verify_restored_checkpoint(local, index)


def test_cached_checkpoint_rejects_extra_corpus_file(tmp_path):
    import json

    from src.benchmark.m2_inputs import verify_restored_checkpoint

    local = tmp_path / "local"
    (local / "data/corpus").mkdir(parents=True)
    (local / "data/corpus/extra.tex").write_text("unexpected")
    index = {"generation": "same", "files": {}, "directories": []}
    (local / ".checkpoint-head.json").write_text(json.dumps(index))
    with pytest.raises(ValueError, match="extra"):
        verify_restored_checkpoint(local, index)


def test_cached_checkpoint_checks_contents_against_index(tmp_path):
    import hashlib
    import json

    from src.benchmark.m2_inputs import verify_restored_checkpoint

    local = tmp_path / "local"
    file = local / "data/corpus/paper/metadata.json"
    file.parent.mkdir(parents=True)
    file.write_text("first", encoding="utf8")
    index = {
        "generation": "g",
        "files": {"data/corpus/paper/metadata.json": hashlib.sha256(b"first").hexdigest()},
        "directories": [],
    }
    (local / "work").mkdir()
    (local / "work/versions.jsonl").write_bytes(b"")
    index["files"]["work/versions.jsonl"] = hashlib.sha256(b"").hexdigest()
    (local / ".checkpoint-head.json").write_text(json.dumps(index))
    verify_restored_checkpoint(local, index)
    file.write_text("other", encoding="utf8")
    with pytest.raises(ValueError, match="changed"):
        verify_restored_checkpoint(local, index)


def test_checkpoint_allows_reconstructed_checkpoint_events(tmp_path):
    import hashlib
    import json

    from src.benchmark.m2_inputs import verify_restored_checkpoint

    local = tmp_path / "local"
    path = local / "work/checkpoint_events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("reconstructed events", encoding="utf8")
    index = {
        "generation": "g",
        "files": {"work/checkpoint_events.jsonl": hashlib.sha256(b"original").hexdigest()},
        "directories": [],
    }
    (local / "work/versions.jsonl").write_bytes(b"")
    index["files"]["work/versions.jsonl"] = hashlib.sha256(b"").hexdigest()
    (local / ".checkpoint-head.json").write_text(json.dumps(index), encoding="utf8")
    verify_restored_checkpoint(local, index)


def test_cached_checkpoint_requires_indexed_versions_journal(tmp_path):
    import json

    from src.benchmark.m2_inputs import verify_restored_checkpoint

    local = tmp_path / "local"
    local.mkdir()
    index = {"generation": "g", "files": {}, "directories": []}
    (local / ".checkpoint-head.json").write_text(json.dumps(index))
    with pytest.raises(ValueError, match="versions.jsonl"):
        verify_restored_checkpoint(local, index)
