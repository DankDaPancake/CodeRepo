import hashlib
import io
import json

import pytest

from src.crawler.s3_prepare import Bundle
from src.benchmark.s3_bulk_download import ResourceSampler, plan_candidates, validate_snapshot, transfer_bundle


def bundle(key, first, last, payload=b'data'):
    return Bundle(key, first, last, len(payload), hashlib.md5(payload).hexdigest(), '2026-07-01')


def test_plan_includes_overlapping_and_later_month_bundles():
    ids = ['2604.20535', '2604.20536', '2604.20537']
    entries = [bundle('src/arXiv_src_2604_001.tar', ids[0], ids[1]),
               bundle('src/arXiv_src_2606_001.tar', ids[1], ids[1])]
    selected, mapping, missing = plan_candidates(entries, ids)
    assert len(selected) == 2
    assert len(mapping[ids[1]]) == 2
    assert missing == [ids[2]]


def test_snapshot_coverage_rejects_duplicates_and_extras(tmp_path):
    path = tmp_path / 'snapshot.jsonl'
    path.write_text('\n'.join(json.dumps({'id': x}) for x in ['2604.20535', '2604.20535']), encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate'):
        validate_snapshot(path, ['2604.20535'])
    path.write_text(json.dumps({'id': '2604.20536'}), encoding='utf-8')
    with pytest.raises(ValueError, match='missing'):
        validate_snapshot(path, ['2604.20535'])


def test_transfer_verified_reuse_and_wrong_existing_file(tmp_path):
    item = bundle('src/arXiv_src_2604_001.tar', '2604.20535', '2604.20535')
    class Client:
        def get_object(self, **kwargs):
            assert kwargs['RequestPayer'] == 'requester'
            return {'Body': io.BytesIO(b'data')}
    local, drive = tmp_path / 'local', tmp_path / 'drive'
    result = transfer_bundle(Client(), item, local, drive)
    assert result['status'] == 'downloaded'
    assert result['download_bytes_per_s'] > 0
    assert (drive / item.key.split('/')[-1]).read_bytes() == b'data'
    reused = transfer_bundle(None, item, local, drive)
    assert reused['status'] == 'reused' and reused['download_bytes_per_s'] is None
    (drive / item.key.split('/')[-1]).write_bytes(b'wrong')
    with pytest.raises(FileExistsError):
        transfer_bundle(None, item, local, drive)


def test_bad_checksum_never_publishes(tmp_path):
    item = bundle('src/arXiv_src_2604_001.tar', '2604.20535', '2604.20535')
    class Client:
        def get_object(self, **kwargs):
            return {'Body': io.BytesIO(b'incorrect')}
    with pytest.raises(ValueError, match='MD5 mismatch'):
        transfer_bundle(Client(), item, tmp_path / 'local', tmp_path / 'drive')
    assert not list((tmp_path / 'drive').iterdir())


def test_reversed_boundaries_fail_closed():
    item = bundle('src/arXiv_src_2604_001.tar', '2604.20537', '2604.20535')
    with pytest.raises(ValueError, match='Reversed'):
        plan_candidates([item], ['2604.20535'])


def test_resource_sampler_records_existing_stage_file(tmp_path):
    (tmp_path / 'test.dat').write_bytes(b'1234')
    with ResourceSampler(tmp_path, interval_s=0.1) as sampler:
        assert sampler.peak_stage_bytes >= 4
    assert sampler.samples >= 1
    assert sampler.peak_rss_bytes > 0
