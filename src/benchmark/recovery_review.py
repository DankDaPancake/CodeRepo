"""Input selection and conservative metadata checks for recovery review."""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path


def read_journal(path: Path) -> dict:
    state = {}
    with Path(path).open(encoding="utf-8") as stream:
        for n, line in enumerate(stream, 1):
            try:
                rec = json.loads(line)
                if not isinstance(rec, dict):
                    raise ValueError("record must be an object")
                key = (rec["arxiv_id"], rec["version"])
                if not isinstance(key[0], str) or not isinstance(key[1], int) or key[1] < 1 or not isinstance(rec["status"], str):
                    raise ValueError("invalid record")
                state[key] = rec
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"Invalid journal {path}:{n}: {exc}") from exc
    return state


def select_s3_sample(records, count: int = 1000, seed: int = 42) -> list[dict]:
    eligible = {}
    for rec in records:
        if (rec.get("version") == 1 and rec.get("status") == "ok" and rec.get("source") == "s3" and rec.get("version_evidence") == "inferred_snapshot_bundle_timestamp"):
            pid = rec["arxiv_id"]
            if pid in eligible and eligible[pid] != rec:
                raise ValueError(f"Conflicting S3 records: {pid}")
            eligible[pid] = rec
    if count < 1 or len(eligible) < count:
        raise ValueError(f"Need {count} eligible IDs; found {len(eligible)}")
    return [eligible[k] for k in random.Random(seed).sample(sorted(eligible), count)]


def _date(value):
    if not isinstance(value, str):
        raise ValueError("missing date")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timezone missing")
    return result.astimezone(timezone.utc)


def classify_metadata(record: dict, metadata: dict | None, arxiv_id: str) -> str:
    try:
        if not metadata or metadata["arxiv_id"] != arxiv_id:
            return "inconclusive"
        bundle = _date(record["bundle_timestamp"])
        versions = metadata["versions"]
        if [v["version"] for v in versions] != list(range(1, metadata["num_versions"] + 1)):
            return "inconclusive"
        dates = [_date(v["date"]) for v in versions]
        if not dates or dates != sorted(dates) or any(d == bundle for d in dates):
            return "inconclusive"
        if dates[0] > bundle or any(d < bundle for d in dates[1:]):
            return "contradiction"
        return "compatible"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "inconclusive"


def unavailable_by_run(states: dict) -> dict:
    result = {}
    for run, state in sorted(states.items()):
        for key, rec in state.items():
            if rec.get("status") == "unavailable":
                result.setdefault(key, []).append(run)
    return result

# Workflow outputs are deliberately separate from evidence and corpus inputs.
import hashlib
import os
import shutil
import time
from collections import Counter


def _hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(temporary, path)


def _append(path, value):
    with Path(path).open('a', encoding='utf8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def _inputs(journals, output, mode, **options):
    output = Path(output).resolve()
    paths = {name: Path(p).resolve() for name, p in journals.items()}
    if not paths:
        raise ValueError('No input journals')
    for path in paths.values():
        # Never put output in an evidence run or an ancestor of an input.
        run = path.parent.parent if path.parent.name == 'work' else path.parent
        if output == run or output.is_relative_to(run) or run.is_relative_to(output):
            raise ValueError('Output overlaps input evidence')
    states = {name: read_journal(p) for name, p in paths.items()}
    identity = {'mode': mode, 'inputs': {n: {'path': str(p), 'sha256': _hash(p)} for n,p in paths.items()}, **options}
    manifest = output/'manifest.json'
    if manifest.exists():
        if json.loads(manifest.read_text(encoding='utf8')) != identity:
            raise ValueError('Output belongs to different inputs or settings')
    elif output.exists() and any(output.iterdir()):
        raise ValueError('Output must be empty or have a matching manifest')
    output.mkdir(parents=True, exist_ok=True)
    _write(manifest, identity)
    return states, output


def make_client():
    from src import config
    from src.crawler.http_client import HttpClient
    from src.crawler.ratelimit import RateLimiter
    return HttpClient(RateLimiter(min_interval_s=config.ARXIV_MIN_INTERVAL_S), config.USER_AGENT)


def review_metadata(journals, output, *, count=1000, seed=42, sample_run=None, discover_live=None, client=None):
    states, output = _inputs(journals, output, 'metadata', count=count, seed=seed, sample_run=sample_run)
    if sample_run is None:
        records = [rec for state in states.values() for rec in state.values()]
    else:
        records = list(states[sample_run].values())
    sample = select_s3_sample(records, count, seed)
    _write(output/'sample.json', sample)
    if discover_live is None:
        from src.crawler.discovery import discover
        client = client or make_client()
        def discover_live(ids, destination):
            return discover(ids, client, destination, refresh=True, snapshot=None,
                            journal=lambda rec: _append(output/'discovery.jsonl', rec))
    error = None
    # Fresh destination guarantees cached metadata cannot be used as evidence.
    import tempfile
    from src.crawler.discovery import read_metadata
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        destination = Path(tmp)
        try:
            discover_live([r['arxiv_id'] for r in sample], destination)
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
        rows = []
        for rec in sample:
            meta = read_metadata(destination, rec['arxiv_id'])
            rows.append({'arxiv_id': rec['arxiv_id'], 'classification': classify_metadata(rec, meta, rec['arxiv_id']),
                         'metadata': meta, 'snapshot_record': rec, 'error': error,
                         'checked_at': datetime.now(timezone.utc).isoformat(),
                         'scope': 'metadata chronology only; S3 content not verified'})
    temporary = output/'results.jsonl.tmp'
    temporary.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf8')
    os.replace(temporary, output/'results.jsonl')
    summary = dict(Counter(r['classification'] for r in rows))
    _write(output/'summary.json', summary)
    return summary


def _tree_hashes(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlink not permitted: {path}')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = _hash(path)
    return result


def retry_unavailable(journals, output, *, process=None, client=None):
    from src.utils.ids import to_folder_name
    from src.crawler.http_client import BlockedError
    from src import config
    states, output = _inputs(journals, output, 'retry')
    corpus = output/'corpus'
    corpus.mkdir(exist_ok=True)
    journal = output/'versions.jsonl'
    prior = read_journal(journal) if journal.exists() else {}
    if process is None:
        from src.run_pipeline import process_version
        client = client or make_client()
        def process(pid, version, corpus):
            return process_version(client, pid, version, data_root=corpus, keep_extensions=config.KEEP_EXTENSIONS)
    for (pid, version), runs in unavailable_by_run(states).items():
        # Validate identifiers before handing them to the downloader's filesystem paths.
        from src.utils.ids import NEW_ID_RE, OLD_ID_RE, split_version
        if not (NEW_ID_RE.fullmatch(pid) or OLD_ID_RE.fullmatch(pid)) or split_version(pid)[1] is not None:
            raise ValueError(f'Invalid base ID: {pid}')
        folder = corpus/to_folder_name(pid)/f'v{version}'
        old = prior.get((pid, version))
        if old and old['status'] in {'ok','no_tex','unavailable'} and folder.exists():
            if old.get('hashes') == _tree_hashes(folder):
                continue
        if folder.is_symlink():
            raise ValueError(f'Version directory is a symlink: {folder}')
        if folder.exists():
            shutil.rmtree(folder)  # discard incomplete or hash-mismatched retry output
        try:
            rec = process(pid, version, corpus)
            if rec.get('arxiv_id') != pid or rec.get('version') != version:
                raise ValueError('Downloader returned a different version')
            if rec.get('status') == 'failed':
                rec['status'] = 'corrupt' if str(rec.get('reason','')).startswith('corrupt archive') else 'inconclusive'
            if rec.get('status') not in {'ok','no_tex','unavailable','corrupt','inconclusive'}:
                raise ValueError('Unknown download status')
            if rec['status'] in {'ok','no_tex','unavailable'}:
                folder.mkdir(parents=True, exist_ok=True)
        except BlockedError as exc:
            _append(journal, {'arxiv_id': pid, 'version': version, 'status': 'inconclusive',
                              'reason': f'{type(exc).__name__}: {exc}', 'original_runs': runs,
                              'checked_at': datetime.now(timezone.utc).isoformat(), 'hashes': {}})
            raise
        except Exception as exc:
            rec = {'arxiv_id':pid, 'version':version, 'status':'inconclusive', 'reason':f'{type(exc).__name__}: {exc}'}
        rec.update(original_runs=runs, checked_at=datetime.now(timezone.utc).isoformat(),
                   hashes=_tree_hashes(folder) if folder.exists() else {})
        _append(journal, rec)
        prior[(pid, version)] = rec
    summary = dict(Counter(r['status'] for r in prior.values()))
    _write(output/'summary.json', summary)
    return summary


def measure_integration(original, recovered, output):
    """Measure a filesystem copy/checkpoint experiment; paths are run roots, not archives."""
    original, recovered, output = map(lambda p: Path(p).resolve(), (original, recovered, output))
    for a,b in [(original,recovered),(original,output),(recovered,output)]:
        if a == b or a.is_relative_to(b) or b.is_relative_to(a):
            raise ValueError('Integration paths must be disjoint')
    if output.exists():
        raise ValueError('Experiment output must not exist')
    staged_records = [r for path in recovered.rglob('versions.jsonl') for r in read_journal(path).values()]
    def verify_staged(root):
        from src.utils.ids import to_folder_name
        for rec in staged_records:
            if rec['status'] not in {'ok', 'no_tex'}:
                raise ValueError('Staging must contain only recovered ok/no_tex records')
            folder = (root/'corpus'/to_folder_name(rec['arxiv_id'])/f"v{rec['version']}").resolve()
            if not folder.is_relative_to(root/'corpus') or not folder.is_dir():
                raise ValueError('Recovered version directory missing or unsafe')
            hashes = _tree_hashes(folder)
            if not isinstance(rec.get('hashes'), dict) or rec['hashes'] != hashes:
                raise ValueError('Recovered version hashes do not match journal')
            if rec['status'] == 'ok' and not hashes:
                raise ValueError('Recovered ok version has no files')
    verify_staged(recovered)
    before = _tree_hashes(original)
    _tree_hashes(recovered)  # reject links before copy
    output.mkdir(parents=True)
    report = {}
    start = time.perf_counter()
    shutil.copytree(original, output/'copy')
    report['restore_s'] = time.perf_counter()-start
    start = time.perf_counter()
    # Merge journals by key instead of replacing the original run journal.
    additions = list(recovered.rglob('versions.jsonl'))
    merged = {}
    for path in additions:
        relative = path.relative_to(recovered)
        target = output/'copy'/relative
        base = read_journal(target) if target.exists() else {}
        base.update(read_journal(path))
        merged[relative] = base
    shutil.copytree(recovered, output/'copy', dirs_exist_ok=True)
    for relative, state in merged.items():
        (output/'copy'/relative).write_text(''.join(json.dumps(r)+'\n' for r in state.values()), encoding='utf8')
    report['update_s'] = time.perf_counter()-start
    start = time.perf_counter()
    shutil.make_archive(str(output/'checkpoint'), 'zip', output/'copy')
    report['checkpoint_s'] = time.perf_counter()-start
    start = time.perf_counter()
    shutil.unpack_archive(str(output/'checkpoint.zip'), output/'restored')
    report['restore_verify_s'] = time.perf_counter()-start
    start = time.perf_counter()
    verify_staged(output/'restored')
    report['hashes_match'] = _tree_hashes(output/'copy') == _tree_hashes(output/'restored')
    report['original_unchanged'] = before == _tree_hashes(original)
    report['journal_records'] = {str(p.relative_to(output/'restored')): len(read_journal(p)) for p in (output/'restored').rglob('versions.jsonl')}
    report['qa_s'] = time.perf_counter()-start
    report['scope'] = 'filesystem and journal integrity; parser QA and Drive timings require separate execution'
    _write(output/'measurement.json', report)
    if not report['hashes_match'] or not report['original_unchanged']:
        raise ValueError('Integration integrity check failed')
    return report
