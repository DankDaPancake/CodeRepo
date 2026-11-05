# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""The real M2 stages end to end: runner -> Parquet shards -> integrity checks."""

import pyarrow.parquet as pq
import pytest

from src.parser.model import TABLES
from src.parser.run import Options, run
from src.parser.writer import SCHEMAS, to_table, write_tables
from src.qa.check_tables import check, read_table
from src.tests.test_parser_run import DOC, make_paper

V1 = r"""\section{Intro}
Deep nets work \cite{vaswani2017}. They are big. See Fig.~\ref{f}.
\begin{figure}[t]\centering\includegraphics{a.pdf}\caption{A figure.}\end{figure}
\begin{equation} a = b \end{equation}
\begin{itemize}\item One. \item Two.\end{itemize}
\section{Related}
Old text.
\begin{thebibliography}{9}
\bibitem{vaswani2017} A. Vaswani, N. Shazeer. Attention is all you need. NeurIPS, 2017.
\end{thebibliography}"""
V2 = r"""\section{Intro}
Deep nets work \cite{vit}. They are big. See Fig.~\ref{f}.
\section{Related}
New text.
\begin{thebibliography}{9}
\bibitem{vit} A. Vaswani, N. Shazeer. Attention is all you need. NeurIPS, 2017.
\end{thebibliography}"""


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    make_paper(root, "2606.00001", [{"main.tex": DOC % V1}, {"main.tex": DOC % V2}])
    make_paper(root, "2606.00002", [{}, {"main.tex": DOC % "Only version two."}])
    make_paper(root, "2606.00003", [{"notes.tex": "no document class"}])
    return root


def test_real_stages_write_valid_parquet_that_passes_every_check(corpus, tmp_path):
    out, work = tmp_path / "out", tmp_path / "work"
    summary = run(corpus, out, work, options=Options(), progress=False)
    assert summary["papers_failed_this_run"] == 0
    for name in TABLES:
        assert list(out.glob(f"shard-*/{name}.parquet"))
    report = check(out)
    assert report["ok"], report["problems"]
    assert report["papers"] == 3 and report["versions"] == 5  # empty and no_root versions count


def test_versions_share_elements_and_the_citation_key_is_unified(corpus, tmp_path):
    out = tmp_path / "out"
    run(corpus, out, tmp_path / "work", options=Options(), progress=False)
    elements, hierarchy = read_table(out, "elements"), read_table(out, "hierarchy")
    bibtex = read_table(out, "bibtex")
    paper = [e for e in elements if e["arxiv_id"] == "2606.00001"]
    sentences = [e for e in paper if e["kind"] == "sentence"]
    assert len({e["content"] for e in sentences}) == len(sentences)  # no sentence stored twice
    assert [b["citation_key"] for b in bibtex if b["arxiv_id"] == "2606.00001"] == ["vaswani2017"]
    assert any("\\cite{vaswani2017}" in e["content"] for e in sentences)
    assert not any("\\cite{vit}" in e["content"] for e in sentences)
    shared = [e["element_id"] for e in sentences if e["content"] == "They are big."]
    versions = {h["version"] for h in hierarchy if h["element_id"] in shared}
    assert versions == {1, 2}
    # the version without TeX is a root and nothing else
    v1_of_2 = [h for h in hierarchy if h["arxiv_id"] == "2606.00002" and h["version"] == 1]
    assert len(v1_of_2) == 1 and v1_of_2[0]["parent_id"] == "2606-00002"


def test_kinds_and_references_section_left_out(corpus, tmp_path):
    out = tmp_path / "out"
    run(corpus, out, tmp_path / "work", options=Options(), progress=False)
    kinds = {e["kind"] for e in read_table(out, "elements")}
    assert {"document", "section", "sentence", "equation", "figure", "itemize", "item"} <= kinds
    assert not any("bibitem" in e["content"] for e in read_table(out, "elements"))


def test_resume_gives_the_same_tables(corpus, tmp_path):
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    run(corpus, out_a, tmp_path / "wa", options=Options(), progress=False)
    run(corpus, out_b, tmp_path / "wb", options=Options(), progress=False, limit=1)
    run(corpus, out_b, tmp_path / "wb", options=Options(), progress=False)
    for name in TABLES:
        a = sorted(map(str, read_table(out_a, name)))
        b = sorted(map(str, read_table(out_b, name)))
        assert a == b


def test_parquet_columns_have_the_statement_types(tmp_path):
    write_tables({"elements": [], "hierarchy": [], "bibtex": []}, tmp_path)
    types = {n: pq.read_schema(tmp_path / f"{n}.parquet") for n in TABLES}
    assert str(types["elements"].field("kind").type).startswith("dictionary")
    assert str(types["bibtex"].field("entry_type").type).startswith("dictionary")
    assert str(types["bibtex"].field("authors").type) == "list<element: string>"
    assert str(types["bibtex"].field("year").type) == "int32"
    assert str(types["hierarchy"].field("version").type) == "int32"
    assert not types["elements"].field("element_id").nullable
    assert not types["hierarchy"].field("parent_id").nullable
    assert not types["bibtex"].field("citation_key").nullable
    assert all(pq.read_table(tmp_path / f"{n}.parquet").num_rows == 0 for n in TABLES)


def test_to_table_keeps_nulls_and_lists():
    row = {
        "arxiv_id": "x",
        "citation_key": "k",
        "entry_type": "misc",
        "authors": ["A B"],
        "year": None,
        "title": None,
    }
    table = to_table("bibtex", [row])
    assert table.to_pylist()[0]["authors"] == ["A B"] and table.to_pylist()[0]["year"] is None
    assert set(SCHEMAS) == set(TABLES)


def test_check_tables_detects_a_broken_hierarchy(corpus, tmp_path):
    out = tmp_path / "out"
    run(corpus, out, tmp_path / "work", options=Options(), progress=False)
    shard = next(out.glob("shard-*"))
    table = pq.read_table(shard / "hierarchy.parquet").to_pylist()
    table[3]["parent_id"] = "2606-00001#s9999"  # a parent that does not exist
    pq.write_table(to_table("hierarchy", table), shard / "hierarchy.parquet")
    report = check(out)
    assert not report["ok"] and any("is not in elements" in p for p in report["problems"])


def test_papers_csv_counts_elements_before_and_after_deduplication(corpus, tmp_path):
    import csv

    work = tmp_path / "work"
    run(corpus, tmp_path / "out", work, options=Options(), progress=False)
    with open(work / "m2_papers.csv", encoding="utf-8", newline="") as fh:
        rows = {r["arxiv_id"]: r for r in csv.DictReader(fh)}
    first = rows["2606.00001"]
    # v1 and v2 share most sentences: fewer elements stored than nodes found
    assert int(first["elements_before"]) > int(first["elements"]) - 2  # minus the two roots
    assert int(first["bibtex_before"]) == 2 and int(first["bibtex"]) == 1  # one reference, 2 keys
    assert rows["2606.00002"]["elements_before"] == "1"  # the empty v1 has no nodes
