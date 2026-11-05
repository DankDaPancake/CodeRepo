# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Sentence splitting for LaTeX prose (M2 statement: "Sentence splitting").

A sentence ends at ``.``, ``?`` or ``!`` followed by a space and the start of a new sentence. It
does **not** end inside

- mathematics (``$...$``, ``\\(...\\)``): the span is masked before the scan;
- commands (``\\cite{a.b}``, ``\\ref{fig:1}``, ``\\url{...}``, ``\\href{...}``): braces masked;
- abbreviations: ``e.g.``, ``i.e.``, ``et al.``, ``Fig.``, ``Eq.``, ``Sec.``, ``cf.``, ``vs.``...;
- URLs, e-mail addresses and file names (``www.x.org``, ``https://...``, ``main.py``);
- decimal numbers (``3.14``), initials (``J. Smith``, ``U.S.``) and list numbers (``1.``).

The next sentence has to start with a capital letter, a command (``\\textbf``), a math span, an
opening bracket or a quote; a lower-case letter after a period means the period was not final.
"""

from __future__ import annotations

import re

# lower-case, without the trailing dot. Never a sentence end, whatever follows.
ABBREVIATIONS = frozenset(
    """e.g i.e et al cf vs viz resp approx ca wrt w.r.t s.t a.k.a fig figs eq eqs sec secs sect
    tab tabs ref refs no nos vol vols pp p ch chap thm thms lem lemma prop cor def defn alg algo
    appx app ex dr mr mrs ms prof sr jr st inc ltd co corp dept univ ed eds repr trans rev
    jan feb mar apr jun jul aug sep sept oct nov dec min max""".split()
)
# Abbreviations that may also close a sentence when a capital letter follows.
ABBREVIATIONS_MAY_END = frozenset({"etc", "al"})

# Commands whose braces hold identifiers, paths or URLs: no sentence break can be inside.
_ARG_COMMAND = re.compile(
    r"\\(?:cite[A-Za-z]*|nocite|[A-Za-z]*ref|eqref|autoref|cref|Cref|pageref|label|url|href|"
    r"includegraphics|input|include|texttt|footnotemark|hyperref|path|file|verb)\*?"
    r"(?:\s*\[[^\]\n]*\]){0,2}\s*\{[^{}]*\}(?:\s*\{[^{}]*\})?"
)
_INLINE_MATH = re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$|(?<!\\)\$.*?(?<!\\)\$|\\\(.*?\\\)", re.S)
_URL = re.compile(
    r"(?:https?://|ftp://|www\.)[^\s<>{}|\\^`]*[^\s<>{}|\\^`.,;:!?)\]]|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
)  # the last character is never punctuation: "see www.x.org." ends the sentence
# first words of a sentence: after "A." one of them means "A." closed the previous sentence
_STARTERS = frozenset(
    """The We This That These Those It Its In Our Their His Her However Moreover Thus Hence
    For To As Since If When While Let Then Also Here There Such One Two Three First Second
    Finally Furthermore Therefore Consequently Note Recall Consider Suppose Assume Given
    By On At An A I They You He She Each Both All Some Most Many Several Although Because
    Before After During Without Using Based Unlike Like With Within Under Over Between""".split()
)
_FILE_NAME = re.compile(r"\b[\w-]+\.(?:py|tex|bib|png|jpg|jpeg|pdf|csv|json|txt|md|org|com|net)\b")
_DECIMAL = re.compile(r"(?<=\d)\.(?=\d)")
_MASK = "\x00{}\x00"
_MASK_RE = re.compile(r"\x00(\d+)\x00")

# punctuation followed by closing quotes/brackets, then white space
# "end.\cite{a} Next": the citation placeholders (group 3) belong to the sentence that ends
_BOUNDARY = re.compile(r"([.!?]+)((?:[\"'”’)\]}]|'')*)((?:\x00\d+\x00)*)(\s+)")
_STARTS_SENTENCE = re.compile(
    r"[A-ZÀ-Ý(\[\"'“‘`{$\\\x00]|\\[A-Za-z]"
)  # capital, bracket, quote, command, math (masked)


def _mask(text: str) -> tuple[str, list[str]]:
    """Replace spans that never contain a sentence break by ``\\x00<n>\\x00`` placeholders."""
    saved: list[str] = []

    def keep(match: re.Match) -> str:
        saved.append(match.group(0))
        return _MASK.format(len(saved) - 1)

    for pattern in (_INLINE_MATH, _ARG_COMMAND, _URL, _FILE_NAME):
        text = pattern.sub(keep, text)
    text = _DECIMAL.sub("\x01", text)  # "3.14" -> "3\x013"; restored by _unmask
    return text, saved


def _unmask(text: str, saved: list[str]) -> str:
    text = text.replace("\x01", ".")
    # a placeholder may hold another placeholder (math inside a command argument)
    for _ in range(3):
        if "\x00" not in text:
            break
        text = _MASK_RE.sub(lambda m: saved[int(m.group(1))], text)
    return text


def _last_word(before: str) -> str:
    """The token before a period: ``'see Fig'`` -> ``'fig'``, ``'e.g'`` -> ``'e.g'``."""
    match = re.search(r"((?:[A-Za-z]\.)*[A-Za-z]+)$", before)
    return match.group(1).lower() if match else ""


def _is_boundary(text: str, match: re.Match) -> bool:
    marks, rest = match.group(1), text[match.end() :]
    if not rest or not _STARTS_SENTENCE.match(rest):
        return False
    if "?" in marks or "!" in marks or len(marks) > 1:
        return True  # "?", "!" and "..." followed by a capital
    before = text[: match.start()]
    word = _last_word(before)
    if word in ABBREVIATIONS:
        return False
    if word in ABBREVIATIONS_MAY_END:
        return rest[0].isupper() and word == "etc"
    if "." in word:  # "i.e", "U.S", "Ph.D": a run of initials, never a sentence end
        return False
    # "J. Smith", "A. B. Jones": a lone capital letter is an initial, unless the next word is
    # one that starts sentences ("... of type A. The model ...")
    if re.search(r"(?:^|\s)[A-Z]$", before) and rest[0].isupper():
        next_word = re.match(r"[A-Za-z]+", rest)
        if next_word is None or next_word.group(0) not in _STARTERS:
            return False
    # a bare list number ("1. Introduction") is not a sentence end
    return re.fullmatch(r"\d{1,2}", before.strip()) is None


def split_sentences(text: str) -> list[str]:
    """Sentences of one paragraph of prose (white space is collapsed first)."""
    text = " ".join(text.split())
    if not text:
        return []
    masked, saved = _mask(text)
    sentences, start = [], 0
    for match in _BOUNDARY.finditer(masked):
        placeholders = _MASK_RE.findall(match.group(3))
        if any(not saved[int(i)].startswith(("\\cite", "\\footnotemark")) for i in placeholders):
            continue  # "etc.$x$": a formula, not a citation, follows the period
        if _is_boundary(masked, match):
            sentences.append(masked[start : match.end(3)])
            start = match.end()
    sentences.append(masked[start:])
    out = (_unmask(s, saved).strip() for s in sentences)
    return [s for s in out if s]
