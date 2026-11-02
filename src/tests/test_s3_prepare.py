import hashlib
import io

import pytest

from src.crawler.s3_prepare import download_bundle, parse_manifest, select_bundles


def manifest(payload=b"data"):
    md5 = hashlib.md5(payload).hexdigest()
    return f"""<manifest><file><filename>src/arXiv_src_2604_001.tar</filename>
      <first_item>2604.00001</first_item><last_item>2604.00100</last_item>
      <size>{len(payload)}</size><md5sum>{md5}</md5sum>
      <timestamp>2026-04-30 00:00:00</timestamp></file></manifest>""".encode()


def test_select_and_find_uncovered_ids():
    bundles = parse_manifest(manifest())
    selected, uncovered = select_bundles(bundles, ["2604.00002", "2604.00200"])
    assert [b.key for b in selected] == ["src/arXiv_src_2604_001.tar"]
    assert uncovered == ["2604.00200"]


def test_download_verifies_before_publish_and_reuses_verified_file(tmp_path):
    bundle = parse_manifest(manifest())[0]

    class S3:
        calls = 0

        def get_object(self, **kwargs):
            assert kwargs["RequestPayer"] == "requester"
            self.calls += 1
            return {"Body": io.BytesIO(b"data")}

    s3 = S3()
    result = download_bundle(s3, bundle, tmp_path)
    assert result["status"] == "downloaded"
    assert (tmp_path / "arXiv_src_2604_001.tar").read_bytes() == b"data"
    assert download_bundle(s3, bundle, tmp_path)["status"] == "reused"
    assert s3.calls == 1


def test_bad_checksum_is_not_published(tmp_path):
    bundle = parse_manifest(manifest())[0]

    class S3:
        def get_object(self, **kwargs):
            return {"Body": io.BytesIO(b"oops")}

    with pytest.raises(ValueError, match="checksum"):
        download_bundle(S3(), bundle, tmp_path)
    assert not (tmp_path / "arXiv_src_2604_001.tar").exists()


def test_rejects_unsafe_key():
    with pytest.raises(ValueError):
        parse_manifest(manifest().replace(b"src/arXiv_src_2604_001.tar", b"../outside.tar"))


def test_modified_existing_file_is_not_overwritten(tmp_path):
    bundle = parse_manifest(manifest())[0]
    target = tmp_path / "arXiv_src_2604_001.tar"
    target.write_bytes(b"bad!")
    with pytest.raises(FileExistsError):
        download_bundle(None, bundle, tmp_path)
    assert target.read_bytes() == b"bad!"


def test_interrupted_download_is_restarted_and_verified(tmp_path):
    bundle = parse_manifest(manifest())[0]

    class BrokenBody(io.BytesIO):
        def read(self, size=-1):
            raise OSError("network interrupted")

    class S3:
        broken = True

        def get_object(self, **kwargs):
            return {"Body": BrokenBody() if self.broken else io.BytesIO(b"data")}

    s3 = S3()
    with pytest.raises(OSError):
        download_bundle(s3, bundle, tmp_path)
    assert not (tmp_path / "arXiv_src_2604_001.tar").exists()
    s3.broken = False
    assert download_bundle(s3, bundle, tmp_path)["status"] == "downloaded"
