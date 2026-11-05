# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
import csv

import pandas as pd

from src.parser.run import Journal
from src.qa.audit_sample import CRITERIA, SHEET_COLUMNS, draw, eligible_papers, main, score


def version(number, status="parsed", root="main.tex"):
    return {"version": number, "status": status, "root": root if status == "parsed" else None}


def write_output(tmp_path, ids):
    """One shard with two versions per paper that share their first sentence."""
    out, work = tmp_path / "out", tmp_path / "work"
    shard = out / "shard-00000"
    shard.mkdir(parents=True)
    work.mkdir()
    elements, hierarchy, bibtex, records = [], [], [], []
    for arxiv_id in ids:
        key = arxiv_id.replace(".", "-")
        for eid, kind, content in [
            (f"{key}#root1", "document", ""),
            (f"{key}#root2", "document", ""),
            (f"{key}#h1", "heading", "Introduction"),
            (f"{key}#s1", "sentence", "Shared sentence."),
            (f"{key}#s2", "sentence", "Only in v2."),
        ]:
            elements.append(
                {"element_id": eid, "arxiv_id": arxiv_id, "kind": kind, "content": content}
            )
        edges = [(1, "root1", key), (1, "h1", "root1"), (1, "s1", "h1"), (2, "root2", key)]
        edges += [(2, "h1", "root2"), (2, "s1", "h1"), (2, "s2", "h1")]
        for v, child, parent in edges:
            hierarchy.append(
                {
                    "arxiv_id": arxiv_id,
                    "version": v,
                    "element_id": f"{key}#{child}",
                    "parent_id": parent if parent == key else f"{key}#{parent}",
                }
            )
        bibtex.append(
            {"arxiv_id": arxiv_id, "citation_key": "k1", "title": "A title", "year": 2001,
             "authors": ["A. One"]}
        )  # fmt: skip
        records.append(
            {
                "arxiv_id": arxiv_id,
                "folder": key,
                "fingerprint": "x",
                "error": None,
                "elapsed_s": 0.1,
                "rows": {},
                "versions": [version(1), version(2)],
            }
        )
    for name, rows in (("elements", elements), ("hierarchy", hierarchy), ("bibtex", bibtex)):
        pd.DataFrame(rows).to_parquet(shard / f"{name}.parquet")
    Journal(work / "shards.jsonl").append({"shard": 0, "committed_at": "now", "papers": records})
    return out, work


def test_failed_papers_are_not_drawn(tmp_path):
    out, work = write_output(tmp_path, ["2606.00001", "2606.00002"])
    papers, _ = Journal(work / "shards.jsonl").load()
    papers["2606.00002"]["error"] = "boom"
    Journal(work / "shards.jsonl").path.unlink()
    Journal(work / "shards.jsonl").append(
        {"shard": 0, "papers": [{**p, "error": p["error"]} for p in papers.values()]}
    )
    assert sorted(eligible_papers(work)) == ["2606.00001"]


def test_draw_writes_trees_with_shared_elements_and_an_empty_sheet(tmp_path):
    ids = [f"2606.0000{n}" for n in range(1, 6)]
    out, work = write_output(tmp_path, ids)
    sheet = draw(out, work, tmp_path / "audit", n=3, seed=1, data_root=None)
    again = draw(out, work, tmp_path / "audit2", n=3, seed=1, data_root=None)
    assert [r["arxiv_id"] for r in sheet] == [r["arxiv_id"] for r in again]  # reproducible
    assert len(sheet) == 3
    page = (tmp_path / "audit" / f"{sheet[0]['arxiv_id'].replace('.', '-')}.md").read_text(
        encoding="utf-8"
    )
    assert "[heading] Introduction" in page and "[sentence] Shared sentence.  (v1, v2)" in page
    assert "[sentence] Only in v2." in page and "`k1` (2001) A. One: A title" in page
    with open(tmp_path / "audit" / "audit_sheet.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == SHEET_COLUMNS and rows[0]["version"] == "2"
    assert all(rows[0][c] == "" for c in CRITERIA)


def fill(path, marks):
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row, mark in zip(rows, marks, strict=False):
        row.update(mark)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_score_rates_per_criterion_and_overall(tmp_path, capsys):
    out, work = write_output(tmp_path, [f"2606.0000{n}" for n in range(1, 5)])
    draw(out, work, tmp_path / "audit", n=4, seed=1, data_root=None)
    sheet = tmp_path / "audit" / "audit_sheet.csv"
    ok = dict.fromkeys(CRITERIA, "y")
    fill(
        sheet,
        [
            ok,
            {**ok, "sentences_ok": "n", "notes": "split inside $a.b$"},
            {**ok, "dedup_ok": "na"},
            {**ok, "math_ok": "", "bibtex_ok": "n", "notes": "missing entries"},
        ],
    )
    summary, wrong = score(sheet)
    rates = {r["criterion"]: (r["correct"], r["checked"]) for r in summary}
    assert rates["sentences_ok"] == (3, 4) and rates["math_ok"] == (3, 3)
    assert rates["dedup_ok"] == (3, 3)  # "na" is not counted
    assert rates["all"] == (2, 4)
    assert [(w["arxiv_id"], w["criteria"]) for w in wrong] == [
        (wrong[0]["arxiv_id"], ["sentences_ok"]),
        (wrong[1]["arxiv_id"], ["bibtex_ok"]),
    ]
    assert main(["score", str(sheet), "--out", str(tmp_path / "summary.csv")]) == 0
    assert "all" in capsys.readouterr().out and (tmp_path / "summary.csv").exists()
