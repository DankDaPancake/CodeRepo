# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
from src.parser.hierarchy import build_tree, render
from src.parser.normalize import normalize

DOC = r"""
\documentclass{article}
\title{Ignored title}
\begin{document}
\maketitle
\begin{abstract}
We study things. It works.
\end{abstract}
\section{Introduction}\label{sec:intro}
Deep nets are used \cite{a}. See Fig.~\ref{fig:1} for an overview.

\begin{figure}[t]
\centering
\includegraphics{x.pdf}
\caption{An overview.}
\label{fig:1}
\end{figure}
\subsection{Setting}
Let $x$ be a point. We write
\begin{equation}
 x = 1. \label{eq:x}
\end{equation}
\begin{itemize}
  \item First, a point. It has two sentences.
  \item Second
  \begin{enumerate}
    \item nested one.
  \end{enumerate}
\end{itemize}
\paragraph{Details.} More text here.
\section*{Acknowledgements}
We thank everyone.
\appendix
\section{Proofs}
Proof text.
\begin{table}
\begin{tabular}{ll} a & b \\ \end{tabular}
\caption{A table.}
\end{table}
\section{References}
\bibliography{refs}
\begin{thebibliography}{9}
\bibitem{a} A. Author. Title. 2020.
\end{thebibliography}
\end{document}
"""


def kinds(tree):
    return [(n.kind, n.content) for n in tree.walk()]


def test_structure_of_a_document():
    tree = build_tree(normalize(DOC))
    text = render(tree)
    top = [(c.kind, c.content) for c in tree.children]
    assert top == [
        ("section", "Abstract"),
        ("section", "Introduction"),
        ("section", "Acknowledgements"),
        ("section", "Proofs"),
    ], text
    intro = tree.children[1]
    assert [c.kind for c in intro.children] == ["sentence", "sentence", "figure", "subsection"]
    setting = intro.children[3]
    assert setting.content == "Setting"
    assert [c.kind for c in setting.children] == [
        "sentence",
        "sentence",
        "equation",
        "itemize",
        "paragraph",
    ]
    assert setting.children[-1].content == "Details"
    assert setting.children[-1].children[0].content == "More text here."


def test_leaves_are_sentences_equations_and_figures_and_tables_are_figures():
    tree = build_tree(normalize(DOC))
    by_kind = {}
    for n in tree.walk():
        by_kind.setdefault(n.kind, []).append(n.content)
    assert "\\begin{equation}\nx = 1.\n\\end{equation}" in by_kind["equation"]
    assert len(by_kind["figure"]) == 2  # the figure and the table
    assert all("\\caption" in f for f in by_kind["figure"])
    assert not any("\\centering" in f or "[t]" in f or "\\label" in f for f in by_kind["figure"])


def test_itemize_is_a_branch_and_each_item_one_level_deeper():
    tree = build_tree(normalize(DOC))
    lst = next(n for n in tree.walk() if n.kind == "itemize")
    assert [c.kind for c in lst.children] == ["item", "item"]
    first, second = lst.children
    assert [c.content for c in first.children] == ["First, a point.", "It has two sentences."]
    assert [c.kind for c in second.children] == ["sentence", "itemize"]
    assert second.children[1].children[0].children[0].content == "nested one."


def test_references_are_left_out_acknowledgements_and_appendix_kept():
    tree = build_tree(normalize(DOC))
    text = render(tree)
    assert "Author" not in text and "bibitem" not in text and "refs" not in text
    assert "Acknowledgements" in text and "Proofs" in text and "Proof text." in text


def test_levels_are_inferred_from_the_headings_not_fixed():
    flat = (
        r"\begin{document}\subsection{Orphan} a b.\section{S}\subsection{T}"
        r"\subsubsection{U} u.\end{document}"
    )
    tree = build_tree(flat)
    assert [(c.kind, c.content) for c in tree.children] == [
        ("subsection", "Orphan"),
        ("section", "S"),
    ]
    assert tree.children[1].children[0].children[0].kind == "subsubsection"
    book = r"\begin{document}\chapter{C}\section{S}x.\chapter{D}y.\end{document}"
    tree = build_tree(book)
    assert [c.kind for c in tree.children] == ["chapter", "chapter"]
    assert tree.children[0].children[0].kind == "section"


def test_unnumbered_starred_sections_are_included():
    tree = build_tree(r"\begin{document}\section*{Appendix}Text here.\end{document}")
    assert (
        tree.children[0].content == "Appendix"
        and tree.children[0].children[0].content == "Text here."
    )


def test_dollar_dollar_and_bracket_math_become_equation_leaves_even_unnormalised():
    tree = build_tree(r"\begin{document}Before $$a=b$$ after \[c=d\] end.\end{document}")
    assert [n.kind for n in tree.children] == [
        "sentence",
        "equation",
        "sentence",
        "equation",
        "sentence",
    ]


def test_theorem_like_environments_are_flattened_into_the_text():
    tree = build_tree(
        r"\begin{document}\section{S}\begin{theorem}[Name] Claim one. \end{theorem}"
        r"\begin{proof} Proof one. \end{proof}\end{document}"
    )
    assert [c.content for c in tree.children[0].children] == ["Claim one.", "Proof one."]


def test_footnotes_come_after_their_paragraph_as_sentences():
    tree = build_tree(r"\begin{document}A claim\footnote{A note.} here. Next one.\end{document}")
    assert [c.content for c in tree.children] == ["A claim here.", "Next one.", "A note."]


def test_review_macros_and_front_matter_are_dropped_but_math_is_kept():
    tree = build_tree(
        r"\begin{document}\author{X}\AD{todo: fix. later} We have $\vec{v}$ and \ref{a}."
        r"\end{document}"
    )
    (sentence,) = tree.children
    assert sentence.content == r"We have $\vec{v}$ and \ref{a}."


def test_verbatim_and_definitions_do_not_leak():
    tree = build_tree(
        r"\begin{document}\newcommand{\x}{y. z.}\begin{verbatim}code. here.\end{verbatim}"
        r"Real.\end{document}"
    )
    assert [c.content for c in tree.children] == ["Real."]


def test_empty_or_odd_input_gives_an_empty_document():
    assert build_tree("").children == []
    assert build_tree(r"\begin{document}\end{document}").children == []
    assert build_tree(r"\begin{document}\section{Unclosed \begin{figure} oops").kind == "document"
