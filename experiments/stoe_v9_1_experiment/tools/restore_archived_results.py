"""Restore byte-identical archived JSON results; refuse to overwrite different files."""
from pathlib import Path
import gzip
import hashlib
import json


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    records = json.loads((root / "ARCHIVED_RESULTS.json").read_text(encoding="utf-8"))
    prepared = []
    for record in records:
        archive = (root / record["archive"]).resolve()
        destination = (root / record["file"]).resolve()
        if archive.parent != root or destination.parent != root:
            raise ValueError("Archive manifest path escapes the experiment directory")
        data = gzip.decompress(archive.read_bytes())
        if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError(f"Archive integrity check failed: {archive.name}")
        if destination.exists() and destination.read_bytes() != data:
            raise FileExistsError(f"Refusing to overwrite changed results: {destination}")
        prepared.append((destination, data))
    for destination, data in prepared:
        if not destination.exists():
            destination.write_bytes(data)
        print(f"Verified: {destination.name}")


if __name__ == "__main__":
    main()
