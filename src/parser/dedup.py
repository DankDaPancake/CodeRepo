# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
r"""Deduplication across the versions of one paper (M2 statement: "Deduplication").

``dedup(arxiv_id, versions)`` turns the trees and the references of every version into the rows
of the three tables.

**References.** The same reference can be written differently in each version (``vaswani2017``
in v1, ``vit_transformer`` in v2) or twice in one version. Entries are matched by DOI, arXiv ID or
normalised title; the matched entries become one: the key used in most versions is kept, the
others are renamed in every ``\cite{...}`` of the text, and the fields are *united* (a field one
version lacks is filled from another; nothing is thrown away). Two different references that
share a key (``ref1`` meaning two papers in two versions) get distinct keys instead of being merged.

**Content.** An element whose cleaned text is equal shares one row of ``elements`` and one ID
(``2310-12345#s7``), whatever version or place it comes from; ``hierarchy`` then has one row per
version and parent. Because the references are renamed *before* the text is compared, sentences
that differ only by the key of a citation are equal too. Leaves (sentences, formulas, figures)
are matched by ``(kind, content)``. A branch (section, list, item) is matched by
``(kind, title, parent, rank among equal siblings)``, so that an element ID has exactly one
parent and the tree can be rebuilt from ``hierarchy``.

IDs: ``<paper>#<letter><n>`` with ``s`` sentence, ``e`` equation, ``f`` figure, ``h`` heading,
``l`` list, ``i`` item, and ``#root<version>`` for the document node of each version (its parent is
the paper key). A version without TeX has only that root, so it still counts in ``hierarchy``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from src.parser.bibitem import BibEntry
from src.parser.model import LEAF_KINDS, Node, Rows, VersionParse, empty_rows
from src.utils.ids import to_folder_name

_PREFIX = {
    "sentence": "s",
    "equation": "e",
    "figure": "f",
    "itemize": "l",
    "item": "i",
}  # every other kind is a heading: "h"

_CITE = re.compile(r"(\\[A-Za-z]*cite[A-Za-z]*\*?(?:\s*\[[^\]]*\]){0,2}\s*\{)([^{}]*)(\})")
_ARXIV_ID = re.compile(
    r"(?:arxiv[:.\s/]*(?:abs/|pdf/)?)(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})", re.I
)
_NON_ALNUM = re.compile(r"[\W_]+", re.UNICODE)


# --------------------------------------------------------------------------- references


def _norm(text: str | None) -> str:
    return _NON_ALNUM.sub("", (text or "").lower())


def _surname(entry: BibEntry) -> str:
    if not entry.authors:
        return ""
    return _norm(entry.authors[0].split()[-1]) if entry.authors[0].split() else ""


def signatures(entry: BibEntry) -> list[tuple]:
    """Keys under which two entries are the same reference (any one shared key is enough)."""
    sigs: list[tuple] = []
    if entry.doi:
        sigs.append(("doi", re.sub(r"^https?://(?:dx\.)?doi\.org/", "", entry.doi.lower()).strip()))
    for source in (entry.url, entry.journal, entry.raw):
        m = _ARXIV_ID.search(source or "")
        if m:
            sigs.append(("arxiv", m.group(1).lower()))
            break
    title = _norm(entry.title)
    if len(title) >= 20:
        sigs.append(("title", title))
    elif title:
        sigs.append(("short", title, _surname(entry), entry.year))
    if not sigs and entry.raw:
        sigs.append(("raw", _norm(entry.raw)[:160]))
    return sigs


class _Groups:
    """Union-find over (version, key) entries that share a signature."""

    def __init__(self) -> None:
        self.parent: dict[tuple, tuple] = {}

    def find(self, item: tuple) -> tuple:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: tuple, b: tuple) -> None:
        self.parent[self.find(a)] = self.find(b)


def _merge(entries: list[BibEntry], key: str) -> BibEntry:
    """Unite the fields of entries that are one reference; the later version wins a conflict."""
    ordered = list(reversed(entries))  # latest version first
    merged = BibEntry(citation_key=key)
    typed = [e.entry_type for e in ordered if e.entry_type and e.entry_type != "misc"]
    merged.entry_type = Counter(typed).most_common(1)[0][0] if typed else "misc"
    for name in ("title", "journal"):  # the fullest spelling
        values = [getattr(e, name) for e in ordered if getattr(e, name)]
        setattr(merged, name, max(values, key=len) if values else None)
    for name in ("doi", "url"):  # the latest non-empty value
        values = [getattr(e, name) for e in ordered if getattr(e, name)]
        setattr(merged, name, values[0] if values else None)
    merged.authors = max((e.authors for e in ordered), key=len, default=[])
    years = [e.year for e in ordered if e.year]
    merged.year = years[0] if years else None
    merged.raw = ordered[0].raw
    merged.source = ordered[0].source
    return merged


def merge_references(
    versions: list[VersionParse],
) -> tuple[list[BibEntry], dict[int, dict[str, str]]]:
    """The united entries of the paper and, per version, ``{old key: key to use}``."""
    groups = _Groups()
    owner: dict[tuple, tuple] = {}  # signature -> first (version, key) that had it
    entries: dict[tuple, BibEntry] = {}
    for v in versions:
        for entry in v.bib:
            item = (v.version, entry.citation_key)
            entries.setdefault(item, entry)
            groups.find(item)
            for sig in signatures(entry):
                if sig in owner:
                    groups.union(item, owner[sig])
                else:
                    owner[sig] = item
    members: dict[tuple, list[tuple]] = defaultdict(list)
    for item in entries:
        members[groups.find(item)].append(item)

    taken: set[str] = set()
    united: list[BibEntry] = []
    renames: dict[int, dict[str, str]] = defaultdict(dict)
    for items in sorted(members.values(), key=lambda g: min(g)):
        items.sort()
        used = Counter(old for _, old in items)  # versions that use each key
        first = {}
        for ver, old in items:
            first.setdefault(old, ver)
        key = max(used, key=lambda k: (used[k], -first[k]))  # most used, then earliest
        final, n = key, 1
        while final in taken:  # same key, another reference: keep both, distinct keys
            n += 1
            final = f"{key}_{n}"
        taken.add(final)
        united.append(_merge([entries[i] for i in items], final))
        for ver, old in items:
            renames[ver][old] = final
    return united, renames


def rename_citations(text: str, mapping: dict[str, str]) -> str:
    r"""``\cite{a, b}`` with the keys of ``mapping`` replaced (a key listed twice is kept once)."""
    if not mapping or "cite" not in text:
        return text

    def swap(m: re.Match) -> str:
        keys = [k.strip() for k in m.group(2).split(",") if k.strip()]
        out = list(dict.fromkeys(mapping.get(k, k) for k in keys))
        return m.group(1) + ",".join(out) + m.group(3)

    return _CITE.sub(swap, text)


# --------------------------------------------------------------------------- elements


class _Registry:
    """Gives equal elements one ID and records each (version, element, parent) edge once."""

    def __init__(self, arxiv_id: str, key: str, rows: Rows) -> None:
        self.arxiv_id, self.key, self.rows = arxiv_id, key, rows
        self.ids: dict[tuple, str] = {}
        self.counters: Counter[str] = Counter()
        self.edges: set[tuple[int, str, str]] = set()

    def element(self, lookup: tuple, kind: str, content: str) -> str:
        found = self.ids.get(lookup)
        if found is not None:
            return found
        prefix = _PREFIX.get(kind, "h")
        self.counters[prefix] += 1
        element_id = f"{self.key}#{prefix}{self.counters[prefix]}"
        self.ids[lookup] = element_id
        self.rows["elements"].append(
            {"element_id": element_id, "arxiv_id": self.arxiv_id, "kind": kind, "content": content}
        )
        return element_id

    def edge(self, version: int, element_id: str, parent_id: str) -> None:
        if (version, element_id, parent_id) not in self.edges:
            self.edges.add((version, element_id, parent_id))
            self.rows["hierarchy"].append(
                {
                    "arxiv_id": self.arxiv_id,
                    "version": version,
                    "element_id": element_id,
                    "parent_id": parent_id,
                }
            )


def _add_children(
    reg: _Registry,
    version: int,
    node: Node,
    parent_id: str,
    renames: dict[str, str],
    parent_key: str = "",
) -> None:
    """``parent_key`` names the parent for matching: the document root of every version is the
    same place (""), any other branch is the element it was matched to."""
    seen: Counter[tuple[str, str]] = Counter()
    for child in node.children:
        content = rename_citations(child.content, renames)
        if child.kind in LEAF_KINDS:
            lookup = (child.kind, content)
        else:
            seen[(child.kind, content)] += 1
            lookup = (child.kind, content, parent_key, seen[(child.kind, content)])
        element_id = reg.element(lookup, child.kind, content)
        reg.edge(version, element_id, parent_id)
        if child.kind not in LEAF_KINDS:
            _add_children(reg, version, child, element_id, renames, element_id)


def dedup(arxiv_id: str, versions: list[VersionParse]) -> Rows:
    """The rows of ``elements``, ``hierarchy`` and ``bibtex`` of one paper (every version)."""
    rows = empty_rows()
    key = to_folder_name(arxiv_id)
    reg = _Registry(arxiv_id, key, rows)
    entries, renames = merge_references(versions)
    for v in sorted(versions, key=lambda x: x.version):
        root = f"{key}#root{v.version}"
        rows["elements"].append(
            {"element_id": root, "arxiv_id": arxiv_id, "kind": "document", "content": ""}
        )
        reg.edge(v.version, root, key)
        if v.tree is not None:
            _add_children(reg, v.version, v.tree, root, renames.get(v.version, {}))
    rows["bibtex"] = [e.to_row(arxiv_id) for e in entries]
    return rows
