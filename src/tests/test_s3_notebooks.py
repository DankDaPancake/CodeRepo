import json
from pathlib import Path


def read(name):
    return json.loads((Path(__file__).parents[1] / "notebooks" / name).read_text(encoding="utf-8"))


def test_original_is_arxiv_only_and_has_no_s3_preparation():
    cells = read("arxiv_nhom1_crawl_benchmark.ipynb")["cells"]
    src = "\n".join("".join(c["source"]) for c in cells)
    assert "S3_DOWNLOAD" not in src
    assert "huggingface" not in src.lower()
    assert "run_benchmark(" in src


def test_hybrid_notebook_partitions_before_planning_and_requires_explicit_crawl():
    cells = read("arxiv_nhom1_s3_arxiv_benchmark.ipynb")["cells"]
    src = "\n".join("".join(c["source"]) for c in cells)
    assert "partition_snapshot(" in src
    assert "partition.only_v1" in src
    assert "S3_DOWNLOAD = False" in src
    assert 'source_mode="arxiv_s3"' in src
    assert "RUN_CRAWL = False" in src
    assert src.index("partition_snapshot(") < src.index("select_bundles(")


def test_hybrid_uses_existing_bulk_and_manifest():
    cells = read("arxiv_nhom1_s3_arxiv_benchmark.ipynb")["cells"]
    src = "\n".join("".join(c["source"]) for c in cells)
    assert "/content/drive/MyDrive/arxiv-s3/packages" in src
    assert "/content/drive/MyDrive/arxiv-s3/runs/20261102-135934/manifest.xml" in src
    assert "s3_bundle_dir=str(S3_BUNDLE_DIR)" in src


def test_hybrid_uses_drive_without_huggingface_configuration():
    cells = read("arxiv_nhom1_s3_arxiv_benchmark.ipynb")["cells"]
    src = "\n".join("".join(c["source"]) for c in cells)
    assert "huggingface" not in src.lower()
    assert "HF_TOKEN" not in src
    assert 'storage_backend="drive"' in src
    assert 'DRIVE / "runs" / RUN_ID / "MANIFEST.json"' in src


def test_hybrid_member_selection_and_checkpoint_defaults():
    cells = read("arxiv_nhom1_s3_arxiv_benchmark.ipynb")["cells"]
    src = "".join(cells[1]["source"])
    assert 'RANGES = ("thien", "tien", "hieu", "dang")' in src
    assert "COUNT = 1000" in src
    assert "CHECKPOINT_S = 600" in src


def test_hybrid_missing_bundle_goes_to_arxiv_fallback():
    cells = read("arxiv_nhom1_s3_arxiv_benchmark.ipynb")["cells"]
    source = "".join(next(c for c in cells if c.get("id") == "3e980f1a")["source"])
    assert "missing bundles will use arXiv fallback" in source
    assert "raise FileNotFoundError" not in source
