# Drafted with the help of an AI assistant (Gemini, Google), cited per the course rules.
"""Tests for ``src.m3.split_partitions`` and ``src.m3.package_dataset``."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.m3 import export_m1_tables, hf_dataset, package_dataset, predictions, split_partitions
from src.m3.labels import label_path, write_matrix
from src.parser.writer import SCHEMAS as M2_SCHEMAS
from src.parser.writer import to_table as m2_to_table

RANGE_PIDS = {
    "thien": ["2606.30734", "2606.30735", "2606.30736", "2606.30737", "2606.30738", "2606.30739"],
    "tien": ["2606.25734", "2606.25735", "2606.25736", "2606.25737", "2606.25738", "2606.25739"],
    "hieu": ["2606.05734", "2606.05735", "2606.05736", "2606.05737", "2606.05738", "2606.05739"],
    "dang": ["2604.20535", "2604.20536", "2604.20537", "2604.20538", "2604.20539", "2604.20540"],
}


def _populate_labels(labels_dir: Path, *, manual_entries: int = 20) -> None:
    cands = ["1706.03762", "1512.03385"]
    manual_ans = {f"k{i:02d}": ("1706.03762" if i == 0 else None) for i in range(manual_entries)}
    auto_ans = {"k00": "1512.03385", "k01": None}
    for pids in RANGE_PIDS.values():
        # First 3 papers per range: manual; remaining 3 papers per range: auto.
        for pid in pids[:3]:
            write_matrix(label_path(labels_dir, "manual", pid), cands, manual_ans)
        for pid in pids[3:]:
            write_matrix(label_path(labels_dir, "auto", pid), cands, auto_ans)


def test_split_partitions_create_verify_and_guards(tmp_path):
    labels = tmp_path / "labels"
    _populate_labels(labels)
    out_csv = tmp_path / "partitions.csv"

    summary = split_partitions.create_partitions(labels, out_csv, seed=20261116)
    assert summary["total_papers"] == 24
    assert summary["papers_by_partition"] == {"test": 8, "train": 8, "valid": 8}
    assert summary["papers_by_partition_and_method"] == {
        "test_auto": 4,
        "test_manual": 4,
        "train_auto": 4,
        "train_manual": 4,
        "valid_auto": 4,
        "valid_manual": 4,
    }
    assert (tmp_path / "partitions_summary.json").is_file()

    # Refuses accidental overwrite of a frozen split.
    with pytest.raises(FileExistsError, match="already exists"):
        split_partitions.create_partitions(labels, out_csv, seed=20261116)

    # Deterministic given the same seed.
    out_csv2 = tmp_path / "partitions2.csv"
    summary2 = split_partitions.create_partitions(labels, out_csv2, seed=20261116)
    assert out_csv.read_bytes() == out_csv2.read_bytes()
    assert summary["partitions_sha256"] == summary2["partitions_sha256"]

    # Verification passes on the created file.
    verified = split_partitions.verify_partitions(out_csv, labels)
    assert verified["papers_by_partition"] == {"test": 8, "train": 8, "valid": 8}

    # Overlap between manual and auto raises cleanly.
    dup_pid = RANGE_PIDS["thien"][0]
    write_matrix(label_path(labels, "auto", dup_pid), ["1706.03762"], {"k00": None})
    with pytest.raises(ValueError, match="both manual and auto"):
        split_partitions.create_partitions(labels, tmp_path / "p_bad.csv")
    label_path(labels, "auto", dup_pid).unlink()

    # Manual paper below Q=20 entry floor raises cleanly.
    bad_labels = tmp_path / "labels_short"
    _populate_labels(bad_labels, manual_entries=10)
    with pytest.raises(ValueError, match="entry floor"):
        split_partitions.create_partitions(bad_labels, tmp_path / "p_short.csv")


def _build_full_six_table_inputs(tmp_path: Path):
    """Create tiny M1, M2 (2 shards across 4 ranges), labels and predictions inputs."""
    corpus = tmp_path / "corpus"
    m2_out = tmp_path / "m2_out"
    labels = tmp_path / "labels"

    shard_rows = [
        {"elements": [], "hierarchy": [], "bibtex": []},
        {"elements": [], "hierarchy": [], "bibtex": []},
    ]
    part_rows = []
    all_pids = [pid for pids in RANGE_PIDS.values() for pid in pids[:2]]

    for idx, pid in enumerate(all_pids):
        folder = corpus / pid.replace(".", "-")
        folder.mkdir(parents=True)
        (folder / "metadata.json").write_text(
            json.dumps(
                {
                    "arxiv_id": pid,
                    "title": f"Paper {idx}",
                    "authors": ["Alice A"],
                    "submission_date": "2026-06-01T00:00:00Z",
                    "revised_dates": [],
                    "venue": None,
                }
            ),
            encoding="utf-8",
        )
        (folder / "references.json").write_text(
            json.dumps(
                {
                    "arxiv_id": pid,
                    "status": "ok",
                    "references": [
                        {
                            "s2_id": f"s{idx}",
                            "title": "Attention Is All You Need",
                            "authors": ["Ashish Vaswani"],
                            "submission_date": "2017-06-12",
                            "arxiv_id": "1706.03762",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        s = shard_rows[idx % 2]
        prefix = pid.replace(".", "-")
        s["elements"].extend(
            [
                {"element_id": f"{prefix}#d0", "arxiv_id": pid, "kind": "document", "content": ""},
                {
                    "element_id": f"{prefix}#s1",
                    "arxiv_id": pid,
                    "kind": "sentence",
                    "content": "Hello world.",
                },
            ]
        )
        s["hierarchy"].append(
            {
                "arxiv_id": pid,
                "version": 1,
                "element_id": f"{prefix}#s1",
                "parent_id": f"{prefix}#d0",
            }
        )
        s["bibtex"].append(
            {
                "arxiv_id": pid,
                "citation_key": "vaswani2017",
                "entry_type": "inproceedings",
                "title": "Attention Is All You Need",
                "authors": ["Vaswani, Ashish"],
                "year": 2017,
                "doi": "10.48550/arXiv.1706.03762",
                "journal": None,
                "url": None,
            }
        )
        method = "manual" if idx % 2 == 0 else "auto"
        write_matrix(label_path(labels, method, pid), ["1706.03762"], {"vaswani2017": "1706.03762"})
        part_rows.append({"arxiv_id": pid, "partition": "test" if idx % 2 == 0 else "train"})

    for i, s in enumerate(shard_rows):
        sd = m2_out / f"shard-{i:05d}"
        sd.mkdir(parents=True)
        for tname in ("elements", "hierarchy", "bibtex"):
            pq.write_table(m2_to_table(tname, s[tname]), sd / f"{tname}.parquet")

    m1_split = tmp_path / "m1_split"
    export_m1_tables.export_m1_tables([corpus], m1_split, split_by_range=True, shard_papers=2)
    m1_all = tmp_path / "m1_all"
    export_m1_tables.export_m1_tables([corpus], m1_all, assigned_only=True, shard_papers=4)

    part_csv = tmp_path / "partitions.csv"
    with part_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["arxiv_id", "partition"])
        w.writeheader()
        w.writerows(part_rows)

    preds_split = tmp_path / "preds_split"
    predictions.run_prediction_pipeline(
        m2_out,
        part_csv,
        preds_split,
        refs_dir=m1_all / "data" / "references",
        labels_dir=labels,
        split_by_range=True,
    )
    preds_all = tmp_path / "preds_all"
    predictions.run_prediction_pipeline(
        m2_out,
        part_csv,
        preds_all,
        refs_dir=m1_all / "data" / "references",
        labels_dir=labels,
        split_by_range=False,
    )
    return m1_split, m1_all, m2_out, preds_split, preds_all, labels


def test_package_dataset_by_range_prepack_and_full_strict_schema(tmp_path):
    m1_split, m1_all, m2_out, preds_split, preds_all, labels = _build_full_six_table_inputs(
        tmp_path
    )

    # Step 1: Pre-package 5/6 M1+M2 tables without predictions.
    pkg_out = tmp_path / "packages_by_range"
    pre = package_dataset.package_datasets(
        m1_dir=m1_split,
        m2_dir=m2_out,
        labels_dir=labels,
        out_dir=pkg_out,
        mode="by-range",
        allow_missing_predictions=True,
        target_rows={"elements": 2, "hierarchy": 1, "bibtex": 1},
    )
    for owner in ("thien", "tien", "hieu", "dang"):
        info = pre["packages"][owner]
        assert info["has_predictions"] is False
        assert info["tables"]["papers"]["rows"] == 2
        assert info["tables"]["references"]["rows"] == 2
        assert info["tables"]["elements"]["rows"] == 4
        assert info["tables"]["hierarchy"]["rows"] == 2
        assert info["tables"]["bibtex"]["rows"] == 2
        assert info["labels_staged"] == 2
        # Verify M2 schemas (including dictionary-encoded kind & entry_type) are preserved.
        el_pq = pkg_out / owner / "data" / "elements" / "part-00000.parquet"
        assert pq.read_schema(el_pq).equals(M2_SCHEMAS["elements"])
        assert pa.types.is_dictionary(pq.read_schema(el_pq).field("kind").type)

    # Step 2: Re-pack with --skip-m2 once predictions land -> strict schema passes & writes README.
    full = package_dataset.package_datasets(
        m1_dir=m1_split,
        m2_dir=m2_out,
        predictions_dir=preds_split,
        labels_dir=labels,
        out_dir=pkg_out,
        mode="by-range",
        skip_m2=True,
        repo_id_template="testuser/arxiv-nhom1-{owner}",
    )
    for owner in ("thien", "tien", "hieu", "dang"):
        assert full["packages"][owner]["strict_schema_verified"] is True
        assert full["packages"][owner]["tables"]["predictions"]["rows"] == 2
        card = (pkg_out / owner / "README.md").read_text(encoding="utf-8")
        assert "path: data/papers/*.parquet" in card
        assert "path: data/predictions/*.parquet" in card
        assert hf_dataset.check_package(pkg_out / owner, strict_schema=True)["elements"] == 4

    # Combined single-dataset mode also passes strict schema.
    comb_out = tmp_path / "packages_combined"
    comb = package_dataset.package_datasets(
        m1_dir=m1_all,
        m2_dir=m2_out,
        predictions_dir=preds_all,
        labels_dir=labels,
        out_dir=comb_out,
        mode="combined",
        repo_id_template="testuser/arxiv-nhom1-all",
    )
    assert comb["packages"]["all"]["strict_schema_verified"] is True
    assert comb["packages"]["all"]["tables"]["elements"]["rows"] == 16
    assert comb["packages"]["all"]["tables"]["predictions"]["rows"] == 8
    assert "path: data/bibtex/*.parquet" in (comb_out / "all" / "README.md").read_text("utf-8")
