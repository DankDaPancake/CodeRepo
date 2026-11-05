"""The notebook is a thin, non-destructive, version-pinned Colab entrypoint."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "name", ["arxiv_nhom1_crawl_benchmark.ipynb", "arxiv_nhom1_s3_arxiv_benchmark.ipynb"]
)
def test_checkout_adds_repo_to_python_path(name):
    cells = json.loads(
        (Path(__file__).parents[1] / "notebooks" / name).read_text(encoding="utf-8")
    )["cells"]
    source = "".join(next(c for c in cells if c.get("id") == "checkout-revision")["source"])
    assert "sys.path.insert(0, str(repo_dir))" in source


def test_single_notebook_has_safe_smoke_defaults_and_no_outputs():
    folder = Path(__file__).parents[1] / "notebooks"
    path = folder / "arxiv_nhom1_crawl_benchmark.ipynb"
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert not (folder / "colab_crawl.ipynb").exists()
    assert not (folder / "colab_benchmark.ipynb").exists()
    source = "\n".join("".join(c["source"]) for c in notebook["cells"])
    assert 'MODE = "sample"' in source
    assert "COUNT = 500" in source
    assert "RESUME = False" in source
    assert "SHIFT_OWNER" not in source
    assert "TAKEOVER" not in source
    assert "run_benchmark(" in source and "prepare_drive(" in source
    assert "rm -rf" not in source
    assert "shutil.rmtree" not in source
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            assert not cell.get("outputs") and cell.get("execution_count") is None
            ast.parse("".join(cell["source"]))


def test_notebook_refuses_cached_pipeline_modules_before_setup():
    path = Path(__file__).parents[1] / "notebooks/arxiv_nhom1_crawl_benchmark.ipynb"
    cells = json.loads(path.read_text(encoding="utf-8"))["cells"]
    guards = [(i, c) for i, c in enumerate(cells) if c.get("id") == "fresh-kernel-guard"]
    assert len(guards) == 1
    index, guard = guards[0]
    setup = next(i for i, c in enumerate(cells) if "drive.mount(" in "".join(c["source"]))
    assert index < setup
    tree = ast.parse("".join(guard["source"]))
    checks = ast.Module(
        body=[n for n in tree.body if not isinstance(n, ast.Import)], type_ignores=[]
    )
    code = compile(ast.fix_missing_locations(checks), "kernel_guard", "exec")
    exec(code, {"sys": SimpleNamespace(modules={"pandas": object()})})
    with pytest.raises(RuntimeError, match="Restart runtime"):
        exec(code, {"sys": SimpleNamespace(modules={"src.benchmark.runner": object()})})


def test_notebook_defaults_to_drive_smoke_without_embedded_token():
    path = Path(__file__).parents[1] / "notebooks/arxiv_nhom1_crawl_benchmark.ipynb"
    nb = json.loads(path.read_text(encoding="utf-8"))
    config = next(c for c in nb["cells"] if "MODE = " in "".join(c["source"]))
    values = {}
    exec("".join(config["source"]), values)
    assert "HF_REPO_ID" not in values
    assert values["MODE"] == "sample" and values["COUNT"] == 500
    assert values["OFFSET"] == 500 and values["CHUNK_SIZE"] == 100
    assert values["SNAPSHOT_PATH"] == "/content/arxiv-assigned-20000.jsonl"
    assert "HF_TOKEN" not in values


@pytest.mark.parametrize("state", ["copy", "existing", "interrupted", "corrupt"])
def test_snapshot_cell_verifies_drive_input_before_storage(tmp_path, monkeypatch, state):
    import hashlib
    import shutil
    import sys

    path = Path(__file__).parents[1] / "notebooks/arxiv_nhom1_crawl_benchmark.ipynb"
    cells = json.loads(path.read_text(encoding="utf-8"))["cells"]
    index, cell = next((i, c) for i, c in enumerate(cells) if c.get("id") == "download-snapshot")
    storage = next(i for i, c in enumerate(cells) if c.get('id') == 'authorize-storage')
    assert index < storage
    target, source = tmp_path / "snapshot.jsonl", tmp_path / "drive" / "input.jsonl"
    source.parent.mkdir()
    record = b'{"id":"2604.20535","versions":[{"version":"v1"}]}\n'
    source.write_bytes(record if state != "corrupt" else b"wrong input")
    if state == "existing":
        target.write_bytes(record)

    def mount(*args, **kwargs):
        if state == "existing":
            pytest.fail("Verified existing local input should not mount Drive")

    monkeypatch.setitem(
        sys.modules, "google.colab", SimpleNamespace(drive=SimpleNamespace(mount=mount))
    )
    if state == "interrupted":

        def interrupted(src, dst):
            Path(dst).write_bytes(record[:10])
            raise OSError("interrupted")

        monkeypatch.setattr(shutil, "copyfile", interrupted)
    values = {
        "SNAPSHOT_PATH": str(target),
        "SNAPSHOT_DRIVE_PATH": str(source),
        "SNAPSHOT_SHA256": hashlib.sha256(record).hexdigest(),
    }
    if state in ("interrupted", "corrupt"):
        with pytest.raises((OSError, ValueError)):
            exec("".join(cell["source"]), values)
        assert not target.exists()
    else:
        exec("".join(cell["source"]), values)
        assert target.read_bytes() == record
    assert source.exists(), "Never delete the Drive input"


def test_drive_authorization_does_not_read_hf_secret(tmp_path, monkeypatch):
    import sys

    path = Path(__file__).parents[1] / "notebooks/arxiv_nhom1_crawl_benchmark.ipynb"
    cells = json.loads(path.read_text(encoding="utf-8"))["cells"]
    cell = next(c for c in cells if c.get("id") == "authorize-storage")

    def forbidden(name):
        pytest.fail(f"Drive branch must not access secret {name}")

    monkeypatch.setitem(
        sys.modules,
        "google.colab",
        SimpleNamespace(
            userdata=SimpleNamespace(get=forbidden), drive=SimpleNamespace(mount=lambda *a: None)
        ),
    )
    values = {"STORAGE_BACKEND": "drive", "DRIVE_DIR": str(tmp_path)}
    exec("".join(cell["source"]), values)
    assert values["DRIVE"] == tmp_path



def test_notebook_is_drive_only():
    path = Path(__file__).parents[1] / "notebooks/arxiv_nhom1_crawl_benchmark.ipynb"
    cells = json.loads(path.read_text(encoding="utf-8"))["cells"]
    source = "\n".join("".join(c["source"]) for c in cells)
    assert "huggingface" not in source.lower()
    assert "HF_TOKEN" not in source
    assert "RUN_CRAWL = False" in source
