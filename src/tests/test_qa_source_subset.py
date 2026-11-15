# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Structural QA on one of the crawl runs only: a subset audit that says it is a subset."""

import json

import pytest

from src.parser.run import Options, run
from src.qa.audit_sample import draw
from src.qa.audit_structure import audit_resumable, present_papers
from src.tests.test_m2_multi_run import keep_logging_as_it_was, two_runs  # noqa: F401


@pytest.fixture
def parsed(two_runs, tmp_path):  # noqa: F811
    a, b = two_runs  # run a holds 2606.00002 and 2606.00004, run b holds 2606.00001 and 00003
    out, work = tmp_path / "out", tmp_path / "work"
    run([a, b], out, work, options=Options(), progress=False, shard_papers=1)
    return a, b, out, work


def test_present_papers_lists_the_folders_of_the_given_runs(parsed):
    a, b, _, _ = parsed
    assert present_papers(a) == {"2606-00002", "2606-00004"}
    assert present_papers([a, b]) == {"2606-00001", "2606-00002", "2606-00003", "2606-00004"}


def test_a_missing_source_stops_a_full_audit_but_not_a_subset_audit(parsed, tmp_path):
    a, _, out, _ = parsed
    with pytest.raises(FileNotFoundError):
        audit_resumable(a, out, tmp_path / "full", {"sha": "one"})
    summary = audit_resumable(
        a, out, tmp_path / "subset", {"sha": "one"}, allow_missing_sources=True
    )
    assert summary["versions"] == 2  # 2606.00002 v2 and 2606.00004 v1 (v1 of 00002 is empty)
    assert summary["scope"]["kind"] == "subset"
    assert summary["scope"]["papers_with_source"] == 2
    assert summary["scope"]["source_runs"]  # which runs, so the evidence cannot be read as full
    assert all(rate == 1.0 for key, rate in summary["agreement_rates"].items() if key != "formulas")


def test_the_journal_check_counts_only_the_papers_that_have_a_source(parsed, tmp_path):
    a, _, out, work = parsed
    summary = audit_resumable(
        a,
        out,
        tmp_path / "subset",
        {"sha": "one"},
        journal=work / "shards.jsonl",
        allow_missing_sources=True,
    )
    assert summary["versions"] == 2
    assert summary["scope"]["parsed_versions_skipped_without_source"] == 2  # both of 2606.00001


def test_a_subset_audit_cannot_be_resumed_as_a_full_one_or_as_another_subset(parsed, tmp_path):
    a, b, out, _ = parsed
    qa = tmp_path / "qa"
    audit_resumable(a, out, qa, {"sha": "one"}, allow_missing_sources=True)
    with pytest.raises(ValueError, match="identity changed"):
        audit_resumable([a, b], out, qa, {"sha": "one"})  # a full audit over the same folder
    with pytest.raises(ValueError, match="identity changed"):
        audit_resumable(b, out, qa, {"sha": "one"}, allow_missing_sources=True)


def test_the_sample_is_drawn_only_from_papers_that_have_a_source(parsed, tmp_path):
    a, _, out, work = parsed
    draw(out, work, tmp_path / "audit", 30, 1, [a], present=present_papers(a))
    names = sorted(p.stem for p in (tmp_path / "audit").glob("*.md"))
    assert names == ["2606-00002", "2606-00004"]
    assert json.loads(json.dumps(names))  # plain list, nothing else drawn
