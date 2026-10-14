# StyleMate · HCI_HANDSOME

StyleMate는 텍스트·이미지 상호작용과 우리가 설계한 장·단기 메모리 시스템으로 원하는 패션 아이템을 찾아주는 에이전트 연구 프로젝트다. 아이템·조건별 취향을 축적하고 지속적 선호와 현재 요구를 구분해 추천에 활용한다. 핵심은 이 시스템을 사용하는 에이전트의 아이템 선호 판단이 사용자의 판단을 얼마나 충실하게 재현하는지 평가하는 것이다.

## 현재 상태와 기술 스택

- 중간보고서용 Project overview·Project objective와 RQ 분리 방향은 [연구 기준](docs/master.md)의 2026-10-14 사용자 동의·설명을 반영한다. RQ1은 설계한 메모리 시스템을 통한 취향 판단의 재현, RQ2는 텍스트·이미지로 취향 정보를 얻는 방식이다. 구체적인 RQ 문안·평가 방법은 Proposed이며 기존 비교·평가는 보존했다. 실제 선호 판단 재현·추천 품질은 아직 사용자 평가 전이다.
- [시스템 동작 설계](docs/workflow.md)는 Figma 화면에서 확인한 구성, 구현 제안, 미정 사항을 구분한다. 실행 중인 앱의 명세로 해석하지 않는다.
- [Issue #2의 로컬 프로토타입](docs/shopping-memory-prototype.md)은 Python 3.11+·SQLite 저장, 장·단기 메모리 context, 일반 쇼핑용17개 목표 feature, CLI와 오프라인 테스트를 제공한다. 실행 의존성은 표준 라이브러리이며 제품 화면·인증·상품 검색/추천 서비스는 구현하지 않았다.
- OpenAI Responses API adapter는 주입된 가상 HTTP 응답으로 연결·검증한다. Issue #2 구현 당시 사용자의 **실제 호출은 나중에**라는 선택에 따라 API 키를 읽거나 실제 LLM을 호출하지 않았다. 기본 demo/rule 실행은 네트워크를 사용하지 않는다.
- [Codex Luna 사전 테스트](artifacts/luna-memory-preflight/README.md)는 2026-10-14 사용자가 선택한 `gpt-6-luna` 에이전트로 합성 자연어 입력8/목표 context10개를 처리한 별도 실험이다. 후보 분해·현재 코드의 조건 보존과 추가 추론/질문 수준을 구분하며 제품 Responses 실호출·입력 UI 구현·일반 사용자 정확도 평가를 뜻하지 않는다.
- [개발자용 Chat/Memory/Feature Map 관찰 도구](docs/developer-memory-inspector.md)는 세 패널로 LLM 추출 후보·확인/장기 동의·실제 SQLite/context·목표값/근거 변화를 관찰한다. `gpt-6-luna` Codex CLI를 실제 호출하는 로컬 도구이며 소비자 UI·참조 이미지·상품 추천 기능과 구분한다.
- [Issue #1의 메모리 설계](docs/memory-design.md)와 [구현 계획](docs/memory-implementation-plan.md)은 2026-10-13 Accepted v0.2의 설계·가상 검증 기록이다. 현재 실행 DTO와 같은 JSON 형식이 아니며 핵심 확인/동의·범위·보관 원칙을 이어받았다.
- [목표 feature 계획](docs/target-feature-inference-plan.md)의 방향은 2026-10-14 사용자가 승인했다. 일반 쇼핑에 맞춘 축소·구현 위임의 범위와 65+9에서17개로 줄인 이유는 [ADR 0003](docs/decisions/0003-consumer-shopping-prototype.md)에 기록했다. 현재 실행 계약은 프로토타입 문서와 코드가 정본이다.
- 기존 산출물은 Markdown과 HTML 문서다. HTML에는 CSS·JavaScript와 Markdown 원문이 포함되어 있으며, 생성기 표기는 `Answer me with HTML 0.4.6`이다. 재생성 도구와 명령은 저장소에 포함되어 있지 않다.
- 개발 절차 검증에는 Python 3.11 이상과 GitHub Actions를 사용한다. 제품 스택 선택은 작업 요청·팀 논의에서 제안·승인하고 필요한 경우 ADR로 기록한다. 관련 Issue가 있으면 함께 연결한다.

## 문서와 폴더

| 경로 | 역할 |
|---|---|
| [AGENTS.md](AGENTS.md) | Codex의 작업·승인·검증 규칙 |
| [docs/engineering-workflow.md](docs/engineering-workflow.md) | 담당 작업별 브랜치 → 기획·구현 → 테스트 → PR → 리뷰·병합 절차 |
| [docs/master.md](docs/master.md) | 현재 연구 목적·문제 정의, 기존 RQ 비교·평가와 Proposed 정렬안 |
| [docs/workflow.md](docs/workflow.md) · [HTML](docs/workflow.html) | 제품의 화면·상태 흐름과 구현 제안 |
| [docs/memory-design.md](docs/memory-design.md) · [구현 계획](docs/memory-implementation-plan.md) | Issue #1의 메모리 결정표·계약·보관/삭제·연구 경계와 승인 후 구현·검증 순서 |
| [docs/target-feature-inference-plan.md](docs/target-feature-inference-plan.md) | 승인된 방향·전체 feature 설계/확장 참조와 원래 계획 기록 |
| [docs/shopping-memory-prototype.md](docs/shopping-memory-prototype.md) · [ADR 0003](docs/decisions/0003-consumer-shopping-prototype.md) | Issue #2의 소비자용 실행 계약·축소 이유·로컬 명령·LLM 연결 경계 |
| [src/stylemate_memory/](src/stylemate_memory/) · [tests/](tests/) · [pyproject.toml](pyproject.toml) | 실제 SQLite·context·목표 추론·Responses adapter·CLI와 오프라인 단위/통합 테스트 |
| [docs/developer-memory-inspector.md](docs/developer-memory-inspector.md) · [로컬 서버](src/stylemate_memory/inspector.py) · [Codex 연결](src/stylemate_memory/codex_llm.py) | 개발자용 세 패널·실제 Codex 추출/목표 호출과 확인/동의·근거·로그 관찰 |
| [docs/decisions/0001-memory-boundaries.md](docs/decisions/0001-memory-boundaries.md) · [0002](docs/decisions/0002-memory-prototype-storage.md) | 범위/동의/삭제와 최소 저장/조회/배치 처리의 Accepted ADR |
| [schemas/memory-contract.schema.json](schemas/memory-contract.schema.json) · [가상 사례](schemas/examples/memory-cases.json) | Accepted v0.2 계약·fixture. 제품/모델/DB 검증과 구분 |
| [scripts/validate_memory_design.py](scripts/validate_memory_design.py) | JSON Schema·가상 정책의 정합성 검사 |
| [docs/research-landscape.md](docs/research-landscape.md) · [HTML](docs/research-landscape.html) | 선행 연구 조사와 평가 제안 |
| [Assignment/Readme.md](Assignment/Readme.md) | 과제 자료의 사용 범위. 이 문서가 제외한 PDF는 개발 기준으로 사용하지 않는다. |
| [Assignment/Figma.url](Assignment/Figma.url) | 기존 디자인 참조 |
| [.github/ISSUE_TEMPLATE/](.github/ISSUE_TEMPLATE/) | 필요할 때 사용하는 Feature Request·Bug Report 양식 |
| [.github/pull_request_template.md](.github/pull_request_template.md) | 짧은 PR 설명을 위한 선택 안내 |
| [.github/workflows/repository-checks.yml](.github/workflows/repository-checks.yml) | 저장소 문서·워크플로 구성 검사 CI |
| [scripts/check_repository.py](scripts/check_repository.py) · [메모리 CI](.github/workflows/memory-tests.yml) | 저장소 검사와 Python 3.11/3.14 오프라인 테스트·가상 데모 CI |

Markdown을 문서 내용의 정본으로 사용한다. 대응 HTML이 있으면 같은 작업에서 본문과 내장 원문을 함께 갱신하고 브라우저로 확인한다. 개발 절차는 `engineering-workflow.md`, 제품 동작 설계는 `workflow.md`에서 관리한다.

## 개발 시작

1. 팀원은 최신 `main`을 기준으로 담당 작업의 새 브랜치를 준비한다. 브랜치 이름에 Issue 번호나 특정 도구 이름을 넣을 필요는 없다.
2. 담당 작업의 목표·범위·완료 조건을 정하고 기획·구현한다. Codex를 쓰면 요청과 관련 자료를 전달하고 구현·테스트 계획을 확인한다. 중요한 설계 변경은 사용자 승인 후 진행한다.
3. 필요한 테스트와 diff 검토를 마치고, 담당자가 Commit·Push 후 PR을 연다. 변경 목적·핵심 변경·검증 결과를 간단히 설명한다.
4. 팀원 리뷰를 반영하고 최신 변경을 검증한 뒤 `main`에 병합한다.

Issue 등록·연결, 별도 기획 문서, 정형 PR 문서·체크리스트는 필수가 아니다. 기존 Issue 양식과 PR 안내는 필요할 때 사용한다. AI의 Commit·Push·원격 PR 생성·병합 등은 명시적인 요청이 있을 때만 수행한다. 개인 Mac 경로·복귀 노트 관리 규칙은 각자의 개인 AI 지침에서 관리하며 저장소 공통 규칙에 포함하지 않는다.

단계별 완료 기준, ADR 기준, 리뷰 요청 예시는 [개발 워크플로](docs/engineering-workflow.md)를 따른다.

## 프로토타입 실행과 검사

Python 3.11 이상에서 실행 의존성 설치 없이 가상 사용자 흐름을 확인한다. 실제 모델이나 사용자 데이터를 사용하지 않는다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.cli demo --synthetic
PYTHONPATH=src python3 -m stylemate_memory.cli features
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

지속 DB·항목별 쓰기·목표값·향후 명시적 OpenAI 호출 설정은 [현재 실행 문서](docs/shopping-memory-prototype.md)를 따른다. 실제 호출·의미 품질 평가와 구조/가상 연결 테스트를 구분한다.

## 개발자용 관찰 도구

개발자용 관찰 도구는 다음 명령으로 연다. 기존 Codex 로그인과 모델 사용 권한이 필요하며 실제 모델을 호출한다. 기본 URL은 `http://127.0.0.1:8765`, DB는 OS 임시 폴더에 생성된다. [실행·확인/저장 흐름·한계](docs/developer-memory-inspector.md)를 따른다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.inspector
```

## 저장소와 역사적 설계 검사

저장소 루트에서 실행한다. 추가 Python 패키지는 필요하지 않다.

```sh
python3 scripts/check_repository.py
git diff --check
```

검사 범위와 한계는 [테스트 절차](docs/engineering-workflow.md#4-testing)에 설명되어 있다. 제품 기능 테스트와 HTML 화면 검토는 별도로 수행한다.

메모리 설계 검증은 별도 가상환경에서 실행한다. 실제 모델의 해석·사용자 동의 진위·DB 원자성·물리 삭제·연구 효과를 검증하는 명령이 아니다.

```sh
python3 -m venv /tmp/stylemate-memory-check
/tmp/stylemate-memory-check/bin/python -m pip install -r scripts/requirements-memory-design.txt
/tmp/stylemate-memory-check/bin/python scripts/validate_memory_design.py
```

설계 당시 실행 결과는 [초기 검증 기록](docs/memory-implementation-plan.md#7-이번-실행-결과와-한계), AC별 근거와 최신 문서 검증은 [Issue #1 문서 마무리 기록](docs/memory-implementation-plan.md#8-2026-10-14-issue-1-문서-마무리)에 있다.

## GitHub 적용 상태

선택적인 Issue 양식·PR 안내와 CI 정의는 저장소 파일로 제공한다. GitHub에 적용하려면 Commit·Push 및 기본 브랜치 반영이 필요하다. 이 안내만으로 현재 원격 Actions 실행 결과·브랜치 보호·권한 설정이 확인됐다고 보지 않는다.

팀에서 필요에 따라 적용할 PR·검사·리뷰 설정은 [GitHub 설정 안내](docs/engineering-workflow.md#최초-적용과-github-설정)에 정리되어 있다.
