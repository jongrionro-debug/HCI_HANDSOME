#!/usr/bin/env python3
"""Generate/check the packaged copy of the canonical Park vocabulary, offline."""

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output/feature-map/park-2025-feature-map.json"
RESOURCE = ROOT / "src/stylemate_memory/resources/park-2025-feature-map.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="읽기 전용 byte 동일성 검사")
    args = parser.parse_args()
    source = SOURCE.read_bytes()
    if args.check:
        if not RESOURCE.is_file() or RESOURCE.read_bytes() != source:
            print("FAIL: packaged registry differs; run python3 scripts/sync_feature_registry.py")
            return 1
        print("OK: canonical and packaged registry are byte-identical")
    else:
        RESOURCE.parent.mkdir(parents=True, exist_ok=True)
        RESOURCE.write_bytes(source)
        print("Generated src/stylemate_memory/resources/park-2025-feature-map.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
