# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""The M1 statistics are computed over the runs of a distributed crawl as one corpus."""

import json

from src.analysis.stats import main, paper_row


def make_paper(root, arxiv_id, n_refs):
    folder = root / arxiv_id.replace(".", "-")
    (folder / "v1").mkdir(parents=True)
    (folder / "v1" / "main.tex").write_text("\\documentclass{article}", encoding="utf-8")
    meta = {"arxiv_id": arxiv_id, "num_versions": 1, "authors": ["A"], "submission_date": "x"}
    (folder / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    refs = [{"s2_id": "s1", "title": "t", "authors": ["a"], "submission_date": "d"}]
    (folder / "references.json").write_text(
        json.dumps({"status": "ok", "references": refs * n_refs}), encoding="utf-8"
    )


def journal(work, arxiv_id):
    work.mkdir(parents=True)
    record = {
        "arxiv_id": arxiv_id,
        "version": 1,
        "status": "ok",
        "kind": "tar.gz",
        "bytes_before": 100,
        "bytes_after": 10,
        "total_s": 2.0,
        "files": ["main.tex"],
    }
    (work / "versions.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    discovery = {"arxiv_id": arxiv_id, "found": True, "source": "api"}
    (work / "discovery.jsonl").write_text(json.dumps(discovery) + "\n", encoding="utf-8")


def test_paper_row_finds_the_paper_in_whichever_root_holds_it(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    make_paper(b, "2606.00001", 3)
    state = {("2606.00001", 1): {"status": "ok", "bytes_before": 100, "bytes_after": 10}}
    row = paper_row("2606.00001", [a, b], state)
    assert row["n_versions_ok"] == 1 and row["n_refs_total"] == 3 and row["has_source"] == 1
    assert paper_row("2606.00001", b, state) == row  # one root, as before
    assert paper_row("2606.00009", [a, b], state)["n_versions"] == 0  # not found: a failed paper


def test_main_exports_one_table_for_all_the_runs(tmp_path):
    roots, works = [], []
    for name, arxiv_id, n_refs in (("a", "2606.00001", 2), ("b", "2606.00002", 5)):
        root = tmp_path / name / "data" / "corpus"
        root.mkdir(parents=True)
        make_paper(root, arxiv_id, n_refs)
        journal(tmp_path / name / "work", arxiv_id)
        roots.append(root)
        works.append(tmp_path / name / "work")
    out = tmp_path / "out"
    args = ["--out", str(out)]
    for root, work in zip(roots, works, strict=True):
        args += ["--data-root", str(root), "--work-dir", str(work)]
    assert main(args) == 0
    lines = (out / "papers_stats.csv").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # header + the paper of each run
    text = "\n".join(lines)
    assert "2606.00001" in text and "2606.00002" in text
