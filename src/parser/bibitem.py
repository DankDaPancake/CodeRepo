# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""References of one version (M2): ``\\bibitem`` entries and ``.bib`` files -> BibTeX rows.

Statement M2: *"convert ``\\bibitem`` entries in the .tex files into standard BibTeX entries"*
using regular expressions; the citation-key and entry-ID formats are left to the group.

    python -m src.parser.bibitem data/corpus/2606-30762/v1          # print the entries
    python -m src.parser.bibitem data/corpus/2606-30762/v1 --json   # one JSON object per entry

What is extracted
-----------------
- ``parse_bibitems(text)``: each ``\\bibitem[label]{key} free text`` of a ``thebibliography``.
  The text comes from BibTeX styles (``\\newblock`` between authors / title / venue), natbib
  labels (``Name et~al.(2017)Full authors``), IEEE (quoted title), LNCS (``Family, A.: Title.``),
  Elsevier (comma separated) or was typed by hand; the style is guessed per entry. ``key``,
  ``year``, ``doi``, ``url`` and arXiv IDs are reliable, ``authors`` / ``title`` / ``journal``
  / ``entry_type`` are heuristics (see ``BibEntry``).
- ``parse_bib(text)``: a ``.bib`` file. M1 keeps ``.bib`` but not ``.bbl``, so a paper that
  uses BibTeX has its references *only* there; without it the ``bibtex`` table would be empty
  for most papers.
- ``extract_references(tex, files)``: both, for one gathered version. A ``.bib`` is read only
  if the compilation path names it (``\\bibliography`` / ``\\addbibresource``) or embeds it
  (``filecontents``), and only its *cited* entries are kept (all with ``\\nocite{*}``): BibTeX
  prints just those, and the goal is what a reader of the PDF sees. A ``\\bibitem`` is always
  printed, so all of them are kept.

Conventions fixed here (the ``bibtex`` table has no column for them):
- ``authors`` are ``"Given Family"`` strings in citation order; ``et al.`` / ``others`` is dropped.
- ``journal`` holds the journal *or* the proceedings / book title (a ``@inproceedings``
  ``booktitle``); ``arXiv preprint arXiv:ID`` for preprints, whose ``url`` is the abs page.
- ``raw`` keeps the whitespace-collapsed source text for deduplication; it is not a table column.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.parser.gather import TexVersion, gather, paper_title, strip_comments

# --------------------------------------------------------------------------- data


@dataclass
class BibEntry:
    """One reference; the fields mirror the columns of the ``bibtex`` table."""

    citation_key: str
    entry_type: str = "misc"
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    journal: str | None = None
    url: str | None = None
    raw: str = ""  # source text, whitespace collapsed (for dedup, not a table column)
    source: str = "bibitem"  # "bibitem", "bib" or "filecontents"

    def to_row(self, arxiv_id: str) -> dict:
        """The ``bibtex`` table row of this entry."""
        return {
            "arxiv_id": arxiv_id,
            "citation_key": self.citation_key,
            "entry_type": self.entry_type,
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "doi": self.doi,
            "journal": self.journal,
            "url": self.url,
        }


@dataclass
class VersionRefs:
    entries: list[BibEntry] = field(default_factory=list)
    bib_files: list[str] = field(default_factory=list)  # .bib files that were read
    missing_bib: list[str] = field(
        default_factory=list
    )  # named by \bibliography, not in the folder
    n_bibitems: int = 0
    n_bib_cited: int = 0  # .bib entries kept because the text cites them
    n_bib_unused: int = 0  # .bib entries the paper never cites (not printed, dropped)


# --------------------------------------------------------------------------- cleaning

_NEWBLOCK = "\x00"
_IT_OPEN, _IT_CLOSE = "\x01", "\x02"

_ACCENTS = {
    "'": "\u0301",
    "`": "\u0300",
    "^": "\u0302",
    '"': "\u0308",
    "~": "\u0303",
    "=": "\u0304",
    ".": "\u0307",
    "u": "\u0306",
    "v": "\u030c",
    "H": "\u030b",
    "c": "\u0327",
    "k": "\u0328",
    "r": "\u030a",
    "d": "\u0323",
    "b": "\u0331",
}
_LETTERS = {
    "ss": "ß",
    "o": "ø",
    "O": "Ø",
    "ae": "æ",
    "AE": "Æ",
    "oe": "œ",
    "OE": "Œ",
    "aa": "å",
    "AA": "Å",
    "l": "ł",
    "L": "Ł",
    "i": "i",
    "j": "j",
}
# \'e  \'{e}  {\'e}  \'{\i}  \v{s}  \c c
_ACCENT_RE = re.compile(r"\\([`'^\"~=.])\s*(?:\{\s*\\?([A-Za-z])\s*\}|\\?([A-Za-z]))")
_ACCENT_LETTER_RE = re.compile(r"\\([uvHckrdb])(?:\s*\{\s*([A-Za-z])\s*\}|\s+([A-Za-z]))")
_LETTER_RE = re.compile(r"\\(ss|aa|AA|ae|AE|oe|OE|[oOlLij])(?![A-Za-z])\s*(?:\{\})?")
_ESCAPES = {"&": "&", "%": "%", "$": "$", "#": "#", "_": "_", "{": "{", "}": "}", " ": " "}
_ESCAPE_RE = re.compile(r"\\([&%$#_{} ])")
_STYLE_ARG_RE = re.compile(
    r"\\(?:textbf|textrm|textsc|textup|textnormal|texttt|mbox|text|uppercase|MakeUppercase|"
    r"bibnamefont|bibfnamefont|citenamefont|bibinfo\s*\{[^{}]*\}|bibfield\s*\{[^{}]*\}|"
    r"protect|ensuremath)\s*(?=\{)"
)
_DROP_ARG_RE = re.compile(r"\\(?:natexlab|noopsort|BibitemOpen|BibitemShut)\s*(?:\{[^{}]*\})?")
_MACRO_RE = re.compile(r"\\[A-Za-z@]+\*?\s*")


def _accent(m: re.Match) -> str:
    base = m.group(2) or m.group(3)
    return unicodedata.normalize("NFC", base + _ACCENTS[m.group(1)])


def _accent_letter(m: re.Match) -> str:
    base = m.group(2) or m.group(3)
    return unicodedata.normalize("NFC", base + _ACCENTS[m.group(1)])


def _balanced(text: str, start: int, open_ch: str = "{", close_ch: str = "}") -> int:
    """Index after the group opened at ``text[start]``; ``len(text)`` if it never closes."""
    depth, i = 0, start
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


_ITALIC_OPEN_RE = re.compile(r"\\(?:emph|textit|textsl)\s*\{|\{\s*\\(?:em|it|sl|itshape|slshape)\b")


def _mark_italics(text: str) -> str:
    """Wrap every italic span in markers: the venue / book title is usually set in italics."""
    out, pos = [], 0
    while m := _ITALIC_OPEN_RE.search(text, pos):
        start = m.start()
        brace = text.index("{", start)
        end = _balanced(text, brace)
        inner = text[m.end() : end - 1]
        if text[start] == "{":  # {\em ...}: the match ends after \em, the group is the content
            inner = text[m.end() : end - 1]
        out.append(text[pos:start])
        out.append(f"{_IT_OPEN}{_unwrap_braces(inner)}{_IT_CLOSE}")
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _unwrap_braces(text: str) -> str:
    return text.replace("{", "").replace("}", "")


def _plain(text: str) -> str:
    """LaTeX source of a reference -> text (accents decoded, macros dropped, math kept)."""
    maths: list[str] = []

    def keep_math(m: re.Match) -> str:
        maths.append(m.group(0))
        return f"\x03{len(maths) - 1}\x03"

    text = re.sub(r"\$[^$]*\$", keep_math, text)
    text = re.sub(r"\\newblock\b", _NEWBLOCK, text)
    text = _DROP_ARG_RE.sub("", text)
    text = _mark_italics(text)
    text = _ACCENT_RE.sub(_accent, text)
    text = _ACCENT_LETTER_RE.sub(_accent_letter, text)
    text = _LETTER_RE.sub(lambda m: _LETTERS[m.group(1)], text)
    text = _ESCAPE_RE.sub(lambda m: _ESCAPES[m.group(1)] if m.group(1) != " " else " ", text)
    text = _STYLE_ARG_RE.sub("", text)
    text = text.replace("\\\\", " ").replace("\\-", "").replace("\\/", "").replace("\\!", "")
    text = text.replace("\\,", " ").replace("\\;", " ").replace("\\:", " ")
    text = _MACRO_RE.sub("", text)
    text = text.replace("~", " ")
    text = text.replace("---", "\u2014").replace("--", "\u2013")
    text = text.replace("``", '"').replace("''", '"').replace("\u201c", '"').replace("\u201d", '"')
    text = _unwrap_braces(text)
    text = re.sub(r"\x03(\d+)\x03", lambda m: maths[int(m.group(1))], text)
    return re.sub(r"[ \t\r\n\f]+", " ", text).strip()


def _strip_markers(text: str) -> str:
    return text.replace(_IT_OPEN, "").replace(_IT_CLOSE, "").replace(_NEWBLOCK, " ")


def _tidy_venue(text: str) -> str:
    """Like ``_tidy`` but ``Phys. Rev. Lett.`` keeps the period of its last abbreviation."""
    text = re.sub(r"\s+", " ", _strip_markers(text)).strip(" ,;:")
    if re.search(r"\b[A-Za-z]{1,6}\.\s+\S", text) and re.search(r"\b[A-Z][a-z]{0,5}\.$", text):
        return text
    return _tidy(text)


def _tidy(text: str) -> str:
    """A field value: markers removed, whitespace collapsed, edge punctuation trimmed."""
    text = re.sub(r"\s+", " ", _strip_markers(text)).strip()
    return text.strip(" .,;:").strip('"').strip(" .,;:")


# --------------------------------------------------------------------------- identifiers

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>{}\\|^`]+", re.IGNORECASE)
_URL_RE = re.compile(r"(?:https?|ftp)://[^\s\"<>{}\\|^`]+", re.IGNORECASE)
_ARXIV_RE = re.compile(
    r"(?:arxiv\s*[:/]\s*|arxiv\.org/(?:abs|pdf)/|\babs/)"
    r"((?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)(?:\s*\[[A-Za-z.\-]+\])?",
    re.IGNORECASE,
)
_HREF_RE = re.compile(r"\\href\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_URL_CMD_RE = re.compile(r"\\url\s*\{([^{}]*)\}")
_DOI_CMD_RE = re.compile(r"\\doi\s*\{([^{}]*)\}|\bdoi\s*:\s*(10\.[^\s,;{}]+)", re.IGNORECASE)


def _clean_url(url: str) -> str:
    url = _ESCAPE_RE.sub(lambda m: m.group(1), url.replace("\\_", "_"))
    return url.rstrip(".,;:)]'\"")


def _split_identifiers(body: str) -> tuple[str, dict]:
    """Pull the DOI, URL and arXiv ID out of ``body``; return the rest and what was found."""
    found: dict = {"doi": None, "url": None, "arxiv": None}

    def take_doi(candidate: str) -> None:
        m = _DOI_RE.search(_clean_url(candidate))
        if m and found["doi"] is None:
            found["doi"] = _clean_url(m.group(0))

    def href(m: re.Match) -> str:
        target = _clean_url(m.group(1))
        if "doi.org/" in target.lower():
            take_doi(target)
        elif found["url"] is None and not target.lower().startswith("mailto:"):
            found["url"] = target
        return m.group(2)  # the visible text of the link stays (it is usually a title)

    def url_cmd(m: re.Match) -> str:
        target = _clean_url(m.group(1))
        if "doi.org/" in target.lower():
            take_doi(target)
        elif (arx := _ARXIV_RE.search(target)) and found["arxiv"] is None:
            found["arxiv"] = arx.group(1)
        elif found["url"] is None:
            found["url"] = target
        return " "

    def doi_cmd(m: re.Match) -> str:
        take_doi(m.group(1) or m.group(2))
        return " "

    body = _HREF_RE.sub(href, body)
    body = _URL_CMD_RE.sub(url_cmd, body)
    body = _DOI_CMD_RE.sub(doi_cmd, body)

    def bare_url(m: re.Match) -> str:
        target = _clean_url(m.group(0))
        if "doi.org/" in target.lower():
            take_doi(target)
        elif (arx := _ARXIV_RE.search(target)) and found["arxiv"] is None:
            found["arxiv"] = arx.group(1)
        elif found["url"] is None:
            found["url"] = target
        return " "

    body = _URL_RE.sub(bare_url, body)
    if found["doi"] is None and (m := _DOI_RE.search(body)):
        take_doi(m.group(0))
        body = body.replace(m.group(0), " ")
    if (m := _ARXIV_RE.search(body)) and found["arxiv"] is None:
        found["arxiv"] = m.group(1)
    if found["arxiv"]:  # "arXiv preprint arXiv:2005.14165, 2020" -> "2020": the ID says it all
        body = _ARXIV_RE.sub(" ", body)
        body = re.sub(r"\b(?:CoRR|ar[Xx]iv)\b(?:\s+(?:preprint|e-?prints?))?[,\s]*", " ", body)
        body = re.sub(r"(?<![A-Z])\.\s*,\s*", ". ", body)  # not the comma after an initial "Y.,"
    return body, found


# --------------------------------------------------------------------------- authors

_PARTICLE = r"(?:van|von|der|den|de|del|della|di|da|dos|du|la|le|ten|ter|bin|al|el|op|y)"
_SURNAME = rf"(?:{_PARTICLE}\s+)*[A-Z][\w'’`\-]*(?:\s+[A-Z][\w'’`\-]*)?"
_INITIALS = r"(?:[A-Z][a-z]?\.(?:\s*-\s*[A-Z][a-z]?\.)?\s*)+"
_INITIALS_FIRST = re.compile(rf"^{_INITIALS}(?:{_PARTICLE}\s+)*{_SURNAME}$")
_FULL_NAME = re.compile(
    r"^[A-Z][\w'’`\-]+(?:\s+[A-Z]\.?)*\s+(?:"
    + _PARTICLE
    + r"\s+)*[A-Z][\w'’`\-]+(?:\s+[A-Z][\w'’`\-]+)?$"
)
_INITIALS_ONLY = re.compile(rf"^{_INITIALS}$|^[A-Z](?:\s?[A-Z]){{0,3}}$")
_SURNAME_ONLY = re.compile(rf"^{_SURNAME}$")
_ET_AL = re.compile(r"(?:,?\s*(?:and\s+)?(?:et\.?\s*al\.?|others))\s*\.?\s*$", re.IGNORECASE)
_TRAILING_YEAR_RE = re.compile(r"[,\s]*[(\[]\s*(?:19|20)\d{2}[a-z]?\s*[)\]]\s*$")
_AND = re.compile(r"\s*(?:,\s*)?\b(?:and|AND)\b\s*|\s*&\s*|\s*;\s*")


def _looks_like_name(token: str) -> bool:
    token = token.strip()
    return bool(
        token
        and len(token) <= 60
        and (_INITIALS_FIRST.match(token) or _FULL_NAME.match(token))
        and not re.search(r"\d", token)
    )


def parse_authors(text: str) -> list[str]:
    """``"A. Vaswani, N. Shazeer, and J. Uszkoreit"`` -> ``["A. Vaswani", ...]``.

    Also reads ``Vaswani, A., Shazeer, N.`` and ``Vaswani, Ashish and Shazeer, Noam``
    (returned as ``"A. Vaswani"``). ``et al.`` / ``others`` is dropped.
    """
    text = _tidy(text)
    text = _TRAILING_YEAR_RE.sub("", text)
    text = _ET_AL.sub("", text).strip(" ,;")
    if not text:
        return []
    chunks = [c.strip() for c in _AND.split(text) if c.strip()]
    # "Family, Given and Family, Given": every chunk holds exactly one comma.
    if len(chunks) > 1 and all(c.count(",") == 1 for c in chunks):
        names = [_given_family(*c.split(",")) for c in chunks]
    else:
        names = []
        for chunk in chunks:
            names.extend(_comma_names(chunk))
    return [n for n in names if n and len(n.split()) <= 6 and not re.search(r"\d", n)]


def _given_family(family: str, given: str) -> str:
    given = given.strip()
    if re.fullmatch(r"(?:[A-Z]\.?\s*){1,4}", given):  # "N" / "D P" / "D. P" -> "N." / "D. P."
        given = " ".join(f"{c}." for c in re.findall(r"[A-Z]", given))
    return f"{given} {family.strip()}".strip()


def _comma_names(chunk: str) -> list[str]:
    tokens = [t.strip() for t in chunk.split(",") if t.strip()]
    # "Vaswani, A., Shazeer, N.": a surname followed by initials, repeated.
    if len(tokens) >= 2 and all(
        _SURNAME_ONLY.match(tokens[i]) and _INITIALS_ONLY.match(tokens[i + 1])
        for i in range(0, len(tokens) - 1, 2)
    ):
        pairs = [(tokens[i], tokens[i + 1]) for i in range(0, len(tokens) - 1, 2)]
        names = [_given_family(f, g) for f, g in pairs]
        if len(tokens) % 2:
            names.append(tokens[-1])
        return names
    return tokens


def _take_authors(text: str) -> tuple[list[str], str]:
    """Longest prefix of a comma/``and`` separated text made of names; the rest is the title."""
    tokens = [t.strip() for t in re.split(r",\s+(?:and\s+|&\s+)?|\s+and\s+|\s+&\s+", text)]
    count = 0
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if _looks_like_name(tok) or (  # "Vaswani, A.": surname then initials
            _SURNAME_ONLY.match(tok) and _INITIALS_ONLY.match(nxt)
        ):
            count = i + 1
        elif _INITIALS_ONLY.match(tok) and i > 0 and _SURNAME_ONLY.match(tokens[i - 1]):
            count = i + 1
        else:
            break
    if not count:
        return [], text
    consumed, pos = 0, 0
    for tok in tokens[:count]:
        pos = text.index(tok, pos) + len(tok)
        consumed = pos
    return parse_authors(text[:consumed]), text[consumed:].lstrip(" ,.:;")


# --------------------------------------------------------------------------- fields

_YEAR_RE = re.compile(r"(?<![\d.])(?:19|20)\d{2}(?![\d])")
_PAREN_YEAR_RE = re.compile(r"[(\[]\s*((?:19|20)\d{2})[a-z]?\s*[)\]]")
_LABEL_YEAR_RE = re.compile(r"\(\s*((?:19|20)\d{2})[a-z]?\s*\)")
_PAGE_RANGE_RE = re.compile(r"\d{3,}\s*[\u2013\-]+\s*\d{3,}")
_QUOTED_RE = re.compile(r'"([^"]{6,}?)"')
_ABBREV = {
    "vs", "jr", "sr", "dr", "st", "proc", "vol", "no", "pp", "ed", "eds", "ph", "d",
    "conf", "trans", "int", "intl", "univ", "dept", "inc", "ltd", "etc", "fig", "ser", "rev",
    "lett", "phys", "math", "sci", "res", "comput", "j", "ann", "bull", "nat", "acad",
}  # fmt: skip


def find_year(text: str, label: str | None = None) -> int | None:
    """The publication year: the natbib label first, then ``(2017)``, then the last bare year."""
    if label and (m := _LABEL_YEAR_RE.search(label)):
        return int(m.group(1))
    text = _PAGE_RANGE_RE.sub(" ", _strip_markers(text))
    if m := _PAREN_YEAR_RE.search(text):
        return int(m.group(1))
    years = _YEAR_RE.findall(text)
    return int(years[-1]) if years else None


def _split_sentences(text: str) -> list[str]:
    """Split a reference at ``. `` followed by a capital, not after an initial or abbreviation."""
    parts, start = [], 0
    for m in re.finditer(r"([.?!])\s+(?=[\"(\x01]?[A-Z0-9\u00c0-\u024f])", text):
        before = text[start : m.start()]
        last = re.split(r"[\s(\x01\x02]", before)[-1] if before else ""
        if m.group(1) == "." and (
            re.fullmatch(r"[A-Z][a-z]?", last)  # an initial
            or last.lower().rstrip(".") in _ABBREV
            or re.fullmatch(r"(?:[A-Z]\.){1,3}[A-Z]?", last + ".")
        ):
            continue
        parts.append(text[start : m.start()].strip())
        start = m.end()
    parts.append(text[start:].strip())
    return [p for p in parts if p]


_VENUE_STOP_RE = re.compile(
    r",?\s*(?:\(?\b(?:19|20)\d{2}[a-z]?\)?\s*[,.:]?\s*$|vol\.?\s*\d|volume\s+\d|pp?\.\s*\d|"
    r"pages?\s+\d|no\.\s*\d|\d+\s*\(\d+\)|,\s*\d+\s*[,:(]|\s\d+\s*,\s*\d+\s*[-–—])",
    re.IGNORECASE,
)


def _venue(text: str) -> str | None:
    """Journal / proceedings name at the start of ``text``, volume, pages and year cut off."""
    text = _strip_markers(text).strip(" .,;:")
    text = re.sub(r"^(?:in|In|IN)\s*:?\s+", "", text)
    if m := _VENUE_STOP_RE.search(text):
        text = text[: m.start()]
    text = _tidy_venue(text)
    return text if len(text) >= 2 and re.search(r"[A-Za-z]{2}", text) else None


def _italic_spans(text: str) -> list[str]:
    return re.findall(f"{_IT_OPEN}(.*?){_IT_CLOSE}", text)


_INPROC_RE = re.compile(
    r"\b(?:proceedings?|proc\.|conference|conf\.|workshop|symposium|advances in neural|"
    r"neurips|nips|icml|iclr|cvpr|iccv|eccv|acl|emnlp|naacl|aaai|ijcai|kdd|sigir|www|"
    r"interspeech|icassp|miccai|colt|aistats|uai)\b",
    re.IGNORECASE,
)
_JOURNAL_RE = re.compile(
    r"\b(?:journal|j\.|transactions|trans\.|letters|lett\.|review|rev\.|annals|nature|science|"
    r"magazine|physica|phys\.|proc\.\s+ieee|bulletin|communications|comm\.)\b",
    re.IGNORECASE,
)
_PUBLISHER_RE = re.compile(
    r"\b(?:press|springer|wiley|elsevier|publishers?|publishing|o'reilly|mcgraw|addison|"
    r"cambridge|oxford|mit press|academic press)\b",
    re.IGNORECASE,
)


_NO_VENUE_TYPES = frozenset({"book", "phdthesis", "mastersthesis", "techreport"})


def guess_type(text: str, venue: str | None, arxiv: bool, italic_title: bool) -> str:
    if re.search(r"\bph\.?\s?d\.?\b.{0,20}(?:thesis|dissertation)|doctoral", text, re.IGNORECASE):
        return "phdthesis"
    if re.search(r"master'?s\s+thesis", text, re.IGNORECASE):
        return "mastersthesis"
    if re.search(r"tech(?:nical|\.)\s+rep(?:ort|\.)", text, re.IGNORECASE):
        return "techreport"
    if venue and re.search(r"\bproc(?:eedings|\.)\s+(?:of\s+the\s+)?ieee\b", venue, re.I):
        return "article"
    if venue and _INPROC_RE.search(venue):
        return "inproceedings"
    if venue and _JOURNAL_RE.search(venue):
        return "article"
    volume_pages = r"\d+\s*\(\d+\)\s*[:,]|\bvol(?:ume|\.)?\s*\d+|\d+\s*,\s*\d+\s*[-–—]\s*\d+"
    if venue and re.search(volume_pages, text, re.IGNORECASE):
        return "article"
    if italic_title or _PUBLISHER_RE.search(text):
        return "book" if not arxiv else "misc"
    if re.match(r"\s*in\b", text, re.IGNORECASE):
        return "inproceedings"
    return "article" if venue and not arxiv else "misc"


_BIBINFO_RE = re.compile(r"\\bibinfo\s*\{(title|journal|booktitle|year)\}\s*\{")


def _bibinfo_fields(body: str) -> dict[str, str]:
    """revtex / APS ``\\bibinfo{title}{...}``: the style says which part is which."""
    found: dict[str, str] = {}
    for m in _BIBINFO_RE.finditer(body):
        end = _balanced(body, m.end() - 1)
        raw_value = _plain(body[m.end() : end - 1])
        value = _tidy(raw_value) if m.group(1) in ("title", "year") else _tidy_venue(raw_value)
        if value:
            found.setdefault(m.group(1), value)
    return found


def _body_fields(label: str | None, body: str) -> dict:
    """Free text of one ``\\bibitem`` -> field values (everything optional)."""
    fields = _guess_fields(label, body)
    explicit = _bibinfo_fields(body)
    if explicit.get("title"):
        fields["title"] = explicit["title"]
    if explicit.get("journal") or explicit.get("booktitle"):
        fields["journal"] = explicit.get("journal") or explicit["booktitle"]
    if (y := explicit.get("year")) and re.fullmatch(r"(?:19|20)\d{2}", y):
        fields["year"] = int(y)
    if fields.get("title"):
        fields["title"] = _TRAILING_YEAR_RE.sub("", fields["title"]).strip(" .,;:") or None
    return fields


def _italic_title_lead(text: str) -> tuple[list[str], str, str] | None:
    """Authors, title and the rest when an italic span follows the names (AMS: ``A, \\emph{T}, V``).

    ``A. Doe, \\emph{Nature} 12 (2000)`` is the other reading (the italics are the journal), so a
    span followed by a volume or a year does not count.
    """
    start = text.find(_IT_OPEN)
    end = text.find(_IT_CLOSE, start)
    if start <= 0 or end < 0:
        return None
    prefix = _strip_markers(text[:start])
    title = _tidy(text[start + 1 : end])
    after = text[end + 1 :].lstrip(" ,.;:")
    if not _all_names(prefix) or len(title) < 4 or not after:
        return None
    if re.match(r"\d+(?!\w)|\((?:19|20)\d{2}|vol(?:ume|\.)?\b", _strip_markers(after), re.I):
        return None  # "12 (2000)" / "(1999)" / "vol. 3": the italics were the journal
    return parse_authors(prefix), title, after


def _guess_fields(label: str | None, body: str) -> dict:
    rest, ids = _split_identifiers(body)
    text = _plain(rest)
    plain = _strip_markers(text)
    authors: list[str] = []
    title: str | None = None
    venue_text = ""
    italic_title = False

    if _NEWBLOCK in text:  # BibTeX styles: authors \newblock title \newblock venue
        blocks = [b.strip() for b in text.split(_NEWBLOCK) if _tidy(b)]
        authors = parse_authors(blocks[0])
        if len(blocks) >= 2:
            title = _tidy(blocks[1])
            italic_title = len(blocks) >= 3 and blocks[1].startswith(_IT_OPEN)
            venue_text = " ".join(blocks[2:])
    elif m := _QUOTED_RE.search(plain):  # IEEE: authors, "Title," venue
        title = _tidy(m.group(1))
        authors = parse_authors(plain[: m.start()])
        venue_text = text[text.find('"', text.find(m.group(1)) + len(m.group(1))) + 1 :]
    else:
        sentences = _split_sentences(text)
        first = sentences[0] if sentences else ""
        # drop a stand-alone year sentence ("Authors. 2017. Title. Venue")
        sentences = [
            s for s in sentences if not re.fullmatch(r"[(\[]?(?:19|20)\d{2}[a-z]?[)\]]?", s)
        ]
        first = sentences[0] if sentences else ""
        colon = re.match(r"^(.{3,}?):\s+(.+)$", first)
        first_noyear = re.sub(
            r"[(\[]\s*(?:19|20)\d{2}[a-z]?\s*[)\]]\s*$", "", _strip_markers(first)
        )
        if lead := _italic_title_lead(text):  # AMS: Authors, \emph{Title}, Venue
            authors, title, venue_text = lead
            italic_title = True
        elif colon and _all_names(_ET_AL.sub("", colon.group(1)).strip(" ,;")):
            names = _ET_AL.sub("", colon.group(1)).strip(" ,;")
            authors, title = parse_authors(names), _tidy(colon.group(2))  # LNCS
            venue_text = " ".join(sentences[1:])
        elif len(sentences) >= 2 and _is_author_list(first_noyear):
            authors = parse_authors(first_noyear)
            title = _tidy(sentences[1])
            venue_text = " ".join(sentences[2:])
        else:  # Elsevier / unknown: authors, Title, venue (all in one "sentence")
            authors, remainder = _take_authors(_strip_markers(first))
            if authors and remainder:
                parts = re.split(r",\s+(?=(?:in|In)\s*:|[A-Z\x01])", remainder, maxsplit=1)
                title = _tidy(parts[0])
                venue_text = (parts[1] if len(parts) > 1 else "") + " ".join(sentences[1:])
            elif len(sentences) >= 2:
                title, venue_text = _tidy(sentences[0]), " ".join(sentences[1:])
            else:
                title = _tidy(first) or None

    italics = _italic_spans(venue_text) or _italic_spans(text)
    journal = None
    if italics and not italic_title:
        journal = _tidy_venue(italics[-1]) or None
    elif italics and italic_title:
        journal = None
    if journal is None and venue_text:
        journal = _venue(venue_text)
    if title and len(title) < 3:
        title = None
    if title and journal and title == journal:
        journal = None

    year = find_year(plain, label)
    if ids["arxiv"] and journal is None:
        journal = "arXiv preprint"
    entry_type = guess_type(plain, journal, bool(ids["arxiv"]), italic_title)
    if entry_type in _NO_VENUE_TYPES:
        journal = None  # a publisher / school is not a journal
    url = ids["url"] or (f"https://arxiv.org/abs/{ids['arxiv']}" if ids["arxiv"] else None)
    if journal == "arXiv preprint" and ids["arxiv"]:
        journal = f"arXiv preprint arXiv:{ids['arxiv']}"
    return {
        "entry_type": entry_type,
        "title": title or None,
        "authors": authors,
        "year": year,
        "doi": ids["doi"],
        "journal": journal,
        "url": url,
    }


def _all_names(text: str) -> bool:
    """True when ``text`` is nothing but a list of author names (LNCS: ``Family, A.: Title``)."""
    names, rest = _take_authors(text)
    return bool(names) and not rest.strip(" .,;")


def _is_author_list(text: str) -> bool:
    """True when ``text`` (the first sentence) consists of names only."""
    names = parse_authors(text)
    if not names:
        return False
    return (
        all(_looks_like_name(n) or re.fullmatch(r"[\w'’`\-. ]+", n) for n in names)
        and len(text) < 400
        and not re.search(r"\b(?:the|of|for|with|using|via|towards?)\b", text)
    )


# --------------------------------------------------------------------------- \bibitem

_BIBITEM_RE = re.compile(r"\\bibitem(?![A-Za-z@])")
# "\def\bibitem{x}", "\renewcommand{\bibitem}[1]{...}": a definition, not a reference
_DEFINITION_RE = re.compile(r"\\(?:def|let|(?:re|new|provide)command\*?)\s*\{?\s*$")
_END_BIB_RE = re.compile(r"\\end\s*\{(?:thebibliography|document)\}")
_MAX_BODY = 4000  # a reference longer than this is a parsing accident, not a reference


def _bibitem_head(text: str, pos: int) -> tuple[str | None, str, int] | None:
    """``(label, key, end)`` of the ``\\bibitem[label]{key}`` starting at ``pos``."""
    i = pos
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    label = None
    if i < len(text) and text[i] == "[":
        end = _balanced(text, i, "[", "]")
        label = text[i + 1 : end - 1]
        i = end
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
    if i >= len(text) or text[i] != "{":
        return None
    end = _balanced(text, i)
    key = re.sub(r"\s+", "", text[i + 1 : end - 1])
    return label, key, end


def parse_bibitems(text: str) -> list[BibEntry]:
    """Every ``\\bibitem`` of ``text`` (comments are ignored) as a ``BibEntry``."""
    code = strip_comments(text)
    starts = [
        m.end()
        for m in _BIBITEM_RE.finditer(code)
        if not _DEFINITION_RE.search(code[max(0, m.start() - 24) : m.start()])
    ]
    entries = []
    for n, pos in enumerate(starts):
        head = _bibitem_head(code, pos)
        if head is None:
            continue  # "\def\bibitem..." and similar
        label, key, body_start = head
        limit = starts[n + 1] - len("\\bibitem") if n + 1 < len(starts) else len(code)
        if m := _END_BIB_RE.search(code, body_start, limit):
            limit = m.start()
        body = code[body_start : min(limit, body_start + _MAX_BODY)]
        if not key:
            continue
        raw = re.sub(r"\s+", " ", body).strip()
        try:
            fields = _body_fields(label, body)
        except Exception:  # a malformed entry must not cost the whole bibliography
            fields = {}
        entries.append(BibEntry(citation_key=key, raw=raw, **fields))
    return entries


# --------------------------------------------------------------------------- .bib

_BIB_START_RE = re.compile(r"@\s*([A-Za-z]+)\s*([({])")
_SKIPPED_TYPES = frozenset({"comment", "preamble"})


def _bib_value(text: str, i: int, macros: dict[str, str]) -> tuple[str, int]:
    """Value of a field starting at ``text[i]``: ``{..}``, ``".."``, a number or a macro."""
    parts: list[str] = []
    n = len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        ch = text[i]
        if ch == "{":
            end = _balanced(text, i)
            parts.append(text[i + 1 : end - 1])
            i = end
        elif ch == '"':
            j, depth = i + 1, 0
            while j < n and not (text[j] == '"' and depth == 0):
                if text[j] == "\\":
                    j += 1
                elif text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            parts.append(text[i + 1 : j])
            i = j + 1
        else:
            m = re.match(r"[A-Za-z0-9_:\-.+/]+", text[i:])
            if not m:
                break
            word = m.group(0)
            parts.append(macros.get(word.lower(), word if word.isdigit() else ""))
            i += m.end()
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i < n and text[i] == "#":
            i += 1
            continue
        break
    return "".join(parts), i


def _bib_body_fields(body: str, macros: dict[str, str]) -> tuple[str, dict[str, str]]:
    comma = body.find(",")
    if comma < 0:
        return body.strip(), {}
    key, fields, i, n = body[:comma].strip(), {}, comma + 1, len(body)
    while i < n:
        m = re.compile(r"\s*,?\s*([A-Za-z][A-Za-z0-9_\-]*)\s*=\s*").match(body, i)
        if not m:
            break
        value, i = _bib_value(body, m.end(), macros)
        fields.setdefault(m.group(1).lower(), value)
    return key, fields


def _bib_text(value: str | None) -> str | None:
    if not value:
        return None
    return _tidy(_plain(value)) or None


def _bib_entry(
    entry_type: str, key: str, fields: dict[str, str], raw: str, source: str
) -> BibEntry:
    authors = []
    for part in re.split(r"\s+and\s+", fields.get("author") or fields.get("editor") or ""):
        name = _tidy(_plain(part))
        if not name or name.lower() in {"others", "et al", "et al."}:
            continue
        if "," in name and name.count(",") == 1:
            family, given = name.split(",")
            name = _given_family(family, given)
        authors.append(name)
    year = None
    for fld in ("year", "date"):
        if m := re.search(r"\b(?:1[89]|20)\d{2}\b", fields.get(fld, "")):
            year = int(m.group(0))
            break
    doi = fields.get("doi", "").strip()
    if doi:
        doi = _clean_url(re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I))
    url = _bib_text(fields.get("url")) and _clean_url(fields["url"].strip())
    eprint = fields.get("eprint", "").strip()
    if not eprint and (m := _ARXIV_RE.search(fields.get("journal", "") + fields.get("note", ""))):
        eprint = m.group(1)
    prefix = fields.get("archiveprefix", fields.get("eprinttype", "arXiv")).lower()
    if eprint and prefix == "arxiv" and not url:
        url = f"https://arxiv.org/abs/{eprint}"
    if not doi and url and (m := _DOI_RE.search(url)) and "doi.org" in url:
        doi = _clean_url(m.group(0))
    journal = _bib_text(
        fields.get("journal") or fields.get("journaltitle") or fields.get("booktitle")
    )
    return BibEntry(
        citation_key=key,
        entry_type=entry_type.lower(),
        title=_bib_text(fields.get("title")),
        authors=authors,
        year=year,
        doi=doi or None,
        journal=journal,
        url=url or None,
        raw=raw,
        source=source,
    )


def parse_bib(text: str, source: str = "bib") -> list[BibEntry]:
    """Entries of a ``.bib`` file, in file order (``@string`` macros are expanded)."""
    macros = {
        m.group(1).lower(): m.group(2)
        for m in re.finditer(
            r"@string\s*[({]\s*([A-Za-z0-9_\-]+)\s*=\s*[{\"]([^}\"]*)[}\"]", text, re.I
        )
    }
    entries, pos = [], 0
    while m := _BIB_START_RE.search(text, pos):
        etype, opener = m.group(1).lower(), m.group(2)
        closer = "}" if opener == "{" else ")"
        end = _balanced(text, m.end() - 1, opener, closer)
        pos = end
        if etype in _SKIPPED_TYPES or etype == "string":
            continue
        body = text[m.end() : end - 1]
        try:
            key, fields = _bib_body_fields(body, macros)
            if key:
                raw = re.sub(r"\s+", " ", text[m.start() : end]).strip()
                entries.append(_bib_entry(etype, key, fields, raw, source))
        except Exception:
            continue
    return entries


# --------------------------------------------------------------------------- one version

CITE_RE = re.compile(
    r"\\(?!citestyle|citeindex)[A-Za-z]*cite[A-Za-z]*\*?(?:\s*\[[^\]]*\]){0,2}\s*\{([^{}]*)\}"
)
_BIBLIOGRAPHY_RE = re.compile(
    r"\\(?:bibliography|addbibresource|addglobalbib|addsectionbib)\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}"
)
_FILECONTENTS_RE = re.compile(
    r"\\begin\s*\{filecontents\*?\}\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}(.*?)\\end\s*\{filecontents\*?\}",
    re.DOTALL,
)


def cite_keys(text: str) -> set[str]:
    """Keys cited in ``text`` (``\\cite``, ``\\citep``, ``\\parencite``... and ``\\nocite``)."""
    keys: set[str] = set()
    for m in CITE_RE.finditer(strip_comments(text)):
        keys.update(k.strip() for k in m.group(1).split(",") if k.strip())
    return keys


def extract_references(tex: TexVersion, files: list[str]) -> VersionRefs:
    """References of one gathered version: ``files`` is ``GatherResult.files`` (root first)."""
    refs = VersionRefs()
    code = "\n".join(tex.tex[f].code for f in files)
    for rel in files:
        found = parse_bibitems(tex.tex[rel].code)
        refs.n_bibitems += len(found)
        refs.entries.extend(found)

    bib_names = [
        name.strip()
        for m in _BIBLIOGRAPHY_RE.finditer(code)
        for name in m.group(1).split(",")
        if name.strip()
    ]
    texts: list[tuple[str, str, str]] = []  # (file name, text, source)
    for rel in files:
        for m in _FILECONTENTS_RE.finditer(tex.tex[rel].text):
            if m.group(1).lower().endswith(".bib"):
                texts.append((m.group(1), m.group(2), "filecontents"))
    on_disk = {p.relative_to(tex.dir).as_posix().lower(): p for p in tex.dir.rglob("*.bib")}
    for name in dict.fromkeys(bib_names):
        wanted = name if name.lower().endswith(".bib") else f"{name}.bib"
        path = on_disk.get(wanted.lower().lstrip("./"))
        if path is None:  # \bibliography{refs} written from a sub-folder: match the file name
            path = next(
                (p for k, p in on_disk.items() if k.rsplit("/", 1)[-1] == wanted.lower()), None
            )
        if path is None:
            if not any(t[0].lower() == wanted.lower() for t in texts):
                refs.missing_bib.append(name)
            continue
        refs.bib_files.append(path.relative_to(tex.dir).as_posix())
        texts.append((wanted, path.read_bytes().decode("utf-8", errors="replace"), "bib"))

    if texts:
        cited = cite_keys(code)
        everything = "*" in cited
        seen: set[str] = {e.citation_key for e in refs.entries}
        for _, text, source in texts:
            for entry in parse_bib(text, source):
                if entry.citation_key in seen and source != "bibitem":
                    continue  # BibTeX takes the first definition of a key
                if everything or entry.citation_key in cited:
                    refs.entries.append(entry)
                    refs.n_bib_cited += 1
                    seen.add(entry.citation_key)
                else:
                    refs.n_bib_unused += 1
    return refs


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the references of one version folder.")
    parser.add_argument("version_dir", type=Path, help="a vN folder of the corpus")
    parser.add_argument("--json", action="store_true", help="one JSON object per entry")
    args = parser.parse_args(argv)

    tex = TexVersion(args.version_dir, paper_title(args.version_dir))
    res = gather(args.version_dir)
    if res.root is None:
        print("no root .tex file: nothing to extract", file=sys.stderr)
        return 1
    refs = extract_references(tex, res.files)
    for entry in refs.entries:
        row = asdict(entry)
        if args.json:
            print(json.dumps(row, ensure_ascii=False))
        else:
            print(f"{entry.citation_key}  [{entry.entry_type}] {entry.year}  {entry.title!r}")
            print(f"    {entry.authors}  | {entry.journal}  | doi={entry.doi} url={entry.url}")
    print(
        f"{len(refs.entries)} entries: {refs.n_bibitems} bibitem, {refs.n_bib_cited} from "
        f"{refs.bib_files}, {refs.n_bib_unused} uncited; missing .bib: {refs.missing_bib}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
