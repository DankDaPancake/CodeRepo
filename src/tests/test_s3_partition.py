import json

import pytest

from src.crawler.s3_partition import partition_snapshot


def row(pid, versions):
    return json.dumps(
        {
            "id": pid,
            "title": "Title",
            "authors": "Author",
            "versions": [{"version": f"v{i}", "created": "2026-06-01T00:00:00Z"} for i in versions],
        }
    )


def test_partition_keeps_missing_and_invalid_separate(tmp_path):
    snapshot = tmp_path / "snapshot.jsonl"
    snapshot.write_text(
        "\n".join(
            [
                row("2606.00001", [1]),
                row("2606.00002", [1, 2]),
                row("2606.00003", [1, 3]),
            ]
        ),
        encoding="utf-8",
    )
    result = partition_snapshot(snapshot, [f"2606.0000{i}" for i in range(1, 5)])
    assert result.only_v1 == ["2606.00001"]
    assert result.multi_version == ["2606.00002"]
    assert set(result.missing) == {"2606.00003", "2606.00004"}


def test_partition_rejects_duplicate_requested_id(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        partition_snapshot(tmp_path / "unused", ["2606.00001", "2606.00001"])
