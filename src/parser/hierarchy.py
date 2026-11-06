# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
r"""The hierarchy of one version (M2 statement: "Hierarchy structure").

``build_tree(text)`` reads the normalised root file (``normalize``) and returns a ``Node`` tree:

- the **document** is the root; ``\chapter``/``\section`` form the level below, then
  ``\subsection``, ``\subsubsection`` and ``\paragraph``. The level of a heading is *inferred*:
  a heading is the child of the nearest earlier heading of a lower rank, so a document without
  ``\chapter`` has its sections right under the root and a ``\subsection`` before any
  ``\section`` hangs from the root;
- the **leaves** are sentences (``sentences.split_sentences``), block formulas
  (``\begin{equation}``) and figures; a table is a figure; the float is one leaf holding its
  cleaned LaTeX (caption and ``\includegraphics`` included);
- an ``itemize`` (also ``enumerate`` and ``description``) is a branch and each ``\item`` a
  branch one level deeper holding the sentences, formulas and lists of that item;
- the abstract becomes a section "Abstract" and an acknowledgements environment a section
  "Acknowledgements"; ``\section*`` and everything after ``\appendix`` are included;
- the **References** (a section of that name, ``thebibliography``, ``\bibliography``) are left out.

Whatever is not prose and not part of the structure (title block, ``\newcommand``, labels,
verbatim code) is dropped. Footnotes become sentences after the paragraph that has them.
"""

from __future__ import annotations

import re

from src.parser.model import Node
from src.parser.normalize import (
    _end_of_env,
    block_equation,
    drop_command,
    inline_equation,
    match_brace,
    normalize_math,
    strip_formatting,
)
from src.parser.sentences import split_sentences

# command -> (kind of the node, rank). Lower rank = closer to the root.
HEADINGS = {
    "chapter": ("chapter", 1),
    "section": ("section", 2),
    "subsection": ("subsection", 3),
    "subsubsection": ("subsubsection", 4),
    "paragraph": ("paragraph", 5),
    "subparagraph": ("paragraph", 6),
}
REFERENCE_TITLES = frozenset(
    {
        "references",
        "reference",
        "bibliography",
        "literature cited",
        "works cited",
        "references cited",
    }
)
FIGURE_ENVS = frozenset(
    """figure figure* table table* wrapfigure wraptable sidewaysfigure sidewaystable algorithm
    algorithm* tabular tabular* tabularx longtable tikzpicture picture""".split()
)
EQUATION_ENVS = frozenset(
    """equation equation* displaymath align align* alignat alignat* flalign flalign* eqnarray
    eqnarray* multline multline* gather gather* split""".split()
)
LIST_ENVS = frozenset(
    """itemize enumerate description compactitem compactenum compactdesc inparaenum
    asparaenum""".split()
)
SKIPPED_ENVS = frozenset(
    """thebibliography verbatim verbatim* lstlisting minted comment filecontents filecontents*
    CCSXML""".split()
)
ABSTRACT_ENVS = frozenset({"abstract"})
ACK_ENVS = frozenset({"acknowledgments", "acknowledgements", "acknowledgment", "ack"})
ARG_ENVS = frozenset({"minipage", "multicols", "tabularx", "adjustbox", "spacing"})

# commands that never carry prose of the paper: front matter, definitions, bibliography calls
_FRONT_MATTER = (
    r"title|author|affiliation|address|email|thanks|date|institute|authorrunning|titlerunning|"
    r"keywords|icmltitle|icmlauthor|icmlaffiliation|icmlcorrespondingauthor|icmlkeywords|"
    r"orcid|ead|fnref|corref|printAffiliationsAndNotice|ccsdesc|acmYear|copyrightyear|"
    r"preprint|authornote|affil|subjclass|footnotetext|altaffiliation|pacs|shorttitle|"
    r"shortauthors|copyrightclause|conference|journalyear|markright|"
    r"setcopyright|acmDOI|acmISBN|acmConference|acmBooktitle|acmPrice|acmSubmissionID|"
    r"settopmatter|institution|city|country|postcode|streetaddress|receipt|received"
)
_DEFINITIONS = r"newcommand|renewcommand|providecommand|DeclareMathOperator|newtheorem|def|let"
_NO_PROSE = r"bibliography|printbibliography|nocite|input|include|usepackage|graphicspath"

_TOKEN = re.compile(
    r"\\(?P<head>chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?(?![A-Za-z])"
    r"|\\begin\s*\{(?P<env>[A-Za-z@]+\*?)\}"
    r"|\\end\s*\{[A-Za-z@]+\*?\}"
    r"|\\\["
    r"|\$\$"
)
_LIST_TOKEN = re.compile(
    r"\\(?P<kind>begin|end)\s*\{(?P<env>" + "|".join(sorted(LIST_ENVS)) + r")\}"
    r"|\\item(?![A-Za-z])"
)
_FOOTNOTE = re.compile(r"\\footnote\s*(?:\[[^\]]*\])?\s*\{")
_HAS_CONTENT = re.compile(r"[A-Za-z0-9\u00c0-\uffff$]")
_BLANK_PARA = re.compile(r"\n[ \t]*\n")

Piece = tuple  # ("text", s) | ("head", kind, rank, title) | ("leaf", kind, content) | ...


# --------------------------------------------------------------------------- cleaning


_MATH_SPAN = re.compile(r"(?<!\\)\$.*?(?<!\\)\$", re.S)
_SHORT_MACRO = re.compile(r"\\([A-Za-z]{2,3})(?![A-Za-z])(?=\s*\{)")
# two- and three-letter commands that really carry text of the paper
_KEEP_SHORT = frozenset(
    {"ref", "url", "doi", "tag", "tt", "em", "bf", "it", "sc", "sf", "rm", "sl"}
)


def _drop_review_macros(text: str) -> str:
    r"""Remove co-author comment macros such as ``\AD{move this up}`` (outside of math).

    Papers define short macros (``\jn``, ``\CQ``) to leave notes to each other; their argument is
    not part of the paper. Any 2-3 letter command with a brace argument is treated this way,
    except the few that carry text (``\ref``, ``\url``...).
    """
    out, pos = [], 0
    for span in [*_MATH_SPAN.finditer(text), None]:
        end = span.start() if span is not None else len(text)
        segment = text[pos:end]
        while True:
            m = next(
                (x for x in _SHORT_MACRO.finditer(segment) if x.group(1) not in _KEEP_SHORT),
                None,
            )
            if m is None:
                break
            open_at = segment.index("{", m.end())
            close = match_brace(segment, open_at)
            segment = segment[: m.start()] + (
                segment[close:] if close > 0 else segment[open_at + 1 :]
            )
        out.append(segment)
        if span is not None:
            out.append(span.group(0))
            pos = span.end()
    return "".join(out)


def _texorpdfstring(text: str) -> str:
    r"""``\texorpdfstring{$T_{max}$}{Tmax}`` -> ``$T_{max}$`` (the TeX version, braces balanced)."""
    key = "\\texorpdfstring"
    while (i := text.find(key)) >= 0:
        first = text.find("{", i)
        end_first = match_brace(text, first) if first >= 0 else -1
        if end_first < 0:
            return text.replace(key, "")
        second = end_first
        while second < len(text) and text[second] in " \t\n":
            second += 1
        end_second = match_brace(text, second) if text[second : second + 1] == "{" else end_first
        text = text[:i] + text[first + 1 : end_first - 1] + text[end_second:]
    return text


def clean_inline(text: str) -> str:
    """One line of prose: the title of a heading, a sentence, an item label."""
    text = _drop_review_macros(text)
    text = strip_formatting(text)
    text = _texorpdfstring(text)
    # drop caps: \IEEEPARstart{A}{ddress} -> Address
    text = re.sub(
        r"\\(?:IEEEPARstart|lettrine)\s*(?:\[[^\]]*\])?\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1\2", text
    )
    text = re.sub(r"\\\\(?:\[[^\]]*\])?|\\newline(?![A-Za-z])", " ", text)
    text = re.sub(r"\\par(?![A-Za-z])", "\n\n", text)
    text = re.sub(r"\\[,;:! ]|\\[-/]", " ", text)
    text = re.sub(r"(?<!\\)~", " ", text)
    text = text.replace("{}", "")
    return " ".join(text.split())


def _extract_footnotes(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    while True:
        m = _FOOTNOTE.search(text)
        if m is None:
            return text, notes
        end = match_brace(text, m.end() - 1)
        if end < 0:
            return text[: m.start()] + text[m.end() :], notes
        notes.append(text[m.end() : end - 1])
        text = text[: m.start()] + text[end:]


def sentences_of(text: str) -> list[str]:
    """The sentences of a run of prose; footnotes come after the paragraph that holds them."""
    out: list[str] = []
    for para in _BLANK_PARA.split(text):
        para, notes = _extract_footnotes(para)
        for chunk in [para, *notes]:
            for sentence in split_sentences(clean_inline(chunk)):
                if _HAS_CONTENT.search(sentence):
                    out.append(sentence)
    return out


def figure_content(env_text: str) -> str:
    """A float as one line of LaTeX without placement options, labels or rules."""
    return " ".join(strip_formatting(env_text).split())


# --------------------------------------------------------------------------- scanning


def _title_at(text: str, i: int) -> tuple[str, int]:
    """The ``{title}`` after a sectioning command (``[short]`` skipped): (title, next index)."""
    n = len(text)
    while i < n and text[i] in " \t\n":
        i += 1
    if i < n and text[i] == "[":
        j = match_brace(text, i, "[", "]")
        i = j if j > 0 else i
        while i < n and text[i] in " \t\n":
            i += 1
    if i < n and text[i] == "{":
        j = match_brace(text, i)
        if j > 0:
            return clean_inline(text[i + 1 : j - 1]).rstrip(" .:"), j
    return "", i


def _env_args(name: str, text: str, i: int) -> int:
    """Skip ``[opt]`` (and ``{arg}`` of environments that take one) right after ``\\begin{..}``."""
    for open_ch, close_ch, wanted in (("[", "]", True), ("{", "}", name in ARG_ENVS)):
        j = i
        while j < len(text) and text[j] in " \t":
            j += 1
        if wanted and j < len(text) and text[j] == open_ch:
            k = match_brace(text, j, open_ch, close_ch)
            if k > 0:
                i = k
    return i


def _items(body: str) -> list[tuple[str, str]]:
    """``(label, text)`` of each ``\\item`` of a list body, nested lists left inside the text."""
    marks, depth = [], 0
    for m in _LIST_TOKEN.finditer(body):
        if m.group("kind") == "begin":
            depth += 1
        elif m.group("kind") == "end":
            depth -= 1
        elif depth == 0:
            marks.append(m)
    items = []
    for k, m in enumerate(marks):
        end = marks[k + 1].start() if k + 1 < len(marks) else len(body)
        text, label = body[m.end() : end], ""
        stripped = text.lstrip()
        if stripped.startswith("["):  # \item[Term] description
            j = match_brace(stripped, 0, "[", "]")
            if j > 0:
                label, text = clean_inline(stripped[1 : j - 1]), stripped[j:]
        items.append((label, text))
    return items


def _pieces(text: str, inside_item: bool = False) -> list[Piece]:
    """Cut a run of LaTeX into text, headings, leaves, lists and groups (abstract...)."""
    pieces: list[Piece] = []
    pos = 0

    def add_text(end: int) -> None:
        if end > pos and text[pos:end].strip():
            pieces.append(("text", text[pos:end]))

    while True:
        m = _TOKEN.search(text, pos)
        if m is None:
            add_text(len(text))
            return pieces
        token = m.group(0)
        if m.group("head"):
            if inside_item:  # a heading cannot be inside a list item; treat it as text
                add_text(m.start())
                pos = m.end()
                continue
            add_text(m.start())
            kind, rank = HEADINGS[m.group("head")]
            title, pos = _title_at(text, m.end())
            pieces.append(("head", kind, rank, title))
        elif token.startswith("\\begin"):
            add_text(m.start())
            name = m.group("env")
            base = name.rstrip("*")
            closing = _end_of_env(text, base, "*" if name.endswith("*") else "", m.end())
            body_start = _env_args(base, text, m.end())
            if closing is None:  # never closed: flatten
                pos = body_start
                continue
            body, after = text[body_start : closing[0]], closing[1]
            if name in SKIPPED_ENVS or base in SKIPPED_ENVS:
                pass
            elif name in FIGURE_ENVS:
                pieces.append(("leaf", "figure", figure_content(text[m.start() : after])))
            elif name in EQUATION_ENVS:
                pieces.append(("leaf", "equation", block_equation(body, base)))
            elif name in LIST_ENVS:
                pieces.append(
                    ("list", [(label, _pieces(item, True)) for label, item in _items(body)])
                )
            elif base in ABSTRACT_ENVS:
                pieces.append(("group", "Abstract", _pieces(body)))
            elif base in ACK_ENVS:
                pieces.append(("group", "Acknowledgements", _pieces(body)))
            else:  # theorem, proof, center, minipage, quote...: its content is ordinary prose
                pos = body_start
                continue
            pos = after
        elif token.startswith("\\end"):
            add_text(m.start())  # the end of a flattened environment
            pos = m.end()
        else:  # \[ ... \]  or  $$ ... $$
            add_text(m.start())
            closer = "\\]" if token == "\\[" else "$$"
            j = text.find(closer, m.end())
            if j < 0:
                pos = m.end()
                continue
            pieces.append(("leaf", "equation", block_equation(text[m.end() : j])))
            pos = j + len(closer)
    # (unreachable)


# --------------------------------------------------------------------------- assembling


def _attach(pieces: list[Piece], parent: Node, root: Node | None = None) -> None:
    """Append what the pieces hold to ``parent`` (no headings: those are handled by the caller)."""
    for piece in pieces:
        tag = piece[0]
        if tag == "text":
            parent.children.extend(Node("sentence", s) for s in sentences_of(piece[1]))
        elif tag == "leaf":
            if piece[2]:
                parent.children.append(Node(piece[1], piece[2]))
        elif tag == "list":
            lst = Node("itemize")
            for label, item_pieces in piece[1]:
                item = Node("item")
                if label:
                    item.children.extend(Node("sentence", s) for s in sentences_of(label + ":"))
                _attach(item_pieces, item)
                lst.children.append(item)
            parent.children.append(lst)
        elif tag == "group":
            section = Node("section", piece[1])
            _attach(piece[2], section)
            (root if root is not None else parent).children.append(section)


def _assemble(pieces: list[Piece], root: Node) -> None:
    stack: list[tuple[int, Node]] = [(0, root)]
    skipping: int | None = None  # rank of the References heading being skipped
    run: list[Piece] = []

    def flush() -> None:
        if run:
            _attach(run, stack[-1][1], root)
            run.clear()

    for piece in pieces:
        if piece[0] != "head":
            if skipping is None:
                run.append(piece)
            continue
        flush()
        _, kind, rank, title = piece
        if skipping is not None:
            if rank > skipping:
                continue
            skipping = None
        if title.lower().strip(" .:") in REFERENCE_TITLES:
            skipping = rank
            continue
        while stack[-1][0] >= rank:
            stack.pop()
        node = Node(kind, title)
        stack[-1][1].children.append(node)
        stack.append((rank, node))
    flush()


def body_of(text: str) -> str:
    """The text between ``\\begin{document}`` and ``\\end{document}`` (all of it if absent)."""
    start = re.search(r"\\begin\s*\{document\}", text)
    if start is not None:
        text = text[start.end() :]
    end = re.search(r"\\end\s*\{document\}", text)
    return text[: end.start()] if end is not None else text


def build_tree(text: str) -> Node:
    """The hierarchy of one version; ``text`` is the output of ``normalize`` (or any LaTeX)."""
    body = body_of(text)
    body = drop_command(body, _FRONT_MATTER, args=1)
    body = drop_command(body, r"markboth", args=2)
    body = drop_command(body, _DEFINITIONS, args=2)
    body = drop_command(body, _NO_PROSE, args=1)
    root = Node("document")
    _assemble(_pieces(normalize_math(body)), root)
    return root


def render(tree: Node, indent: str = "  ") -> str:
    """The tree as indented text (for the audit sheet and for debugging)."""
    lines = []

    def visit(node: Node, depth: int) -> None:
        text = node.content if len(node.content) <= 100 else node.content[:97] + "..."
        lines.append(f"{indent * depth}[{node.kind}] {' '.join(text.split())}".rstrip())
        for child in node.children:
            visit(child, depth + 1)

    visit(tree, 0)
    return "\n".join(lines)


__all__ = ["build_tree", "render", "sentences_of", "clean_inline", "inline_equation"]
