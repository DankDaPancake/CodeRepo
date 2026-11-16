import json

import pyarrow.parquet as pq
import pytest

from src.parser.run import Options, run
from src.qa.check_tables_bounded import check_run
from src.qa.filter_empty_roots import filter_output
from src.tests.test_m2_pipeline import corpus  # noqa: F401


def test_filter_removes_only_empty_roots_and_preserves_original(corpus, tmp_path):  # noqa: F811
    out, work = tmp_path / "original", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    journal = work / "shards.jsonl"
    source = {p: p.read_bytes() for p in out.rglob("*.parquet")}
    target = tmp_path / "filtered"
    report = filter_output(out, journal, target)
    assert report["removed_roots"] > 0
    assert all(p.read_bytes() == contents for p, contents in source.items())
    assert check_run(target, journal, empty_without_root=True)["ok"]
    assert not check_run(target, journal)["ok"]
    assert report["removed_roots"] == sum(
        v["status"] == "empty"
        for s in map(json.loads, journal.read_text().splitlines())
        for p in s["papers"]
        for v in p["versions"]
    )


def test_filter_refuses_overwrite(corpus, tmp_path):  # noqa: F811
    out, work = tmp_path / "original", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    with pytest.raises(ValueError):
        filter_output(out, work / "shards.jsonl", out)


def test_filter_rejects_empty_version_with_content(corpus, tmp_path):  # noqa: F811
    out, work = tmp_path / "original", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    journal = work / "shards.jsonl"
    entries = [json.loads(line) for line in journal.read_text().splitlines()]
    for shard in entries:
        for paper in shard["papers"]:
            for version in paper["versions"]:
                if version["status"] == "parsed":
                    version["status"] = "empty"
                    journal.write_text("".join(json.dumps(x) + "\n" for x in entries))
                    with pytest.raises(ValueError, match="Unexpected empty version edges"):
                        filter_output(out, journal, tmp_path / "derived")
                    return
    pytest.fail("No parsed version in fixture")


def test_filter_keeps_all_nonempty_rows_and_bibtex(corpus, tmp_path):  # noqa: F811
    out, work = tmp_path / "original", tmp_path / "work"
    run(corpus, out, work, options=Options(), progress=False, shard_papers=1)
    journal = work / "shards.jsonl"
    target = tmp_path / "filtered"
    filter_output(out, journal, target)
    for shard in out.iterdir():
        if not shard.name.startswith("shard-"):
            continue
        assert (shard / "bibtex.parquet").read_bytes() == (
            target / shard.name / "bibtex.parquet"
        ).read_bytes()
        before = pq.read_table(shard / "elements.parquet").to_pylist()
        after = pq.read_table(target / shard.name / "elements.parquet").to_pylist()
        assert all(row in before for row in after)
        assert all(row["kind"] == "document" for row in before if row not in after)


def test_notebook_valid_and_disabled_by_default():
    import nbformat

    notebook = nbformat.read("src/notebooks/arxiv_nhom1_m2_filter_empty.ipynb", as_version=4)
    nbformat.validate(notebook)
    code = "\n".join(cell.source for cell in notebook.cells if cell.cell_type == "code")
    assert "RUN_FILTER = False" in code
    assert "empty_without_root=True" in code
    for cell in notebook.cells:
        if cell.cell_type == "code":
            compile(cell.source, "notebook", "exec")
