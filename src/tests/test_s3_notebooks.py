import json
from pathlib import Path


def read(name):
    root = Path(__file__).parents[1]
    folder = (
        "artifacts/attempts"
        if name in {"arxiv_nhom1_crawl_benchmark.ipynb", "arxiv_nhom1_s3_arxiv_benchmark.ipynb"}
        else "notebooks"
    )
    return json.loads((root / folder / name).read_text(encoding="utf-8"))


def test_original_is_arxiv_only_and_has_no_s3_preparation():
    cells = read("arxiv_nhom1_crawl_benchmark.ipynb")["cells"]
    src = "\n".join("".join(c["source"]) for c in cells)
    assert "S3_DOWNLOAD" not in src
    assert "run_benchmark(" in src


def test_hybrid_notebook_partitions_before_planning_and_requires_explicit_crawl():
    cells = read("arxiv_nhom1_s3_arxiv_benchmark.ipynb")["cells"]
    src = "\n".join("".join(c["source"]) for c in cells)
    assert "partition_snapshot(" in src
    assert "partition.only_v1" in src
    assert "S3_DOWNLOAD" not in src
    assert "download_bundle" not in src
    assert 'source_mode="arxiv_s3"' in src
    assert "RUN_CRAWL = False" in src
    assert src.index("partition_snapshot(") < src.index("select_bundles(")


def test_hybrid_uses_existing_bulk_and_manifest():
    cells = read("arxiv_nhom1_s3_arxiv_benchmark.ipynb")["cells"]
    src = "\n".join("".join(c["source"]) for c in cells)
    assert "/content/drive/MyDrive/arxiv-s3/packages" in src
    assert "/content/drive/MyDrive/arxiv-s3/runs/20261102-135934/manifest.xml" in src
    assert "s3_bundle_dir=str(S3_BUNDLE_DIR)" in src


def test_hybrid_uses_drive_configuration():
    cells = read("arxiv_nhom1_s3_arxiv_benchmark.ipynb")["cells"]
    src = "\n".join("".join(c["source"]) for c in cells)
    assert 'storage_backend="drive"' in src
    assert 'DRIVE / "runs" / RUN_ID / "MANIFEST.json"' in src


def test_hybrid_member_selection_and_checkpoint_defaults():
    cells = read("arxiv_nhom1_s3_arxiv_benchmark.ipynb")["cells"]
    src = "".join(next(c for c in cells if c.get("id") == "f94c4b6e")["source"])
    assert 'RANGES = ("thien", "tien", "hieu", "dang")' in src
    assert "COUNT = 1000" in src
    assert "CHECKPOINT_S = 600" in src


def test_hybrid_missing_bundle_goes_to_arxiv_fallback():
    cells = read("arxiv_nhom1_s3_arxiv_benchmark.ipynb")["cells"]
    source = "".join(next(c for c in cells if c.get("id") == "3e980f1a")["source"])
    assert "missing bundles will use arXiv fallback" in source
    assert "raise FileNotFoundError" not in source


def test_only_v1_has_no_aws_download_and_keeps_preflight():
    src = "\n".join(
        "".join(c["source"]) for c in read("arxiv_nhom1_only_v1_benchmark.ipynb")["cells"]
    )
    assert "download_bundle" not in src and "S3_DOWNLOAD" not in src
    assert "select_bundles(" in src and "missing bundles will use arXiv fallback" in src


def test_s3_preflight_restores_manifest_and_bundle_paths_on_resume():
    for name in ("arxiv_nhom1_only_v1_benchmark.ipynb", "arxiv_nhom1_s3_arxiv_benchmark.ipynb"):
        source = "\n".join("".join(c["source"]) for c in read(name)["cells"])
        assert 'saved["config"]["s3_manifest"]' in source
        assert 'saved["config"]["s3_bundle_dir"]' in source


def test_download_notebook_defaults_to_all_ids_and_preview():
    src = "\n".join(
        "".join(c["source"]) for c in read("arxiv_nhom1_s3_download_benchmark.ipynb")["cells"]
    )
    assert "DOWNLOAD = False" in src
    assert "validate_snapshot(" in src and "plan_candidates(" in src
    assert "20000" in src and "RequestPayer" not in src  # requester pays handled in helper
