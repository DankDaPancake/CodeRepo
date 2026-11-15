# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
from src.parser.run import Options, run
from src.qa.audit_structure import audit, count_source, main
from src.tests.test_m2_pipeline import V1, V2, corpus  # noqa: F401  (fixture)
from src.tests.test_parser_run import DOC, make_paper


def test_count_source_ignores_comments_definitions_references_and_nested_floats():
    text = r"""\begin{document}
\newcommand{\x}{\begin{itemize}\item hidden\end{itemize}}
\begin{abstract}A.\end{abstract}
\section{Intro} % \section{Commented}
\subsection{Setting with $x_{i}$ and \textbf{bold}}
\begin{equation} a \end{equation} $$ b $$ \[ c \] and a line break \\[2pt] here
\begin{table}\begin{tabular}{l} a \end{tabular}\end{table}
\begin{figure}x\end{figure}
\begin{itemize}\item one \item two\end{itemize}
\section{References}
\subsection{Hidden}
\end{document}"""
    assert count_source(text) == {"headings": 3, "formulas": 3, "floats": 2, "items": 2}


def test_the_pipeline_output_agrees_with_its_source(corpus, tmp_path):  # noqa: F811
    out = tmp_path / "out"
    run(corpus, out, tmp_path / "work", options=Options(), progress=False)
    rows = audit(corpus, out)
    assert len(rows) == 3 or len(rows) == 2  # versions with a root; empty ones are skipped
    parsed = [r for r in rows if r["arxiv_id"] == "2606.00001"]
    assert len(parsed) == 2
    for row in parsed:
        assert row["headings_agree"] == row["floats_agree"] == row["items_agree"] == 1, row


def test_main_writes_the_csv_and_prints_rates(corpus, tmp_path, capsys):  # noqa: F811
    out = tmp_path / "out"
    run(corpus, out, tmp_path / "work", options=Options(), progress=False)
    code = main(
        ["--data-root", str(corpus), "--out-dir", str(out), "--report", str(tmp_path / "r")]
    )
    assert code == 0 and (tmp_path / "r" / "structure_audit.csv").exists()
    assert "headings" in capsys.readouterr().out
    assert V1 and V2 and DOC and make_paper  # fixtures shared with test_m2_pipeline


def test_audit_streams_completed_shards(corpus, tmp_path, monkeypatch):  # noqa: F811
    import src.qa.audit_structure as module

    out = tmp_path / "out"
    run(corpus, out, tmp_path / "work", options=Options(), progress=False, shard_papers=1)
    original = module.TexVersion.gather
    checked = []

    def observe(self):
        checked.append(self.dir)
        return original(self)

    monkeypatch.setattr(module.TexVersion, "gather", observe)
    rows = module.iter_audit(corpus, out)
    first = next(rows)
    assert first["arxiv_id"] == "2606.00001"
    assert len(checked) < 3
    assert len(list(rows)) >= 1


def test_structural_audit_resumes_without_repeating_finished_shard(corpus, tmp_path, monkeypatch):  # noqa: F811
    import pytest

    import src.qa.audit_structure as module

    out = tmp_path / "out"
    run(corpus, out, tmp_path / "work", options=Options(), progress=False, shard_papers=1)
    qa = tmp_path / "qa"

    def interrupt(done, total):
        if done == 1:
            raise RuntimeError("interrupt")

    with pytest.raises(RuntimeError, match="interrupt"):
        module.audit_resumable(corpus, out, qa, {"sha": "one"}, on_progress=interrupt)
    original = module._audit_shard
    called = []

    def observed(roots, shard, expected_status=None, present=None):
        called.append(shard.name)
        yield from original(roots, shard, expected_status, present)

    monkeypatch.setattr(module, "_audit_shard", observed)
    summary = module.audit_resumable(corpus, out, qa, {"sha": "one"})
    assert "shard-00000" not in called
    assert summary["versions"] == len(audit(corpus, out))
    assert (qa / "structure_audit.csv").exists()
    assert (qa / "structure_summary.json").exists()
    assert (
        summary["agreement_rates"]["headings"]
        == summary["agreement"]["headings"] / summary["versions"]
    )
    with pytest.raises(ValueError, match="identity"):
        module.audit_resumable(corpus, out, qa, {"sha": "two"})


def test_structural_audit_refuses_oversized_shard(corpus, tmp_path):  # noqa: F811
    import pytest

    from src.qa.audit_structure import audit_resumable

    out = tmp_path / "out"
    run(corpus, out, tmp_path / "work", options=Options(), progress=False)
    with pytest.raises(ValueError, match="row limit"):
        audit_resumable(corpus, out, tmp_path / "qa", {"sha": "one"}, max_shard_rows=1)
    assert not (tmp_path / "qa/structure_audit.csv").exists()


def test_structural_audit_does_not_silently_skip_missing_source(corpus, tmp_path):  # noqa: F811
    import shutil

    import pytest

    from src.qa.audit_structure import audit_resumable

    out = tmp_path / "out"
    run(corpus, out, tmp_path / "work", options=Options(), progress=False)
    shutil.rmtree(corpus / "2606-00001/v1")
    with pytest.raises(FileNotFoundError, match="2606.00001v1"):
        audit_resumable(corpus, out, tmp_path / "qa", {"sha": "one"})
    assert not (tmp_path / "qa/structure_audit.csv").exists()


def test_structural_audit_rejects_parsed_version_without_source_root(corpus, tmp_path):  # noqa: F811
    import pytest

    from src.qa.audit_structure import audit_resumable

    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False)
    (corpus / "2606-00001/v1/main.tex").write_text("no root", encoding="utf8")
    with pytest.raises(ValueError, match="Expected parsed source root"):
        audit_resumable(corpus, out, tmp_path / "qa", {"sha": "one"}, journal=work / "shards.jsonl")


def test_structural_audit_rejects_missing_parsed_version_in_hierarchy(corpus, tmp_path):  # noqa: F811
    import pyarrow.parquet as pq
    import pytest

    from src.parser.writer import to_table
    from src.qa.audit_structure import audit_resumable

    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False)
    path = out / "shard-00000/hierarchy.parquet"
    rows = pq.read_table(path).to_pylist()
    rows = [r for r in rows if not (r["arxiv_id"] == "2606.00001" and r["version"] == 1)]
    pq.write_table(to_table("hierarchy", rows), path)
    with pytest.raises(ValueError, match="Parsed versions missing"):
        audit_resumable(corpus, out, tmp_path / "qa", {"sha": "one"}, journal=work / "shards.jsonl")
    assert not (tmp_path / "qa/structure_audit.csv").exists()


def test_structural_audit_rejects_changed_shard(corpus, tmp_path):  # noqa: F811
    import pyarrow.parquet as pq
    import pytest

    from src.benchmark.m2_sync import _tree_hashes
    from src.qa.audit_structure import audit_resumable

    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False)
    hashes = {p.name: _tree_hashes(p) for p in out.glob("shard-*")}
    path = out / "shard-00000/bibtex.parquet"
    pq.write_table(pq.read_table(path), path, compression="NONE")
    with pytest.raises(ValueError, match="hash mismatch"):
        audit_resumable(corpus, out, tmp_path / "qa", {"sha": "one"}, expected_hashes=hashes)


def test_structure_excludes_error_status_even_when_source_has_root(corpus, tmp_path):  # noqa: F811
    import json

    from src.qa.audit_structure import audit_resumable

    out, work = tmp_path / "out", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False)
    journal = work / "shards.jsonl"
    records = [json.loads(line) for line in journal.read_text(encoding="utf8").splitlines()]
    for shard in records:
        for paper in shard["papers"]:
            if paper["arxiv_id"] == "2606.00001":
                paper["versions"][0]["status"] = "error"
    journal.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf8")
    summary = audit_resumable(corpus, out, tmp_path / "qa", {"sha": "one"}, journal=journal)
    assert summary["versions"] == 2
