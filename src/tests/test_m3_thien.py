# Drafted with the help of an AI assistant (Gemini, Google), cited per the course rules.
"""Unit and end-to-end tests for Thiên's M3 pipeline modules.

Covers:
- ``restore_inputs.restore_m1_json`` / ``restore_metadata``
- ``cleaning`` (LaTeX/accent normalization, stop-words, surnames, arXiv ID parsing)
- ``export_m1_tables`` (exact M1/M3 Parquet schemas, flat columns, dedup, range split)
- ``candidates`` (sharded bounded-memory candidate matrix builder from Parquet and JSON)
- ``auto_label`` (cascading rules, ambiguity guard, >=10% stratified sampling, manual evaluation)
- ``predictions`` (exact Arrow schema incl. dictionary partition, validators, pluggable ranker)
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.m3 import (
    auto_label,
    candidates,
    cleaning,
    crosscheck,
    export_m1_tables,
    hf_dataset,
    predictions,
)
from src.m3.labels import label_path, read_matrix, write_matrix
from src.m3.restore_inputs import restore_m1_json, restore_metadata
from src.parser.writer import to_table as m2_to_table

# Real assigned-range IDs (one per member, plus extra papers for stratified sampling).
P_THIEN = ["2606.30734", "2606.30735", "2606.30736", "2606.30737", "2606.30738"]
P_TIEN = ["2606.25734", "2606.25735", "2606.25736", "2606.25737", "2606.25738"]
P_HIEU = ["2606.05734", "2606.05735", "2606.05736", "2606.05737", "2606.05738"]
P_DANG = ["2604.20535", "2604.20536", "2604.20537", "2604.20538", "2604.20539"]
ALL_PIDS = P_THIEN + P_TIEN + P_HIEU + P_DANG


def _build_synthetic_corpus(tmp_path: Path):
    """Build a 20-paper synthetic M1 + M2 corpus spanning all four assigned ranges."""
    corpus = tmp_path / "corpus"
    m2 = tmp_path / "m2"
    shard0_rows: list[dict] = []
    shard1_rows: list[dict] = []

    for idx, pid in enumerate(ALL_PIDS):
        folder = corpus / pid.replace(".", "-")
        folder.mkdir(parents=True)
        meta = {
            "arxiv_id": pid,
            "title": f"Synthetic Paper {idx}: Lattices and Graphs",
            "authors": [f"Alice Author{idx}", "Bob Coauthor"],
            "submission_date": "2026-06-01T10:00:00Z",
            "revised_dates": ["2026-06-10T10:00:00Z"] if idx % 2 == 0 else [],
            "venue": "NeurIPS 2026" if idx % 3 == 0 else None,
            "num_versions": 2 if idx % 2 == 0 else 1,
            "categories": ["cs.LG"],
            "doi": None,
        }
        (folder / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

        refs = [
            {
                "s2_id": f"s2-{idx}-a",
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani", "Noam Shazeer"],
                "submission_date": "2017-06-12",
                "year": 2017,
                "venue": "NeurIPS",
                "arxiv_id": "1706.03762",
            },
            {
                "s2_id": f"s2-{idx}-b",
                "title": "Deep Residual Learning for Image Recognition",
                "authors": ["Kaiming He", "Xiangyu Zhang", "Shaoqing Ren", "Jian Sun"],
                "submission_date": "2015-12-10",
                "year": 2015,
                "venue": "CVPR",
                "arxiv_id": "1512.03385",
            },
            {
                "s2_id": f"s2-{idx}-c",
                "title": "Quantum Field Theory in Curved Spacetime Review",
                "authors": ["R. M. Wald"],
                "submission_date": "1999-01-15",
                "year": 1999,
                "venue": None,
                "arxiv_id": "hep-th/9901001",
            },
            {
                "s2_id": f"s2-{idx}-dup",
                "title": "Duplicate of Attention",
                "authors": ["Ashish Vaswani"],
                "submission_date": "2017-06-12",
                "arxiv_id": "1706.03762",  # duplicate arXiv ID -> must be dropped
            },
            {
                "s2_id": None,
                "title": "A Non-ArXiv Textbook",
                "authors": ["Donald Knuth"],
                "submission_date": "1997",
                "arxiv_id": None,  # non-arXiv -> must be filtered out of references table
            },
        ]
        (folder / "references.json").write_text(
            json.dumps({"arxiv_id": pid, "status": "ok", "references": refs}), encoding="utf-8"
        )

        entries = [
            # Entry 1: explicit arXiv DOI match (even if title is abbreviated)
            {
                "arxiv_id": pid,
                "citation_key": "vaswani2017",
                "entry_type": "inproceedings",
                "title": "Transformer Architecture",
                "authors": ["Vaswani, Ashish"],
                "year": 2017,
                "doi": "10.48550/arXiv.1706.03762",
                "journal": None,
                "url": None,
            },
            # Entry 2: exact cleaned title match (with LaTeX braces & accent noise)
            {
                "arxiv_id": pid,
                "citation_key": "he2016",
                "entry_type": "inproceedings",
                "title": "{Deep} \\emph{Residual} Learning for Image Recognition",
                "authors": ["He, Kaiming", "Zhang, Xiangyu"],
                "year": 2016,
                "doi": None,
                "journal": "CVPR",
                "url": None,
            },
            # Entry 3: old-style arXiv ID in URL
            {
                "arxiv_id": pid,
                "citation_key": "wald1999",
                "entry_type": "article",
                "title": "Curved Spacetime QFT",
                "authors": ["Wald, R."],
                "year": 1999,
                "doi": None,
                "journal": None,
                "url": "https://arxiv.org/abs/hep-th/9901001v2",
            },
            # Entry 4: non-arXiv book (no match)
            {
                "arxiv_id": pid,
                "citation_key": "knuth1997",
                "entry_type": "book",
                "title": "The Art of Computer Programming",
                "authors": ["Knuth, Donald E."],
                "year": 1997,
                "doi": None,
                "journal": None,
                "url": None,
            },
        ]
        (shard0_rows if idx < 10 else shard1_rows).extend(entries)

    (m2 / "shard-00000").mkdir(parents=True)
    (m2 / "shard-00001").mkdir(parents=True)
    pq.write_table(m2_to_table("bibtex", shard0_rows), m2 / "shard-00000" / "bibtex.parquet")
    pq.write_table(m2_to_table("bibtex", shard1_rows), m2 / "shard-00001" / "bibtex.parquet")
    return corpus, m2


def test_restore_m1_json_and_metadata(tmp_path):
    m1, m2run = tmp_path / "m1", tmp_path / "m2run"
    remote = m1 / "runs" / "r1"
    meta_bytes = b'{"arxiv_id": "2606.30734"}'
    ref_bytes = b'{"references": []}'
    sha_m = hashlib.sha256(meta_bytes).hexdigest()
    sha_r = hashlib.sha256(ref_bytes).hexdigest()

    (remote / "data/corpus/2606-30734").mkdir(parents=True)
    (remote / "data/corpus/2606-30734/metadata.json").write_bytes(meta_bytes)
    (remote / "data/corpus/2606-30734/references.json").write_bytes(b"corrupted mirror")
    (remote / ".checkpoint-objects" / sha_r[:2]).mkdir(parents=True)
    (remote / ".checkpoint-objects" / sha_r[:2] / sha_r).write_bytes(ref_bytes)

    files = {
        "data/corpus/2606-30734/metadata.json": sha_m,
        "data/corpus/2606-30734/references.json": sha_r,
        "data/corpus/2606-30734/v1/main.tex": "0" * 64,
    }
    (remote / "INDEX.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    m2run.mkdir(parents=True)
    (m2run / "M2_MANIFEST.json").write_text(
        json.dumps({"runs": {"r1": "runs/r1"}}), encoding="utf-8"
    )

    dest = tmp_path / "local_corpus"
    res = restore_m1_json(m2run, m1, dest)
    assert res == {"copied": 2, "reused": 0, "total": 2}
    assert (dest / "2606-30734/metadata.json").read_bytes() == meta_bytes
    assert (dest / "2606-30734/references.json").read_bytes() == ref_bytes
    assert not (dest / "2606-30734/v1").exists()

    assert restore_metadata(m2run, m1, dest) == {"copied": 0, "reused": 1, "total": 1}


def test_cleaning_text_authors_and_arxiv_ids():
    assert cleaning.clean_text(r"M\"{o}bius \textbf{Transform} — $O(n)$") == "mobius transform o n"
    assert cleaning.title_tokens("A Survey of Deep Learning for Graphs") == [
        "survey",
        "deep",
        "learning",
        "graphs",
    ]
    assert cleaning.extract_author_surnames(["Vaswani, Ashish", "N. Shazeer", "et al."]) == {
        "vaswani",
        "shazeer",
    }
    assert cleaning.extract_arxiv_ids(
        "DOI: 10.48550/arXiv.2401.12345v3 and https://arxiv.org/abs/hep-th/9901001v1"
    ) == ["2401.12345", "hep-th/9901001"]
    # Must not falsely treat a non-arXiv year-like DOI token as an arXiv ID (month 20 is invalid).
    assert cleaning.extract_arxiv_ids("10.1145/2020.12345") == []
    assert cleaning.entry_mentions_arxiv_id(
        {"doi": "10.48550/arXiv.1706.03762", "url": None, "journal": None}, "1706.03762"
    )
    assert not cleaning.entry_mentions_arxiv_id(
        {"doi": "10.1109/TIFS.2023.3268881", "url": None, "journal": None}, "1706.03762"
    )


def test_export_m1_tables_combined_and_split_by_range(tmp_path):
    corpus, _ = _build_synthetic_corpus(tmp_path)
    out = tmp_path / "m1_out"
    summary = export_m1_tables.export_m1_tables(
        [corpus], out, shard_papers=8, assigned_only=True, use_data_prefix=True
    )
    assert summary["papers_written"] == 20
    assert summary["references_written"] == 60  # 3 unique arXiv-keyed refs per paper
    assert summary["shards"] == 3

    paper_shards = sorted((out / "data" / "papers").glob("*.parquet"))
    ref_shards = sorted((out / "data" / "references").glob("*.parquet"))
    assert len(paper_shards) == 3 and len(ref_shards) == 3
    assert pq.read_schema(paper_shards[0]).equals(export_m1_tables.SCHEMAS["papers"])
    assert pq.read_schema(ref_shards[0]).equals(export_m1_tables.SCHEMAS["references"])

    # Flat columns only (no struct or map).
    for shard in (paper_shards[0], ref_shards[0]):
        assert not [
            f.name for f in pq.read_schema(shard) if str(f.type).startswith(("struct", "map"))
        ]

    # Split by range produces one directory per member with data/{papers,references}/.
    split_out = tmp_path / "m1_split"
    split_summary = export_m1_tables.export_m1_tables(
        [corpus], split_out, shard_papers=10, split_by_range=True
    )
    assert split_summary["papers_written"] == 20
    for owner in ("thien", "tien", "hieu", "dang"):
        assert split_summary["ranges"][owner]["papers_written"] == 5
        assert (split_out / owner / "data" / "papers" / "part-00000.parquet").is_file()
        assert (split_out / owner / "data" / "references" / "part-00000.parquet").is_file()


def test_candidates_sharded_builder_from_parquet_and_json(tmp_path):
    corpus, m2 = _build_synthetic_corpus(tmp_path)
    m1_out = tmp_path / "m1_out"
    export_m1_tables.export_m1_tables([corpus], m1_out, shard_papers=10)

    cand_pq = tmp_path / "cand_pq"
    stats_pq = candidates.build_candidate_shards(
        m2, cand_pq, refs_dir=m1_out / "data" / "references"
    )
    cand_json = tmp_path / "cand_json"
    stats_json = candidates.build_candidate_shards(m2, cand_json, corpus_dir=corpus)

    assert stats_pq == stats_json
    assert stats_pq["shards_written"] == 2
    assert stats_pq["papers_with_candidates"] == 20
    assert stats_pq["entries_total"] == 80
    assert stats_pq["candidate_pairs_total"] == 80 * 3  # 4 entries x 3 cands x 20 papers
    assert pq.read_schema(cand_pq / "shard-00000.parquet").equals(
        candidates.CANDIDATE_MATRIX_SCHEMA
    )


def test_auto_label_rules_ambiguity_run_and_evaluate(tmp_path):
    corpus, m2 = _build_synthetic_corpus(tmp_path)
    m1_out = tmp_path / "m1_out"
    export_m1_tables.export_m1_tables([corpus], m1_out, shard_papers=10)
    refs_dir = m1_out / "data" / "references"

    # Unit checks on tricky cases (near-match + tie rejection).
    cands = [
        {
            "ref_arxiv_id": "2101.00001",
            "ref_title": "Scalable Graph Neural Networks for Molecular Modeling",
            "ref_authors": ["Jane Smith", "John Doe"],
            "ref_submission_date": "2021-01-10",
        },
        {
            "ref_arxiv_id": "2101.00002",
            "ref_title": "Scalable Graph Neural Networks for Molecular Modeling Part Two",
            "ref_authors": ["Jane Smith", "John Doe"],
            "ref_submission_date": "2021-02-10",
        },
    ]
    # Exact title match picks 2101.00001.
    rid, rule = auto_label.match_entry(
        {
            "title": "Scalable Graph Neural Networks for Molecular Modeling",
            "authors": ["Smith, Jane"],
            "year": 2021,
            "doi": None,
            "url": None,
            "journal": None,
        },
        cands,
    )
    assert rid == "2101.00001" and rule == "exact_title"

    # Unrelated entry gets no_match.
    rid_none, rule_none = auto_label.match_entry(
        {
            "title": "Introduction to Classical Mechanics",
            "authors": ["Goldstein, H."],
            "year": 2002,
            "doi": None,
            "url": None,
            "journal": None,
        },
        cands,
    )
    assert rid_none is None and rule_none == "no_match"

    # Mark 4 manual papers (1 per range) so auto-labeler excludes them.
    labels_dir = tmp_path / "labels"
    manual_pids = [P_THIEN[0], P_TIEN[0], P_HIEU[0], P_DANG[0]]
    cand_ids = ["1706.03762", "1512.03385", "hep-th/9901001"]
    ground_truth = {
        "vaswani2017": "1706.03762",
        "he2016": "1512.03385",
        "wald1999": "hep-th/9901001",
        "knuth1997": None,
    }
    for pid in manual_pids:
        write_matrix(label_path(labels_dir, "manual", pid), cand_ids, ground_truth)

    # Run auto-labeler with min_papers=8 (2 per range, >=10% of remaining 16 papers).
    summary = auto_label.run_auto_label(
        m2,
        labels_dir,
        refs_dir=refs_dir,
        total_corpus_papers=20,
        ratio=0.10,
        min_papers=8,
        seed=42,
    )
    assert summary["manual_excluded"] == 4
    assert summary["selected_papers"] == 8
    assert summary["per_range"] == {"dang": 2, "hieu": 2, "thien": 2, "tien": 2}
    assert summary["entries_labeled"] == 32
    assert summary["entries_matched"] == 24
    assert summary["rule_counts"]["explicit_id"] == 16
    assert summary["rule_counts"]["exact_title"] == 8
    assert summary["rule_counts"]["no_match"] == 8

    # Every auto CSV must pass Tiến's strict read_matrix validation and never overlap manual pool.
    auto_files = sorted((labels_dir / "auto").glob("*.csv"))
    assert len(auto_files) == 8
    for p in auto_files:
        got_cands, got_ans = read_matrix(p)
        assert got_cands == cand_ids
        assert got_ans == ground_truth
        assert p.stem.replace("-", ".") not in manual_pids

    # Evaluate auto-labeler against manual ground truth.
    eval_dir = tmp_path / "eval"
    report = auto_label.evaluate_on_manual(m2, labels_dir, refs_dir=refs_dir, out_dir=eval_dir)
    assert report["papers_evaluated"] == 4
    assert report["entries_evaluated"] == 16
    assert report["exact_accuracy"] == 1.0
    assert report["precision"] == 1.0
    assert report["recall"] == 1.0
    assert report["no_match_specificity"] == 1.0
    assert (eval_dir / "auto_eval_report.json").is_file()


def test_predictions_schema_validation_and_runner(tmp_path):
    corpus, m2 = _build_synthetic_corpus(tmp_path)
    m1_out = tmp_path / "m1_out"
    export_m1_tables.export_m1_tables([corpus], m1_out, shard_papers=10)
    refs_dir = m1_out / "data" / "references"

    labels_dir = tmp_path / "labels"
    cand_ids = ["1706.03762", "1512.03385", "hep-th/9901001"]
    gt = {
        "vaswani2017": "1706.03762",
        "he2016": "1512.03385",
        "wald1999": "hep-th/9901001",
        "knuth1997": None,
    }
    write_matrix(label_path(labels_dir, "manual", P_THIEN[0]), cand_ids, gt)
    write_matrix(label_path(labels_dir, "auto", P_THIEN[1]), cand_ids, gt)
    write_matrix(label_path(labels_dir, "manual", P_DANG[0]), cand_ids, gt)

    part_csv = tmp_path / "partitions.csv"
    with part_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["arxiv_id", "partition"])
        w.writeheader()
        w.writerow({"arxiv_id": P_THIEN[0], "partition": "test"})
        w.writerow({"arxiv_id": P_THIEN[1], "partition": "valid"})
        w.writerow({"arxiv_id": P_DANG[0], "partition": "train"})

    pred_out = tmp_path / "preds"
    summary = predictions.run_prediction_pipeline(
        m2,
        part_csv,
        pred_out,
        refs_dir=refs_dir,
        labels_dir=labels_dir,
        split_by_range=True,
    )
    assert summary["papers_requested"] == 3
    assert summary["papers_written"] == 3
    assert summary["rows_written"] == 12
    assert summary["metrics"]["by_partition"]["test"]["mrr5_matched_only"] == 1.0
    assert summary["metrics"]["by_partition_and_method"]["test_manual"]["mrr5_matched_only"] == 1.0

    # Verify Parquet schema matches M3 spec (dictionary partition, non-null keys, flat columns).
    thien_pq = pred_out / "thien" / "data" / "predictions" / "part-00000.parquet"
    table = pq.read_table(thien_pq)
    assert table.schema.equals(predictions.PREDICTIONS_SCHEMA)
    assert pa.types.is_dictionary(table.schema.field("partition").type)
    assert table.num_rows == 8  # 2 papers x 4 entries

    # Validation rejects non-split papers, null gaps, duplicate top-5, invalid candidate IDs.
    bad_gap = [
        {
            "arxiv_id": P_THIEN[0],
            "partition": "test",
            "citation_key": "k1",
            "groundtruth_arxiv_id": None,
            "cand_1": None,
            "cand_2": "1706.03762",
            "cand_3": None,
            "cand_4": None,
            "cand_5": None,
        }
    ]
    with pytest.raises(ValueError, match="after a null slot"):
        predictions.validate_prediction_rows(bad_gap)

    bad_dup = [
        {
            "arxiv_id": P_THIEN[0],
            "partition": "test",
            "citation_key": "k1",
            "groundtruth_arxiv_id": None,
            "cand_1": "1706.03762",
            "cand_2": "1706.03762",
            "cand_3": None,
            "cand_4": None,
            "cand_5": None,
        }
    ]
    with pytest.raises(ValueError, match="duplicate candidate"):
        predictions.validate_prediction_rows(bad_dup)

    bad_unlisted = [
        {
            "arxiv_id": P_TIEN[0],
            "partition": "train",
            "citation_key": "k1",
            "groundtruth_arxiv_id": None,
            "cand_1": None,
            "cand_2": None,
            "cand_3": None,
            "cand_4": None,
            "cand_5": None,
        }
    ]
    with pytest.raises(ValueError, match="not in Train/Valid/Test"):
        predictions.validate_prediction_rows(bad_unlisted, allowed_partitions={P_THIEN[0]: "test"})


def test_hf_dataset_data_prefix_and_strict_schema(tmp_path):
    pkg = tmp_path / "pkg_thien"
    data = pkg / "data"
    for t in hf_dataset.TABLES:
        (data / t).mkdir(parents=True)

    pq.write_table(
        export_m1_tables.to_table(
            "papers",
            [
                {
                    "arxiv_id": P_THIEN[0],
                    "title": "T",
                    "authors": ["A"],
                    "submission_date": "2026-06-01T00:00:00Z",
                    "revised_dates": [],
                    "venue": None,
                }
            ],
        ),
        data / "papers" / "part-00000.parquet",
    )
    pq.write_table(
        export_m1_tables.to_table(
            "references",
            [
                {
                    "arxiv_id": P_THIEN[0],
                    "ref_arxiv_id": "1706.03762",
                    "ref_title": "Attention",
                    "ref_authors": ["Vaswani"],
                    "ref_submission_date": "2017-06-12",
                    "ref_s2_id": "s1",
                }
            ],
        ),
        data / "references" / "part-00000.parquet",
    )
    pq.write_table(
        m2_to_table(
            "elements",
            [
                {
                    "element_id": "2606-30734#d0",
                    "arxiv_id": P_THIEN[0],
                    "kind": "document",
                    "content": "",
                }
            ],
        ),
        data / "elements" / "part-00000.parquet",
    )
    pq.write_table(
        m2_to_table(
            "hierarchy",
            [
                {
                    "arxiv_id": P_THIEN[0],
                    "version": 1,
                    "element_id": "2606-30734#s1",
                    "parent_id": "2606-30734#d0",
                }
            ],
        ),
        data / "hierarchy" / "part-00000.parquet",
    )
    pq.write_table(
        m2_to_table(
            "bibtex",
            [
                {
                    "arxiv_id": P_THIEN[0],
                    "citation_key": "k1",
                    "entry_type": "article",
                    "title": "Attention",
                    "authors": ["Vaswani"],
                    "year": 2017,
                    "doi": None,
                    "journal": None,
                    "url": None,
                }
            ],
        ),
        data / "bibtex" / "part-00000.parquet",
    )
    pq.write_table(
        predictions.to_predictions_table(
            [
                {
                    "arxiv_id": P_THIEN[0],
                    "partition": "test",
                    "citation_key": "k1",
                    "groundtruth_arxiv_id": "1706.03762",
                    "cand_1": "1706.03762",
                    "cand_2": None,
                    "cand_3": None,
                    "cand_4": None,
                    "cand_5": None,
                }
            ]
        ),
        data / "predictions" / "part-00000.parquet",
    )

    hf_dataset.main(
        [
            "--package-dir",
            str(pkg),
            "--repo-id",
            "user/arxiv-nhom1-thien",
            "--range",
            "thien",
            "--strict-schema",
            "--dry-run",
        ]
    )
    card_text = (pkg / "README.md").read_text(encoding="utf-8")
    assert "path: data/papers/*.parquet" in card_text
    assert "path: data/predictions/*.parquet" in card_text

    # Strict schema rejects plain-string partition column in predictions.
    bad_pred = pa.table(
        {
            "arxiv_id": [P_THIEN[0]],
            "partition": ["test"],
            "citation_key": ["k1"],
            "groundtruth_arxiv_id": ["1706.03762"],
            "cand_1": ["1706.03762"],
            "cand_2": [None],
            "cand_3": [None],
            "cand_4": [None],
            "cand_5": [None],
        }
    )
    pq.write_table(bad_pred, data / "predictions" / "part-00000.parquet")
    with pytest.raises(SystemExit, match="dictionary-encoded"):
        hf_dataset.check_package(pkg, strict_schema=True)


def test_crosscheck_review_rank_surfaces_id_and_author_matches():
    # Simulates a misaligned BibTeX entry whose title is garbage, but DOI or authors still match.
    distractors = [
        {
            "ref_arxiv_id": f"2201.{i:05d}",
            "ref_title": f"Proceedings Volume {i} Conference Notes",
            "ref_authors": [f"Other Author{i}"],
            "ref_submission_date": "2022-01-01",
        }
        for i in range(15)
    ]
    target_by_id = {
        "ref_arxiv_id": "1706.03762",
        "ref_title": "Attention Is All You Need",
        "ref_authors": ["Ashish Vaswani", "Noam Shazeer"],
        "ref_submission_date": "2017-06-12",
    }
    entry_id = {
        "title": "Proceedings Volume Conference",  # noisy/misaligned title
        "authors": [],
        "doi": "10.48550/arXiv.1706.03762",
        "url": None,
        "journal": None,
    }
    ranked_id = crosscheck._rank_for_review(entry_id, distractors + [target_by_id])
    assert ranked_id[0]["ref_arxiv_id"] == "1706.03762"

    entry_auth = {
        "title": "Proceedings Volume Conference",
        "authors": ["Vaswani, Ashish", "Shazeer, Noam"],
        "doi": None,
        "url": None,
        "journal": None,
    }
    ranked_auth = crosscheck._rank_for_review(entry_auth, distractors + [target_by_id])
    assert ranked_auth[0]["ref_arxiv_id"] == "1706.03762"
