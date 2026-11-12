import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.benchmark.recovery_review import read_journal, select_s3_sample, classify_metadata, unavailable_by_run


class ReviewTests(unittest.TestCase):
    def test_journal_last_and_corruption(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / 'versions.jsonl'
            p.write_text('\n'.join(json.dumps(x) for x in [
                {'arxiv_id': '2601.00001', 'version': 1, 'status': 'unavailable'},
                {'arxiv_id': '2601.00001', 'version': 1, 'status': 'ok'},
            ]), encoding='utf8')
            self.assertEqual(read_journal(p)[('2601.00001', 1)]['status'], 'ok')
            p.write_text('{broken', encoding='utf8')
            with self.assertRaises(ValueError): read_journal(p)

    def test_sample_unique_and_repeatable(self):
        records = [{'arxiv_id': f'2601.{i:05d}', 'version': 1, 'status': 'ok', 'source': 's3', 'version_evidence': 'inferred_snapshot_bundle_timestamp'} for i in range(10)]
        self.assertEqual(select_s3_sample(records, 5, 42), select_s3_sample(records, 5, 42))
        self.assertEqual(len(select_s3_sample(records + records, 5, 42)), 5)
        with self.assertRaises(ValueError): select_s3_sample(records, 11, 42)

    def test_metadata_comparison(self):
        record = {'bundle_timestamp': '2026-07-05T06:57:08Z'}
        metadata = {'arxiv_id': '2601.00001', 'num_versions': 2, 'versions': [{'version': 1, 'date': '2026-01-01T00:00:00Z'}, {'version': 2, 'date': '2026-08-01T00:00:00Z'}]}
        self.assertEqual(classify_metadata(record, metadata, '2601.00001'), 'compatible')
        metadata['versions'][1]['date'] = '2026-06-01T00:00:00Z'
        self.assertEqual(classify_metadata(record, metadata, '2601.00001'), 'contradiction')
        record['bundle_timestamp'] = '2026-07-05 06:57:08'
        self.assertEqual(classify_metadata(record, metadata, '2601.00001'), 'inconclusive')
        self.assertEqual(classify_metadata(record, None, '2601.00001'), 'inconclusive')

    def test_unavailable_keeps_all_runs(self):
        rec = {'arxiv_id': '2601.00001', 'version': 2, 'status': 'unavailable'}
        self.assertEqual(unavailable_by_run({'a': {('2601.00001', 2): rec}, 'b': {('2601.00001', 2): rec}}), {('2601.00001', 2): ['a', 'b']})



class WorkflowTests(unittest.TestCase):
    def test_review_persists_discovery_failure_and_manifest(self):
        from src.benchmark.recovery_review import review_metadata
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'evidence').mkdir()
            journal = root / 'evidence/input.jsonl'
            journal.write_text(json.dumps({'arxiv_id':'2601.00001','version':1,'status':'ok','source':'s3','version_evidence':'inferred_snapshot_bundle_timestamp'})+'\n')
            def offline(ids, destination):
                raise RuntimeError('network down')
            result = review_metadata({'a': journal}, root / 'review', discover_live=offline, count=1)
            self.assertEqual(result['inconclusive'], 1)
            self.assertIn('network down', (root/'review/results.jsonl').read_text())
            self.assertTrue((root/'review/manifest.json').exists())

    def test_retry_resumes_only_verified_files_and_keeps_provenance(self):
        from src.benchmark.recovery_review import retry_unavailable
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'evidence').mkdir()
            journal = root/'evidence/input.jsonl'
            journal.write_text(json.dumps({'arxiv_id':'2601.00001','version':2,'status':'unavailable'})+'\n')
            calls = []
            def download(pid, version, corpus):
                calls.append(version)
                folder = corpus/'2601-00001'/f'v{version}'
                folder.mkdir(parents=True, exist_ok=True)
                (folder/'main.tex').write_text('hello')
                return {'arxiv_id':pid,'version':version,'status':'ok','files':['main.tex']}
            out = root/'retry'
            retry_unavailable({'a':journal,'b':journal}, out, process=download)
            retry_unavailable({'a':journal,'b':journal}, out, process=download)
            self.assertEqual(calls, [2])
            rec = read_journal(out/'versions.jsonl')[('2601.00001',2)]
            self.assertEqual(rec['original_runs'], ['a','b'])
            (out/'corpus/2601-00001/v2/stale.tex').write_text('leftover')
            (out/'corpus/2601-00001/v2/main.tex').write_text('damaged')
            retry_unavailable({'a':journal,'b':journal}, out, process=download)
            self.assertEqual(calls, [2,2])
            self.assertFalse((out/'corpus/2601-00001/v2/stale.tex').exists())
            with self.assertRaises(ValueError):
                retry_unavailable({'a':journal}, root, process=download)

    def test_copy_integration_preserves_original_and_verifies_restore(self):
        from src.benchmark.recovery_review import measure_integration
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            original=root/'original'; original.mkdir()
            (original/'keep.txt').write_text('original')
            recovered=root/'recovered'; recovered.mkdir()
            (recovered/'new.txt').write_text('recovered')
            import hashlib
            (recovered/'corpus/2601-00001/v1').mkdir(parents=True)
            (recovered/'corpus/2601-00001/v1/main.tex').write_bytes(b'hello')
            (recovered/'work').mkdir()
            (recovered/'work/versions.jsonl').write_text(json.dumps({'arxiv_id':'2601.00001','version':1,'status':'ok','hashes':{'main.tex':hashlib.sha256(b'hello').hexdigest()}})+'\n')
            report=measure_integration(original, recovered, root/'experiment')
            self.assertFalse((original/'new.txt').exists())
            self.assertTrue(report['hashes_match'])
            self.assertIn('restore_verify_s', report)


class EdgeTests(unittest.TestCase):
    def test_empty_versions_and_non_object_journal_are_not_accepted(self):
        self.assertEqual(classify_metadata({'bundle_timestamp':'2026-01-01T00:00:00Z'}, {'arxiv_id':'x','num_versions':0,'versions':[]}, 'x'), 'inconclusive')
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'j.jsonl'; p.write_text('[]\n')
            with self.assertRaises(ValueError): read_journal(p)

    def test_integration_rejects_unresolved_retry_records(self):
        from src.benchmark.recovery_review import measure_integration
        with TemporaryDirectory() as tmp:
            root=Path(tmp); original=root/'a'; recovered=root/'b'
            original.mkdir(); recovered.mkdir()
            (recovered/'versions.jsonl').write_text(json.dumps({'arxiv_id':'2601.00001','version':1,'status':'inconclusive'})+'\n')
            with self.assertRaises(ValueError): measure_integration(original,recovered,root/'out')

class IntegrationIntegrityTests(unittest.TestCase):
    def test_missing_recovered_corpus_is_rejected(self):
        from src.benchmark.recovery_review import measure_integration
        with TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'a').mkdir(); (root/'b/work').mkdir(parents=True)
            (root/'b/work/versions.jsonl').write_text(json.dumps({'arxiv_id':'2601.00001','version':1,'status':'ok','hashes':{'main.tex':'missing'}})+'\n')
            with self.assertRaises(ValueError): measure_integration(root/'a',root/'b',root/'out')

class BlockedRecoveryTests(unittest.TestCase):
    def test_blocked_client_stops_then_resume_retries(self):
        from src.benchmark.recovery_review import retry_unavailable
        from src.crawler.http_client import BlockedError
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'input').mkdir()
            journal = root / 'input' / 'versions.jsonl'
            journal.write_text(''.join(json.dumps({'arxiv_id': f'2601.{i:05d}', 'version': 1, 'status': 'unavailable'}) + '\n' for i in (1, 2)))
            class BlockedClient:
                def __init__(self): self.calls = []
                def stream(self, url, consume, **kwargs):
                    self.calls.append(url)
                    raise BlockedError(url, 'blocked', 403, 1)
            client = BlockedClient()
            with self.assertRaises(BlockedError):
                retry_unavailable({'run': journal}, root / 'output', client=client)
            self.assertEqual(len(client.calls), 1)
            state = read_journal(root / 'output' / 'versions.jsonl')
            self.assertEqual(state[('2601.00001', 1)]['status'], 'inconclusive')
            retried = []
            def later(pid, version, corpus):
                retried.append(pid)
                return {'arxiv_id': pid, 'version': version, 'status': 'unavailable'}
            retry_unavailable({'run': journal}, root / 'output', process=later)
            self.assertEqual(retried, ['2601.00001', '2601.00002'])

class PackagingTests(unittest.TestCase):
    def test_runtime_package_has_verified_journals_and_code(self):
        from src.benchmark.package_recovery import package_runtime
        import hashlib, zipfile
        with TemporaryDirectory() as tmp:
            root = Path(tmp); journal = root / 'versions.jsonl'; journal.write_text('{"test":1}\n')
            path = root / 'runtime.zip'
            package_runtime({'example': journal}, path)
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read('runtime-manifest.json'))
                self.assertEqual(archive.read('evidence/example/work/versions.jsonl'), journal.read_bytes())
                self.assertIn('src/benchmark/recovery_review.py', manifest['sha256'])
                for name, expected in manifest['sha256'].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)

if __name__ == '__main__': unittest.main()
