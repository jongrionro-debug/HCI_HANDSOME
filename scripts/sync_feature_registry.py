#!/usr/bin/env python3
"""Generate/check the packaged copies of the canonical vocabularies, offline."""

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Park 원문 사전(fixture·출처 메타데이터)과 PI v3 상·하의 실행 사전(scripts/build_lumi_pi_v3.py --export-runtime).
NAMES = ("park-2025-feature-map.json", "lumi-pi-v3.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="읽기 전용 byte 동일성 검사")
    args = parser.parse_args()
    failed = False
    for name in NAMES:
        source = (ROOT / "output/feature-map" / name).read_bytes()
        resource = ROOT / "src/stylemate_memory/resources" / name
        if args.check:
            if not resource.is_file() or resource.read_bytes() != source:
                print(f"FAIL: packaged {name} differs; run python3 scripts/sync_feature_registry.py")
                failed = True
            else:
                print(f"OK: canonical and packaged {name} are byte-identical")
        else:
            resource.parent.mkdir(parents=True, exist_ok=True)
            resource.write_bytes(source)
            print(f"Generated src/stylemate_memory/resources/{name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
