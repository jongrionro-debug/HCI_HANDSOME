# 메모리 구현 계획과 검증 기록

- 상태: **Accepted — 2026-10-13 설계·기술·P0–P6 계획의 역사적 기록**. 2026-10-14 사용자가 목표 feature 방향의 구현·소비자용 축소를 위임했다. 실제 범위·축소 DTO·검증은 [현재 실행 문서](shopping-memory-prototype.md)와 [ADR 0003](decisions/0003-consumer-shopping-prototype.md)을 따른다. 아래 예정 모듈/전체 운영이 모두 구현됐다는 뜻이 아니다.
- 승인 근거: 2026-10-13 · 현재 채팅의 승인 질문(D01–D12·ADR 0001/0002·보관 기간·Python+SQLite 최소안)에 사용자가 **“권고안 전체 승인”**으로 응답했다.
- 기준: 2026-10-13 · `codex/1-memory-design` · HEAD `77f38f28a1e0c43bde96f9f46b961cbc4b737a7b` + 이번 미커밋 설계 자료, 기존 `AGENTS.md` 변경
- Related Issue: [#1](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/1)
- 동작 정본: [memory-design.md](memory-design.md) · 이유: [ADR 0001](decisions/0001-memory-boundaries.md), [ADR 0002](decisions/0002-memory-prototype-storage.md)

## 1. 이번 산출물과 후속 경계

이번 브랜치는 D01–D12 최종 선택·대안·트레이드오프, Accepted ADR, 계약·가상 사례·검증기, 제품 흐름/HTML·README 연결과 사용자 승인된 구현 계획을 제공한다. 2026-10-13 전체 승인 회신으로 Issue #1의 설계·계획 완료 조건을 충족했다. 원격 Issue 상태는 변경하지 않았다. 제품 코드·SQLite DB·공개 API·실제 LLM·배포·참여자 수집은 추가하지 않는다.

| 이번 파일 | 책임 |
|---|---|
| [memory-design.md](memory-design.md) | 결정표, 입력→판단→쓰기→조회→UI, 보관·삭제, 연구 경계, C01–C13 기대 사례 |
| [memory-contract.schema.json](../schemas/memory-contract.schema.json) | 단일 Accepted v0.2 스키마, 객체별 $defs, 구조·필드 제약 |
| [memory-cases.json](../schemas/examples/memory-cases.json) | 가상 사용자·현재 입력 근거와 상태, 정책 시나리오·기대값·부정 fixture |
| [validate_memory_design.py](../scripts/validate_memory_design.py) | 스키마와 가상 정책의 정합성 검증. 제품 저장/모델 실행은 하지 않음 |
| [검증 의존성](../scripts/requirements-memory-design.txt) | 재현 가능한 schema validator 설치 |
| [workflow.md](workflow.md) · [HTML](workflow.html), [README](../README.md) | 기존 화면 근거와 승인된 메모리 상세 설계의 연결 |

### 1.1. 2026-10-14 사용자 목적 구체화 — 목표 feature 추론용 context

사용자는 제공한 「최종 Feature Map」을 아이템 feature 추출의 기준으로 삼고, 장·단기 메모리를 LLM context로 전달하려는 목적을 설명했다. 추가 확인에서 메모리 context를 받은 LLM의 추론 대상은 **“사용자가 원하는 아이템의 목표 feature 값”**이라고 명시했다. 이번 메모리 작업의 소비자는 이 목표값 추론 단계다. 사진·상품 정보에서 기존 아이템의 실제 속성을 추출하는 단계와 목표값 추론 단계는 구분한다.

참고 원본은 사용자가 제공한 Downloads의 `b3e544f7-9c17-4fe7-b81d-00ad57e411fc_최종_Feature_Map.pdf`(9쪽)다. PDF의 전체 텍스트와 9쪽 렌더를 확인했다. 원본 PDF를 저장소로 복사하지 않았다. 이 PDF는 `Assignment/Readme.md`가 제외한 과제 PDF와 다른 사용자 지정 작업 자료다.

**사용자가 지정한 방향:** 대화·이미지 선택 근거 → 장기 기본 취향과 현재 요청의 단기 조건 → 유효한 기억 조회·충돌 해결 → feature 추론용 context → LLM의 목표 feature 제안. LLM 제안은 사용자 확인·동의 없이 기억으로 저장하지 않는다. 기존 D01–D12·보관 기간·SQLite 선택·외부 모델 미도입 원칙은 유지한다.

사용자의 계획 작성 요청에 따라 [목표 feature 추론 계획](target-feature-inference-plan.md)에 다음을 구체화했다. 작성 당시 Proposed였으며 이후 방향 승인·구현/축소 위임을 받았다. 2026-10-13의 Accepted 범위에 새 실행 DTO를 소급해 포함하지 않는다.

- item 16그룹·65 attribute와 outfit 9 attribute의 연결·직접 대응/추론/미정 처리 계획.
- 기존 기억의 재사용과 target selector·canonical feature key의 계약 확장 경계, 대상별 조회/충돌 순서.
- context·목표값 출력 예시, 값/연산/상태·근거와 버전 검증, 모델 제안의 자동 저장 금지.
- F0–F5의 예정 파일·의존·검증 순서와 후속 Issue 로컬 초안·AC-F01–AC-F11.

새 key/selector·충돌 규칙·입출력 계약은 ADR 0003의 사용자 위임과 현재 실행 문서에 기록한다. [Issue #2](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/2)는 쇼핑용17개 속성·SQLite·context·목표 inference·LLM 연결 코드를 구현하며, 기존 P1–P5의 필요한 저장/조회/삭제 검증을 적용한다. 실제 LLM 호출은 사용자가 나중으로 정했고 전체 UI는 이번 범위가 아니다.

2026-10-14 **이전 목적 구체화 작업**의 실제 문서 검증: `python3 scripts/check_repository.py` **PASS**(Markdown 링크146·HTML 원문쌍4·Issue Form2·PR양식1), `git diff --check` **PASS**. 당시 문서/노트5개의 공백·로컬 링크52개 검사도 **PASS**. 현재 계획 작성의 최신 검증은 [후속 계획의 기록](target-feature-inference-plan.md#11-이번-계획-검증과-남은-승인)을 따른다. 이 과거 기록을 이번 제품/모델 실행으로 보고하지 않는다.

## 2. 승인 후 최소 구현의 책임·입출력

아래 경로는 **예정 파일**이며 현재 존재하는 제품 코드가 아니다. 이번 승인된 계획에 따라 후속 구현 Issue에서 구현한다. 최소 Python 모듈만 정하며 전체 웹앱 스택까지 확정하지 않는다.

| 모듈·예정 경로 | 입력 → 출력·책임 | 실패·검증 |
|---|---|---|
| `src/stylemate_memory/contracts.py` | 스키마 객체 → 검증된 내부 타입/오류. 서버가 IDs·사용자를 채움 | 필드/format/unknown 필드·참조·기간 검사, schema mutation tests |
| `request_service.py` | 인증 user+new/resume/close/cancel/clone → Request/revision | 빈 입력·전송 멱등·소유권·kind·날짜 재확인·보관 만료 |
| `evidence.py`, `intent.py` | 현재 이벤트+제시 snapshot+문맥 → IntentDecision | 인용·과거·모델 동의 거부, 내용/범위 대응. 초기 fake/rule adapter, 실제 모델 없음 |
| `policy.py` | decision+trusted evidence+현재 상태 → 검증된 Batch/질문 | confirm와 approval 분리, 이미지 요소, 전이/계보/중복·삭제 closure |
| `store.py`, `migrations/0001_memory.sql` | Batch+CAS → item/event/result 또는 전체 실패 | SQLite 제약·prepared parameters·트랜잭션·원자성·멱등·재시도·lock 오류 |
| `retrieval.py` | user/request/facts/시각/예산 → ContextResult | inactive/타사용자/다른 요청·기간 제외, 조건unknown, 관련성·충돌·사본·예산 |
| `retention.py`, `deletion.py` | 보관 시한/확정 삭제 범위 → 차단·삭제 job/완료 | 원문·snapshot·파생·journal·영수증, 실패 뒤 재시도, 과거 재유입 |
| `orchestrator.py`, `ui_adapter.py` | request/profile revision+context → panel/저장 결과/추천 갱신 상태 | 늦은 결과·오래된 모달 폐기, 실제 성공 목록, empty profile |
| `study_adapter.py` | synthetic study/trial namespace+조건 → unified/split context | 교차 오염 금지·동일 입력/후보·임시 이월 차이. 실제 연구 프로토콜과 구분 |
| `cli.py`, `tests/`, `pyproject.toml` | 가상 시나리오 실행·테스트 | 네트워크 없는 로컬 데모. 실데이터·인증 구현으로 주장하지 않음 |

공개 API는 최소안에서 만들지 않는다. 내부 함수는 인증 문맥을 별도 인자로 받으며 payload의 `user_id`를 신뢰하지 않는다. 통합 시 runtime에서 검증한 evidence와 fixture의 수동 oracle를 구분한다. 후속 외부 모델 adapter는 읽기/제안만 허용하고 모델/가격/전송·보관은 별도 승인한다.

## 3. 저장 경계·실행 순서·복구

예정 저장 집합은 requests, user profile revision, memory items, item별 evidence snapshots, batch receipts, 내용 없는 events, 삭제 jobs·경계 metadata다. 추천 기록은 사용/제외 IDs·버전·이유만 보관한다. 원문은 요청 보관 시한에 한정하고 장기 동의 snapshot과 분리한다. 내부 FK/같은 사용자 제약과 삭제 cascade를 DB 수준에서도 검증한다.

쓰기에는 `BEGIN IMMEDIATE` 같은 명시 트랜잭션 경계, expected request/profile revision과 item version 검사, staged actions 전체 검증, item/event/result 동시 commit이 필요하다. 실패 시 rollback 뒤 실제 상태를 다시 읽는다. 저장 처리 내부에 외부 모델 호출을 넣지 않는다. 모델 결과를 받은 뒤 최신 버전을 재검사한다. 저장 성공 뒤 UI 전달이 실패해도 같은 batch ID로 최초 result를 복원한다.

delete는 먼저 접근 차단·삭제 범위 job을 확정하고 idempotent 삭제를 수행한다. DB 행과 참조 제거, cache 무효화, SQLite 정리·잔여 journal 확인 뒤 완료한다. 실패하면 차단을 유지하고 미완료를 보고한다. `secure_delete=ON`·지속 WAL 없음·삭제 후 VACUUM을 최소 후보로 검증하되 실제 사용하는 SQLite 버전의 삭제 범위를 확인한다. 민감 내용이 별도 FTS/벡터 shadow table에 남는 구조는 만들지 않는다. 단순 SQL DELETE를 실제 전체 삭제의 증거로 사용하지 않는다.

## 4. 의존 순서와 단계별 완료 기준

| 단계 | 의존·변경 파일 | 완료 근거·테스트 |
|---|---|---|
| P0 · 설계 승인 | D01–D12·ADR·기간/파라미터·최종 검토 | **완료 — 2026-10-13 “권고안 전체 승인” 회신**, ADR/계약/문서 Accepted. 원격 이슈는 미변경 |
| P1 · 계약·요청 경계 | P0 → contracts/request/evidence·pyproject | 현 fixture 이식, timezone 자정·기간 경계·새 요청/재개/복제·소유권·스키마 부정 테스트 |
| P2 · 쓰기·저장 | P1 → policy/store/migration | 후보/confirm/promote/direct long/replace/withdraw. CAS·같은 ID 재시도·다른 본문·두 actions 중 실패·이벤트 실패 주입·DB 재접속 결과 |
| P3 · 조회·추천 문맥 | P2 → retrieval/orchestrator | 실제 저장된 객체에 조회·조건/기간·중복·동일/서로 다른 우선순위 충돌·상한/문자 예산. 조건 변경·profile 변경 후 stale 결과 폐기 |
| P4 · 보관·삭제 | P2/P3 → retention/deletion | 시간 주입 만료·배치 삭제 closure·사용 중 차단·재시도·원문 없는 snapshot·DB/journal/캐시 탐색·오래된 summary 재조회 없음 |
| P5 · 가상 동작 연결 | P1–P4 → cli/ui/study adapters | 직접/이미지/빈 설정 → 요청 → 추천 → subset 저장 → 다음 요청·수정·철회·삭제의 통합. unified/split fixture namespace 격리 |
| P6 · 후속 범위 결정 | P5 결과 | 실제 UI·인증·모델·업로드·외부 저장·참여자 연구가 필요하면 각각 요구·권한·비용·테스트와 ADR/프로토콜 별도 검토 |

P1–P5의 모듈 경계는 한 프로세스 안에서 구현 가능하다. 기능별 독립 서비스·브랜치·배포를 자동으로 만드는 계획이 아니다. 규모·실행 명령·테스트는 구현 Issue의 AC와 연결한다. 날짜·담당자·진행률은 지정하지 않는다. 목표일 **미정**.

## 5. 실행·CI 계획

현재 설계 검증 명령:

```sh
python3 -m venv /tmp/stylemate-memory-check
/tmp/stylemate-memory-check/bin/python -m pip install -r scripts/requirements-memory-design.txt
/tmp/stylemate-memory-check/bin/python scripts/validate_memory_design.py
python3 scripts/check_repository.py
git diff --check
```

별도 Python 가상환경을 사용하며 전역 제품 의존성을 설치하지 않는다. schema 검증은 Draft202012Validator와 FormatChecker를 활성화한다. 의존성이 없으면 완전한 schema 검증을 통과했다고 보고하지 않는다. 설치 실패·미실행과 정책 fixture 결과를 구분한다.

현재 CI에는 문서 검사가 있다. 승인된 후속 계획에 따라 검증 dependencies 설치+memory validator 실행 단계를 추가할 예정이며, 이번에 GitHub Actions를 실행/활성화했다고 주장하지 않는다. 제품 구현 시 Python 3.11 기준 환경에서 단위/SQLite 통합 테스트를 추가한다.

예정 제품 명령(현재 실행 불가):

```sh
# 후속 P1–P5 구현 뒤 제공할 명령
python -m unittest discover -s tests
python -m stylemate_memory.cli demo --synthetic
```

CLI는 temp DB와 가상 evidence만 사용한다. 실제 원문·연구 데이터 경로를 기본 인자로 삼지 않는다. 제품 UI·빌드/브라우저 테스트는 해당 스택 선택 후 추가한다.

## 6. AC별 완료 근거

| AC | 검토 자료·검증 근거 | 현재 상태 |
|---|---|---|
| AC1 결정 완결성 | 설계 3절 D01–D12, 두 ADR, C01–C13 | 충족 — D01–D12 전체 최종 선택·이유·영향과 사용자 승인 근거 기록 |
| AC2 데이터 계약 | 설계 4절, schema의 각 객체·필드, 객체/참조 fixture | 충족 — 계약 채택·스키마/참조/claim 정합성 검증, 아래 실제 결과 기록 |
| AC3 쓰기 정책 | 설계 6–7절, 초기/이미지/동의/선택저장 전이 사례 | 충족 — 쓰기 정책·가상 사례 검증. 실제 모델·UI 구현은 후속 범위 |
| AC4 읽기/결합 | 설계 5·8절, 소유권/기간/충돌/중복/예산 context 사례 | 충족 — 결정적 읽기/결합·조회 사례 검증. 실제 DB는 후속 범위 |
| AC5 보관/삭제 | 설계 9절, retention·삭제/재유입 사례 | 충족 — 종류별 시한·삭제 정책 승인, 가상 closure 검증. 실제 저장소 소거는 후속 범위 |
| AC6 실패/경계 | 설계 7절, batch/evidence/result·CAS/멱등/늦은 응답 사례 | 충족 — 권한/실패 계약·가상 검증. 실제 DB failure injection은 P2/P4 |
| AC7 연구 정합성 | 설계 10절, C13, 현 master 불변 | 충족 — 가상 비교·공통 통제·RQ2 경계 정의, 연구 기준 유지. 전체 실험·효과는 후속 범위 |
| AC8 사례 검증 | 설계 11절·실행 가능한 fixture/validator | 충족 — C01–C13·70 시나리오/31 변조 검사, 실제 결과·한계 아래 기록 |
| AC9 구현 계획 | 이 문서 2–5절과 두 Accepted ADR | 충족 — 모듈/파일/의존/오류/검증/명령 계획·최소 기술 및 ADR 승인 |
| AC10 문서/검토 | README·workflow/HTML·정본·ADR·schema·diff 검사 | 충족 — 정본/HTML/계약·검증 근거 정합성, 사용자 전체 승인 회신 기록 |

## 7. 이번 실행 결과와 한계

2026-10-13의 초기 설계 검증과 사용자 승인 반영 후 재검증 기록이다. Python **3.14.5**, 임시 venv `/private/tmp/hci-memory-design-venv`, `jsonschema 4.26.0`·`rfc3339-validator 0.1.4`를 사용했다. Python 3.11에서의 실행은 후속 CI 검증 대상이다.

| 명령·검토 | 실제 결과·범위 |
|---|---|
| venv의 `python scripts/validate_memory_design.py` | **PASS** — Draft202012+FormatChecker, 계약 객체 39개·입력 기반 시나리오 70개·실제 거부한 계약 변조 31개 |
| venv의 `python -m pip check` | **PASS** — broken requirements 없음 |
| 의존성 없는 `python3 scripts/validate_memory_design.py` | 의도한 **exit 1**·설치 안내. schema 검사 없이 성공 표시하지 않는 경계 확인 |
| `python3 scripts/check_repository.py` | **PASS** — Markdown 링크 133개·HTML 원문 쌍 2개·Issue Form 2개·PR 양식 1개 |
| `git diff --check` | **PASS** |
| Python AST·모든 schema/fixture JSON 파싱 | **PASS** |
| 최신 diff·미추적 파일·독립 리뷰 | 기대값 복사·역할/소유권·버전·claim/요청 경계·삭제 관계의 공백을 수정하고 변형 거부를 확인. 기존 `AGENTS.md` 변경은 수정하지 않음 |
| workflow HTML 브라우저 검토 | A/G 본문·Accepted 승인 표시·링크·레이아웃, 테마/밝기 전환 확인. 복사 handler가 내장 Markdown과 같은 텍스트를 전달함을 검사. 화면은 기존 문서이고 제품 UI가 아님 |

시나리오는 `input`으로 상태/조작을 제공하고 정책 모델이 계산한 전체 결과를 `expected`와 비교한다. 사례 ID·기대값으로 결과를 만들지 않는다. 확인/동의와 claim 대응은 가상의 trusted snapshot을 쓰며 자연어 의미를 실제 판별하지 않는다. 멱등 replay·다른 본문 충돌·CAS·실패 주입 rollback·조회 필터/조건/충돌/사본/예산·지역 자정/DST·기억 삭제 후 파생 그래프/영수증·과거 재유입 거부/새 동의·시험 namespace 비교를 로컬 모델에서 확인했다.

검증 모델은 서비스가 관리할 전체 운영을 구현하지 않는다. 요청·계정 전체 삭제, 실제 DB/journal/파일/백업 소거, 보관 만료·영수증 TTL 스케줄러, 다중 프로세스 동시성, 실제 UI·인증·외부 모델·이미지 해석은 미실행이다. 이들은 P1–P5의 제품 구현 검증에 남는다. 삭제 증거는 가상 항목·snapshot·의존 그래프와 메타데이터 경계에 한정한다. 승인된 계약과 실제 운영 완료를 구분한다.

schema·fixture 검증은 제품 DB·API·인증·추천 모델·이미지 이해·물리 삭제·사용자 연구 효과를 검증하지 않는다. CI·Figma 최신 화면·외부 모델 호출·실데이터 수집은 실행하지 않는다. 이번 승인 반영에서도 원격 Issue 종료·Commit·Push·PR 생성·게시·배포는 수행하지 않았다.
