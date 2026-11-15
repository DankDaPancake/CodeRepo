import ast
import json
from pathlib import Path

from src.tests.test_m2_pipeline import corpus  # noqa: F401


def test_qa_notebook_has_clean_python_cells_and_separate_run_paths():
    path = Path(__file__).parents[1] / "notebooks" / "arxiv_nhom1_m2_qa.ipynb"
    notebook = json.loads(path.read_text(encoding="utf8"))
    cells = {c.get("id"): c for c in notebook["cells"]}
    config = "".join(cells["qa-config"]["source"])
    values = {}
    exec(config, values)
    assert values["M2_RUN_ID"] == "m2-full-01"
    assert values["QA_RUN_ID"] != values["M2_RUN_ID"]
    assert values["RUN_QA"] is False
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]))
            assert cell["execution_count"] is None and cell["outputs"] == []


def test_qa_notebook_wires_the_real_checker_and_distinct_evidence():
    path = Path(__file__).parents[1] / "notebooks" / "arxiv_nhom1_m2_qa.ipynb"
    cells = json.loads(path.read_text(encoding="utf8"))["cells"]
    by_id = {c.get("id"): "".join(c["source"]) for c in cells}
    for required in (
        "qa-checkout",
        "qa-prepare",
        "qa-restore",
        "qa-check",
        "qa-corpus",
        "qa-structure",
        "qa-sample",
        "qa-score",
        "qa-export",
    ):
        assert required in by_id
    assert "prepare_qa(" in by_id["qa-prepare"]
    assert "restore_shards(" in by_id["qa-restore"]
    assert "check_run(" in by_id["qa-check"]
    assert "restore_m2(" in by_id["qa-corpus"]
    assert "audit_resumable(" in by_id["qa-structure"]
    assert "draw(" in by_id["qa-sample"]
    assert "src.qa.audit_sample" in by_id["qa-score"]
    assert "m2_qa_evidence" in by_id["qa-export"]
    assert "NotImplementedError" not in "\n".join(by_id.values())


def test_evidence_export_does_not_embed_its_previous_zip(tmp_path):
    import shutil
    import zipfile

    path = Path(__file__).parents[1] / "notebooks" / "arxiv_nhom1_m2_qa.ipynb"
    cells = json.loads(path.read_text(encoding="utf8"))["cells"]
    export = next(c for c in cells if c.get("id") == "qa-export")
    qa, local = tmp_path / "qa", tmp_path / "local"
    qa.mkdir()
    local.mkdir()
    (qa / "check_tables.json").write_text("{}", encoding="utf8")
    (qa / "m2_qa_evidence.zip").write_bytes(b"old")
    (qa / ".qa-sample-interrupted").mkdir()
    (qa / ".qa-sample-interrupted/partial.md").write_text("incomplete")
    values = {"RUN_QA": True, "LOCAL": local, "QA_DESTINATION": qa, "shutil": shutil}
    values["table_report"] = {"ok": True}  # a stale report must not imply this session passed
    exec("".join(export["source"]), values)
    with zipfile.ZipFile(qa / "m2_qa_evidence.zip") as archive:
        assert archive.namelist() == ["check_tables.json", "qa_status.json"]
        status = json.loads(archive.read("qa_status.json"))
        assert status["structure"] == "incomplete"
        assert status["manual_review"] == "pending"
        assert status["table_check"] == "incomplete_or_failed"


def test_evidence_copy_failure_preserves_previous_archive(tmp_path, monkeypatch):
    import shutil

    import pytest

    path = Path(__file__).parents[1] / "notebooks" / "arxiv_nhom1_m2_qa.ipynb"
    cells = json.loads(path.read_text(encoding="utf8"))["cells"]
    export = next(c for c in cells if c.get("id") == "qa-export")
    qa, local = tmp_path / "qa", tmp_path / "local"
    qa.mkdir()
    local.mkdir()
    destination = qa / "m2_qa_evidence.zip"
    destination.write_bytes(b"previous")

    def fail_copy(src, dst):
        Path(dst).write_bytes(b"partial")
        raise OSError("drive interrupted")

    monkeypatch.setattr(shutil, "copy2", fail_copy)
    with pytest.raises(OSError, match="interrupted"):
        exec(
            "".join(export["source"]),
            {"RUN_QA": True, "LOCAL": local, "QA_DESTINATION": qa, "shutil": shutil},
        )
    assert destination.read_bytes() == b"previous"


def test_interrupted_sample_can_be_retried_without_deleting_user_data(tmp_path, monkeypatch):
    import hashlib

    import pytest

    import src.qa.audit_sample as sample
    import src.qa.qa_inputs as inputs

    path = Path(__file__).parents[1] / "notebooks" / "arxiv_nhom1_m2_qa.ipynb"
    cells = json.loads(path.read_text(encoding="utf8"))["cells"]
    cell = next(c for c in cells if c.get("id") == "qa-sample")
    qa, local = tmp_path / "qa", tmp_path / "local"
    qa.mkdir()
    local.mkdir()
    monkeypatch.setattr(sample, "eligible_papers", lambda path: {"paper": {}})

    def interrupted(out, work, report, **kwargs):
        report.mkdir(parents=True)
        (report / "partial.md").write_text("partial")
        raise RuntimeError("interrupted")

    monkeypatch.setattr(sample, "draw", interrupted)
    (local / "shards.jsonl").write_text('{"shard":0,"papers":[]}\n', encoding="utf8")
    monkeypatch.setattr(inputs, "verify_checkpoint", lambda *args, **kwargs: {})
    scope = {
        "RUN_QA": True,
        "QA_DESTINATION": qa,
        "LOCAL": local,
        "Path": Path,
        "local_out": local / "out",
        "DATA_ROOTS": [],
        "local_journal": local / "shards.jsonl",
        "identity": {
            "journal_sha256": hashlib.sha256((local / "shards.jsonl").read_bytes()).hexdigest()
        },
        "qa_table_passed": True,
        "qa_sources_verified": True,
        "hashes": {},
    }
    from tqdm.auto import tqdm

    scope["tqdm"] = tqdm
    with pytest.raises(RuntimeError, match="interrupted"):
        exec("".join(cell["source"]), scope)
    assert not (qa / "audit30").exists()


def test_structure_does_not_run_when_source_restore_is_incomplete(tmp_path):
    import pytest
    from tqdm.auto import tqdm

    path = Path(__file__).parents[1] / "notebooks" / "arxiv_nhom1_m2_qa.ipynb"
    cells = json.loads(path.read_text(encoding="utf8"))["cells"]
    cell = next(c for c in cells if c.get("id") == "qa-structure")
    scope = {
        "RUN_QA": True,
        "DATA_ROOTS": [],
        "local_out": tmp_path,
        "QA_DESTINATION": tmp_path / "qa",
        "identity": {"x": 1},
        "hashes": {},
        "tqdm": tqdm,
        "MAX_SHARD_ROWS": 1,
        "local_journal": tmp_path / "journal",
        "qa_sources_verified": False,
        "qa_table_passed": True,
    }
    with pytest.raises(RuntimeError, match="source"):
        exec("".join(cell["source"]), scope)


def test_failed_restore_invalidates_previous_stage_success(tmp_path, monkeypatch):
    import pytest

    import src.qa.qa_inputs as inputs

    path = Path(__file__).parents[1] / "notebooks" / "arxiv_nhom1_m2_qa.ipynb"
    cells = json.loads(path.read_text(encoding="utf8"))["cells"]
    cell = next(c for c in cells if c.get("id") == "qa-restore")

    def fail(*args, **kwargs):
        raise ValueError("bad hash")

    monkeypatch.setattr(inputs, "restore_shards", fail)
    scope = {
        "RUN_QA": True,
        "LOCAL": tmp_path / "local",
        "SOURCE": tmp_path,
        "hashes": {},
        "qa_table_passed": True,
        "qa_structure_complete": True,
        "qa_sources_verified": True,
    }
    with pytest.raises(ValueError, match="bad hash"):
        exec("".join(cell["source"]), scope)
    assert not scope["qa_table_passed"] and not scope["qa_structure_complete"]
    assert not scope["qa_sources_verified"]


def test_sample_rejects_modified_shard_after_table_check(tmp_path):
    import hashlib

    import pytest
    from tqdm.auto import tqdm

    notebook = Path(__file__).parents[1] / "notebooks" / "arxiv_nhom1_m2_qa.ipynb"
    cells = json.loads(notebook.read_text(encoding="utf8"))["cells"]
    cell = next(c for c in cells if c.get("id") == "qa-sample")
    qa, local = tmp_path / "qa", tmp_path / "local"
    shard = local / "out/shard-00000"
    shard.mkdir(parents=True)
    qa.mkdir()
    (shard / "file").write_bytes(b"changed")
    journal = local / "shards.jsonl"
    journal.write_text(
        json.dumps({"shard": 0, "papers": [{"arxiv_id": "2606.00001"}]}) + "\n", encoding="utf8"
    )
    hashes = {"shard-00000": {"file": hashlib.sha256(b"original").hexdigest()}}
    scope = {
        "RUN_QA": True,
        "qa_table_passed": True,
        "qa_sources_verified": True,
        "QA_DESTINATION": qa,
        "LOCAL": local,
        "local_out": local / "out",
        "local_journal": journal,
        "DATA_ROOTS": [],
        "hashes": hashes,
        "tqdm": tqdm,
        "identity": {"journal_sha256": hashlib.sha256(journal.read_bytes()).hexdigest()},
    }
    with pytest.raises(ValueError, match="hash mismatch"):
        exec("".join(cell["source"]), scope)
    assert not (qa / "audit30").exists()
    assert scope["qa_table_passed"] is False


def test_sample_does_not_publish_if_input_changes_during_draw(tmp_path, monkeypatch):
    import hashlib

    import pytest
    from tqdm.auto import tqdm

    import src.qa.audit_sample as sample

    notebook = Path(__file__).parents[1] / "notebooks" / "arxiv_nhom1_m2_qa.ipynb"
    cells = json.loads(notebook.read_text(encoding="utf8"))["cells"]
    cell = next(c for c in cells if c.get("id") == "qa-sample")
    qa, local = tmp_path / "qa", tmp_path / "local"
    shard = local / "out/shard-00000"
    shard.mkdir(parents=True)
    qa.mkdir()
    file = shard / "file"
    file.write_bytes(b"original")
    journal = local / "shards.jsonl"
    journal.write_text(
        json.dumps({"shard": 0, "papers": [{"arxiv_id": "2606.00001"}]}) + "\n", encoding="utf8"
    )
    hashes = {"shard-00000": {"file": hashlib.sha256(b"original").hexdigest()}}
    monkeypatch.setattr(sample, "eligible_papers", lambda path: {"paper": {}})

    def mutate(out, work, report, **kwargs):
        report.mkdir(parents=True)
        (report / "audit_sheet.csv").write_text("sheet")
        file.write_bytes(b"changed")
        return [{}]

    monkeypatch.setattr(sample, "draw", mutate)
    scope = {
        "RUN_QA": True,
        "qa_table_passed": True,
        "qa_sources_verified": True,
        "QA_DESTINATION": qa,
        "LOCAL": local,
        "local_out": local / "out",
        "local_journal": journal,
        "DATA_ROOTS": [],
        "hashes": hashes,
        "tqdm": tqdm,
        "Path": Path,
        "identity": {"journal_sha256": hashlib.sha256(journal.read_bytes()).hexdigest()},
    }
    with pytest.raises(ValueError, match="hash mismatch"):
        exec("".join(cell["source"]), scope)
    assert not (qa / "audit30").exists()
    assert scope["qa_table_passed"] is False


def test_qa_cells_run_end_to_end_and_resume(corpus, tmp_path):  # noqa: F811
    import hashlib
    import os
    import shutil
    import time

    from src.benchmark.m2_sync import sync_to_drive
    from src.parser.run import Options, run

    m1, source = tmp_path / "m1", tmp_path / "m2" / "run"
    original, work, report = tmp_path / "out", tmp_path / "work", tmp_path / "report"
    remote = m1 / "run1"
    shutil.copytree(corpus, remote / "data/corpus")
    (remote / "work").mkdir(parents=True)
    (remote / "work/versions.jsonl").write_text("{}\n", encoding="utf8")
    files = {
        p.relative_to(remote).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in remote.rglob("*")
        if p.is_file()
    }
    directories = [
        p.relative_to(remote).as_posix() + "/"
        for p in (remote / "data/corpus").rglob("*")
        if p.is_dir()
    ]
    index = {"generation": "one", "files": files, "directories": directories}
    (remote / "INDEX.json").write_text(json.dumps(index), encoding="utf8")
    run(corpus, original, work, options=Options(), progress=False, shard_papers=1)
    source.mkdir(parents=True)
    manifest = {
        "m2_run_id": "run",
        "run_mode": "smoke",
        "expected_ids": 3,
        "code_revision": "parser-sha",
        "runs": {"run1": "run1"},
        "crawl_index_sha256": {
            "run1": hashlib.sha256((remote / "INDEX.json").read_bytes()).hexdigest()
        },
    }
    (source / "M2_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf8")
    (source / "SESSION_STATE.json").write_text(
        json.dumps({"sessions": [{"status": "complete", "returncode": 0}]}), encoding="utf8"
    )
    sync_to_drive(original, work, report, source)
    cells = json.loads(
        (Path(__file__).parents[1] / "notebooks/arxiv_nhom1_m2_qa.ipynb").read_text(encoding="utf8")
    )["cells"]
    by_id = {c.get("id"): "".join(c["source"]) for c in cells}
    qa = source / "qa" / "qa-01"
    scope = {
        "SOURCE": source,
        "M2_RUN_ID": "run",
        "QA_RUN_ID": "qa-01",
        "QA_REVISION": "qa-sha",
        "QA_DESTINATION": qa,
        "LOCAL": tmp_path / "local",
        "M1_DRIVE_DIR": str(m1),
        "LOCAL_CORPUS_ROOT": str(tmp_path / "source-local"),
        "REUSE_PARTIAL_RESTORE": False,
        "RESTORE_WORKERS": 1,
        "MAX_SHARD_ROWS": 10000,
        "EXPECTED_SHARDS": 3,
        "RUN_QA": True,
        "Path": Path,
        "json": json,
        "hashlib": hashlib,
        "os": os,
        "shutil": shutil,
        "time": time,
    }
    for cell in (
        "qa-prepare",
        "qa-restore",
        "qa-check",
        "qa-corpus",
        "qa-structure",
        "qa-sample",
        "qa-export",
    ):
        exec(by_id[cell], scope)
    assert scope["table_report"]["ok"]
    assert scope["table_report"]["timing_scope"] == "current_session_only"
    assert (qa / "structure_audit.csv").exists() and (qa / "audit30/audit_sheet.csv").exists()
    assert (qa / "m2_qa_evidence.zip").exists()
    sheet = qa / "audit30/audit_sheet.csv"
    before = sheet.read_bytes()
    for cell in (
        "qa-prepare",
        "qa-restore",
        "qa-check",
        "qa-corpus",
        "qa-structure",
        "qa-sample",
        "qa-export",
    ):
        exec(by_id[cell], scope)
    assert sheet.read_bytes() == before
    scope["RUN_SCORE"] = True
    exec(by_id["qa-score"], scope)
    exec(by_id["qa-export"], scope)
    status = json.loads((qa / "qa_status.json").read_text(encoding="utf8"))
    assert status["manual_review"] == "scored_inspect_counts"
    assert (qa / "audit30/audit_summary.csv").exists()
    sheet.write_bytes(sheet.read_bytes() + b"\n")
    exec(by_id["qa-export"], scope)
    status = json.loads((qa / "qa_status.json").read_text(encoding="utf8"))
    assert status["manual_review"] == "pending"
