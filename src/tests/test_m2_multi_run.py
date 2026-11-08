# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""The runner reads the runs of a distributed crawl as one corpus."""

import json
import logging

import pytest

from src import config
from src.parser.run import (
    DuplicatePaperError,
    IncompleteCorpusError,
    Options,
    assigned_folders,
    check_assigned,
    crawl_index,
    list_papers,
    main,
    run,
)
from src.qa.check_tables import check
from src.tests.test_parser_run import DOC, make_paper


@pytest.fixture(autouse=True)
def keep_logging_as_it_was():
    """``main`` adds a file handler and sets the root level: do not leak that to other tests."""
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)
    yield
    for handler in set(root.handlers) - set(handlers):
        handler.close()
    root.handlers, root.level = handlers, level


@pytest.fixture
def two_runs(tmp_path):
    a, b = tmp_path / "run-a" / "data" / "corpus", tmp_path / "run-b" / "data" / "corpus"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    make_paper(a, "2606.00002", [{"main.tex": DOC % "Beta one."}])
    make_paper(a, "2606.00004", [{"main.tex": DOC % "Delta one."}])
    make_paper(
        b, "2606.00001", [{"main.tex": DOC % "Alpha one."}, {"main.tex": DOC % "Alpha two."}]
    )
    make_paper(b, "2606.00003", [{}])
    return a, b


def journal(root, statuses):
    work = root.parent.parent / "work"
    work.mkdir(parents=True, exist_ok=True)
    with open(work / "versions.jsonl", "w", encoding="utf-8") as fh:
        for (arxiv_id, version), status in statuses.items():
            row = {"arxiv_id": arxiv_id, "version": version, "status": status, "kind": "tar.gz"}
            fh.write(json.dumps(row) + "\n")
    return work


def test_the_papers_of_all_runs_are_listed_in_folder_order(two_runs):
    a, b = two_runs
    names = [p.name for p in list_papers([a, b])]
    assert names == ["2606-00001", "2606-00002", "2606-00003", "2606-00004"]
    assert [p.name for p in list_papers([b, a])] == names  # the order of the roots is irrelevant
    assert [p.name for p in list_papers(a)] == ["2606-00002", "2606-00004"]  # one run, as before


def test_a_paper_in_two_runs_is_an_error(two_runs, tmp_path):
    a, b = two_runs
    make_paper(b, "2606.00002", [{"main.tex": DOC % "again"}])
    with pytest.raises(DuplicatePaperError, match="2606-00002"):
        list_papers([a, b])
    code = main(
        ["--data-root", str(a), "--data-root", str(b), "--out-dir", str(tmp_path / "o"),
         "--work-dir", str(tmp_path / "w"), "--no-progress"]
    )  # fmt: skip
    assert code == 5


def test_the_crawl_journals_of_the_runs_are_merged(two_runs):
    a, b = two_runs
    wa = journal(a, {("2606.00002", 1): "ok", ("2606.00004", 1): "ok"})
    wb = journal(b, {("2606.00001", 1): "ok", ("2606.00001", 2): "ok", ("2606.00003", 1): "no_tex"})
    index = crawl_index([wa, wb])
    assert set(index) == {"2606.00001", "2606.00002", "2606.00003", "2606.00004"}
    assert index["2606.00003"][1]["status"] == "no_tex" and index["2606.00001"][2]["status"] == "ok"
    assert crawl_index(None) == {}


def test_one_run_over_two_roots_gives_valid_tables_for_every_paper(two_runs, tmp_path):
    a, b = two_runs
    out = tmp_path / "out"
    work_a = journal(a, {("2606.00002", 1): "ok"})
    work_b = journal(b, {("2606.00003", 1): "no_tex"})
    summary = run(
        [a, b], out, tmp_path / "work", options=Options(), progress=False,
        crawl_work_dir=[work_a, work_b],
    )  # fmt: skip
    assert summary["papers_committed_total"] == 4 and summary["papers_failed_this_run"] == 0
    assert len(summary["data_roots"]) == 2
    report = check(out)
    assert report["ok"], report["problems"]
    assert report["papers"] == 4 and report["versions"] == 5


def test_the_audits_find_each_paper_in_whichever_run_holds_it(two_runs, tmp_path):
    from src.qa.audit_sample import draw
    from src.qa.audit_structure import audit

    a, b = two_runs
    out, work = tmp_path / "out", tmp_path / "work"
    run([a, b], out, work, options=Options(), progress=False)
    rows = audit([a, b], out)
    assert {r["arxiv_id"] for r in rows} == {"2606.00001", "2606.00002", "2606.00004"}
    assert all(r["headings_agree"] == 1 for r in rows)
    draw(out, work, tmp_path / "audit", 3, 1, [a, b])
    text = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "audit").glob("*.md"))
    assert str(a) in text and str(b) in text  # the source path points into the right run


def test_expect_assigned_stops_unless_the_corpus_is_exactly_the_assigned_ids(
    two_runs, tmp_path, monkeypatch
):
    a, b = two_runs
    monkeypatch.setattr(config, "RANGES", {"x": ("2606.00001", "2606.00005")})
    monkeypatch.setattr(config, "MONTH_END", {})
    assert len(assigned_folders()) == 5
    report = check_assigned(list_papers([a, b]))
    assert report["missing"] == ["2606-00005"] and report["extra"] == []
    work = tmp_path / "work"
    with pytest.raises(IncompleteCorpusError, match="1 missing"):
        run([a, b], tmp_path / "out", work, options=Options(), progress=False, expect_assigned=True)
    assert json.loads((work / "assigned_check.json").read_text())["missing"] == ["2606-00005"]
    assert not list((tmp_path / "out").glob("shard-*"))  # nothing was parsed

    make_paper(b, "2606.00005", [{"main.tex": DOC % "Epsilon."}])
    summary = run(
        [a, b], tmp_path / "out2", tmp_path / "work2", options=Options(), progress=False,
        expect_assigned=True,
    )  # fmt: skip
    assert summary["assigned_check"] == {"expected": 5, "found": 5}


def test_an_extra_paper_that_is_not_assigned_also_stops_the_run(two_runs, tmp_path, monkeypatch):
    a, b = two_runs
    monkeypatch.setattr(config, "RANGES", {"x": ("2606.00001", "2606.00003")})
    monkeypatch.setattr(config, "MONTH_END", {})
    code = main(
        ["--data-root", str(a), "--data-root", str(b), "--out-dir", str(tmp_path / "o"),
         "--work-dir", str(tmp_path / "w"), "--expect-assigned", "--no-progress"]
    )  # fmt: skip
    assert code == 5
