"""Build the portable Colab recovery runtime from local journals."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

RUNS = (
    'only-v1-drive-evidence',
    'multi-dang-0000-4999-drive-evidence',
    'multi-hieu-0000-4999-drive-evidence',
    'multi-thien-0000-4999-drive-evidence',
    'multi-tien-0000-4999-drive-evidence',
)
ROOT = Path(__file__).resolve().parents[2]


def package_runtime(journals, output):
    files = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in (ROOT / 'src').rglob('*.py')
             if 'tests' not in p.parts and '__pycache__' not in p.parts}
    for name, journal in journals.items():
        if not name or Path(name).name != name or name in {'.', '..'}:
            raise ValueError('Unsafe run name')
        files[f'evidence/{name}/work/versions.jsonl'] = Path(journal).read_bytes()
    files['requirements-recovery.txt'] = (
        b'requests>=2.31.0,<2.35.0\nlxml>=5.0.0\npsutil>=5.9.0\n'
        b'filelock>=3.13,<4\ntqdm>=4.66.0\n'
    )
    manifest = {'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
                'runs': list(journals)}
    files['runtime-manifest.json'] = json.dumps(manifest, indent=2).encode()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    temporary.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    journals = {run: args.evidence / run / 'work' / 'versions.jsonl' for run in RUNS}
    print(package_runtime(journals, args.output))


if __name__ == '__main__':
    main()
