"""Restore original v3 report JSON files after checking lengths and SHA-256 hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile


def main():
    runs = Path(__file__).resolve().parents[1]/'runs'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=runs)
    args = parser.parse_args()
    output = args.output.resolve()
    records = json.loads((runs/'ARCHIVED_RESULTS.json').read_text(encoding='utf-8'))
    prepared = []
    with tarfile.open(runs/'results.tar.gz', 'r:gz') as archive:
        for record in records:
            destination = (output/record['file']).resolve()
            if destination.parent != output:
                raise ValueError('Result path escapes output directory')
            data = archive.extractfile(record['file']).read()
            if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('Result integrity check failed: '+record['file'])
            if destination.exists() and destination.read_bytes() != data:
                raise FileExistsError('Refusing to overwrite changed results: '+str(destination))
            prepared.append((destination, data))
    output.mkdir(parents=True, exist_ok=True)
    for destination, data in prepared:
        if not destination.exists():
            destination.write_bytes(data)
    print(f'Verified and restored {len(prepared)} reports to {output}')


if __name__ == '__main__':
    main()
