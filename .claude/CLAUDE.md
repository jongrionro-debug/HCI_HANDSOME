# Claude Code 안내 (LUMI · HCI_HANDSOME)

작업 규칙의 정본은 `AGENTS.md`다. 아래 import로 그대로 따른다. 이 파일은 Claude Code가 바로 쓸 명령·경로만 덧붙이며 규칙을 중복하지 않는다.

@../AGENTS.md

## 먼저 읽을 곳

- 현재 구현·실행·남은 일: [docs/project.md](../docs/project.md) (유일한 현재 상태 정본)
- 결정 이유: [docs/adr/](../docs/adr/README.md) · 수집 계약: [docs/specs/crawling.md](../docs/specs/crawling.md)
- 루트에 새 `.md`를 만들지 않는다. `scripts/check_context.py`가 `README.md`·`AGENTS.md` 외 루트 Markdown을 실패로 처리하므로 Claude 전용 안내는 이 `.claude/` 아래에 둔다.

## 코드 지도

- 패키지: `src/stylemate_memory/` (이름은 과거 `stylemate` 유지, 시스템 이름은 LUMI)
  - 서비스·HTTP: `app.py`(`ConsumerService`), `consumer.py`, `consumer*.js/css/html`
  - 메모리 저장: `store.py`, `store_v1.py`, `store_feedback.py`, `store_cleanup.py`
  - 조회·목표: `retrieval.py`, `inference.py`, `context.py`
  - 상품·비교: `catalog*.py`, `product_search.py`, `comparison.py`, `hypotheses.py`
  - 모델: `llm.py`, `model_io.py`, `codex_llm.py`, `settings.py`
  - 계약·사전: `contracts.py`, `errors.py`, `registry.py`, `resources/park-2025-feature-map.json`(생성 사본, 직접 편집 금지)
- 수집 스크립트: `scripts/crawl_naver.mjs`, `scripts/probe_sites.mjs` (Node, Playwright)
- 테스트: `tests/test_*.py`(unittest), `tests/*.mjs`(node --test / Playwright 브라우저 검사)
- `archive/`는 동결 자료다. 링크 검사 대상이 아니며 수정하지 않는다.

## 자주 쓰는 명령 (저장소 루트, Python 3.11+, 추가 Python 의존성 없음)

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -q      # 단위·SQLite·통합 (약 20초)
python3 scripts/check_repository.py                           # 문서·링크·템플릿 검사
python3 scripts/check_context.py                              # 문서 구조 검사
python3 scripts/sync_feature_registry.py --check              # 사전 정본/패키지 사본 일치
PYTHONPATH=src python3 -m stylemate_memory.cli demo --synthetic
PYTHONPATH=src python3 scripts/evaluate_offline.py
node --test tests/test_naver_crawler.mjs tests/test_probe_sites.mjs
node tests/check_consumer_http_browser.mjs                    # Playwright 필요
node tests/check_hypothesis_browser.mjs
```

- 단일 테스트: `PYTHONPATH=src python3 -m unittest tests.test_store -q`
- 브라우저 검사는 `playwright`를 import한다. 전역 설치만 있는 환경에서는 ESM이 `NODE_PATH`를 무시하므로 `node_modules/playwright`를 전역 설치로 symlink한다(`node_modules/`는 gitignore).
- CI(`.github/workflows/`)는 Python 3.11/3.14 unittest·demo·`check_repository.py`만 돌린다. Node 테스트는 로컬 전용이다.

## 실행

```sh
export STYLEMATE_DB=/private/tmp/lumi-local/memory.sqlite3
export STYLEMATE_CATALOG_DB=/private/tmp/lumi-local/catalog.sqlite3
PYTHONPATH=src python3 -m stylemate_memory.cli catalog-import --file tests/fixtures/catalog/valid.jsonl
PYTHONPATH=src python3 -m stylemate_memory.cli catalog-map
PYTHONPATH=src python3 -m stylemate_memory.consumer --provider fake   # http://127.0.0.1:8766
```

DB·이미지·수집 원본은 반드시 저장소 밖 경로를 쓴다. 기본 provider `fake`는 외부 호출이 없다. 실제 모델(`opencode-go`, `openai`)과 Codex 기반 관찰 도구는 사용자가 요청한 실행에서만 쓴다.

## 데이터 위치

- 수집 원본은 저장소 밖 `LUMI-data/`(사용자 Mac, 예: `~/Documents/LUMI-data`)에 둔다. 사이트별 `summary.json`에 PI 7축 채움률이 있다.
- 저장소에는 스크립트와 요약만 올린다. 참여자 정보·동의서·원시 응답·실행 DB는 커밋하지 않는다.
