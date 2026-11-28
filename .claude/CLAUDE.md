# Claude Code 안내 (LUMI · HCI_HANDSOME)

작업 규칙의 정본은 `AGENTS.md`다. 아래 import로 그대로 따른다. 이 파일은 Claude Code가 바로 쓸 명령·경로만 덧붙이며 규칙을 중복하지 않는다.

@../AGENTS.md

## 먼저 읽을 곳

- 현재 구현·실행·남은 일: [docs/project.md](../docs/project.md) (유일한 현재 상태 정본)
- 결정 이유: [docs/adr/](../docs/adr/README.md) · 수집 계약: [docs/specs/crawling.md](../docs/specs/crawling.md) · 에이전트 제안: [docs/specs/agent-pipeline.md](../docs/specs/agent-pipeline.md)
- 할 일: GitHub Issue(`gh issue list`). project.md "지금 할 일"이 Issue 번호를 가리킨다
- 질문 설계 초안·근거 카드: [research/question-design/](../research/question-design/README.md) (`qd/<파트>-<이름>` 브랜치, [ADR 0017](../docs/adr/0017-question-design-research-workspace.md))
- 루트에 새 `.md`를 만들지 않는다. `scripts/check_context.py`가 `README.md`·`AGENTS.md` 외 루트 Markdown을 실패로 처리하므로 Claude 전용 안내는 이 `.claude/` 아래에 둔다.

## 코드 지도

- 패키지: `src/stylemate_memory/` (이름은 과거 `stylemate` 유지, 시스템 이름은 LUMI)
  - 서비스·HTTP: `app.py`(`ConsumerService`), `consumer.py`, `consumer*.js/css/html`
  - 메모리 저장: `store.py`, `store_v1.py`, `store_feedback.py`, `store_cleanup.py`
  - 조회·목표: `retrieval.py`, `inference.py`, `context.py`
  - 상품·비교: `catalog*.py`, `product_search.py`, `comparison.py`, `hypotheses.py`
  - 모델: `llm.py`, `model_io.py`, `settings.py`
  - 계약·사전: `contracts.py`, `errors.py`, `registry.py`, `resources/*.json`(`output/feature-map/` 정본의 생성 사본, 직접 편집 금지)
  - 의도 순환 엔진(기본 엔진, langgraph 필요. `--engine legacy`는 이전 비교 흐름): `graph/`(`engine.py`, `service.py`, `grid.py`, `scoring.py`, `questions.py`(질문 루프, ADR 0020), `parse.py`, `intent.py`, `hypotheses.py`, `memory.py`, `situations.py`)
- 수집 스크립트: `scripts/crawl_29cm.mjs`, `scripts/crawl_naver.mjs`, `scripts/probe_sites.mjs` (Node, Playwright), `scripts/fetch_shopify_first_images.py`
- 카탈로그 빌드: `scripts/build_lumi_pi_v2.py` → `fill_pi_v2_text.py`·`fill_pi_v2_image.py`(DeepSeek, 실행 요청 시만) → `build_lumi_pi_v3.py`(Pillow, 이전 실행 사전 `lumi-pi-v3`). 최종 통합 map은 `build_lumi_pi_unified.py`(+`fill_pi_unified.py`, DeepSeek)가 만들고 `--export-runtime`으로 기본 실행 사전 `lumi-pi-v5.1`·가져오기 조각 파일을 쓴다(ADR 0021). 29CM 원문 정규화는 `build_29cm_registry.py`(v2 빌드가 import), 원문 PI 보완은 `fill_pi_deepseek.py`
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
# graph 엔진(저장소 밖 venv)
PYTHONPATH=src ~/.venvs/lumi-graph/bin/python -m unittest tests.test_graph_engine tests.test_graph_logic -q
LUMI_GRAPH_PYTHON=~/.venvs/lumi-graph/bin/python node tests/check_graph_browser.mjs
```

- 단일 테스트: `PYTHONPATH=src python3 -m unittest tests.test_store -q`
- 브라우저 검사는 `playwright`를 import한다. 전역 설치만 있는 환경에서는 ESM이 `NODE_PATH`를 무시하므로 `node_modules/playwright`를 전역 설치로 symlink한다(`node_modules/`는 gitignore).
- CI(`.github/workflows/`)는 Python 3.11/3.14 unittest(graph 의존성 포함)·demo·`check_repository.py`만 돌린다. Node 테스트는 로컬 전용이다.

## 실행

```sh
export STYLEMATE_DB=/private/tmp/lumi-local/memory.sqlite3
export STYLEMATE_CATALOG_DB=/private/tmp/lumi-local/catalog.sqlite3
PYTHONPATH=src python3 -m stylemate_memory.cli catalog-import --file tests/fixtures/catalog/valid.jsonl
PYTHONPATH=src python3 -m stylemate_memory.cli catalog-map
PYTHONPATH=src ~/.venvs/lumi-graph/bin/python -m stylemate_memory.consumer --provider fake   # http://127.0.0.1:8766, 기본 graph·lumi-pi-v5.1
# 위 fixture는 Park 사전(Pants) 형식 예시다. 실제 v3 카탈로그는 docs/project.md "로컬 실행"
```

실행 DB는 저장소 밖 경로를 쓴다. 수집 원본·이미지는 저장소 안 `data/`(gitignore, [ADR 0014](../docs/adr/0014-crawled-catalog-pi-v2.md))에 둔다. 기본 provider `fake`는 외부 호출이 없다. 실제 모델(`opencode-go`, `openai`)은 사용자가 요청한 실행에서만 쓴다.

## 데이터 위치

- 수집 원본·첫 이미지는 저장소 안 `data/`(커밋 제외)에 둔다: `data/raw/<출처>/`, `data/images/<출처>/`, `data/catalog/lumi-pi-v2.jsonl`·`lumi-pi-v3.jsonl`·통합 `lumi-pi-unified.jsonl`(+ `-report.json` 축별 채움률, 이미지 `data/images/lumi-pi-unified/`). 만드는 명령은 위 카탈로그 빌드 순서를 따른다.
- 저장소에는 스크립트와 요약만 올린다. 참여자 정보·동의서·원시 응답·실행 DB는 커밋하지 않는다.
