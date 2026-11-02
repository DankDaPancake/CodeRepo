import hashlib
import io
import tarfile

import pytest

from src.crawler.s3_prepare import Bundle
from src.crawler.s3_sources import index_verified_bundle


def test_index_marks_unversioned_member_unverified_and_rejects_bad_bundle(tmp_path):
    path = tmp_path / "arXiv_src_2604_001.tar"
    with tarfile.open(path, "w") as tar:
        member = tarfile.TarInfo("2604.20535.gz")
        member.size = 4
        tar.addfile(member, io.BytesIO(b"data"))
    digest = hashlib.md5(path.read_bytes()).hexdigest()
    bundle = Bundle("src/" + path.name, "2604.20535", "2604.20535", path.stat().st_size, digest, "")
    indexed = index_verified_bundle(path, bundle, {"2604.20535"})
    assert indexed["2604.20535"]["status"] == "version_unverified"
    assert indexed["2604.20535"]["member"] == "2604.20535.gz"
    path.write_bytes(b"tampered")
    import pytest

    with pytest.raises(ValueError, match="checksum"):
        index_verified_bundle(path, bundle, {"2604.20535"})


def test_index_accepts_matching_md5_with_different_manifest_size(tmp_path):
    path = tmp_path / "arXiv_src_2604_001.tar"
    with tarfile.open(path, "w") as tar:
        member = tarfile.TarInfo("2604.20535.gz")
        member.size = 4
        tar.addfile(member, io.BytesIO(b"data"))
    bundle = Bundle(
        "src/" + path.name,
        "2604.20535",
        "2604.20535",
        4,
        hashlib.md5(path.read_bytes()).hexdigest(),
        "",
    )
    assert "2604.20535" in index_verified_bundle(path, bundle, {"2604.20535"})


def test_explicit_v2_member_never_inferred_as_v1(tmp_path):
    from src.crawler.s3_sources import extract_inferred_v1

    path = tmp_path / "arXiv_src_2604_001.tar"
    with tarfile.open(path, "w") as tar:
        data = b"\\documentclass{article}"
        member = tarfile.TarInfo("2604.20535v2.tex")
        member.size = len(data)
        tar.addfile(member, io.BytesIO(data))
    bundle = Bundle(
        "src/" + path.name,
        "2604.20535",
        "2604.20535",
        path.stat().st_size,
        hashlib.md5(path.read_bytes()).hexdigest(),
        "2026-05-05 00:00:00",
    )
    entry = index_verified_bundle(path, bundle, {"2604.20535"})["2604.20535"]
    with pytest.raises(ValueError, match="version"):
        extract_inferred_v1(
            path, entry, tmp_path / "v1", ["2026-04-20T00:00:00Z"], bundle.timestamp
        )
    assert not (tmp_path / "v1").exists()


def test_duplicate_member_is_not_selected(tmp_path):
    path = tmp_path / "arXiv_src_2604_001.tar"
    with tarfile.open(path, "w") as tar:
        for name in ("2604.20535.gz", "2604.20535.tar.gz"):
            member = tarfile.TarInfo(name)
            member.size = 4
            tar.addfile(member, io.BytesIO(b"data"))
    bundle = Bundle(
        "src/" + path.name,
        "2604.20535",
        "2604.20535",
        path.stat().st_size,
        hashlib.md5(path.read_bytes()).hexdigest(),
        "",
    )
    import pytest

    with pytest.raises(ValueError, match="duplicate"):
        index_verified_bundle(path, bundle, {"2604.20535"})


def test_extract_refuses_member_without_matching_version_hash(tmp_path):
    from src.crawler.s3_sources import extract_verified_member

    content = b"\\documentclass{article}\n\\begin{document}Hi\\end{document}"
    path = tmp_path / "arXiv_src_2604_001.tar"
    with tarfile.open(path, "w") as tar:
        member = tarfile.TarInfo("2604.20535.tex")
        member.size = len(content)
        tar.addfile(member, io.BytesIO(content))
    bundle = Bundle(
        "src/" + path.name,
        "2604.20535",
        "2604.20535",
        path.stat().st_size,
        hashlib.md5(path.read_bytes()).hexdigest(),
        "",
    )
    index = index_verified_bundle(path, bundle, {"2604.20535"})["2604.20535"]
    import pytest

    with pytest.raises(ValueError, match="version"):
        extract_verified_member(path, index, tmp_path / "v1", "0" * 64)
    assert not (tmp_path / "v1").exists()
    res = extract_verified_member(path, index, tmp_path / "v1", hashlib.sha256(content).hexdigest())
    assert res.has_tex
    assert (tmp_path / "v1" / "2604.20535.tex").read_bytes() == content


def test_index_bundle_set_reports_missing_without_conflating_404(tmp_path):
    from src.crawler.s3_sources import index_bundle_set

    path = tmp_path / "arXiv_src_2604_001.tar"
    with tarfile.open(path, "w") as tar:
        member = tarfile.TarInfo("2604.20535.gz")
        member.size = 4
        tar.addfile(member, io.BytesIO(b"data"))
    bundle = Bundle(
        "src/" + path.name,
        "2604.20535",
        "2604.20536",
        path.stat().st_size,
        hashlib.md5(path.read_bytes()).hexdigest(),
        "",
    )
    result = index_bundle_set(tmp_path, [bundle], {"2604.20535", "2604.20536"})
    assert result["2604.20535"]["status"] == "version_unverified"
    assert result["2604.20536"]["status"] == "source_missing"


def test_v1_inference_requires_single_snapshot_version_and_bundle_after_margin():
    from src.crawler.s3_sources import infer_v1

    assert infer_v1(["2026-04-20T12:00:00Z"], "2026-04-22 12:00:00")
    assert not infer_v1(["2026-04-20T12:00:00Z"], "2026-04-21 11:59:59")
    assert not infer_v1(["2026-04-20T12:00:00Z", "2026-04-23T00:00:00Z"], "2026-04-30 00:00:00")


def test_extract_inferred_source_records_the_assumption(tmp_path):
    from src.crawler.s3_sources import extract_inferred_v1

    content = b"\\documentclass{article}\n\\begin{document}Hi\\end{document}"
    path = tmp_path / "arXiv_src_2604_001.tar"
    with tarfile.open(path, "w") as tar:
        member = tarfile.TarInfo("2604.20535.tex")
        member.size = len(content)
        tar.addfile(member, io.BytesIO(content))
    bundle = Bundle(
        "src/" + path.name,
        "2604.20535",
        "2604.20535",
        path.stat().st_size,
        hashlib.md5(path.read_bytes()).hexdigest(),
        "2026-04-23 00:00:00",
    )
    index = index_verified_bundle(path, bundle, {"2604.20535"})["2604.20535"]
    rec = extract_inferred_v1(
        path, index, tmp_path / "v1", ["2026-04-20T00:00:00Z"], bundle.timestamp
    )
    assert rec["status"] == "ok"
    assert rec["version_evidence"] == "inferred_snapshot_bundle_timestamp"
    assert (tmp_path / "v1/2604.20535.tex").read_bytes() == content


def test_inferred_extraction_rejects_modified_bundle(tmp_path):
    from src.crawler.s3_sources import extract_inferred_v1

    path = tmp_path / "arXiv_src_2604_001.tar"
    with tarfile.open(path, "w") as tar:
        item = tarfile.TarInfo("2604.20535.tex")
        item.size = 4
        tar.addfile(item, io.BytesIO(b"data"))
    bundle = Bundle(
        "src/" + path.name,
        "2604.20535",
        "2604.20535",
        path.stat().st_size,
        hashlib.md5(path.read_bytes()).hexdigest(),
        "2026-04-23 00:00:00",
    )
    entry = index_verified_bundle(path, bundle, {"2604.20535"})["2604.20535"]
    with path.open("ab") as f:
        f.write(b"extra")
    import pytest

    with pytest.raises(ValueError, match="changed"):
        extract_inferred_v1(
            path, entry, tmp_path / "v1", ["2026-04-20T00:00:00Z"], bundle.timestamp
        )
