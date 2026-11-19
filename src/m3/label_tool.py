# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Manual labeling tool: shows one BibTeX entry next to the paper's candidates, a person decides.

    python -m src.m3.label_tool --m2-dir M2_OUT --corpus-dir data/corpus \
        --labels-dir labels --arxiv-id 2606.25801

Works in a terminal and in a Colab cell (it only uses ``input()``). The tool **never
pre-fills an answer**: candidates are only *ordered* by title similarity so the right one is
easy to find; the person reads and types the choice. Every answer is saved at once to
``<labels-dir>/manual/<folder>.csv`` (format in ``labels.py``), so the session can stop and
resume at any entry. Entries already answered are skipped; ``--redo`` starts over.

Keys at the prompt:
    <number>  this candidate is the correct reference (yes in its column, no elsewhere)
    0         no candidate is correct (whole row no)
    a         show all candidates (default shows the first --show)
    /word     show only candidates whose title contains "word"
    b         back to the previous entry
    q         save and quit
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.m3.labels import (
    author_overlap,
    label_path,
    load_bibtex,
    load_candidates,
    norm_text,
    read_matrix,
    ref_year,
    title_sim,
    write_matrix,
)


def _fmt_entry(e: dict) -> str:
    authors = "; ".join(e.get("authors") or [])
    lines = [
        f"  key    : {e['citation_key']}",
        f"  title  : {e.get('title') or '-'}",
        f"  authors: {authors or '-'}",
        f"  year   : {e.get('year') or '-'}   journal: {e.get('journal') or '-'}",
    ]
    if e.get("doi") or e.get("url"):
        lines.append(f"  doi/url: {e.get('doi') or ''} {e.get('url') or ''}")
    return "\n".join(lines)


def _fmt_cand(i: int, c: dict) -> str:
    authors = ", ".join((c["ref_authors"] or [])[:4]) + (" …" if len(c["ref_authors"]) > 4 else "")
    return (
        f"  [{i:>3}] {c['ref_arxiv_id']:<16} {ref_year(c) or '----'}  {c['ref_title'] or '-'}\n"
        f"        {authors}"
    )


def order_candidates(entry: dict, candidates: list[dict]) -> list[dict]:
    """Display order only: most similar title first, then authors (no answer is chosen)."""
    return sorted(
        candidates,
        key=lambda c: (
            -title_sim(entry.get("title"), c["ref_title"]),
            -author_overlap(entry.get("authors"), c["ref_authors"]),
        ),
    )


def label_paper(entries, candidates, path: Path, show: int = 15, redo: bool = False, ask=input):
    """Interactive loop; returns the answers dict (also saved after every answer)."""
    cand_ids = [c["ref_arxiv_id"] for c in candidates]
    answers: dict[str, str | None] = {}
    if path.exists() and not redo:
        old_ids, answers = read_matrix(path)
        if old_ids != cand_ids:
            raise SystemExit(f"{path} was made with other candidates; use --redo to restart")
    keys = [e["citation_key"] for e in entries]
    i = next((k for k, key in enumerate(keys) if key not in answers), len(keys))
    while i < len(entries):
        entry = entries[i]
        ordered = order_candidates(entry, candidates)
        view, limit = ordered, show
        while True:
            print(f"\n=== entry {i + 1}/{len(entries)}  ({len(answers)} answered) ===")
            print(_fmt_entry(entry))
            print(f"--- candidates ({len(view)} of {len(candidates)}) ---")
            for n, c in enumerate(view[:limit], start=1):
                print(_fmt_cand(n, c))
            cmd = ask("choice [number / 0 none / a all / /word / b back / q quit]: ").strip()
            if cmd == "q":
                return answers
            if cmd == "b":
                i = max(i - 1, 0)
                answers.pop(keys[i], None)
                write_matrix(path, cand_ids, {k: answers[k] for k in keys if k in answers})
                break
            if cmd == "a":
                view, limit = ordered, len(ordered)
                continue
            if cmd.startswith("/"):
                word = norm_text(cmd[1:])
                view, limit = (
                    [c for c in ordered if word in norm_text(c["ref_title"])],
                    len(ordered),
                )
                continue
            if cmd.isdigit() and 0 <= int(cmd) <= min(limit, len(view)):
                answers[entry["citation_key"]] = (
                    None if cmd == "0" else view[int(cmd) - 1]["ref_arxiv_id"]
                )
                write_matrix(path, cand_ids, {k: answers[k] for k in keys if k in answers})
                i += 1
                break
            print("  ?? not understood")
    print(f"\nDone: {len(answers)} entries saved to {path}")
    return answers


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--m2-dir", type=Path, required=True, help="folder holding shard-*/bibtex.parquet"
    )
    p.add_argument("--corpus-dir", type=Path, required=True, help="M1 corpus (references.json)")
    p.add_argument("--labels-dir", type=Path, default=Path("labels"))
    p.add_argument("--arxiv-id", required=True)
    p.add_argument("--show", type=int, default=15, help="candidates shown before 'a'")
    p.add_argument("--redo", action="store_true", help="discard existing answers of this paper")
    a = p.parse_args(argv)

    entries = sorted(load_bibtex(a.m2_dir, [a.arxiv_id]), key=lambda e: e["citation_key"])
    candidates = load_candidates(a.corpus_dir, a.arxiv_id)
    if not entries or not candidates:
        raise SystemExit(
            f"{a.arxiv_id}: {len(entries)} BibTeX entries, {len(candidates)} candidates"
        )
    label_paper(entries, candidates, label_path(a.labels_dir, "manual", a.arxiv_id), a.show, a.redo)


if __name__ == "__main__":
    main()
