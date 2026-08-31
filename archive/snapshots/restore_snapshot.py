"""Verify and restore one historical source snapshot without extracting arbitrary paths."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', nargs='?', help='Snapshot name; omit to list names')
    parser.add_argument('--output', type=Path, default=root/'restored')
    args = parser.parse_args()
    manifest_bytes = (root/'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    by_name = {row['name']: row for row in manifest['snapshots']}
    if args.snapshot is None:
        print('\n'.join(by_name))
        return
    if args.snapshot not in by_name:
        parser.error('Unknown snapshot; run without a name to list available snapshots')
    target = (args.output.resolve()/args.snapshot).resolve()
    if target.parent != args.output.resolve():
        raise ValueError('Snapshot path escapes output directory')
    prepared = []
    with tarfile.open(root/'source-snapshots.tar.gz', 'r:gz') as archive:
        if archive.extractfile('manifest.json').read() != manifest_bytes:
            raise ValueError('Archive and external manifest differ')
        for relative, record in by_name[args.snapshot]['files'].items():
            destination = (target/relative).resolve()
            if not destination.is_relative_to(target):
                raise ValueError('Source path escapes snapshot directory')
            data = archive.extractfile('blobs/'+record['sha256']).read()
            if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('Source integrity check failed: '+relative)
            if destination.exists() and destination.read_bytes() != data:
                raise FileExistsError('Refusing to overwrite changed file: '+str(destination))
            prepared.append((destination, data))
    for destination, data in prepared:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            destination.write_bytes(data)
    print(f'Verified and restored {len(prepared)} files to {target}')


if __name__ == '__main__':
    main()
