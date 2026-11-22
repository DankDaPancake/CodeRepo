# Drafted with the help of an AI assistant (Gemini, Google), cited per the course rules.
"""M3 data cleaning: text normalization, stop-word removal, author tokens and arXiv ID parsing.

Shared by the rule-based automatic labeler (``src.m3.auto_label``) and downstream feature
engineering. Keeps preprocessing classical, deterministic and free of external models.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Common English function words stripped when computing content-token title overlap.
TITLE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "its",
        "of",
        "on",
        "or",
        "over",
        "that",
        "the",
        "their",
        "this",
        "to",
        "toward",
        "towards",
        "under",
        "using",
        "via",
        "with",
    }
)

# Noise tokens that appear in BibTeX author lists instead of real surnames.
AUTHOR_NOISE = frozenset({"others", "al", "et", "jr", "sr", "ii", "iii", "iv"})

# New-style arXiv IDs (since 0704): YYMM.NNNN(N), optionally followed by v<N>.
# Allows prefixes like ``arXiv.1706.03762`` or ``/abs/1706.03762`` while rejecting ``1.1706.03762``.
_NEW_ARXIV_RE = re.compile(
    r"(?<!\d)(?<!\d\.)((?:0[7-9]|[12]\d)(?:0[1-9]|1[0-2])\.\d{4,5})(?:v\d+)?(?!\d)",
    re.IGNORECASE,
)

# Old-style arXiv IDs (before 0704): archive(.XX)?/NNNNNNN, optionally followed by v<N>.
# Allows ``/abs/hep-th/9901001`` and ``arXiv:hep-th/9901001``.
_OLD_ARXIV_RE = re.compile(
    r"(?<![a-z0-9\-])("
    r"(?:astro-ph|cond-mat|gr-qc|hep-ex|hep-lat|hep-ph|hep-th|math-ph|nlin|nucl-ex|nucl-th|"
    r"physics|quant-ph|math|cs|q-bio|q-fin|stat|eess|econ)"
    r"(?:\.[a-z]{2})?/\d{7})(?:v\d+)?(?!\d)",
    re.IGNORECASE,
)

# LaTeX accent commands: punctuation accents (\"{o}, \'e) vs letter accents (\c{c}, \v s).
_LATEX_PUNCT_ACCENT_RE = re.compile(r"\\['\"`^~=.]\s*\{?([a-zA-Z])\}?")
_LATEX_LETTER_ACCENT_RE = re.compile(r"\\[uvHcdbrt](?:\s*\{([a-zA-Z])\}|\s+([a-zA-Z])\b)")
# Remaining LaTeX control sequences such as \textbf, \emph, \alpha.
_LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]+\*?")


def clean_text(text: str | None) -> str:
    """Lowercase, strip accents and LaTeX markup, collapse punctuation to single spaces."""
    if not text:
        return ""
    s = str(text)
    s = _LATEX_PUNCT_ACCENT_RE.sub(r"\1", s)
    s = _LATEX_LETTER_ACCENT_RE.sub(lambda m: m.group(1) or m.group(2), s)
    s = _LATEX_CMD_RE.sub(" ", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^0-9a-zA-Z]+", " ", s).lower()
    return " ".join(s.split())


def title_tokens(title: str | None, *, remove_stopwords: bool = True) -> list[str]:
    """Tokenize a cleaned title; optionally drop English stop-words and single-char noise."""
    tokens = clean_text(title).split()
    if not remove_stopwords:
        return tokens
    filtered = [t for t in tokens if t not in TITLE_STOPWORDS and (len(t) > 1 or t.isdigit())]
    return filtered or tokens


def title_char_similarity(a: str | None, b: str | None) -> float:
    """Character-level SequenceMatcher ratio on cleaned titles."""
    ca, cb = clean_text(a), clean_text(b)
    if not ca or not cb:
        return 0.0
    return SequenceMatcher(None, ca, cb).ratio()


def title_token_jaccard(a: str | None, b: str | None) -> float:
    """Jaccard similarity over stop-word-filtered title content tokens."""
    ta, tb = set(title_tokens(a)), set(title_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def title_token_containment(a: str | None, b: str | None) -> float:
    """Share of the shorter title's content tokens present in the longer title."""
    ta, tb = set(title_tokens(a)), set(title_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def extract_author_surnames(authors: list[str] | None) -> set[str]:
    """Normalized surnames from ``Last, First`` or ``First Last`` author strings."""
    out: set[str] = set()
    for raw in authors or []:
        if not raw:
            continue
        name = str(raw).strip()
        if "," in name:
            parts = clean_text(name.split(",", 1)[0]).split()
        else:
            parts = clean_text(name).split()
        parts = [p for p in parts if p not in AUTHOR_NOISE]
        if not parts:
            continue
        surname = parts[-1]
        if len(surname) > 1:
            out.add(surname)
    return out


def author_surname_jaccard(a: list[str] | None, b: list[str] | None) -> float:
    """Jaccard overlap between normalized author surname sets."""
    sa, sb = extract_author_surnames(a), extract_author_surnames(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def author_surname_overlap_min(a: list[str] | None, b: list[str] | None) -> float:
    """Overlap coefficient ``|A & B| / min(|A|, |B|)`` (handles truncated ``et al.`` lists)."""
    sa, sb = extract_author_surnames(a), extract_author_surnames(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def extract_arxiv_ids(text: str | None) -> list[str]:
    """Extract canonical base arXiv IDs (version suffix stripped, lowercase, deduplicated)."""
    if not text:
        return []
    s = str(text)
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (_NEW_ARXIV_RE, _OLD_ARXIV_RE):
        for match in pattern.finditer(s):
            cid = match.group(1).lower()
            if cid not in seen:
                seen.add(cid)
                found.append(cid)
    return found


def entry_mentions_arxiv_id(entry: dict, ref_arxiv_id: str | None) -> bool:
    """Return True if ``ref_arxiv_id`` appears as a bounded arXiv ID in doi/url/journal."""
    if not ref_arxiv_id:
        return False
    target = ref_arxiv_id.strip().lower()
    if not target:
        return False
    blob = " ".join(str(entry.get(k) or "") for k in ("doi", "url", "journal")).lower()
    if not blob.strip():
        return False
    if target in extract_arxiv_ids(blob):
        return True
    # Direct bounded fallback for any non-standard old-style archive prefix.
    pattern = rf"(?<![a-z0-9\-])(?<!\d\.){re.escape(target)}(?:v\d+)?(?![a-z0-9])"
    return re.search(pattern, blob) is not None


def parse_year(value) -> int | None:
    """Extract a 4-digit year from an int, ISO date string, or year string."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1800 <= value <= 2100 else None
    m = re.match(r"^\s*(\d{4})\b", str(value))
    if not m:
        return None
    year = int(m.group(1))
    return year if 1800 <= year <= 2100 else None
