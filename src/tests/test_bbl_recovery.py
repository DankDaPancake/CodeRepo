import io
import json
import tarfile

import pytest

from src.benchmark.bbl_recovery import inspect_archive, recover, select_candidates


def source_archive():
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, content in [("nested/main.bbl", b"\\bibitem{a} A"), ("refs.bib", b"@article{x}")]:
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            tar.addfile(entry, io.BytesIO(content))
    return out.getvalue()


def test_selection_deduplicates_version_and_preserves_runs(tmp_path):
    rec = {
        "arxiv_id": "2601.00001",
        "version": 1,
        "status": "ok",
        "files": ["main.tex"],
        "dropped": {".bbl": {"files": 1}},
    }
    paths = {}
    for name in ("a", "b"):
        p = tmp_path / name / "versions.jsonl"
        p.parent.mkdir()
        p.write_text(json.dumps(rec) + "\n")
        paths[name] = p
    chosen = select_candidates(paths)
    assert len(chosen) == 1 and chosen[0]["runs"] == ["a", "b"]


def test_archive_keeps_bbl_when_bib_exists_and_rejects_traversal():
    files, bib = inspect_archive(io.BytesIO(source_archive()))
    assert files == {"nested/main.bbl": b"\\bibitem{a} A"} and bib == ["refs.bib"]
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        e = tarfile.TarInfo("../bad.bbl")
        e.size = 1
        tar.addfile(e, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        inspect_archive(io.BytesIO(out.getvalue()))


def test_recovery_resume_verifies_files(tmp_path):
    rec = {
        "arxiv_id": "2601.00001",
        "version": 1,
        "status": "ok",
        "files": ["main.tex"],
        "dropped": {".bbl": {"files": 1}},
    }
    p = tmp_path / "input" / "versions.jsonl"
    p.parent.mkdir()
    p.write_text(json.dumps(rec) + "\n")

    class Response:
        status = 200
        attempts = 1

        def __init__(self, value):
            self.value = value

    class Client:
        def __init__(self):
            self.calls = 0

        def stream(self, url, consume, **kwargs):
            self.calls += 1
            return Response(consume(io.BytesIO(source_archive()), {}))

    client = Client()
    output = tmp_path / "result"
    assert recover({"a": p}, output, client=client)["recovered"] == 1
    recover({"a": p}, output, client=client)
    assert client.calls == 1
    (output / "files/2601-00001/v1/nested/stale.bbl").write_text("stale")
    (output / "files/2601-00001/v1/nested/main.bbl").write_text("changed")
    recover({"a": p}, output, client=client)
    assert client.calls == 2
    assert not (output / "files/2601-00001/v1/nested/stale.bbl").exists()


def test_blocked_stops_and_is_recorded(tmp_path):
    from src.crawler.http_client import BlockedError

    rec = {
        "arxiv_id": "2601.00001",
        "version": 1,
        "status": "ok",
        "files": [],
        "dropped": {".bbl": {"files": 1}},
    }
    p = tmp_path / "in" / "versions.jsonl"
    p.parent.mkdir()
    p.write_text(json.dumps(rec) + "\n")

    class Client:
        def stream(self, url, consume, **kwargs):
            raise BlockedError(url, "blocked", 403, 1)

    progress = []
    with pytest.raises(BlockedError):
        recover({"x": p}, tmp_path / "out", client=Client(), on_progress=progress.append)
    assert progress[0]["status"] == "inconclusive"
    assert json.loads((tmp_path / "out/versions.jsonl").read_text())["status"] == "inconclusive"
    assert not (tmp_path / "out/.running").exists()


def test_no_bbl_and_unavailable_are_not_confused(tmp_path):
    rec = {
        "arxiv_id": "2601.00001",
        "version": 1,
        "status": "ok",
        "files": [],
        "dropped": {".bbl": {"files": 1}},
    }
    p = tmp_path / "in" / "versions.jsonl"
    p.parent.mkdir()
    p.write_text(json.dumps(rec) + "\n")

    class Response:
        status = 404
        attempts = 1

    class Client:
        def stream(self, url, consume, **kwargs):
            return Response()

    assert recover({"x": p}, tmp_path / "out", client=Client()) == {"unavailable": 1}


def test_archive_total_uncompressed_limit_applies_to_non_bbl(monkeypatch):
    import src.benchmark.bbl_recovery as module

    monkeypatch.setattr(module, "MAX_UNPACKED", 4)
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        member = tarfile.TarInfo("figure.pdf")
        member.size = 5
        tar.addfile(member, io.BytesIO(b"12345"))
    with pytest.raises(ValueError, match="uncompressed"):
        inspect_archive(io.BytesIO(data.getvalue()))


def test_progress_reports_completed_and_resumed_versions(tmp_path, capsys):
    rec = {
        "arxiv_id": "2601.00001",
        "version": 1,
        "status": "ok",
        "files": [],
        "dropped": {".bbl": {"files": 1}},
    }
    journal = tmp_path / "input" / "versions.jsonl"
    journal.parent.mkdir()
    journal.write_text(json.dumps(rec) + "\n")

    class Response:
        status = 404
        attempts = 1

    class Client:
        def stream(self, url, consume, **kwargs):
            return Response()

    events = []
    recover({"a": journal}, tmp_path / "out", client=Client(), on_progress=events.append)
    assert events == [
        {
            "completed": 1,
            "total": 1,
            "arxiv_id": "2601.00001",
            "version": 1,
            "status": "unavailable",
            "skipped": False,
        }
    ]
    assert capsys.readouterr().out == ""
    events.clear()
    recover({"a": journal}, tmp_path / "out", client=Client(), on_progress=events.append)
    assert events == [
        {
            "completed": 1,
            "total": 1,
            "arxiv_id": "2601.00001",
            "version": 1,
            "status": "unavailable",
            "skipped": True,
        }
    ]


def test_notebook_rejects_stale_runtime(tmp_path):
    import hashlib
    import json
    from pathlib import Path

    notebook = json.loads(
        (Path(__file__).parents[1] / "notebooks/arxiv_nhom1_bbl_recovery.ipynb").read_text(
            encoding="utf8"
        )
    )
    source = "".join(
        next(
            c
            for c in notebook["cells"]
            if "requirements-recovery.txt" in "".join(c.get("source", []))
        )["source"]
    )
    guard = source.split("# Verify the BBL runtime matches this notebook.\n", 1)[1].split(
        "# End runtime version check.\n", 1
    )[0]
    module = tmp_path / "src/benchmark/bbl_recovery.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        (Path(__file__).parents[1] / "benchmark/bbl_recovery.py").read_text(encoding="utf8"),
        encoding="utf8",
    )
    exec(guard, {"REPO": tmp_path, "hashlib": hashlib})
    module.write_text("outdated code", encoding="utf8")
    with pytest.raises(RuntimeError, match="runtime"):
        exec(guard, {"REPO": tmp_path, "hashlib": hashlib})
