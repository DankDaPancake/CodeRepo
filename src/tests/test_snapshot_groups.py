import json
import ast
from dataclasses import replace

import pytest

from src.benchmark.runner import BenchmarkConfig, plan_chunks


def test_verified_group_snapshot_selects_ids_and_rejects_other_group(tmp_path, monkeypatch):
    import hashlib
    from src.benchmark import runner
    snapshot = tmp_path / "only.jsonl"
    record = {"id": "2604.20535", "title": "Title", "authors_parsed": [["Ada", "", ""]],
              "versions": [{"version": "v1", "created": "Mon, 1 Jan 2024 00:00:00 GMT"}]}
    snapshot.write_text(json.dumps(record) + "\n", encoding="utf8")
    fingerprint = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    monkeypatch.setattr(runner, "GROUP_SNAPSHOT_HASHES", {"only_v1": fingerprint, "multi_version": "other"})
    cfg = BenchmarkConfig("test", "partition", ("dang",), count=2, snapshot=str(snapshot), snapshot_group="only_v1")
    assert [p for c in plan_chunks(cfg) for p in c.ids] == ["2604.20535"]
    with pytest.raises(ValueError, match="group"):
        plan_chunks(replace(cfg, snapshot_group="multi_version"))
    snapshot.write_text(snapshot.read_text() + "\n")
    with pytest.raises(ValueError, match="missing"):
        plan_chunks(cfg)


def test_group_snapshot_provenance_uses_same_assigned_source():
    from src.analysis.group_evidence import snapshot_origin
    from src.benchmark.runner import GROUP_SNAPSHOT_HASHES
    full = "033d7bded327d3aa1595f5502ebfc44bcfe353a89a2011b297742d287ba4de15"
    assert snapshot_origin(GROUP_SNAPSHOT_HASHES["only_v1"]) == full
    assert snapshot_origin(GROUP_SNAPSHOT_HASHES["multi_version"]) == full
    assert snapshot_origin("different") == "different"


def test_split_snapshot_preserves_records_and_detects_missing(tmp_path, monkeypatch):
    from src import config
    from src.crawler.split_assigned_snapshot import split_snapshot
    monkeypatch.setattr(config, "RANGES", {"dang": ("2604.20535", "2604.20536")})
    first = {"id": "2604.20535", "title": "First", "authors_parsed": [["Ada", "", ""]],
             "versions": [{"version": "v1", "created": "Mon, 1 Jan 2024 00:00:00 GMT"}]}
    second = {**first, "id": "2604.20536", "versions": [first["versions"][0],
              {"version": "v2", "created": "Tue, 2 Jan 2024 00:00:00 GMT"}]}
    source = tmp_path / "snapshot.jsonl"
    source.write_text("\n".join(map(json.dumps, [first, second])) + "\n", encoding="utf8")
    result = split_snapshot(source, tmp_path / "output")
    assert result["arxiv-assigned-only-v1.jsonl"]["papers"] == 1
    assert result["arxiv-assigned-multi-version.jsonl"]["papers"] == 1
    assert json.loads((tmp_path / "output/arxiv-assigned-multi-version.jsonl").read_text()) == second
    source.write_text(json.dumps(first) + "\n", encoding="utf8")
    with pytest.raises(ValueError, match="missing"):
        split_snapshot(source, tmp_path / "missing")


def test_plan_selects_disjoint_snapshot_groups(tmp_path):
    snapshot = tmp_path / "snapshot.jsonl"
    def paper(pid, versions):
        return {"id": pid, "title": "Title", "authors_parsed": [["Author", "A", ""]],
                "versions": [{"version": f"v{i}", "created": "Mon, 1 Jan 2024 00:00:00 GMT"} for i in range(1, versions + 1)]}
    snapshot.write_text("\n".join(json.dumps(paper(pid, count)) for pid, count in
        [("2604.20535", 1), ("2604.20536", 2), ("2604.20537", 1)]) + "\n", encoding="utf8")
    cfg = BenchmarkConfig("sample", "partition", ("dang",), count=3, chunk_size=2, snapshot=str(snapshot))
    single = [pid for chunk in plan_chunks(replace(cfg, snapshot_group="only_v1")) for pid in chunk.ids]
    multi = [pid for chunk in plan_chunks(replace(cfg, snapshot_group="multi_version")) for pid in chunk.ids]
    assert single == ["2604.20535", "2604.20537"]
    assert multi == ["2604.20536"]
    snapshot.write_text("", encoding="utf8")
    with pytest.raises(ValueError, match="missing"):
        plan_chunks(replace(cfg, snapshot_group="only_v1"))


@pytest.mark.parametrize("group", ["only_v1", "multi_version"])
def test_group_notebooks_are_pinned_and_select_all_ranges(group):
    from pathlib import Path
    path = Path(__file__).parents[1] / "notebooks" / f"arxiv_nhom1_{group}_benchmark.ipynb"
    cells = json.loads(path.read_text(encoding="utf8"))["cells"]
    code = "\n".join("".join(c["source"]) for c in cells if c["cell_type"] == "code")
    ast.parse(code)
    assert f'snapshot_group="{group}"' in code
    assert ('RANGES = ("thien", "tien", "hieu", "dang")' if group == "only_v1" else 'RANGES = (MEMBER,)') in code
    assert 'CODE_REF = "main"' in code
    assert 'revision = saved["code_revision"]' in code
    assert "RUN_CRAWL = False" in code
