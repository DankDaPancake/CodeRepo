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
