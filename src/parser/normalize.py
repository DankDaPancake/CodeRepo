# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
r"""Cleanup and math normalisation of one version (M2 statement: "Cleanup and normalisation").

``normalize(text)`` takes the root file with its ``\input``/``\include`` expanded and returns the
same document where

- comments are gone;
- formatting commands that carry no meaning are removed: ``\centering``, placement options such
  as ``[htbp]``, ``\midrule``, ``\vspace{..}``, ``\label{..}``, ``\noindent``, size switches...;
- text styling is unwrapped: ``\textbf{x}`` -> ``x`` (the words stay, the typography goes);
- inline math is always ``$...$`` (from ``\(...\)`` and ``math``);
- block math is always ``\begin{equation} ... \end{equation}`` (from ``$$...$$``, ``\[...\]``,
  ``equation*``, ``displaymath``, and the multi-line ``align``, ``gather``, ``multline``,
  ``eqnarray``... whose lines go into an ``aligned``/``gathered`` block inside the equation).

Nothing else is rewritten, so the result is still compilable LaTeX and every other command
(``\cite``, ``\ref``, ``\section``, figures, tables) reaches ``build_tree`` as it was written.
"""

from __future__ import annotations

import re

from src.parser.gather import strip_comments

# --------------------------------------------------------------------------- brace helpers


def match_brace(text: str, start: int, open_ch: str = "{", close_ch: str = "}") -> int:
    """Index just after the group opened at ``text[start]``; ``-1`` when it never closes."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def unwrap_command(text: str, names: str) -> str:
    r"""``\textbf{x}`` -> ``x`` for every command in the regex alternative ``names``."""
    pattern = re.compile(r"\\(?:" + names + r")\*?\s*\{")
    while True:
        m = pattern.search(text)
        if m is None:
            return text
        end = match_brace(text, m.end() - 1)
        if end < 0:  # unbalanced: drop the command name only
            text = text[: m.start()] + text[m.end() :]
            continue
        text = text[: m.start()] + text[m.end() : end - 1] + text[end:]


def drop_command(text: str, names: str, args: int = 1) -> str:
    r"""Remove ``\name[opt]{arg}...`` (``args`` brace groups) for the commands in ``names``."""
    pattern = re.compile(r"\\(?:" + names + r")\*?(?![A-Za-z])")
    out, pos = [], 0
    for m in pattern.finditer(text):
        if m.start() < pos:
            continue
        i = m.end()
        for _ in range(args):
            j = i
            while j < len(text) and text[j] in " \t\n":
                j += 1
            if j < len(text) and text[j] == "[":
                k = match_brace(text, j, "[", "]")
                j = k if k > 0 else j
            if j < len(text) and text[j] == "{":
                k = match_brace(text, j)
                if k < 0:
                    break
                i = k
            else:
                break
        out.append(text[pos : m.start()])
        pos = i
    out.append(text[pos:])
    return "".join(out)


# --------------------------------------------------------------------------- formatting

_NO_ARG = (
    r"centering|raggedright|raggedleft|noindent|indent|clearpage|newpage|cleardoublepage|"
    r"small|footnotesize|scriptsize|tiny|large|Large|LARGE|huge|Huge|normalsize|"
    r"bfseries|itshape|rmfamily|sffamily|ttfamily|mdseries|upshape|slshape|scshape|"
    r"hline|toprule|midrule|bottomrule|hfill|hfil|vfill|vfil|smallskip|medskip|bigskip|"
    r"protect|relax|sloppy|fussy|linebreak|pagebreak|nopagebreak|nolinebreak|"
    r"maketitle|tableofcontents|listoffigures|listoftables|appendix|noappendix|"
    r"allowbreak|nobreak|break"
)
_NO_ARG_RE = re.compile(r"\\(?:" + _NO_ARG + r")(?![A-Za-z])\s*")
_ONE_ARG = (
    r"label|vspace|hspace|index|thispagestyle|pagestyle|bibliographystyle|"
    r"phantom|hphantom|vphantom|pagenumbering|color|pagecolor|"
    r"footnotemark|cline|noalign|hypertarget"
)
_TWO_ARGS = r"rule|setcounter|addtocounter|setlength|addtolength|hypersetup"
_THREE_ARGS = r"addcontentsline"
_DIMENSION_RE = re.compile(
    r"\\[vh]skip\s*-?[\d.]+\s*[a-z]{2}(?:\s+(?:plus|minus)\s*[\d.]+\s*[a-z]{2})*"
)
_CMIDRULE_RE = re.compile(r"\\cmidrule\*?(?:\([^)]*\))?\s*\{[^{}]*\}")
_STYLE_ONLY_UNWRAP = (
    r"textbf|textit|textsl|textsc|textrm|textsf|textup|textnormal|emph|underline|uline"
)
_PLACEMENT_RE = re.compile(
    r"(\\begin\s*\{(?:figure|table|algorithm|wrapfigure|wraptable|sidewaysfigure|"
    r"sidewaystable)\*?\})\s*\[[!htbpHcm]*\]"
)
_FORMAT_ENVS_RE = re.compile(
    r"\\(?:begin|end)\s*\{(?:center|flushleft|flushright|small|footnotesize|scriptsize|"
    r"tiny|large|Large|LARGE|huge|Huge|normalsize|raggedright|raggedleft)\}\s*"
)
_COLOR_RE = re.compile(r"\\textcolor\s*\{[^{}]*\}\s*\{([^{}]*)\}")  # \textcolor{red}{x} -> x


def strip_formatting(text: str) -> str:
    r"""Drop the commands that only say how the text looks (not what it says)."""
    text = _PLACEMENT_RE.sub(r"\1", text)
    text = _FORMAT_ENVS_RE.sub("", text)
    text = drop_command(text, _ONE_ARG, args=1)
    text = drop_command(text, _TWO_ARGS, args=2)
    text = drop_command(text, _THREE_ARGS, args=3)
    text = _CMIDRULE_RE.sub("", _DIMENSION_RE.sub("", text))
    text = _COLOR_RE.sub(r"\1", text)
    text = _NO_ARG_RE.sub("", text)
    return unwrap_command(text, _STYLE_ONLY_UNWRAP)


# --------------------------------------------------------------------------- math

# environments whose body is a single formula, and the ones that hold several aligned lines
_ONE_LINE = ("equation", "displaymath", "math")
_MULTI_LINE = {
    "align": "aligned",
    "alignat": "aligned",
    "flalign": "aligned",
    "eqnarray": "aligned",
    "split": "aligned",
    "multline": "aligned",
    "gather": "gathered",
}
_MATH_ENV_RE = re.compile(
    r"\\begin\s*\{(" + "|".join(list(_ONE_LINE) + list(_MULTI_LINE)) + r")(\*?)\}"
)
_MATH_JUNK_RE = re.compile(r"\\(?:nonumber|notag)(?![A-Za-z])|\\label\s*\{[^{}]*\}")
_ALIGNAT_ARG_RE = re.compile(r"^\s*\{\d+\}")


def _tidy_formula(body: str) -> str:
    body = _MATH_JUNK_RE.sub("", body)
    return " ".join(body.split())


def block_equation(body: str, env: str | None = None) -> str:
    r"""The one spelling of a displayed formula: ``\begin{equation}...\end{equation}``."""
    body = _tidy_formula(_ALIGNAT_ARG_RE.sub("", body) if env == "alignat" else body)
    if env in _MULTI_LINE:
        inner = _MULTI_LINE[env]
        body = f"\\begin{{{inner}}} {body} \\end{{{inner}}}"
    return f"\\begin{{equation}}\n{body}\n\\end{{equation}}"


def inline_equation(body: str) -> str:
    return "$" + " ".join(body.split()) + "$"


def _end_of_env(text: str, name: str, star: str, start: int) -> tuple[int, int] | None:
    """``(start of \\end, end of \\end)`` of the environment opened before ``start``."""
    begin = re.compile(r"\\begin\s*\{" + re.escape(name + star) + r"\}")
    end = re.compile(r"\\end\s*\{" + re.escape(name + star) + r"\}")
    depth, pos = 1, start
    while True:
        e, b = end.search(text, pos), begin.search(text, pos)
        if e is None:
            return None
        if b is not None and b.start() < e.start():
            depth += 1
            pos = b.end()
            continue
        depth -= 1
        if depth == 0:
            return e.start(), e.end()
        pos = e.end()


def normalize_math(text: str) -> str:
    r"""Inline math to ``$..$``, displayed math to ``\begin{equation}..\end{equation}``."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            nxt = text[i + 1 : i + 2]
            if nxt == "(":
                j = text.find("\\)", i + 2)
                if j > 0:
                    out.append(inline_equation(text[i + 2 : j]))
                    i = j + 2
                    continue
            elif nxt == "[":
                j = text.find("\\]", i + 2)
                if j > 0:
                    out.append("\n" + block_equation(text[i + 2 : j]) + "\n")
                    i = j + 2
                    continue
            elif text.startswith("\\begin", i):
                m = _MATH_ENV_RE.match(text, i)
                if m is not None:
                    closing = _end_of_env(text, m.group(1), m.group(2), m.end())
                    if closing is not None:
                        body = text[m.end() : closing[0]]
                        if m.group(1) == "math":
                            out.append(inline_equation(body))
                        else:
                            out.append("\n" + block_equation(body, m.group(1)) + "\n")
                        i = closing[1]
                        continue
            out.append(text[i : i + 2])  # \$, \%, \\ ...: an escaped character, copied as is
            i += 2
            continue
        if c == "$":
            if text.startswith("$$", i):
                j = _unescaped(text, "$$", i + 2)
                if j > 0:
                    out.append("\n" + block_equation(text[i + 2 : j]) + "\n")
                    i = j + 2
                    continue
            else:
                j = _unescaped(text, "$", i + 1)
                if j > 0 and "\n\n" not in text[i:j]:
                    out.append(inline_equation(text[i + 1 : j]))
                    i = j + 1
                    continue
        out.append(c)
        i += 1
    return "".join(out)


def _unescaped(text: str, token: str, start: int) -> int:
    """Index of the next ``token`` at or after ``start`` that is not escaped; ``-1`` if none."""
    i = start
    while True:
        j = text.find(token, i)
        if j < 0:
            return -1
        k, slashes = j - 1, 0
        while k >= 0 and text[k] == "\\":
            slashes += 1
            k -= 1
        if slashes % 2 == 0:
            return j
        i = j + 1


# --------------------------------------------------------------------------- entry point

_BLANK_LINES_RE = re.compile(r"[ \t]*\n(?:[ \t]*\n){2,}")


def normalize(text: str) -> str:
    """Comments out, meaningless formatting out, math in its one canonical spelling."""
    text = strip_comments(text)
    text = normalize_math(text)
    text = strip_formatting(text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = _BLANK_LINES_RE.sub("\n\n", text)
    # one newline around a displayed formula, so that normalising twice changes nothing
    text = re.sub(r"\s*\n(\\begin\{equation\})", r"\n\1", text)
    text = re.sub(r"(\\end\{equation\})[ \t]*\n[ \t\n]*", r"\1\n", text)
    return text.strip() + "\n"
