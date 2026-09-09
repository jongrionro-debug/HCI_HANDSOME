#!/usr/bin/env python3
"""강의 자료를 repo 밖의 지정 폴더로 복사합니다. 기존 파일은 덮어쓰지 않습니다."""
import argparse
import hashlib
from pathlib import Path
import shutil
import sys


def digest(path):
    with path.open('rb') as stream:
        result = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
        return result.digest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='교안 원본 폴더')
    parser.add_argument('destination', type=Path, help='repo 밖의 첨부 준비 폴더')
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    target = args.destination.expanduser().resolve()
    repository = Path(__file__).resolve().parents[1]
    if target == repository or repository in target.parents:
        parser.error('교안 대상은 repo 밖의 폴더여야 합니다.')
    if source == target or source in target.parents or target in source.parents:
        parser.error('원본과 대상은 서로 분리된 폴더여야 합니다.')
    if not source.is_dir():
        parser.error('원본 폴더를 찾거나 읽을 수 없습니다.')
    count = 0
    conflicts = 0
    # iterdir는 접근 실패를 숨기지 않습니다.
    def walk(folder):
        for item in sorted(folder.iterdir()):
            if item.is_symlink() or item.name.startswith('.'):
                continue
            if item.is_dir():
                yield from walk(item)
            elif item.is_file():
                yield item
    for original in walk(source):
        relative = original.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            output = destination.open('xb')
        except FileExistsError:
            if destination.is_file() and digest(original) == digest(destination):
                print(f'동일 파일 유지: {relative}')
            else:
                print(f'충돌 — 기존 파일 유지: {relative}', file=sys.stderr)
                conflicts += 1
            continue
        try:
            with output, original.open('rb') as incoming:
                shutil.copyfileobj(incoming, output)
        except OSError:
            destination.unlink(missing_ok=True)
            raise
        count += 1
        print(f'복사: {relative}')
    print(f'복사 {count}개, 충돌 {conflicts}개. 필요한 파일을 Notion 교안 DB에 직접 첨부해 주세요.')
    return 1 if conflicts else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except OSError as error:
        print(f'복사 중단: {error}. 이미 복사된 파일은 유지됩니다.', file=sys.stderr)
        sys.exit(1)
