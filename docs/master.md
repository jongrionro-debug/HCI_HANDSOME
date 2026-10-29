# LUMI 프로젝트 기준과 실행 안내

설계·연구·현재 구현·실행 방법은 이 문서에서 관리한다. 개발 작업 규칙은 [AGENTS.md](../AGENTS.md), 허용값의 정본은 [Feature Map JSON](../output/feature-map/park-2025-feature-map.json)이다. CSV는 JSON에서 생성하는 보기용 자료로 사용하고 별도로 수정하지 않는다. 각 주제는 해당 절에서만 갱신하며 다른 문서는 링크로 연결한다.

- [기준과 자료](#기준과-자료)
- [시스템 설계](#시스템-설계)
- [저장·입출력 계약 v1](#저장입출력-계약-v1)
- [이미지·텍스트 인터랙션](#이미지텍스트-인터랙션)
- [Feature Map](#feature-map)
- [연구와 평가](#연구와-평가)
- [현재 구현과 실행](#현재-구현과-실행)
- [다음 작업](#다음-작업)

## 기준과 자료

시스템 이름은 **LUMI**다. **시스템·연구 설계의 source of truth는 중간보고서**다(2026-10-28 사용자 지정). 보고서가 정하지 않은 속성 사전은 [ADR 0004](decisions/0004-adopt-park-2025-feature-map.md)의 사용자 승인으로 구체화했다. 발표자료·Figma는 보조 자료이며 보고서보다 우선하지 않는다. 보고서 원문 PDF와 승인·검증 기록은 보존한다.

설계와 현재 구현을 구분한다. 보고서가 정하지 않은 저장 기간·조회 예산·모델·제품 스택을 확정 요구사항으로 만들지 않는다. 문서나 오프라인 fixture의 검사 통과를 실제 모델 의미 품질·추천 품질·사용자 효과로 확대하지 않는다.

| 자료 | 역할 | PDF 쪽수 | 바이트 | SHA-256 |
|---|---|---:|---:|---|
| [Team4_mid-term_report.pdf](sources/Team4_mid-term_report.pdf) | 시스템·연구 설계 기준 | 20 | 737,007 | `97cdd6791d4aed737d3faae93d46e26ef112d06346ecef34b3a3c3af4b8a69f5` |
| [Team4_mid-term_presentation.pdf](sources/Team4_mid-term_presentation.pdf) | 발표용 보조 자료 | 14 | 41,281,335 | `5b708cbef817a999fec1b1ee5ba0c2119ed7d07e9d08164b53146521bf1d2248` |

두 PDF는 기존에 인계된 원본을 보존한다. 쪽수는 표지·목차를 포함한 PDF 페이지다.

[Figma · LUMI.WEB · 298:2](https://www.figma.com/design/LAU2SC2gHCR1jlCh41K7PD/?node-id=298-2)는 화면 배치·조작을 구체화할 때 참고하는 UI 자료다. 보고서 3.7의 동작과 충돌하면 보고서를 우선하고 구현 전에 차이를 확인한다. 이번 정리에서 Figma의 현재 화면을 새로 검증하지 않았다.

### 보고서 참조 위치

| 작업 | 보고서 위치 |
|---|---|
| 목표·연구 질문 | 1~2장 · pp. 3–4 |
| 입력 해석·장단기 메모리 | 3.2 · pp. 5–6 |
| 현재 요청에 관련된 기억 조회 | 3.3 · p. 6 |
| 목표 Item Feature Map·충돌 처리 | 3.4 · pp. 6–7 |
| 실제 상품 속성·필수 조건 필터·선호 랭킹 | 3.5 · p. 7 |
| 선택 이유·확인·메모리 갱신 | 3.6 · p. 7 |
| 온보딩·새 요청·이미지 탐색·저장/종료 UI | 3.7 · pp. 8–9 |
| 사용자 연구·측정·분석 계획 | 4~5장 · pp. 10–16 |
| 후속 구현·평가 | 6장 · p. 16 |
| 설문 원문 | 7장 · pp. 17–20 |

### 결정 기록과 보관 자료

| 기록 | 현재 적용 범위 |
|---|---|
| [ADR 0001](decisions/0001-memory-boundaries.md) | 확인·이후 활용 동의 분리, 요청 범위·교체/철회/삭제·보관 경계 |
| [ADR 0002](decisions/0002-memory-prototype-storage.md) | Python·SQLite 기반, 배치/버전/멱등·조회/삭제 설계 근거. 역사적 v0.2 JSON Schema 자체가 현재 실행 형식은 아님 |
| [ADR 0003](decisions/0003-consumer-shopping-prototype.md) | 현재 17개 사전·로컬 신뢰 호출자·읽기 전용 모델 제안과 축소 실행 계약 |
| [ADR 0005 · Accepted](decisions/0005-evidence-linked-memory.md) | 2026-10-29 A0 실행 요청으로 1차 로컬 구현 기준 채택. 공통 인터페이스만 정의됐으며 저장·모델·검색·UI 연결은 단계별 미구현 |

확정 사전과 후속 이관에는 [ADR 0004](decisions/0004-adopt-park-2025-feature-map.md)를 추가로 적용한다. ADR 0003은 현재 실행 코드의 기록으로 보존하며 이번 문서 반영으로 대체 구현이 완료됐다고 보지 않는다.

[archive](../archive/README.md)는 과거 설계·RQ 검토·과제·설명·검증 자료이며 현재 개발 기준이 아니다. 당시 내용·승인·결과는 그대로 보존한다. 과제 작성 브랜치 전체를 개발 기준으로 가져오지 않는다. 이전 독립 User Preference Map·후보 5개/2:1:2·별도 Agent 구성·과거 RQ 비교안을 현재 필수 요구사항으로 승계하지 않는다. [2026-10-29 통합 전 문서](../archive/docs/consolidation-20261029/)도 같은 방식으로 보관한다.

## 시스템 설계

```text
사용자 입력 → Input-to-Memory Model → 단기 메모리
                              └→ 내용 확인 + 별도 이후 활용 동의 → 장기 메모리
현재 요청 + 관련 단기·장기 메모리 조회 → 목표 Item Feature Map
→ 상품별 Item Feature Map과 비교·검색 → 추천 → 선택·수정·필요한 확인 ↺
→ 사용자 최종 선택·종료 / 별도 장기 저장 선택
```

보고서 3장의 설계 요약이다. 현재 요청의 명시 조건이 기존 취향과 충돌하면 이번 목표에 우선 반영하고 장기 취향은 보존한다. 이미지 선택·반복 선택·최종 확정만으로 장기 메모리를 바꾸지 않는다.

### 메모리와 피드백 원칙

보고서 3.2~3.7의 요구사항이다.

- 기억의 내용, 대상 옷·상황, 직접 발화/시스템 추정, 원래 발화·선택 근거를 연결한다. “상의는 여유핏, 바지는 슬림핏”을 전역 핏 하나로 합치지 않는다.
- “빈티지한 느낌”은 표현과 맥락을 보존한다. 근거 없이 특정 색·원단의 확정 선호로 바꾸거나 모르는 속성을 채우지 않는다.
- 단기는 현재 요청의 요구·상황·선택·수정·확인 중인 해석을 다룬다. 새 요청에 이전 요청의 단기를 자동 적용하지 않는다.
- 장기는 내용 확인과 이후 활용에 대한 별도 동의가 필요하다. 반복 선택·내용 확인·최종 아이템 확정은 장기 갱신 동의가 아니다.
- 현재 명시 요구가 장기 취향과 충돌하면 이번 목표에서 우선하고 장기 원본을 보존한다. 충돌하지 않는 장기 선호는 함께 활용한다.
- 이미지 선택은 선택 사실의 근거다. 모든 속성 선호나 미선택 후보의 비선호를 뜻하지 않는다. 이유 해석이 다음 추천을 바꿀 때 필요한 질문/비교를 제공하며 확인하지 못한 이유는 미확인으로 둔다.
- 상품 속성이 미확인이면 필수 조건을 충족했다고 판정하지 않는다. 결과가 없으면 조건 완화를 임의로 실행하지 않고 사용자에게 조정 선택을 제공한다.
- 최종 선택·탐색 종료·장기 저장은 별개의 사용자 결정이다. 저장하지 않고 끝내거나 아이템 선택 없이 종료할 수 있어야 한다.

### 장단기 메모리 핵심 설계안

**2026-10-29 A0 · 1차 로컬 구현 기준 승인, 실행 연결 미구현.** 사용자가 공통 규칙과 TASK A0를 실행하라고 요청하면서 아래 방향과 v1 계약을 제한된 로컬 구현 기준으로 채택했다. 공통 Python 인터페이스 정의와 실행 기능 구현은 구분한다. 결정 이유·승인 범위는 [ADR 0005](decisions/0005-evidence-linked-memory.md), 실제 동작은 [현재 구현과 실행](#현재-구현과-실행)을 따른다. 보고서의 RQ·평가·이미지 선택 흐름과 기존 확인·동의·삭제 경계는 유지한다.

#### 기억 표현과 정본

**장단기는 적용·활용 범위이고, 사건·취향·가설은 내용의 종류다.** 요약이나 반복 선택을 거쳤다고 장기 활용 권한이 생기지 않는다. 다음은 논리 모델이며 별도 DB나 에이전트 세 개를 뜻하지 않는다.

| 구성 | 보존할 내용 | 적용 원칙 |
|---|---|---|
| 입력·선택 근거 | 필요한 발화 구절과 최소 맥락, 선택한 후보·이미지 부분·해당 버전의 참조, 관찰 시각 | 선택 사실과 이유 해석을 구분. 전체 속성 선호·미선택 비선호로 확대하지 않음 |
| 기억 항목 | 독립적으로 확인·수정 가능한 취향·요구·상황 문장, 대상, 조건, 기간, 긍정/회피·강도·연산 | 단기는 해당 요청에만, 장기는 확인과 별도 이후 활용 동의를 받은 내용에만 적용 |
| 해석 가설 | 선택 이유나 모호한 표현의 시스템 해석, 근거와 대안, 미확인 상태 | 확인 질문의 후보. 모델 자신감·반복 횟수는 확인이나 동의가 아님 |
| 현재 요청 상태 | 목표·필수 조건·수정사항, 유효 기억 참조, 미해결 질문 | 유효 근거에서 재구성하는 작업 맥락. 새 요청에 이전 단기·가설을 자동 이월하지 않음 |

기억의 정본은 **최소 자연어 내용과 근거·적용 범위·확인/동의 상태**다. PI/FEA 매핑은 선택적인 해석이며 사전 버전·근거·지정/추론/미정 상태를 연결한다. 매핑이 없어도 “빈티지한 느낌”을 보존할 수 있어야 한다. 문장을 확인했다고 특정 PI/FEA 값까지 확인한 것으로 보지 않는다. 의미가 일대일인 명시값의 정규화는 직접 근거를 유지하되, “빈티지”에서 특정 소재를 정하는 해석은 추론으로 구분한다. 목표 Feature Map은 조회 뒤 생성하는 결과이며 그 결과를 새 사용자 발화나 장기 취향으로 재저장하지 않는다.

필드 역할은 아래와 같이 구분한다. 후속 구현의 구체 필드·입출력 계약은 [저장·입출력 계약 v1](#저장입출력-계약-v1)에서 관리한다.

| 필드 묶음 | 필요한 정보 |
|---|---|
| 식별·버전 | 소유 사용자, 항목/근거 ID, 요청 ID, 항목·요청·프로필·저장 형식 버전 |
| 내용·적용 | 기억 종류, 최소 내용, 대상 옷/slot, 상황 조건, scope, 유효 시작/종료·보관 시한 |
| 출처·확인 | 직접 발화/선택/시스템 추론의 출처, 근거 참조, 내용 확인 이벤트, 별도 이후 활용 동의와 동의한 내용·대상·조건 snapshot |
| 상태·관계 | 후보/활성/교체/철회, supports·derived_from·supersedes 등 근거 관계. 다른 사용자의 항목과 연결하지 않음 |
| 사전 해석 | 선택적인 PI/FEA 값, 해석 근거·상태·사전/매핑 버전. 미지원 표현을 새 enum으로 만들지 않음 |

#### 쓰기·확인·장기 활용

1. **근거 접수·후보 생성:** 현재 요청 안에 최소 발화/선택 근거를 연결하고, LLM은 기억 문장·대상·조건·선택적 매핑·가설을 제안한다. 사전 밖 표현은 매핑 미정으로 남긴다. 원문/선택 참조·소유권·형식·사전 값은 코드가 검증한다. 이미지 처리 전에는 선택 근거 형식과 가상 입력만 정의한다.
2. **이번 요청 반영:** 명확한 직접 발화는 신뢰된 입력 이벤트가 내용 확인 근거가 될 수 있다. 모호한 범위나 시스템 해석은 확인 전 확정 조건이 아니다. 현재 관찰 도구의 후보 확인 버튼은 이 흐름을 연결하기 전까지 유지한다.
3. **선택 이유 확인:** 해석에 따라 다음 추천이 달라질 때 짧은 질문/비교를 제공한다. 이유를 확인하지 못하면 선택 사실만 유지하며 가설을 확정 선호로 사용하지 않는다. 유효한 발화·상황·선택 사실에서 만든 목표의 추론 제안도 직접 지정 조건과 구분한다.
4. **별도 장기 활용 선택:** 다음에도 사용할 내용·대상·조건을 보여주고 별도 동의로 장기 항목과 독립된 최소 근거 snapshot을 만든다. 요청 slot이나 일회성 조건을 자동 제거해 동의 범위를 넓히지 않는다. 직접 장기 생성과 단기 승격에 같은 확인·동의 규칙을 적용한다.
5. **수정·교체:** 이번 요청의 예외인지 지속 취향 변경인지 구분한다. 의미 변경은 새 항목과 필요한 새 확인·동의로 연결하고 이전 항목·요약·색인의 적용 상태를 함께 갱신한다. 반복 선택·최종 추천 확정은 장기 갱신 이벤트가 아니다.

LLM은 DB 쓰기·동의·최종 상태를 결정하지 않는다. 기존 `MemoryStore.apply_batch()`의 원자성·멱등·버전 검사를 근거/관계 갱신에도 확장한다. 근거 접수 뒤 추출이 실패하면 미처리 상태를 표시하며 후보·확정·목표 생성 성공으로 보고하지 않는다.

#### 조회와 목표 Feature Map

조회는 상품 검색과 별개의 **사용자 기억 검색**이다. 다음 순서를 고정하고 점수로 권한·범위·필수 조건을 뒤집지 않는다.

1. **유효성 필터:** 소유권 → 활성/확인·장기 동의 → 현재 요청 또는 허용된 장기 범위 → 기간/보관 → 대상·상황 조건을 검사한다. 선택 사실의 확인은 이유의 확인이 아니다. 미확인 가설은 별도 질문 입력으로만 다룬다.
2. **직접 조건 확보:** 현재 명시 요구와 유효한 필수 조건을 먼저 확보한다. 현재 요구가 장기 취향과 충돌하면 이번 목표에서만 우선한다. 같은 우선순위 충돌은 최신성·유사도만으로 해소하지 않고 질문으로 남긴다.
3. **관련 후보 조회:** 구조화 조건은 SQL로, 자유 표현은 키워드·의미 검색으로 조회해 후보를 합친다. 초기에는 결정적 순위 결합을 사용하고 별도 학습형 관리자·LLM 재순위 모델은 도입하지 않는다.
4. **근거 묶음 구성:** 항목과 필요한 대상·조건·예외·근거를 함께 가져온다. 같은 발화/선택의 중복 요약을 독립 선호로 여러 번 세지 않는다. 요약은 유효 항목에서 재생성하고 원본을 대체하지 않는다. 현재 장기12/단기20개·6,000자 예산은 비교 기준이며 새 구조의 최적값이 아니다. 필수 조건을 담지 못하면 잘라내지 않고 보류한다.
5. **목표 해석·검증:** 관련 근거를 고정 PI/FEA 사전에 매핑하고 값·대상·조건·지정/추론 상태를 검증한다. Brand 전체 목록·Price 경계·타 품목의 미정 규칙을 생성해 채우지 않는다. 매핑이 정해지지 않으면 기억은 보존하고 해당 목표는 미정으로 둔다.
6. **최신성 재검사:** 응답 적용 전 요청/프로필·사용 근거/기억·사전·색인 버전을 확인한다. 수정·철회·삭제·만료나 불완전한 색인으로 근거가 달라지면 이전 응답을 적용하지 않는다. 검색된 과거 요약도 새 사용자 근거가 될 수 없다.

목표에는 어떤 현재 요구·장기 취향을 반영했는지, 제외·일시 대체·상충한 이유를 연결한다. 모델에는 필요한 내용과 최소 참조만 전달하며 내부 사용자 식별자·동의 원문 전체·불필요한 대화를 보내지 않는다. 조회 채널 실패는 사용 불가/부분 조회로 표시하고 필요한 근거가 없으면 목표 생성을 보류한다. 다른 모델·서비스로 자동 전환하지 않는다.

#### 저장·파생 자료·삭제

Python·SQLite를 정본으로 유지하며 근거·항목·관계·동의 snapshot을 같은 저장 경계에서 관리한다. 관계 표현을 위해 그래프 DB를 추가하지 않는다. 색인·임베딩·요약은 원본 ID/버전에서 다시 만드는 파생 자료이고, 조회·요약·재색인이 원본의 동의나 보관 시한을 갱신하지 않는다.

- 근거·가설·파생 자료에도 원본의 소유권·요청 scope·유효성·보관 경계를 전파한다. 서로 다른 scope/동의 범위의 내용을 한 장기 요약으로 합치지 않는다.
- 요청 삭제/만료와 장기 항목 삭제를 구분한다. 독립 동의한 장기 항목은 그 최소 snapshot으로 유지할 수 있지만 요청의 전체 대화·선택 이력을 복제해 보관하지 않는다. 장기 snapshot은 동의한 내용·대상·조건에 한정한 독립 근거로 두어 원 요청 삭제가 장기 항목의 근거 단절을 일으키지 않게 한다. 일반 파생 자료처럼 단기 원문의 보관 시한을 연장하는 방식으로 만들지 않는다. 장기 항목 철회/삭제는 기존 promote 가족과 파생 자료에 함께 적용한다.
- 철회는 즉시 조회에서 제외한다. 삭제는 관련 근거 부분·사본·요약·색인·캐시·목표 참조까지 처리한다. 혼합된 근거/요약에서는 대상 내용을 제거하고 남은 근거로 재구성한다. 단순 supports 연결과 삭제 전파가 필요한 복제/파생 관계를 구분해 무관한 기억의 연쇄 삭제를 막는다.
- 색인은 원본 버전과 대조해 오래되거나 삭제된 적중을 차단한다. 재시작·재색인·재시도도 과거 요약/모델 출력에서 기억을 재생성하지 않는다. 파생 자료·저장소 정리에 실패하면 삭제 완료로 표시하지 않는다.

보관 기간·삭제 영수증은 [기존 실행 계약](#메모리-쓰기-계약)을 유지한다. 임베딩의 외부 전송·이미지 바이트 보관·백업·예약 정리·인증/공개 API·운영 DB 접근은 이 기획으로 실행하지 않는다.

#### 핵심 스택과 도입 범위

| 역할 | 승인한 1차 로컬 구현 방향 | 연결 위치·범위 |
|---|---|---|
| 정책·저장 | 기존 Python·SQLite, 항목별 관계·버전, 원자적 batch | `store.py` 확장. 별도 DB·메모리 제품·멀티 에이전트 프레임워크는 추가하지 않음 |
| 입력·목표 해석 | 교체 가능한 공통 complete/extract/propose adapter. 기본 실행은 fake, 명시적 OpenAI 설정의 기본 모델 후보는 `gpt-6-luna` | `llm.py`·`codex_llm.py`와 `inference.py` 검증 확장 예정. Responses API 연결 코드는 후속 C1이며 실제 호출·키 접근은 이번 승인에 포함되지 않음 |
| 기억 검색 | SQL 필터 + 키워드/별칭 + 교체 가능한 의미 검색 adapter | 구조 검색 기준선을 만든 뒤 같은 합성 한국어 질의에서 누락 개선·오탐·비용을 비교. 최초 연결은 fake adapter, 실제 임베딩 모델/의존성은 비교 결과로 선택 |
| 요청 맥락·요약 | 근거 ID/버전으로 재구성하는 현재 상태와 제한된 근거 묶음 | 초기에는 결정적 묶음/축약. LLM 오프라인 요약은 별도 효과 검증 전 필수 경로로 넣지 않음 |
| 사용자 제어 | 현재 반영 내용·미확인 가설·다음 활용 선택의 분리 | 관찰 도구에서 상태 변화를 먼저 확인한 뒤 보고서 3.7 소비자 UI에 연결 |
| 상품 공급·소비자 화면 | 표준 로컬 JSON/JSONL 가져오기, 기존 로컬 HTTP와 별도 HTML/CSS/JavaScript | 크롤러·외부 저장 서비스·인증/공개 배포는 제외. 실험용 선택이며 최종 제품 스택 확정은 아님 |

**한국어 의미 검색 모델과 새 조회 예산 수치는 아직 선택 전**이다. 구조 검색만으로도 동의·요청 격리·표현 보존이 검증돼야 하며, 이를 의미 검색까지 구현된 상태로 보고하지 않는다.

#### 선행연구에서 가져오는 범위

| 근거 | 적용 관점 | 도입 경계 |
|---|---|---|
| [MemoCRS](https://arxiv.org/abs/2407.04960) | 관련 개인 선호 조회와 공통 지식 분리 | 협업 지식을 사용자 확인 취향으로 취급하지 않음 |
| [Hindsight](https://arxiv.org/abs/2512.12818) | 관찰·해석 분리, 근거·시간을 고려한 복합 검색 | 전체 제품/그래프 스택·자동 신념 갱신을 도입하지 않음 |
| [LightMem](https://arxiv.org/abs/2510.18866) | 입력 필터링과 통합 작업을 요청 추론에서 분리 | 자동 장기화·수면형 예약 작업을 필수로 두지 않음 |
| [AgeMem](https://arxiv.org/abs/2601.01885) | 쓰기·조회·수정·맥락 정리를 하나의 관리 문제로 설계 | 강화학습 정책이나 모델에 동의/삭제 결정을 맡기지 않음 |
| [AgentMemRec](https://arxiv.org/abs/2610.34673) | 후보 조회·순위·근거 묶음 구성을 분리 | 논문의 학습 모델·평가 수치를 LUMI 성능으로 재사용하지 않음 |

위 기억/QA 연구는 설계 참고이며 LUMI의 추천 적합성·통제감·표현 부담에 대한 증거가 아니다. [보고서의 평가 계획](#보고서의-평가-계획)은 유지하고 아래 기술 검증은 구현의 보조 검증으로 둔다.

### 저장·입출력 계약 v1

**2026-10-29 A0 · 인터페이스 고정, 실행 연결 미구현.** 계약 이름은 `lumi-memory-v1`이며 저장 형식 버전과 사전 버전 `park-2025-source-v1`을 구분한다. 사용자 실행 요청으로 아래 제한된 로컬 구현 기준을 승인했다. Python/JSON 필드·함수 경계는 [contracts.py](../src/stylemate_memory/contracts.py), 공통 오류 이름은 [errors.py](../src/stylemate_memory/errors.py)가 정의한다. 이 절은 현재 `consumer-17-v1` 실행 경로를 변경하거나 DB를 이관한 결과가 아니다. 구조·대안·영향은 [ADR 0005](decisions/0005-evidence-linked-memory.md)에 연결하며 기존 보관·동의·삭제 경계는 유지한다.

#### 공통 형식과 객체 경계

저장은 Python·SQLite, 모듈 간 교환은 UTF-8 JSON으로 한다. 임의 JSON 한 덩어리를 기억 정본으로 저장하지 않고 다음 객체를 분리한다. 아래는 논리 테이블과 필드 계약이며 실제 DDL·색인 구현은 후속 작업이다.

| 객체 | 정본으로 저장할 내용 | 핵심 관계·제약 |
|---|---|---|
| `Request` / `Profile` | 기존 요청 상태·기간·revision과 사용자별 profile revision | 새 요청은 새 ID. 기존 요청 재개와 새 요청 구분 |
| `Evidence` | `kind`, 최소 `quote`/맥락 또는 선택 사실, 대상, 원래 회차·후보 참조 | `kind`: `user_text`, `image_selection`, `ui_response`, `consent_snapshot`. 사용자 입력·관찰 근거이며 모델 출력 자체는 새 근거가 아님 |
| `MemoryItem` | 독립 자연어 내용, 취향/요구/상황 종류, scope·대상·조건·확인·수명 | feature 매핑 없이도 저장 가능. 원래 출처와 확인 여부는 별도 필드 |
| `FeatureBinding` | 기억을 PI 값 또는 FEA 요구 태그에 연결한 해석, 사전 버전·근거·확인 | 기억 내용 확인이 모든 binding의 확인을 뜻하지 않음. 매핑 없음은 binding 목록 `[]`이며 가짜 속성값을 만들지 않음 |
| `Confirmation` / `Consent` | 확인한 내용 또는 이후 활용을 허용한 내용·대상·조건의 최소 snapshot | 목적이 다르므로 별도 객체. `Consent.purpose`는 `future_reuse`, 활성 장기에 필수 |
| `ComparisonRound` / `CandidateSet` / `Feedback` | 제시한 후보 묶음·상품/이미지 버전·비교 축·피드백 종류·선택/텍스트 근거 참조 | 후보 묶음은 발행 뒤 불변. 선택과 같은 회차의 텍스트 근거를 함께 접수 |
| `MemoryLink` / 파생 자료 | supports·derived_from·supersedes, promote 가족, 요약·색인의 원본 ID/버전 | 관계 종류별 삭제 전파를 구분. 파생 자료는 정본이 아님 |

새 사용자별 저장 객체의 공통 메타데이터는 `id`, `user_id`, `request_id`, `contract_version`, `version`, `created_at`, `retention_until`이다. `version`은 1부터 시작하는 정수이며 ID·소유자·시각·상태·보관 시한은 시스템이 부여한다. 장기 항목과 독립 장기 snapshot·장기 Confirmation/Consent의 `request_id`는 `null`, 요청 전용 객체와 TargetMap은 해당 요청 ID다. 기존 Profile은 user_id/revision, Request는 자체 ID/revision 등의 현재 고유 형식을 유지하며 이 공통 필드를 기계적으로 추가하지 않는다. 여러 요청의 원문을 합친 장기 요약은 v1에서 만들지 않는다.

ID는 의미를 담지 않는 opaque 문자열이다. 참조는 `{ "type": "memory", "id": "mem-1", "version": 1 }`처럼 종류·ID·버전을 함께 가진다. 다른 소유자·다른 요청 단기·없는 객체·부적합한 버전을 참조하면 거부한다. 관계나 객체 종류별 고유 필드는 닫힌 목록으로 검증하며 알 수 없는 필드를 조용히 무시하지 않는다. 시각은 timezone을 포함한 ISO 8601, 유효 구간은 기존처럼 `[valid_from, valid_until)`이다. JSON의 bool을 정수 버전으로 허용하지 않는다.

입력 `text`는 일시적으로 처리하고 필요한 원문 구절·최소 맥락만 Evidence에 남긴다. 원문 인용은 실제 입력과 대조하며 없는 원문·모델 요약을 직접 발화로 만들지 않는다. 전체 채팅·모델 원본을 별도 장기 로그로 복제하지 않는다. 최소 근거 준비에 실패하면 선택·텍스트 중 일부만 접수하지 않고 해당 피드백을 미접수로 표시한다.

다음은 1차 로컬 v1의 입력 자원 상한이며 의미 품질·최적 UX 수치가 아니다. 초과는 `invalid_input`으로 거부하고 조용히 자르지 않는다. 기존 보관 자료를 새 상한으로 잘라 이관하지 않는다.

| 항목 | v1 상한 |
|---|---|
| 입력 text·MemoryItem content·Evidence 인용 | 각각 4,000 Unicode code point |
| ID·nonce·사전의 개별 문자열 값 | 각각 128 code point. canonical 사전 값은 추가로 사전 검사 |
| batch actions / source_refs / object_versions | 각각 32 / 64 / 256개 |
| 한 기억의 binding / PI values / conditions | 각각 16 / 32 / 3개. conditions의 key는 occasion/activity/goal로 제한 |
| 모델 추출 candidates / questions | 각각 16 / 3개. 한 번에 질문할 필요성은 별도 정책 |
| CandidateSet cards / feedback selections | 각각 4개. selections는 제시된 카드·부분 중 중복 없는 선택 |
| 내부 JSON 입력 전체 | UTF-8 직렬화 기준 256 KiB. 모델 context 예산은 이 상한과 별개 |

#### 기억과 가설의 저장 필드

| `MemoryItem` 필드 | 형식·규칙 |
|---|---|
| `kind` / `content` | `preference`, `requirement`, `situation` 중 하나 / 비어 있지 않은 최소 자연어 문장. 이미지 선택 사실은 Evidence에 저장 |
| `fact` | situation의 선택적 `{ "key": "occasion", "value": "발표" }`, 나머지는 `null`. key는 occasion/activity/goal이고 value는 비어 있지 않은 문자열. 미확인/없는 fact를 조건 충족 근거로 쓰지 않음 |
| `scope` / `request_id` | `short_term`이면 현재 요청 ID, `long_term`이면 `null` |
| `selector` | `{ "garment_type": "Pants", "slot_id": null }` 형태. garment 종류는 대상 분류이며 PI의 `Type=Slacks`와 다른 수준. 요청 slot은 목표 `target_id`에 대응하며 장기에는 금지 |
| `conditions` | `occasion`, `activity`, `goal` 중 확인된 조건의 문자열→문자열 객체. 조건들은 AND, 미확인 조건은 충족으로 보지 않음. 상황의 추측을 hard 조건으로 만들지 않음 |
| `polarity` / `strength` | `prefer`, `avoid`, `require`, `indifferent` / `soft`, `hard`. indifferent는 명시적 상관없음이며 strength=soft만 허용. 회피와 강도를 별도로 보존하며 모델 해석만으로 필수 조건을 만들지 않음 |
| `origin` / `confirmed` | `explicit`, `inferred` / 실제 bool. 처음 시스템이 추론한 사실은 나중에 사용자가 확인해도 `origin=inferred`를 보존하고 `confirmed`만 변경 |
| `status` | `candidate`, `active`, `superseded`, `withdrawn`. `active`에는 내용 확인 근거가 필요. 삭제는 `deleted` 상태로 원문을 남기지 않고 실제 제거 |
| `source_refs` / `confirmation_ref` | 비어 있지 않은 근거 참조 목록 / 내용 확인 참조 또는 `null`. 명확한 직접 발화도 신뢰된 입력 계층이 확인 snapshot으로 연결할 수 있음 |
| `consent_ref` / `family_id` | 장기는 활성 이후 활용 동의 필수 / 같은 promote 가족의 중복 적용·철회/삭제에 사용하는 시스템 ID |
| `valid_from` / `valid_until` | timezone 포함 시각 또는 `null`. 보관 시한과 별개이며 조회 시 둘 다 검사 |

**가설은 별도 복제 테이블 대신 `origin=inferred`, `confirmed=false`, `status=candidate`인 MemoryItem으로 표현**한다. 직접 발화에서 추출했지만 아직 확인 중인 후보는 `origin=explicit`, `confirmed=false`일 수 있다. 가설을 확인하면 같은 내용 항목을 활성화할 수 있지만 원래 추론 출처를 지우지 않는다. 거절은 철회, 질문 건너뛰기/모르겠음은 피드백에 기록하고 가설을 미확인으로 유지한다. 내용·대상·조건의 의미 수정은 기존처럼 새 ID와 교체 관계로 처리한다.

`Confirmation`은 `memory_id`, 확인한 내용·selector·conditions·기간·강도의 snapshot, 확인을 뒷받침하는 사용자 근거, 확인 시각을 가진다. `Consent`는 독립 장기 `memory_id`, `purpose=future_reuse`, 동의한 동일 의미의 snapshot, 신뢰된 사용자 동의 이벤트 참조, 동의 시각·보관/활용 시한·활성/철회 상태를 가진다. 동의한 문장에 없는 새 해석·대상·기간을 snapshot에 추가하지 않는다.

장기 Confirmation/Consent의 필수 근거는 같은 장기 범위의 독립 snapshot으로 연결한다. 원 요청의 동의 클릭/발화 이벤트는 생성 당시 검증하되, 요청 삭제 뒤 그 원문이나 선택 이력 전체를 필수 외래키 때문에 남기지 않는다. 단기 원문이 사라져도 독립 장기 snapshot으로 확인·동의 범위를 검증할 수 있어야 한다.

단기 승격은 단기 행의 scope 수정이 아니라 같은 가족의 **새 장기 MemoryItem + 독립 Evidence snapshot + Consent**를 한 batch로 생성하는 전이다. 장기 직접 생성도 내용 확인과 별도 동의가 모두 필요하다. 장기 snapshot에는 이후 활용을 허용한 최소 내용과 범위만 두며, 원 요청 삭제 뒤에도 유효한 독립 근거로 유지한다. 장기 항목 삭제는 그 가족·snapshot·사본·파생 자료에 전파한다. 기존 내용 없는 삭제 영수증에는 대상 ID나 원문을 남기지 않는다.

#### PI·FEA binding과 목표 출력

`FeatureBinding`에는 공통 메타데이터 외에 `subject=user_target`, `memory_id`, `registry_version`, `polarity`, `strength`, `origin`, `confirmed`, `status`, `source_refs`, `confirmation_ref`를 둔다. status는 candidate/active/superseded/withdrawn이고 원래 항목·근거가 유효해야 활용할 수 있다. 확인되지 않은 binding은 검증된 soft 추론으로만 사용할 수 있으며 hard 제약·사용자 지정으로 승격하지 않는다. 확인된 binding은 확인 이벤트가 정확한 binding ID/version·값/태그와 방향을 가리켜야 한다.

한 MemoryItem은 독립 의미·대상·조건·요구 방향을 다룬다. “색은 좋고 핏은 싫다”는 서로 다른 항목으로 나누며 binding별 polarity/strength는 그 항목의 의미와 대조한다. 추론 binding을 soft로 두더라도 원래 명시 hard 요구를 삭제하거나 충족했다고 주장하지 않는다. indifferent binding은 사용자 명시 근거로 확인된 경우만 허용하며 질문 건너뛰기나 후보 없음에서 추론하지 않는다. 상품 사실은 `subject=product`인 별도 상품 Map에서 product_id/map_version·출처/검증 근거로 다루며 사용자 binding에 섞어 넣지 않는다. binding 내용은 아래 두 종류를 구분한다. 값이 정해지지 않은 표현은 자연어 MemoryItem만 남긴다.

| binding 종류 | 내용 필드 | 의미 |
|---|---|---|
| PI | `domain=PI`, `feature`(7항목 중 하나), `values`, `match` | 일반 방향의 values는 비어 있지 않은 canonical 문자열 배열이며 값이 하나여도 배열. 명시적 indifferent만 values/match=null로 허용. any/all과 기존 range는 해당 사전·필드가 실행 의미를 지원하는 경우에만 사용 |
| FEA | `domain=FEA`, `category`, `subcategory`, `tag` | JSON 사전의 정확한 category/subcategory/tag 경로. 임의 수치나 성능 값을 넣지 않음. binding의 polarity/strength로 그 요구 태그를 원하는지·피하는지 표현 |

PI 값·FEA 경로는 사전에서 검증한다. `Brand`의 미공개 값이나 미정인 `Price` 경계·타 품목 매핑을 이 계약으로 확정하지 않는다. 새 사전에서 실행할 수 없는 range/값은 원래 의미를 보존한 매핑 미정으로 두며 필수 조건을 충족한 것처럼 실행하지 않는다. PI와 FEA를 37개 평면 속성으로 합치지 않는다.

목표 출력 `TargetMap`은 `contract_version`, `registry_version`, `context_id`, `targets`, `constraints`, `questions`, 내부 최신성 묶음 `basis`를 가진다. 각 target은 `target_id`, 대상 분류 `garment_type`, `product_information`, `consumer_needs`로 나눈다. garment_type은 입력 target에서 복사하며 PI Type에서 역추론하지 않는다. 상품의 관찰/검증 사실은 별도 상품 Map 참조이며 사용자 요구와 같은 객체로 저장하지 않는다.

| 목표 영역 | 값 필드 | 공통 근거 필드 |
|---|---|---|
| `product_information` | 7항목별 `values: null \| canonical 문자열 배열` | `status`, `constraint_ids`, `source_refs` |
| `consumer_needs` | 사전의 category/subcategory/tag 구조를 보존하고 태그별 `preference: null \| prefer \| avoid \| require` | `status`, `constraint_ids`, `source_refs`. preference는 사용자의 요구 방향이며 상품 성능 판정이 아님 |

모든 사전 항목을 출력하며 미정은 생략이나 `[]` 대신 해당 값 필드를 `null`로 둔다. `status`는 다음 규칙을 적용하고 필드별 `constraint_ids`가 가리키는 제약을 연산 정본으로 사용한다.

| `status` | 값 필드 | 규칙 |
|---|---|---|
| `unspecified` | `null` | 원하는 값 미정. PI에서 “검정은 피함”처럼 알려진 회피는 constraints에 남고 원하는 색은 미정일 수 있음 |
| `inferred` | 후보 배열 또는 요구 방향 | 미확인 해석, soft 제안만 가능. 실제 사용자 지정처럼 표시하거나 hard 필터로 사용하지 않음 |
| `specified` | 확인된 배열 또는 요구 방향 | 직접 지정·확인된 binding 근거 필요. 기억 문장의 확인만으로 모든 binding을 지정으로 올리지 않음 |
| `indifferent` | `null` | 사용자가 해당 요청의 soft 선호 축은 상관없다고 명시. 기존 hard require/avoid와 장기 원본은 자동 취소하지 않음 |
| `not_applicable` | `null` | 실제 대상에 적용되지 않는다는 근거가 있음 |
| `unsupported` | `null` | 실행 사전/매핑 지원 범위 밖. 타 품목의 미제공 값 등을 비적용으로 숨기지 않음 |
| `conflict` | `null` | 같은 우선순위 상충. 대안·근거·질문을 보존하고 임의로 한 값을 고르지 않음 |

constraints에는 ID, target, binding 참조와 내용, polarity/strength, 대상·조건, 확인/추론 상태, 근거 참조를 넣는다. PI의 서로 다른 any/all 연산을 한 값 목록으로 평탄화하지 않는다. 현재 코드의 집계 `match=null`과 새 값 미정 `values=null`은 다른 의미이며 새 출력은 개별 constraints의 match를 사용한다. 값과 판단 상태, 긍정/회피·강도는 서로를 대신하지 않는다.

#### 입력·모델 제안·쓰기·조회 경계

신뢰된 로컬 호출자가 `user_id`를 별도 인자로 전달한다. 아래 JSON은 내부 모듈 계약이며 공개 HTTP API·인증·배포 계약이 아니다. UI/모델이 저장 ID·소유권·보관 기간·최종 확인/동의를 임의 지정할 수 없다.

| 경계 | 입력/출력 | 검증·쓰기 권한 |
|---|---|---|
| 사용자 피드백 접수 | 입력: `contract_version`, `batch_id`, `request_id`, `expected`, `actions`. action의 종류는 텍스트/선택/질문 응답 | 후보 묶음·참조·원문을 검증하고 최소 Evidence·Feedback을 같은 batch에 저장. 입력 text는 현재처럼 최대 4,000 Unicode 문자이며 조용히 자르지 않음 |
| 모델 후보 추출 | 입력: 현재 최소 근거·유효 기억·대상·사전. 출력: `candidates`, `questions` | `ExtractedCandidate`는 임시 `candidate_key`, content/kind/fact, selector/conditions/condition_quotes, polarity/strength·origin_hint, scope_hint, source_ids/quote, bindings를 가진다. 인용은 실제 제공 근거와 대조하며 origin_hint·scope_hint는 상태/쓰기 권한이 아님 |
| 후보 저장·사용자 조작 | 후보는 코드가 원문·참조를 검증해 단기 미확인으로 생성. 확인·승격·교체·철회·삭제는 별도 command | 기존 `apply_batch()`의 원자성·멱등·기대 revision/항목 version 검사 확장. 모델이 confirmed·Consent·실제 쓰기 command를 생성하면 거부 |
| 기억 조회 | 현재 request·targets와 `expected` 기준으로 snapshot 조회 | 유효 memory/binding·최소 근거·직접 constraints·질문을 조립. 가설은 별도 질문용, hard 직접 조건은 우선 확보 |
| 목표 제안 | 모델 출력은 `suggestions`, `questions`만. suggestion은 target·binding 내용·source IDs·reason | 직접 제약을 코드가 결합하고 값/대상/근거/최신성 검증 후 TargetMap 생성. 모델이 지정/확정/hard 상태를 만들지 않음 |

모델에는 제공된 근거 ID만 참조하게 하고 내부 user ID·revision 묶음·Consent snapshot 원문 전체·raw DB 행은 전송하지 않는다. 실제 모델 실행은 별도 사용자 요청 때만 수행한다. 모델이 제안한 인용/내용의 형식·존재 검사는 의미·동의 진위 검증과 구분한다.

`expected`는 `request_revision`, `profile_revision`, `object_versions`를 가진다. 객체 수정에는 해당 항목 버전, 선택에는 회차·후보 묶음 버전이 필수다. 발행된 묶음에 기록된 **모든** 상품 Map·이미지 버전도 현재 상태와 대조해 후보 간 비교 근거의 변경을 감지한다. `candidate_id`는 회차 안의 제시 카드, `product_id`는 실제 상품, `target_id`는 찾는 아이템을 구분한다. UI 선택은 candidate ID를 보내고 상품/이미지 참조는 검증된 후보 묶음에서 해석한다.

CandidateSet은 공통 메타데이터와 `target_ids`, `cards`, `compared_features`, 생성 근거 `basis`를 가진다. 각 card는 `candidate_id`, `target_id`, `product_id`, `product_map_version`, `image_id`, `image_version`, 표시 순서를 가진다. ComparisonRound는 해당 set ID/version, 질문 ID 목록, active/replaced/closed 상태를 가진다. set을 바꿀 때 기존 내용을 수정하지 않고 새 set을 발행하고 회차 버전을 올린다. expected의 set ID/version이 이 불변 카드 목록과 전체 버전 묶음을 지칭하므로 별도의 임의 상품 사실이나 digest를 UI에서 받지 않는다.

회차 안의 질문은 시스템이 부여한 ID, 표시 문구, 대상·binding/후보 참조, 선택지, open/answered/skipped 상태로 보존한다. 모델이 제안한 질문을 표시했다고 사용자 근거가 생기지는 않는다. 확인/동의 이벤트는 사용자가 본 내용·대상·조건 snapshot과 그 표시 버전에 연결하고, 단순 질문 응답·내용 확인·명시적 future_reuse 동의를 구분한다. 확인·동의 action은 이 신뢰된 이벤트 참조를 받으며 모델 출력의 bool이나 “평소” 힌트로 이벤트를 생성하지 않는다.

`actions`는 순서가 있는 비어 있지 않은 목록이다. 피드백 접수 batch에는 `submit_feedback` 하나를 두고, 기억 조작은 confirm→promote 등 여러 action을 같은 batch로 묶을 수 있다. delete는 기존처럼 delete action끼리만 묶는다. batch 전체는 성공 또는 rollback이며 같은 batch ID의 동일 `contract_version+request_id+actions`는 최초 결과를 반환하고 다른 본문은 충돌이다. 같은 본문의 비교는 정규 JSON 의미 기준이며 소유 사용자 범위 안에서 수행한다. expected는 batch 시작 상태를, action의 expected_version은 앞선 action을 반영한 해당 시점 상태를 검사한다. 이미 완료된 동일 작업의 재시도가 새 쓰기를 만들지 않는다.

`op=submit_feedback`의 필드는 `round_id`, `candidate_set_id`, `reaction`, `selections`, `text`, `question_id`다. `reaction`은 `selected`, `none`, `unsure`, `text_only`, `question_skipped` 중 하나다. selected는 하나 이상의 선택이 필요하고 none/unsure/text_only는 선택 목록 `[]`다. text_only는 비어 있지 않은 text, question_skipped는 기존 question ID·선택 목록 `[]`·text=null이 필요하다. none/unsure에는 선택적인 텍스트 설명을 함께 보낼 수 있다. 질문 건너뛰기는 선택/답변·동의를 만들지 않는다. text가 없는 경우는 `null`이며 빈 문자열은 거부한다. 초기 텍스트 입력은 text_only와 비어 있는 selections를 사용하며 비교 이전의 round_id/candidate_set_id는 둘 다 `null`이다. 이미지 반응에는 유효한 회차·후보 묶음이 필수이고 question_id는 실제 질문 응답일 때만 제공한다.

각 selection은 `target_id`, `candidate_id`, `part_ref`를 가진다. 전체 선택의 part_ref는 `null`, 부분 선택은 이미지 ID/버전과 `region_id` 또는 정규화 box를 포함한다. box는 원본 이미지 기준 `[x0,y0,x1,y1]`, 각 값은 0~1이고 양의 면적이어야 한다. 후보에 없는 이미지·대상·범위 밖 좌표나 서로 맞지 않는 부분 참조는 거부한다. 여러 선택의 배열 순서를 선호 순위로 해석하지 않는다.

피드백의 최소 근거 접수와 해석 후보의 확정은 별도 단계다. 근거 접수 뒤 후보 생성/모델 해석이 실패하면 이미 기록된 근거는 유지하고 `interpretation=pending`으로 표시하며 취향 반영 성공으로 보고하지 않는다. 같은 피드백을 다시 접수해 원문/선택을 복제하지 않고 해당 Evidence를 기준으로 재처리한다. 접수 영수증은 최초 접수 결과이고 이후 해석 진행 상태는 별도 조회한다. 후보 저장·확인·동의 command에는 각각 별도의 batch ID를 사용한다.

쓰기 command별 본문은 아래로 제한한다. `user_id`, 실제 lifecycle/version·보관 시한은 본문에서 받지 않는다. 생성용 `memory`는 kind/content/fact/selector/conditions/polarity/strength/valid_from/valid_until만 포함하며 scope·origin·confirmed·상태는 코드가 결정한다. `bindings`는 binding 내용의 제안 목록이고 실제 ID·확인 상태는 코드가 부여한다. 신뢰된 사용자 입력 이벤트 참조로 확인/동의 객체를 같은 action 안에서 생성하므로 새 memory ID를 UI가 미리 지정할 필요가 없다.

| command | 주요 본문 | 적용 규칙 |
|---|---|---|
| `create` | `memory`, `source_refs`, `bindings`, 선택적 `confirmation_event_ref` | 기본은 단기 미확인 후보. 명확한 직접 발화 등 신뢰된 내용 확인 이벤트가 있으면 Confirmation을 생성해 같은 action 안에서 내용 확인 가능 |
| `confirm` | `memory_id`, `expected_version`, `confirmation_event_ref`, `binding_confirmations` | 내용 확인과 명시적으로 확인한 binding ID/version 목록만 활성화. 빈 binding 목록은 문장 확인만 뜻함 |
| `propose_bindings` | `memory_id`, `expected_version`, `bindings`, `source_refs` | 기존 문장의 사전 해석 제안. 원문의 의미·방향·조건과 registry를 검사하며 미확인 해석을 지정값으로 저장하지 않음 |
| `confirm_bindings` | `memory_id`, `expected_version`, binding ID/version 목록, `confirmation_event_ref` | 사용자 확인이나 검증된 일대일 정규화 근거를 해당 binding에만 연결 |
| `promote` | `memory_id`, `expected_version`, `consent_event_ref` | 활성·확인된 단기와 동의 snapshot을 검증해 새 독립 장기 항목 생성. scope를 제자리에서 수정하지 않음 |
| `create_long_term` | `memory`, `bindings`, `source_refs`, `confirmation_event_ref`, `consent_event_ref` | 직접 장기 생성. 내용/범위 확인·동의를 같은 원자적 경계에서 검사 |
| `replace` | `memory_id`, `expected_version`, `memory`, `bindings`, 새 근거·확인/필요한 동의 이벤트 참조 | 같은 scope의 새 의미·ID. 장기 교체는 새 동의 필수. 새 미확인 후보만으로 기존 활성 기억을 교체하지 않음 |
| `withdraw` / `delete` | `memory_id`, `expected_version`, 사용자 조작 근거 참조 | 즉시 활용 제외 / 실제 삭제. 가족과 관련 파생 자료에 전파 |

저장 성공은 `BatchReceipt(outcome=applied|unchanged)`와 revision·변경/근거 참조를 반환한다. 거부는 기존처럼 `StyleMateError`를 발생시켜 전체 rollback하며 부분 성공 영수증을 반환하지 않는다. 소비자 서비스가 이를 `ConsumerResult(outcome=rejected, error=...)`로 변환한다. 근거 접수 여부와 목표 생성 여부는 구분하며 실패한 작업을 성공처럼 합쳐 표시하지 않는다. 삭제 결과·재시도는 내용 없는 기존 영수증 경계를 유지한다. 오류 이름은 `errors.V1_ERROR_CODES`를 사용하고 provider 원문·자격 증명을 노출하지 않는다.

#### A0 공통 인터페이스와 담당 경계

아래는 **후속 세션이 구현할 고정 인터페이스**다. A0에서 실행되는 것은 `validate_ref()`의 작은 참조 형식 검사와 `batch_fingerprint()`뿐이다. TypedDict는 닫힌 필드 목록의 정의이고 런타임 검증기가 아니다. 객체의 모든 키는 기본적으로 필수이며 예외는 `MemoryItem.legacy`(NotRequired)와 Conditions의 선택적 occasion/activity/goal key다. 값 없음은 명시적 `null`, 매핑 없음은 `bindings=[]`다. PI/FEA 이름·허용값은 이 파일에 복제하지 않고 A1의 사전에서 읽는다. 객체별 소유권·의미·권한·원자성 검증은 각 담당 모듈에서 구현해야 한다.

| 담당 | 실제 연결 위치 / 고정 호출 경계 | 입출력·소유권 |
|---|---|---|
| A0/A | `contracts.py`, `errors.py`, master, ADR, 공통 진입점·설정 | 공통 필드·Protocol·오류 정본. 다른 세션은 중복 DTO/API를 만들지 않음 |
| A1/A | `registry.py`: `RegistryPort.describe()`, `validate_binding(binding, garment_type)`, `validate_observation(observation,garment_type)` | `version`과 canonical 사전 JSON, PI/FEA 경로·값·지원 여부. 저장 계약 버전과 별개; 상품 관찰을 사용자 요구 binding으로 위장하지 않음 |
| B1~B4/B | `store.py`: `MemoryStorePort.start_request`, `snapshot`, `apply_batch`, `issue_display`, `record_user_event`, `interpretation_status`, `publish_candidates` | ID·시각·수명·소유권·상태·신뢰 이벤트·관계·원자적 저장/삭제. D의 `CatalogFreshness`를 A가 주입 |
| C1/C | `llm.py`·`codex_llm.py`: `ModelGateway.complete(instructions,payload,schema)`, `extract(ExtractionInput)`, `propose(ProposalInput)` | 출력은 JSON/ExtractionResult/Proposal. `complete`는 좁은 JSON 변환, 도메인 정책은 각 모듈. 기존 CLI bridge는 호환 보존 |
| C2/C | `context.py`, 필요시 `retrieval.py`: `build_context_v1(snapshot,targets,registry=...,semantic=None,char_budget=6000)` | `MemoryContext`의 내부 basis·alias→근거 묶음과 외부 model_input을 분리. SemanticSearch는 유효 후보 ObjectRef만 반환 |
| C3/C | `inference.py`: `infer_v1(context,adapter,registry=...)` | 검증한 직접 constraints + soft 제안 → 전체 PI/FEA `TargetMap`. 모델은 사용자 지정/hard 상태를 발행하지 않음 |
| D1/D | `catalog.py`: `CatalogPort.import_records`, `export_records`, `current_versions`, `resolve_image` | 표준 CatalogRecord, 원자료·상품 Map·이미지의 독립 버전. JSON/JSONL 파일 I/O는 이 포트의 얇은 입출력 연결 |
| D2/D | `catalog_mapping.py`: `build_product_map(record,raw_version=...,registry=...,gateway=...)`; catalog의 `get_product_map`, `save_product_map` | `subject=product`인 ProductMap. raw/map 기대 버전 검증 후 저장, 사용자 MemoryItem과 별개 |
| D3/D | `product_search.py`: `search_products(target_map,target_id,catalog)`; `comparison.py`: `build_candidate_cards(results,target_map,catalog)` | target별 SearchResult → CandidatePlan(cards,compared_features,questions,basis). B가 불변 set·회차를 발행 |
| E1/E, A2/A, E2/E | E fixture/HTTP adapter와 A의 `ConsumerService.state(request_id=None)`, `command(ConsumerCommand)` | 동일 ConsumerState/ConsumerResult. E는 화면·상호작용, A는 실제 서비스·HTTP·trusted user 공급 책임 |

`snapshot(user_id,request_id,contract_version=...)`는 내부 `MemorySnapshot`을 반환한다. 같은 요청의 후보·근거·binding·확인/동의·피드백·회차와 소유한 장기를 포함하며 조회 적격성 판단은 C가 수행한다. `include_closed=True`는 보관 시한 내 종료 요약·별도 장기 활용 화면용이다. 새 요청에 이전 단기·가설을 합치지 않는다. 모델에는 `MemoryContext.model_input`만 전달하며 raw snapshot·내부 basis·동의 원문·실제 사용자 ID를 전달하지 않는다. `source_id`는 호출별 alias이고 코드가 실제 종류/ID/version과 근거 묶음으로 되돌린다.

`apply_batch(user_id,request_id,batch_id=...,actions=...,contract_version=...,expected=...,catalog_freshness=...)`가 v1 쓰기 경계다. 기존 `expected_request_revision`/`expected_profile_revision` 인자는 legacy에서 유지하고, v1 `expected`와 서로 다른 값을 함께 전달하면 `invalid_input`이다. v1의 expected는 필수이며 일반 확인·동의·binding·교체·철회·삭제와 `record_extraction`, `select_final`, `end_request`의 본문은 contracts의 해당 TypedDict로 고정한다. `create`의 `confirmation_event_ref`/`consent_event_ref`도 키는 필수이고 미제공은 null이다. 단기 create에 consent 참조를 붙여 권한을 넓히지 않는다.

**접수와 추출 재처리:** `submit_feedback` 하나가 최소 Evidence·Feedback·`InterpretationState(status=pending)`를 함께 저장한다. Feedback에는 전체 입력 text를 중복 보관하지 않고 최소 Evidence 참조·반응/회차/질문만 둔다. 반환 영수증은 최초 접수 결과이며 이후 `interpretation_status(user_id,request_id,feedback_ref)`로 상태를 읽는다. C의 실패는 같은 근거를 유지하고 pending 상태와 안전한 error를 기록한다. 성공 시 내부 `record_extraction(feedback_ref,extraction_key,result,error)` action으로 후보·질문·complete를 원자적으로 저장한다. 성공은 result만, 실패는 error만 비어 있지 않아야 하며 재시도에는 새 feedback을 만들지 않는다. extraction_key는 서비스가 정한 근거 ID/version+사전 버전+추출 adapter/version의 fingerprint다. 같은 근거/키의 완료 결과는 중복 후보를 만들지 않고, 근거·요청이 달라졌거나 닫혔으면 stale로 거부한다. 모델 출력에서 `record_extraction`을 포함한 DB command·confirmed·consent를 받지 않는다.

**확인·동의 발행 주체:** A의 서비스가 B의 `issue_display()`로 서버 조회에서 만든 `ReviewSnapshot`과 basis를 저장한다. UI에는 `ReviewView(ref,purpose,snapshot)`만 보내며 UI가 보낸 snapshot/digest·모델 bool을 증거로 수입하지 않는다. UI의 `respond_review(display_ref,decision)`를 받은 서비스만 서버 설정의 user_id와 명시적 purpose로 `record_user_event()`를 호출한다. B는 저장된 표시 객체의 소유권·요청·버전·basis·보관 시한을 검사하고 서버 ID를 가진 TrustedUserEvent 참조를 발행한다. accept만 목적에 맞는 확인/동의에 쓰고 decline/skip은 확인·동의를 생성하지 않는다. future_reuse는 별도 표시·별도 action이어야 하며 기본 선택하지 않는다.

내용 확인 이벤트는 해당 문장·대상·조건·기간·강도만, binding 확인 이벤트는 실제 표시한 ID/version·정확한 값/태그·방향만 확인한다. 처음 v1 연결은 명시적 검토 응답을 사용하며 모델 추출을 직접 발화 자동 확인으로 취급하지 않는다. 확인한 추론도 `origin=inferred`는 보존한다. 장기 승격/직접 생성 시 새 장기 ID에 맞춘 독립 최소 display/event/Evidence/Confirmation/Consent snapshot을 같은 batch로 만들고 원 요청을 필수 외래키로 남기지 않는다. 원 이벤트는 생성 시 대조하고, 원 요청 삭제 후에는 동의 범위만 보존한 독립 증거를 사용한다. supports는 활용 근거일 뿐 무조건 삭제 cascade가 아니며 derived_from·promoted_from의 사본/가족은 관련 삭제 전파 대상이다.

**멱등과 전이:** 저장 영수증 키는 `(trusted user_id,batch_id)`이고 fingerprint는 `contract_version+request_id+actions`의 정규 UTF-8 JSON SHA-256이다. object key 순서·공백은 무시하고 배열 순서·문자열·타입은 보존한다. batch_id와 expected는 본문 fingerprint에서 제외한다. 동일 완료 batch는 최신 expected 검사 전에 최초 영수증을 반환하고 다른 본문은 idempotency_conflict다. API command도 `(user_id,command_id)`로 같은 action을 식별하며 서버가 이벤트 ID를 매번 새로 만들어 재시도를 충돌시키지 않는다. `(command_id,display_ref,purpose)`의 발행 이벤트는 한 번만 사용·연결하고 동일 재시도에 같은 참조를 돌려준다. 이벤트만 저장한 중간 상태가 생겨도 도메인 command 재시도는 원자적으로 동일 결과에 도달해야 한다. 삭제 시 일반 fingerprint·원문·대상 ID를 장기 영수증에 남기지 않고 기존 24시간 내용 없는 nonce/tombstone 규칙을 적용한다.

`select_final`은 유효 set의 candidate ID를 실제 상품/목표로 해석해 `RequestState.final_selection`만 바꾸며 요청은 open이다. `end_request`는 별도 전이로 탐색을 closed로 바꾸며 final_selection=null도 허용하고 기존 선택을 보존한다. 두 전이 모두 Confirmation/Consent/장기 기억을 만들지 않는다. closed에서는 새 피드백·재탐색·최종 선택 변경을 막고, 보관 시한 내 요약 읽기와 이미 확인한 내용의 별도 장기 활용·개별 기억 관리만 허용한다. 만료·삭제된 요청에서는 재활용할 snapshot을 발행하지 않는다. 기존 `close_request()`는 legacy 동작을 보존하며 A2가 v1 end_request와 연결한다.

**최신성 공급과 적용:** Basis는 request_id, request/profile revision, object_versions, contract/registry/index version, CatalogVersions, 가장 이른 valid_until을 가진다. B가 객체·요청·현재 시각을, C가 사전/색인·조회 근거를, D의 `CatalogPort.current_versions(product_ids,image_ids)`가 raw/map/image/catalog 버전을 공급한다. A2는 모델/검색 후 재조회하고 B의 쓰기 직전에도 D 공급자를 `catalog_freshness`로 전달한다. 선택 카드뿐 아니라 발행 set 전체의 모든 Map·이미지 참조가 현재 버전과 같아야 한다. 공급자가 없거나 버전/의존성이 누락되면 적용하지 않는다. 변경·철회/삭제·만료·종료·색인 미완료는 stale_context/context_blocked로 보류한다. A2 로컬 서비스는 카탈로그 쓰기와 적용을 같은 lock으로 직렬화한다. 서버가 떠 있는 동안 별도 프로세스에서 카탈로그를 변경하는 운영은 지원하지 않으며 가져오기는 중지 후 또는 같은 서비스 경계에서 수행한다.

**로컬 소비자 경계:** 후속 A2의 고정 경로는 `GET /api/state[?request_id=opaque-id]`, `POST /api/command`, `GET /api/images/{image_id}?version=N`이며 자산은 패키지 allowlist에서만 제공한다. 서버 생성 시 하나의 trusted user_id·외부 DB/상품/이미지 root를 설정하고 HTTP body/query로 user_id·provider·파일 경로·임의 StoreAction을 받지 않는다. 루프백 단일 테스터, Host/동일 Origin·JSON 형식·기존 24,000-byte HTTP body 상한을 유지한다. 내부 JSON 256 KiB 상한은 HTTP 허용량을 늘리는 근거가 아니다. 이미지 요청은 catalog ID/version을 설정 root 안에서 해석하며 traversal/symlink escape를 거부한다. 이미지 공급 ref를 가져오는 크롤러·임의 파일 탐색 API는 만들지 않는다.

`ConsumerCommand`는 contract_version/command_id/request_id/expected/action을 가진다. start_request만 request_id/expected=null이며 나머지는 서버 state의 해당 request/expected를 사용한다. `prepare_review`는 표시 준비일 뿐 확인/동의가 아니다. 수정은 proposed_text를 새 사용자 근거로 검증하고 서버가 교체할 의미를 구성해 다시 표시한다.

| UI action | 허용 payload / 동작 |
|---|---|
| start_request | mode=onboarding 또는 shopping, timezone, targets, text(없으면 null). 텍스트는 최소 근거 접수에 연결하며 가짜 발화를 생성하지 않음 |
| resume_request | op만. 같은 요청·보관 상태 복원; 새 요청 생성과 구분 |
| submit_feedback | FeedbackAction 그대로. 비교/텍스트·선택·부분 선택·질문 응답을 같은 근거 접수로 처리 |
| retry_extraction | feedback_ref. 원문 재접수 없이 pending 해석만 재처리 |
| explore | op만. 현재 유효 조건으로 재탐색. 모델 실패를 다른 provider 성공으로 대체하지 않음 |
| prepare_review | purpose, subject_refs, proposed_text(null 허용). 기억 내용/binding 확인·이후 활용·교체·철회·삭제·요청 삭제의 서버 표시 준비 |
| respond_review | display_ref, decision=accept/decline/skip. 표시 snapshot은 입력받지 않음 |
| select_final | candidate_set_ref, candidate_id. 최종 선택만 기록 |
| end_request | op만. 상품/저장 없이 종료 가능. 온보딩에서 저장 없이 시작할 때도 단기를 다음 요청에 이월하지 않음 |

`ConsumerState`는 state_version/request/requests/expected, phase, operation, memories/cards/reviews/questions, 안전한 error를 반환한다. RequestState는 사용자 ID/DB 행을 포함하지 않는 서비스 조회용 형태이고 내부 MemorySnapshot은 보관 시한·user_id 등이 있는 RequestRecord를 사용한다. 카드 image_id/version이 둘 다 null이면 이미지 없음으로 표시하며 없는 이미지를 만들지 않는다. `operation=interpretation_pending|blocked|no_results|stale|error`를 정상 완료와 구분하고 pending의 접수 성공을 선호 확정으로 표시하지 않는다. UI는 expected/ref를 전송하되 화면 본문에 내부 version·DB·prompt를 나열하지 않는다. E1 fixture와 E2 HTTP adapter가 같은 ConsumerCommand/State를 사용한다.

#### 상품 가져오기와 provenance 계약

JSON은 CatalogRecord 배열, JSONL은 한 줄에 한 CatalogRecord다. `format_version=lumi-catalog-v1`이고 모든 필드는 contracts의 정의를 따른다. source_id/URL/collected_at과 title·description·raw_metadata·garment_type·images·labels를 공급한다. 비어 있는 description은 null, 없는 이미지/라벨은 []로 둔다. 실행 파일은 저장소 밖에서 주입하며 작은 합성 fixture만 저장소에 둔다. 아래는 **형식 설명용 합성 레코드**이며 실제 이미지·상품 공급이나 가져오기 기능 구현을 뜻하지 않는다.

```json
{
  "format_version": "lumi-catalog-v1",
  "product_id": "synthetic-pants-1",
  "source": {"source_id": "synthetic", "url": "https://example.invalid/pants/1", "collected_at": "2026-10-29T12:00:00+09:00"},
  "title": "합성 바지 1",
  "description": null,
  "garment_type": "Pants",
  "raw_metadata": {"supplier_color": "navy"},
  "images": [{"image_id": "synthetic-image-1", "kind": "local", "location": "pants-1.png", "source_revision": "supplied-1", "sha256": null, "regions": []}],
  "labels": []
}
```

catalog는 product_id의 출처 정체성이 다르면 catalog_conflict로 거부한다. 동일 레코드 재공급은 멱등이며 원자료(source/title/description/garment_type/raw_metadata/labels)가 바뀌면 raw_version이 증가하고 이전 Map은 stale다. 상품 Map 저장은 expected_raw_version/expected_map_version을 검사하고 내용이나 기반 raw가 바뀌면 map_version을 증가시킨다. 이미지 source_revision·해시·ref 변경은 image version을 독립 증가시키며 Map 값을 조용히 바꾸지 않는다. 어느 축이든 공개 상태가 바뀌면 catalog_version을 증가시킨다. 수집자가 같은 URL의 바이트를 바꿨으면 source_revision도 갱신해야 한다. catalog의 최신성은 **공급된 revision/해시 기준**이며 원격 이미지 바이트를 실시간 검사했다는 뜻이 아니다. 전체 재가져오기로 빠진 상품을 자동 삭제하지 않고 명시적 갱신/삭제 경계를 통해 처리한다.

ImageSource.regions는 공급자가 제공한 region_id/garment_type/정규화 box 목록이고 미제공은 []다. B는 D의 resolve_image 결과로 이름 있는 부분 참조를 검사하며 없는 region_id를 생성하지 않는다. 사용자가 직접 지정한 box는 범위·면적·이미지 버전을 검사하고 그 위치의 모든 속성이 확인됐다고 해석하지 않는다. 이미지 없는 카드의 전체 선택은 이미지 참조 둘 다 null인 선택 사실로 남길 수 있지만 부분 선택은 거부한다.

ProductAssertion은 PI 관찰(values) 또는 FEA 관찰(present:bool|null), status, provenance 목록을 가진다. 사용자 요구 방향(prefer/avoid/require)과 상품의 관찰값을 섞지 않는다.

| provenance.kind | 최소 근거 / 허용 해석 |
|---|---|
| raw_metadata | source_field·원문 quote. 공급자의 원자료/주장임을 보존; 모델이 새 사실을 채운 것이 아님 |
| provided_label | 누가 제공했는지 verifier와 해당 source_field/evidence_ref. 검증 없이 confirmed로 승격하지 않음 |
| verified_label | verifier·verified_at·evidence_ref와 실제 검증 근거 필수. 근거가 뒷받침하는 범위의 속성만 confirmed 가능 |
| model_interpretation | source_field/quote 또는 이미지 ref에 연결한 해석. inferred, hard 충족 근거로 사용 불가 |
| unknown | 값은 null, 확인 근거 없음. 상품 없음·비적용으로 바꿔 숨기지 않음 |

원문에 직접 적힌 소재/색 등의 기술 속성은 사전 정규화와 근거 검증을 거쳐 확인할 수 있지만, FEA 태그·사진·사용자 희망만으로 보온성/신축성/내구성 같은 성능을 확정하지 않는다. 성능 hard 조건에는 그 성능을 실제 뒷받침하는 검증된 라벨 근거가 필요하다. unknown/inferred/conflict는 hard 충족이 아니다. map 생성은 `complete` gateway를 재사용해도 provenance/성능 판단은 D의 코드가 통제한다. 아직 미정인 Brand 전체/Price 경계·통화·타 품목 값은 unsupported_mapping으로 두고 만들지 않는다.

#### 단계적 전환과 공통 오류

기존 호출에서 contract_version을 생략하면 기존 consumer-17-v1 경로다. 후속 B에서 v1 객체/요청만 명시적 `contract_version=lumi-memory-v1`, `registry_version=park-2025-source-v1`로 만들고 읽는다. C의 새 함수는 `build_context_v1`/`infer_v1`, 모델 adapter도 명시적 v1 구성으로 연결한다. legacy request를 v1 실행처럼 해석하거나 새 사전에서 legacy 값을 조용히 정규화하지 않는다. 혼합·미지원 계약은 쓰기 전에 unsupported_contract로 거부한다. A1의 사전 추가는 기본 CLI·inspector 전환이 아니며 A2에서 v1 진입점을 별도로 연결한다. `stylemate_memory`/`STYLEMATE_` 이름과 기존 호출은 유지한다.

이관의 `MemoryItem.legacy`는 original 원래 항목·옛 registry_version·evidence_status(reference_only/missing)·mapping_status(unmapped/requires_review/equivalent)를 보존한다. 원래 인용이 없으면 Evidence.quote를 합성하지 않고 legacy 자료로 읽을 수 있게 남긴다. legacy confirmation/consent는 원래 의미·대상·기간에만 유효하고 v1 TrustedUserEvent를 소급 발행하지 않는다. 정확한 의미 대응이 없으면 binding=[]와 미정/재확인 상태로 두며 기존 active 의미를 임의의 새 hard 조건으로 실행하지 않는다. Relaxed→Wide, 원단 종류→섬유 원료 자동 변환은 금지다. 이관은 합성 DB에서 의미 보존·실패 rollback·재실행 멱등부터 검증하며 실제 사용자 DB는 이번 범위 밖이다.

오류의 역할은 다음과 같다. 모델/HTTP 오류의 원문은 메시지·장기 로그에 넣지 않는다. 다른 사용자/없는 참조의 응답은 not_found로 통일하고 소유권 정보를 누출하지 않는다.

| 오류 | 의미 |
|---|---|
| invalid_input / unsupported_contract | 닫힌 필드·타입/상한 위반 / 계약 혼합·미지원 |
| not_found / version_conflict / idempotency_conflict | 소유 범위에 없는 참조 / 기대 버전 불일치 / 같은 ID의 다른 본문 |
| confirmation_required / consent_required / invalid_user_event | 필요한 내용/binding 확인·별도 동의 누락 / 서버 표시·목적·이벤트 참조 부적합 |
| unsupported_mapping / registry_unavailable | 사전/품목/연산 지원 밖 / 사전 사용 불가 |
| request_closed / request_expired / stale_context / context_blocked | 요청 수명·최신성·필수 근거 보존 실패 |
| invalid_extraction / invalid_output | 인용·참조·형식·제안 범위 위반. 근거 접수 결과와 분리 |
| catalog_conflict / cleanup_pending | 상품 ID·출처 충돌 / 파생 삭제 실패로 삭제 미완료 |
| provider_* / empty_response | timeout·429·거부·불완전·형식 오류 등 안전한 분류. 자동 provider fallback 없음 |

#### 계약 예제와 이관 확인

다음은 **합성 ID를 사용한 피드백 접수 입력 예제**다. 상품 속성은 발행된 set-1에서 검증하며 입력자가 임의 상품 사실을 덧붙일 수 없다.

```json
{
  "contract_version": "lumi-memory-v1",
  "batch_id": "feedback-1",
  "request_id": "req-1",
  "expected": {
    "request_revision": 4,
    "profile_revision": 2,
    "object_versions": [
      {"type": "round", "id": "round-1", "version": 1},
      {"type": "candidate_set", "id": "set-1", "version": 1}
    ]
  },
  "actions": [{
    "op": "submit_feedback",
    "round_id": "round-1",
    "candidate_set_id": "set-1",
    "reaction": "selected",
    "selections": [
      {"target_id": "pants-1", "candidate_id": "card-A", "part_ref": null}
    ],
    "text": "A의 색은 좋은데 조금 더 좁은 핏이면 좋겠어요.",
    "question_id": null
  }]
}
```

다음은 저장 계층이 생성한 ID/시각/수명 메타데이터를 제외한 **매핑 없는 기억 조회 결과의 부분 예제**다. 이 항목은 지원 feature/values 없이도 보존할 수 있다. evidence-1은 실제 입력에서 검증한 최소 구절이며 confirmed=false라 내용 확정이나 장기 활용은 아직 아니다. `bindings`는 관련 FeatureBinding을 조회한 목록이며 MemoryItem에 중복 저장하는 값이 아니다.

```json
{
  "kind": "preference",
  "content": "빈티지한 느낌을 선호한다.",
  "fact": null,
  "scope": "short_term",
  "request_id": "req-1",
  "selector": {"garment_type": "Pants", "slot_id": "pants-1"},
  "conditions": {},
  "polarity": "prefer",
  "strength": "soft",
  "origin": "explicit",
  "confirmed": false,
  "status": "candidate",
  "source_refs": [{"type": "evidence", "id": "evidence-1", "version": 1}],
  "confirmation_ref": null,
  "consent_ref": null,
  "bindings": []
}
```

다음은 **TargetMap 중 한 target의 일부 필드만 발췌한 출력 예제**다. 실제 출력은 사전의 전체 7항목·30태그를 각 영역에 포함한다. clause-1은 네이비 선호, clause-2는 따뜻한 옷이 필요하다는 확인된 사용자 요구를 표현하며 따뜻한 실제 상품이 확인됐다는 뜻이 아니다.

```json
{
  "target_id": "pants-1",
  "product_information": {
    "Color": {"status": "specified", "values": ["Navy"], "constraint_ids": ["clause-1"], "source_refs": [{"type": "memory", "id": "mem-1", "version": 1}]},
    "Fit": {"status": "unspecified", "values": null, "constraint_ids": [], "source_refs": []}
  },
  "consumer_needs": {
    "Functional": {
      "Protection": {
        "Warmth": {"status": "specified", "preference": "require", "constraint_ids": ["clause-2"], "source_refs": [{"type": "memory", "id": "mem-2", "version": 1}]},
        "Durability": {"status": "unspecified", "preference": null, "constraint_ids": [], "source_refs": []}
      }
    }
  }
}
```

이관에서는 기존 content·feature/values·출처·확인·동의·기간·promote 가족을 보존한다. 현재 확인 동작이 inferred를 explicit으로 바꾼 과거 기록에서 사라진 추론 이력을 복원했다고 주장하지 않는다. 새 계약의 의미·사전 매핑을 확보하지 못한 원래 항목은 원래 버전의 읽기 가능한 자료로 유지하고 임의 변환하지 않는다. 실제 DB 대신 합성 DB로 먼저 검증한다.

구현 전/후 검증에는 매핑 없는 기억, PI/FEA 경로·값, 부분/다중 선택·text 결합, 잘못된/다른 소유자 참조, bool 버전, 내용 확인과 binding 확인의 분리, 미확인 장기 쓰기, scope 변경·조건 확대, 같은/다른 batch 재시도, 실패 rollback, 원본 삭제·재색인·늦은 응답을 포함한다. 예제 JSON 구문 확인과 문서 검사는 SQL 원자성·정책 구현·모델 의미 품질의 검증을 대신하지 않는다. A0의 TypedDict·Protocol과 참조 형식/fingerprint 외의 도메인 런타임 validator·DDL·스키마 연결은 후속 구현이다.

### 이미지·텍스트 인터랙션

**2026-10-29 A0 · 인터랙션 구현 기준 승인, 화면·검색 미구현.** 사용자는 짧은 자유 텍스트 뒤 미정인 Feature Map 값을 구체화할 이미지 후보를 제시하고, 선택과 텍스트 보완을 반복하는 방향을 채택했다. 목표는 **현재 조건에 맞는 실제 상품 예시를 비교하면서 여러 feature의 선호를 함께 좁히는 것**이다. 한 번의 선택에서 얻은 정보는 여러 feature의 가설에 활용하되, 각 값의 확정 여부는 따로 판단한다. 보고서 3.5~3.7을 구체화하며 RQ·비교 조건·과제·설문·장기 동의 흐름은 유지한다.

#### 흐름과 사용자 조작

| 단계 | 사용자 경험 | 시스템 처리 |
|---|---|---|
| 1. 초기 자유 입력 | 필요한 아이템·착용 상황·원하는 느낌을 짧게 입력. 모든 조건을 미리 답할 필요 없음 | 명시 요구와 관련 기억을 정리해 부분 목표 Map 생성. 근거 부족은 [미정값 규칙](#미정값과-점진적-구체화)에 따라 `null` 유지 |
| 2. 이미지 비교 | 현재 요구에 가까우면서 차이를 비교할 수 있는 실제 상품 이미지 확인 | 확정된 필수 조건을 충족하는 후보 중 중요한 미정/미확인 요소를 구체화할 묶음 구성 |
| 3. 선택·텍스트 보완 | 하나 또는 여러 후보 선택, 전체/아이템 부분 선택, 선택 없이 텍스트만 입력도 가능 | 선택 사실·대상과 자유 입력을 같은 회차의 근거로 연결. 선택 즉시 화면을 교체하지 않고 사용자가 반영할 때 함께 처리 |
| 4. 필요한 확인 | 해석에 따라 다음 추천이 달라질 때 짧은 질문이나 비교에 응답. 건너뛰기 가능 | 선택 이유·상충을 확인하고 확인된 내용만 이번 요청에 반영. 설명하지 못한 이유는 가설로 유지 |
| 5. 갱신·재탐색 | “이 느낌으로 더 보기”로 후보 갱신하거나 원하는 상품으로 결정 | 유효 근거로 목표 Map을 다시 만들고 검색. 모든 feature를 채우거나 고정 회차를 마칠 때까지 종료를 막지 않음 |

탐색 화면은 보고서처럼 이미지·선택 영역과 대화 영역을 함께 둔다. **자유 입력은 항상 제공**해 마음에 드는 후보가 있을 때도 “A의 색에 B의 핏이면 좋겠어요”처럼 유지할 부분과 바꿀 부분을 함께 표현할 수 있게 한다. 텍스트가 이미지 선택과 다른 내용이면 임의로 하나를 확정하지 않고 수정 의도와 대상을 구분한다.

“마음에 드는 게 없어요”와 “잘 모르겠어요”를 구분해 제공하고 선택을 강요하지 않는다. 전자는 해당 후보 묶음에 대한 반응이고 후자는 선호를 판단하지 못한 상태이며, 어느 쪽도 개별 속성 전체에 대한 비선호가 아니다. 텍스트 설명 없이도 다른 후보를 보거나 탐색을 끝낼 수 있다. 여러 이미지를 골랐다고 선택 순서를 선호 순위로 해석하지 않는다. 부분 선택은 피드백 대상을 좁히는 조작이며 그 부분의 모든 속성을 확인한 것이 아니다.

후보 없음·판단 보류·질문 건너뛰기·이미지 선택 없이 텍스트만 보냄은 서로 다른 반응 종류로 기록한다. 후보 없음은 다른 후보를 탐색할 수 있는 신호이고 판단 보류/건너뛰기는 해당 해석을 미확인으로 유지하는 신호다. 어느 반응도 그 자체로 속성 비선호나 확정 선호를 만들지 않는다. 텍스트만 보낸 경우에는 실제 텍스트의 근거를 별도로 처리한다.

선택 이유 질문은 매번 띄우지 않는다. 이미 텍스트로 이유가 명확하면 중복 질문 없이 처리하고, 중요한 해석 차이가 있을 때만 “어떤 점이 원하는 느낌에 가까웠나요?”와 현재 비교한 요소·다른 이유·잘 모르겠음 등의 응답을 제공한다. 질문을 생략하거나 건너뛴 것을 시스템 해석에 동의한 것으로 보지 않는다. 선택 사실은 유지하되 미확인 이유를 확정 필터·확인된 상품 사실·장기 승격의 근거로 사용하지 않는다.

#### 비교 후보 구성

1. **조건 충족부터 확인:** 상품별 Feature Map에서 현재 명시 필수 조건과 대상의 적합성을 확인한다. 필수 상품 속성이 미확인이면 충족으로 판정하지 않는다. 선택을 유도하기 위해 필수 조건을 어긴 상품을 탐색 후보로 섞지 않는다.
2. **이번 비교의 초점 선택:** 추천에 영향이 크고 불확실하며 이미지로 비교할 수 있는 요소를 우선한다. 초기에는 색·핏처럼 핵심 1~2개 축을 중심으로 차이를 만들되 다른 feature에서 얻는 정보도 가설로 보존한다. 모든 미정 feature를 별도의 질문으로 순회하지 않는다.
3. **구분 가능한 차이 구성:** 알려진 조건은 유지하고 핵심 비교 축의 값에 차이를 둔다. 비교와 무관한 구도·배경·다른 옷의 차이는 가능한 한 줄인다. 거의 같은 상품만 반복하거나 인기 상품만으로 선호 범위를 좁히지 않는다. 고정된 후보 역할 비율이나 이전 5개/2:1:2 구성을 도입하지 않는다.
4. **실제 데이터의 한계 반영:** 필요한 조합의 실제 상품이 없으면 비교 축을 줄이거나 넓은 탐색으로 제시한다. 비교가 통제됐다고 꾸미거나 없는 상품·허용값을 생성하지 않는다. 라벨 품질이 부족한 속성은 해당 비교의 확정 근거로 쓰지 않는다.

예를 들어 `Type=Slacks`이고 Color/Fit이 미정일 때 비슷한 실제 상품이 확보되면 Navy/Wide·Navy/Straight·Beige/Wide·Beige/Straight를 비교할 수 있다. Navy/Wide 선택은 선택 사실이며 두 값을 모두 확정한 것은 아니다. “둘 다 좋아요”처럼 비교 대상의 의미를 사용자가 확인하면 해당 요청의 선호로 반영하고, 필수라고 하지 않은 선호를 hard 조건으로 바꾸지 않는다.

| 후보 수 | 초기 사용 가정 |
|---|---|
| 기본 3개 | 소수 후보에서 선호 방향 탐색 |
| 필요시 4개 | 색×핏처럼 두 축의 조합을 나눠 볼 필요가 있고 실제 상품이 확보된 경우 |
| 세밀한 비교 2개 | 해석 차이 하나를 확인하는 후속 비교 |

이 수치는 **파일럿에서 조정할 가정**이며 최적 개수나 부담 감소가 입증된 규칙이 아니다. 적합한 후보가 적으면 수를 맞추기 위해 부적합한 후보를 채우지 않는다. 비교 축·화면에서 읽어야 하는 정보·조작 부담을 함께 보며, 전체 Feature Map이나 내부 점수를 기본 화면에 노출하지 않는다.

#### 입력 방식별 역할과 갱신 근거

| 입력/근거 | 주로 다룰 내용 | 구분할 한계 |
|---|---|---|
| 이미지 비교 | 색·실루엣·보이는 디테일·시각적 분위기 | 선택 이유와 해당 상품 전체 속성의 선호는 별개. 보온성·신축성·내구성 등 실제 성능을 사진으로 확인하지 않음 |
| 자유 텍스트·짧은 질문 | 착용 상황, 기능/편안함 요구, 가격 조건, 선택 이유·수정사항 | 사용자의 희망 조건이며 실제 상품 성능의 증거가 아님. 모호한 표현은 원문·맥락과 함께 보존 |
| 상품 정보·검증된 라벨 | 상품의 소재·가격·기능 등 확인 가능한 속성 | 출처·버전을 연결하고 미확인은 유지. 리뷰의 체감과 확인된 성능을 동일시하지 않음 |

각 회차에는 요청/회차·후보 묶음의 안정적인 ID, 선택 대상, 제시한 후보와 상품 Map 버전, 비교한 요소, 반응 종류, 함께 입력한 텍스트와 필요한 시각·버전을 최소 근거로 연결한다. 원하는 아이템의 target ID, 제시 카드의 candidate ID, 실제 상품의 product ID는 분리한다. 부분 선택은 이미지/버전과 대상 부분 참조를 함께 보존해 재렌더링된 좌표만으로 해석하지 않는다. 사용자 목표 요구와 상품 관찰/검증 사실도 근거 종류를 분리해 같은 속성 이름 때문에 섞이지 않게 한다. 구체 필드는 [저장·입출력 계약](#저장입출력-계약-v1)을 따른다.

이미지 파일·전체 상품 이력의 무제한 복제는 전제하지 않으며 [메모리 저장·삭제 경계](#저장파생-자료삭제)를 적용한다. 같은 피드백의 선택·텍스트 근거는 동일한 원자적 batch·멱등 경계로 접수한다. 적용 시 기대하는 회차/후보 묶음·상품 Map·요청/기억 버전을 재검사하고, 후보 교체나 요청/기억 수정 뒤 도착한 오래된 응답은 적용을 보류한다. 근거 접수 뒤 해석이 실패하면 근거의 저장 상태와 미확인 해석 상태를 구분해 표시한다.

사용자에게는 반영한 조건을 짧게 보여주고 수정할 수 있게 한다. 상세 보기에서 “이번 요청”·“참고한 평소 취향”·“확인 중인 해석”을 구분한다. 추론 내용은 확정처럼 표시하지 않고, 별도 확인 없이 오래 보여줬다는 이유로 확정하지 않는다. 필수 조건을 충족하는 상품이 없으면 결과 없음을 알리고 유지·조정·종료를 선택하게 한다. 최종 상품 선택·탐색 종료·장기 활용 동의는 별개다.

#### 설계 근거와 구현 확인

| 근거 | 참고할 점 | 적용 한계 |
|---|---|---|
| [Viappiani et al., AAAI 2006](https://cdn.aaai.org/AAAI/2006/AAAI06-033.pdf) | 예시를 보고 비평하며 선호를 구체화하고 탐색용 제안을 제공 | 주거 검색 사용자 연구이며 시간도 증가. LUMI의 부담·정확도 개선을 입증한 결과가 아님 |
| [Parapar & Radlinski, WSDM 2021](https://research.google/pubs/diverse-user-preference-elicitation-with-multi-armed-bandits/) | 선호를 파악하는 단계부터 후보 다양성 고려 | 논문의 bandit 알고리즘을 필수로 도입하거나 패션 사용자 효과를 주장하지 않음 |
| [Fashion IQ, CVPR 2021](https://research.ibm.com/publications/fashion-iq-a-new-dataset-towards-retrieving-images-by-natural-language-feedback) | 이미지와 자연어 수정 피드백을 결합한 검색 | 데이터·검색 모델 연구를 이 UI의 사용자 부담 검증으로 해석하지 않음 |
| [Park et al., 2025](https://doi.org/10.1186/s40691-025-00435-w) | 세 속성 또는 세 상품을 제시한 구현 선례 | 사용자 시뮬레이터 평가이므로 3개가 사람에게 최적이라는 근거가 아님 |

초기 구현은 합성 상품 Map·선택 이벤트로 후보 구성, 대상별 텍스트 결합, 선택 이유/확정 구분, 없음/모르겠음, 미정 유지, 오래된 응답 차단을 검증한 뒤 실제 이미지·상품에 연결한다. 기존 연구 계획을 유지하며 파일럿에서 조작·질문 부담, 잘못 확정한 값과 수정, 원하는 후보 도달을 함께 살핀다. 채운 feature 수나 턴 감소만을 성공 기준으로 삼지 않는다. 현재 관찰 도구에는 이 이미지 비교·상품 검색·소비자 UI가 구현돼 있지 않다.

## Feature Map

**2026-10-29 사용자 확정: Park et al. (2025)의 상품정보(PI) 7항목과 FEA 소비자 요구 30개 태그를 고정 사전으로 차용한다.** 기존 RQ·비교 조건·과제·설문·평가 계획·이미지 선택·메모리 흐름은 유지한다. 결정 근거는 [ADR 0004](decisions/0004-adopt-park-2025-feature-map.md)다.

| 영역 | 구성 | 허용값·분류의 정본 |
|---|---|---|
| 상품정보(PI) | Type·Brand·Price·Color·Fit·Fabric·Detail의 7항목 | [JSON의 product_information](../output/feature-map/park-2025-feature-map.json) |
| 소비자 요구(FEA) | Functional 8·Expressive 13·Aesthetic 9의 30개 태그 | [JSON의 consumer_needs_taxonomy](../output/feature-map/park-2025-feature-map.json) |

두 영역을 합쳐 37개의 동등한 상품 속성으로 취급하지 않는다. 전체 목록은 [보기용 CSV](../output/feature-map/park-2025-feature-map.csv)로 확인한다. 이 문서에 전체 enum을 다시 복제하지 않는다.

출처: Park, H., Kim, S., Choi, Y., & An, H. (2025). *Application of the FEA consumer needs model in e-commerce: a conversational recommendation system for fashion products*. Fashion and Textiles, 12, 24. [논문 원문](https://doi.org/10.1186/s40691-025-00435-w)의 Table 1(PDF pp. 8–10)은 FEA, Table 2(PDF p. 10)는 PI다. 원문의 영문 이름·값·분류를 보존하고 한국어 표시명을 추가했다. 출처·CC BY 4.0 라이선스·변환 내역·승인 메타데이터는 JSON에 기록한다.

고정 사전은 상품 Map과 목표 Map에서 같은 이름·값·의미로 참조한다. 대화·이미지 선택·부분 선택·관련 메모리는 이 사전에 매핑하는 입력이며 대화 중 새 속성이나 허용값을 추가하지 않는다. 목표의 근거 부족은 미정, 상품의 근거 부족은 미확인으로 유지한다. 이미지 선택만으로 모든 속성 선호를 확정하거나, 방수·보온 같은 성능을 사진만으로 확인된 사실로 만들지 않는다. 기존 확인·별도 장기 활용 동의·현재 요청 우선 규칙도 유지한다.

원문 범위와 아직 정하지 않은 실행 규칙은 다음과 같다.

- 상품정보 값은 **무신사 여성 바지** 기준이다. 이 선택이 기존 연구 과제를 바지로 바꾼다는 뜻은 아니며, 상의·아우터·드레스의 허용값이 원문에 있다고 보지 않는다. 그 범위의 실행 매핑은 아직 제공하지 않는다.
- Brand의 419개 전체 목록은 공개되지 않았다. 예시만으로 전체 enum을 만들지 않는다. Price는 원문 구간 표기를 보존하며 경계값 포함 규칙·통화 코드는 원문 Table 2만으로 확정하지 않는다.
- Fit은 바지 형태이며 기존 `fit`의 Regular·Relaxed·Oversized와 자동 대응하지 않는다. Fabric은 섬유 원료이므로 기존 `fabric`의 Denim·Knit 같은 원단 종류와 단순 치환하지 않는다.
- FEA는 소비자 요구의 의미 분류다. Role 태그를 사용자 나이·직업 추정으로 사용하거나, 리뷰의 체감과 확인된 상품 성능을 동일시하지 않는다.

### 미정값과 점진적 구체화

**후속 구현의 값/상태 계약**이다. 근거가 부족하거나 예측하기 어려운 feature는 값 `null`로 둘 수 있어야 하며, 세션의 텍스트·이미지 선택·필요한 확인을 통해 이번 추천에 필요한 값을 점진적으로 구체화한다. 이는 현재 실행 코드의 JSON이나 DB가 이미 해당 형식으로 바뀌었다는 뜻이 아니다.

| 상태 | 값의 표현 | 의미 |
|---|---|---|
| 미정 | `null` | 판단 근거 부족. 후보 가설은 별도로 보존 가능 |
| 추론 | 후보 값과 미확인 표시 | 시스템 해석이며 사용자 지정/확인과 구분 |
| 지정·확인 | 직접 지정하거나 확인한 값 | 해당 대상·조건·요청 범위 안에서 적용 |

이 `null`은 값 필드의 미정을 뜻하며 상태와 연산 필드는 따로 관리한다. 구체적인 PI의 `values`와 FEA 태그별 `preference`, 지원 범위 밖 상태, 회피-only 제약의 표현은 [저장·입출력 계약](#pifea-binding과-목표-출력)을 따른다. 현재 실행 계약의 `feature.match = null`은 any/all 혼합의 표시 의미이므로 값 미정과 혼동하거나 새 의미로 덮어쓰지 않는다. 상관없음·회피·비적용·상충은 각각의 의미와 근거를 구분하고 단순 미정 `null`로 뭉개지 않는다. 여러 허용값이 가능한 항목의 연산·강도도 보존한다. 새 근거로 기존 해석을 수정하거나 미정/상충으로 되돌릴 수 있으며 값이 채워졌다고 확정이 끝난 것은 아니다. 관련 없거나 판단할 수 없는 feature는 종료 때까지 `null`이어도 된다. 이번 요청의 값 확정은 장기 저장 동의가 아니다. 구체적 후보/입력 흐름은 [이미지·텍스트 인터랙션](#이미지텍스트-인터랙션)을 따른다.

## 연구와 평가

### 목표와 연구 질문

평소 취향과 이번 상황을 함께 반영하는 패션 아이템·코디 탐색에서, 장·단기 메모리와 이미지 선택·선택적 확인을 결합한 LUMI의 사용 경험을 평가한다.

| 질문 | 보고서의 초점 |
|---|---|
| RQ1 · Memory reflection and user control | 한 세션의 두 요청에서 Baseline 대비 통제감과 최종 코디 적합성(취향 반영·상황 적합성)을 평가한다. 기억 충실도는 LUMI 전용 평가로 살핀다. |
| RQ2 · Taste expression and specification | Baseline 대비 표현 부담, 원하는 스타일의 구체화, 이해받는 느낌을 평가한다. |

RQ의 초점을 나눈 것이 메모리·이미지·질문의 독립 효과를 분리하는 실험을 뜻하지는 않는다. 목표 속성의 구조 검증이나 이해받는 느낌을 실제 상품 선호 판단의 정확도로 바꿔 보고하지 않는다.

### 보고서의 평가 계획

- **설계(4.2):** 온라인 패션 구매 경험이 있는 성인 20~24명의 참가자 내 비교다. 조건 순서와 상황 시나리오 배정을 교차 균형화한다.
- **조건(4.2):** LUMI와 ChatGPT+Musinsa의 Baseline을 비교한다. 보고서의 Baseline은 ChatGPT 메모리·개인화·이미지 생성·웹 검색을 끄고, Musinsa는 비로그인 검색·필터만 사용하는 통제 조건이다. 이는 실험 설정 계획이며 현재 서비스 설정을 검증한 결과가 아니다.
- **과제(4.3):** 조건마다 자유 요청 1회와 상황 요청 1회를 같은 세션에서 수행한다. LUMI는 과제 전 평소 취향 등록을 하고, 요청 말미에 이후 활용할 선호를 별도로 선택한다. Baseline의 두 요청은 같은 ChatGPT 대화에서 이어진다.
- **측정(4.4):** Baseline↔LUMI 대응 문항, LUMI 전용 문항, 두 조건의 Raw NASA-TLX와 LUMI의 SUS, 개방형 응답을 구분한다.
- **분석(5장):** 대응 비교와 LUMI 전용 중립점 비교를 구분하고 RQ별 Holm 보정·효과크기·탐색 분석을 보고한다. 문항·점수 계산·결측 처리·검정은 원문을 따른다.

기억 충실도는 Baseline 우월성 비교로 해석하지 않는다. 일시 요구의 다음 요청 비이월(Q9-15)은 상황 요청 뒤에 추가 요청이 필요하므로 이 사용자 연구의 측정에서 제외돼 있다(4.4). 해당 동작의 코드 회귀 검증과 사용자 연구에서 입증한 효과를 구분한다.

### 개발과 평가의 경계

[현재 구현과 실행](#현재-구현과-실행)에 명시한 범위와 연구에서 평가할 효과를 구분한다.

파일럿·과제 안내·실험 환경·설문 구현은 별도 연구 준비 작업이다. 보고서 인용만으로 연구 수행·참여자 동의·실제 설문 배포를 완료했다고 보고하지 않는다. 참여자 정보·동의서·원시 응답은 저장소 밖에서 관리한다.

## 현재 구현과 실행

이 절은 현재 코드의 실행 계약이다. **A1에서 Park et al. PI/FEA 사전의 명시적 로딩·검증·패키징을 구현했다. 저장·추출·목표 생성·상품·화면의 v1 연결과 데이터 이관은 아직 미구현**이며 기존 실행의 기본 사전은 `consumer-17-v1`이다. 두 사전의 값은 혼용하지 않는다. 기존 Python 패키지·CLI·환경 변수의 `stylemate_memory`/`STYLEMATE_` 이름은 호환성을 위해 유지한다.

### 구현 상태

| 보고서 | 현재 코드·검증의 범위 | 남은 범위 |
|---|---|---|
| 3.2 · Input-to-Memory Model | [codex_llm.py](../src/stylemate_memory/codex_llm.py)의 텍스트 후보 추출·형식/인용 검사, [inspector.py](../src/stylemate_memory/inspector.py)의 수동 확인·동의 | 사전으로 표현되지 않는 취향과 대화 맥락의 지속 보존, 이미지 선택 입력·근거 연결, 소비자 입력 흐름 |
| 3.2 · Memory Layer | [store.py](../src/stylemate_memory/store.py)의 장·단기 항목, 대상/상황/근거 참조, 확인·동의·교체·철회·삭제, SQLite 원자성 | 자유 표현·선택 사실·미확인 이유를 함께 다룰 표현과 확인 흐름. 현재 메모리는 지원 feature/fact와 values가 필요함 |
| 3.3 · Context-Aware Memory Retrieval | [context.py](../src/stylemate_memory/context.py)의 요청/대상/조건/기간 필터, 단기 예외·장기 보존, 출처·제외 이유 | 자연어·이미지 선택 근거까지 포함하는 조회와 관련성 평가. 현재 미확인 후보는 확정 binding에서 제외됨 |
| 3.4 · 목표 Item Feature Map | [registry.py](../src/stylemate_memory/registry.py)의 기존 17개 사전과 명시적 PI 7항목·FEA 30태그 로딩/검증, [inference.py](../src/stylemate_memory/inference.py)의 기존 지정/추론/미정/상충 구분, [app.py](../src/stylemate_memory/app.py)의 기존 최신성 재검사 | 새 사전을 추출·저장·목표 생성에 연결·이관, 확인 질문·검색 입력 연결 |
| 3.5 · Item Retrieval / Final Suggestion | 미구현 | 상품 수집·속성 검증, 필수 조건 필터, 선호 랭킹, 결과 없음과 사용자 조건 조정, 최종 제안 |
| 3.6 · Feedback / Memory Update | 확인·승격·교체의 저장 기반과 개발자 도구의 텍스트 수정 | 이미지/부분 선택·선택 이유 가설·필요한 확인·재검색·최종 확정/장기 저장 통합 |
| 3.7 · UI | 개발자 관찰 도구만 존재 | 보고서의 온보딩·새 요청·이미지 탐색·반영 정보 확인·최종 선택·별도 저장 UI |

코드의 `stylemate_memory`는 이전 명칭을 유지하는 실행 패키지다. 개발자 관찰 도구의 세 패널을 보고서의 소비자 UI로 보지 않는다. 목표 Item Feature Map과 상품별 Item Feature Map도 구분한다.

**A0 구현 범위:** [contracts.py](../src/stylemate_memory/contracts.py)에 v1의 TypedDict·Protocol·작은 참조 형식 검사/멱등 fingerprint, [errors.py](../src/stylemate_memory/errors.py)에 v1 오류 이름을 추가했다. [계약 테스트](../tests/test_contracts.py)는 이 작은 정상/오류 경계만 검사한다. A0에서는 store·registry·모델·context·상품·HTTP/UI에 v1을 연결하거나 실제 DB를 이관하지 않았다. 루트 [확인.md](../확인.md)는 기존 [HTML](../확인.html)의 원문 연결을 복구한 역사적 검토안이며 현재 RQ·평가 기준이 아니다.

### PI·FEA 사전 실행 자원 (A1)

[registry.py](../src/stylemate_memory/registry.py)의 `load_registry("park-2025-source-v1")`는 A0의 `RegistryPort`를 구현한 `ParkRegistry`를 반환한다. `describe()`는 정본 JSON의 이름·값·계층·출처를 보존하고 별도 `execution`에 현재 지원 범위를 표시한다. 저장 계약 `lumi-memory-v1`과 사전 버전은 별개다. 인자 없는 `registry_metadata()`·`validate_values()`·기존 CLI/관찰 도구는 기존 17개 계약을 유지하며 새 값으로 자동 변환하지 않는다.

- `validate_binding(binding, garment_type)`은 `BindingSpec`의 PI/FEA 필드·값·경로·any/all을 검사한다. 저장 객체의 메타데이터나 확인/동의 필드를 전달하지 않는다. `Relaxed`→`Wide`, `Denim`→섬유 원료 같은 자동 치환과 모든 `range` 연산은 거부한다.
- `validate_observation(observation, garment_type)`은 별도 상품 관찰의 PI values 또는 FEA present(bool/null)를 검사한다. 사용자 선호 방향과 상품 성능을 섞지 않으며 이 검사는 출처·검증 라벨이나 hard 조건 충족을 승인하지 않는다.
- 현재 값이 있는 실행 매핑은 `garment_type="Pants"`만 지원한다. selector의 `Pants`와 PI `Type`의 바지 종류는 별개다. 다른 품목·미정 대상의 값 있는 PI/FEA 매핑은 `unsupported_mapping`이며 원문 기억은 매핑 없이 보존할 수 있다. 값이 null인 상품 관찰은 미확인 표현으로 허용한다.
- Brand는 `values=null`·예시·미공개 목록 상태를 보존하며 예시를 포함한 브랜드 값의 실행 검증은 지원하지 않는다. Price는 **정본의 구간 문자열과의 일치만** 검증한다. 수치에서 구간을 계산하거나 통화·경계 포함 규칙·range를 실행하지 않는다.
- `empty_target(target_id, garment_type)`은 7항목·30태그의 계층과 null 값/빈 근거 목록을 모두 반환한다. 지원 범위는 `unspecified`, Brand와 미지원 품목은 `unsupported`로 시작한다. `validate_target_value(path, value, garment_type)`은 unspecified/inferred/specified/indifferent/not_applicable/unsupported/conflict의 값·null·참조 **형식만** 검사한다. 실제 지정/확인·비적용·상충의 근거 판단은 B/C/D에서 맡으며 이 함수로 상태를 승격하지 않는다.

사전이 없거나 형식/개수가 손상되면 `registry_unavailable`, 명시한 사전 버전이 미지원이면 `unsupported_contract`로 실패한다. 새 사전 경로의 형식 오류는 `invalid_input`, 미지원 값/경로/품목/연산은 `unsupported_mapping`이다. [사전 테스트](../tests/test_registry.py)는 전체 정본 값·FEA 경로, 오류/상태, 기존 실행 호환과 자원 동일성을 검사한다.

패키지의 [JSON 자원](../src/stylemate_memory/resources/park-2025-feature-map.json)은 [정본](../output/feature-map/park-2025-feature-map.json)의 생성 사본이며 수동 편집하지 않는다. [동기화 스크립트](../scripts/sync_feature_registry.py)가 byte 그대로 복사하고 `--check`와 사전 테스트가 동일성을 확인한다. 자원은 `pyproject.toml`의 package-data로 배포하며 `importlib.resources`로 네트워크 없이 읽는다. 원본의 `runtime_implemented=false`는 전체 실행 경로 전환 전까지 보존하고 현재 단계는 `execution`과 이 절에서 구분한다.

```sh
python3 scripts/sync_feature_registry.py         # 정본 변경 시 패키지 사본 생성
python3 scripts/sync_feature_registry.py --check # 읽기 전용 동일성 검사
PYTHONPATH=src python3 -m stylemate_memory.cli features --registry park-2025-source-v1
```

위 features 명령은 사전 조회이며 DB 이관·v1 목표 생성·소비자 서버 연결을 수행하지 않는다.

### 메모리 실행 계약

신뢰된 로컬 호출자가 요청·기억 확인·이후 활용 동의를 전달한다. SQLite가 항목별 상태와 버전을 저장하고, 현재 요청/대상에 유효한 기억만 context로 조립한다. rule 또는 OpenAI adapter가 목표값을 제안하면 시스템이 값·대상·근거·제약과 최신 상태를 검증한다. 모델 출력은 메모리를 자동으로 바꾸지 않는다.

실제 상품 feature 추출·검색·추천/조합·구매, 일반 제품 화면·로그인·이미지 처리·자연어의 사용자 의도/동의 진위 판별은 이 실행 모듈에 없다. CLI의 사용자 ID·확인/동의 참조는 상위의 신뢰된 입력 이벤트가 제공해야 한다. 공개 API로 그대로 노출할 인증 계약이 아니다.

후속 [개발자용 관찰 도구](#개발자-관찰-도구)는 이 저장/context/목표 검증 코드 위에 Codex LLM의 자연어 **후보 추출**과 로컬 테스터의 확인·동의 버튼을 연결한다. 소비자 제품 UI·자연어 동의 진위 판별·실제 상품 추출을 구현한 것이 아니며, 기존 장기 확인/동의와 읽기 전용 목표 추론 계약을 유지한다.

### 현재 실행 중인 17개 속성

**현재 실행 코드는 여전히 `consumer-17-v1`을 사용한다.** 이는 [이전 전체 feature 계획](../archive/docs/target-feature-inference-plan.md)의 item65/outfit9를 축소한 로컬 실행 사전이며 위의 확정 사전과 다르다. 아래 표의 과거 대응과 `pdf` metadata를 중간보고서나 Park et al. 논문에서 정한 상품 스키마로 읽지 않는다. 기본 카테고리는 아이템 종류에서 파생하고 기장은 대상별로 통합했으며 근거 없는 값은 미정으로 남긴다.

| key | 표시 | 과거 사전 대응·축소 |
|---|---|---|
| garment_type | 아이템 종류 | Garment Type. Main Category는 파생; Type Variant 제외 |
| color | 기본 색상 | Primary Color. 패턴/그래픽 색과 별도 |
| fit | 전체 핏 | Visual Fit. 바짓단/어깨/허리 실루엣 세부 제외 |
| length | 기장 | 상의·바지·치마·아우터·드레스 길이를 대상별 통합 |
| sleeve_length | 소매 길이 | Sleeve Length. 소매 모양/커프 제외 |
| neckline | 넥라인 | Neckline Type. 칼라 세부 제외 |
| pattern | 무늬 | Pattern Type. 무늬 크기/밀도/방향/위치 제외 |
| logo | 로고 크기 | Visibility+Size를 None/Small/Medium/Large로 축약. 실제 로고 존재를 추출한 결과가 아님 |
| fabric | 원단 | Fabric Type. 섬유 조성/혼용률·Material Appearance 제외 |
| texture | 표면 질감 | Surface Texture. 워싱/광택/비침 제외 |
| style | 스타일 | Item Style Affinity. 복수 라벨 허용 |
| mood | 분위기 | Visual Mood. 복수 라벨 허용 |
| formality | 격식 정도 | 1~5. 명시 범위는 양끝 포함 |
| season | 계절 | Suitable Seasons. 복수 라벨 허용 |
| thickness | 두께 | Thickness |
| warmth | 보온성 | Thermal Insulation |
| functions | 기능 | Functional Properties. 원하는 성능이며 실제 상품 성능은 별도 근거 필요 |

`registry.py`가 현재 실행 허용값·적용 category·과거 추출 source·한국어 표시를 관리한다. model prompt도 이 사전에서 만든다. `pdf`/`source` metadata는 이전 feature 자료의 상품 추출 방법이며 중간보고서 인용이나 사용자 목표를 추론한 근거가 아니다. 예를 들어 기능의 실제 추출 source는 Metadata이며, Waterproof 목표 제안은 상품의 방수 성능 증명이 아니다.

`occasion`, `activity`, `goal`은 목표 feature가 아닌 확인된 상황 facts다. 상황과 그 조건·대상/근거를 보존하고, fact를 모델이 추론한 hard feature로 자동 변환하지 않는다.

### 메모리 쓰기 계약

`MemoryStore.apply_batch(user_id, request_id, batch_id=..., actions=...)`가 쓰기 경계다. 같은 batch ID의 같은 본문은 최초 결과, 다른 본문은 충돌이다. 단일 batch의 actions는 전체 성공/전체 rollback이며 기대 request/profile revision과 항목 version을 검사한다.

create의 주요 입력은 다음과 같다. ID/version/lifecycle/profile revision은 저장 계층이 관리한다.

| 필드 | 의미 |
|---|---|
| feature / values | 지원 key와 값 목록. formality 정수 외에는 canonical 문자열 |
| polarity | prefer / avoid / require |
| strength | soft / hard. 범위/현재 예외의 우선순위를 대신하지 않음 |
| match | any / all / range. range는 formality 두 정수·양끝 포함 |
| selector | garment_type / slot_id. 셔츠와 바지 조건을 분리. 빈 값은 공통 적용 |
| conditions | 확인된 occasion/activity/goal 등의 상황과 비교할 AND 조건 |
| content | 항목의 최소 사용자 의미. 전체 대화/이미지 원문을 저장하지 않음 |
| scope | short_term / long_term |
| origin / confirmed | explicit / inferred와 내용 확인. inferred는 미확인 단기 후보만 생성 |
| evidence_ref / consent_ref | 현재 사용자 확인과 이후 활용 동의의 참조. 장기에는 별도 동의 필수 |
| valid_from / valid_until | timezone을 가진 절대 시각. `[from, until)` |

명시된 hard Slim 요구는 values=[Slim], require/hard/any로 표현한다. Black 회피는 avoid와 강도를 유지하며 Navy로 바꾸지 않는다. style의 여러 값에서 any와 all을 구분한다. 사용자 명시값을 모델이 허용 집합·강도·연산으로 바꾸지 못한다.

create / confirm / promote / replace / withdraw / delete를 지원한다. 단기 후보를 확인하는 것과 장기로 승격하는 동의는 별도다. 장기 직접 create는 확인과 동의가 모두 필요하다. replace는 같은 scope 안의 새 의미에 새 ID와 필요한 새 동의를 사용한다. scope 변경은 replace로 하지 않는다. promote 가족은 context에서 한 번만 적용하고 철회/삭제에 함께 처리한다.

요청 전용 `selector.slot_id`가 있는 항목은 그대로 장기 생성/승격하지 않는다. slot을 자동 삭제해 동의 범위를 넓히지도 않는다. 이후 활용할 대상과 새 내용을 확인하고 새 consent로 장기 create해야 한다. 확인은 실제 bool, 기대 version/revision은 bool/문자열/실수를 제외한 int로 검증한다.

요청은 비활동30일/생성90일 중 이른 시한, 활성 장기는 동의365일, 철회/교체 내용은 기존 시한과 비활성30일 중 이른 시한을 적용한다. 기간이 지난 조건은 다시 활용하지 않는다. `prune_expired()`는 호출자가 실행하는 로컬 보관 정리이며 상시/예약 작업은 설치하지 않는다.

삭제 뒤에는 과거 항목 ID/content/일반 payload digest를 영수증에 보존하지 않는다. 내용 없는 삭제 명령의 단방향 fingerprint와 opaque nonce로 24시간 동일 요청 replay/다른 본문 충돌을 구분한다. 요청을 삭제/만료 정리할 때도 해당 재시도 경계를 tombstone으로 이전한다. 24시간 뒤 ID 재사용은 허용하므로 영구 멱등성이나 삭제된 원문의 의미를 영구 비교하는 정책이 아니다. 이후 입력은 새 신뢰된 사용자 이벤트여야 하며 과거 모델/요약의 memory ID는 새 context의 근거가 될 수 없다.

### Context와 목표값

대상 목록은 `[{"id":"pants-1","garment_type":"Pants"}]`처럼 전달한다. 원래 제품 ID와 다르며 이번 요청의 목표 아이템을 식별한다.

context는 다음을 적용한다.

1. 사용자·현재 request·active/confirmed·기간·보관·상황·대상 조건.
2. 대상별 promote 가족 대표·중복 제거와 현재 예외·상충 판정.
3. 장기12/단기20개·사용자 내용/조건6,000자 예산. 직접/필수 현재 조건을 조용히 삭제하지 않고 보류한다. feature 사전 metadata는 별도다.
4. 유효 기억·직접 bindings·확인된 facts와 source IDs/version·미정 질문·registry 값의 분리.

selector 없는 facts는 공통 맥락, selector가 있는 facts는 `facts_by_target`에만 전달한다. 조건도 해당 target의 facts로 평가한다. 같은 우선순위의 상충 fact는 실행 맥락에서 빼고 질문으로 남기며 입력 순서로 한 값을 선택하지 않는다.

모델의 제안 형식은 `suggestions`와 `questions`뿐이다. suggestion은 `target_id`, `feature`, `values`, `match`, `source_ids`, `reason`이다. 시스템이 inferred/soft 의미를 부여하며 모델이 explicit/confirmed/hard를 만들어내면 거부한다.

최종 프로필에는 feature별 지정됨(specified), 추론 제안(inferred), 미정(unspecified), 비적용(not_applicable), 상충(conflict)이 있다. None 같은 실제 허용값은 미정/N/A가 아니다. 직접 bindings는 모델이 누락해도 보존하고, 복수 라벨의 값·조건·근거를 손실 없이 전달한다.

복수 style 등의 any/all 의미가 섞이면 평탄한 `feature.match`는 null이다. `feature.constraints`와 개별 suggestions의 match가 연산 정본이며, 합쳐진 표시용 values 하나만으로 조건을 실행하지 않는다.

`ShoppingApp.infer_request()`는 응답 뒤 최신 SQLite snapshot으로 context를 다시 만든다. 요청 종료, 기억 변경/철회/삭제, 기간 만료로 context가 달라지면 stale_context로 폐기한다. 추론 실패·재시도·가상 응답 어느 경우도 자동 장기 쓰기가 아니다.

반환값에는 `request_id`, `versions.request/profile/memories`와 context/registry 식별자를 붙인다. memory version 목록은 실제 사용한 DB 항목만 포함하며 현재 호출에서 주입한 상황 facts를 DB memory로 꾸미지 않는다. 이 내부 버전 묶음과 사용자 ID는 모델 전송 payload에 포함하지 않는다.

### 오프라인 실행과 검증

아래 명령은 합성 입력과 가상 adapter를 사용하며 실제 외부 모델을 호출하지 않는다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.cli demo --synthetic
PYTHONPATH=src python3 -m stylemate_memory.cli features
PYTHONPATH=src python3 -m stylemate_memory.cli features --registry park-2025-source-v1
python3 scripts/sync_feature_registry.py --check
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/check_repository.py
git diff --check
```

실행 의존성은 Python 3.11+ 표준 라이브러리뿐이다. 저장소 루트에서 실행한다.

가상 데모는 임시 DB로 기본 Relaxed/Navy → 이번 Slim → 다음 요청 Relaxed를 확인한다. rule adapter는 단순 연결 fixture이며 실제 LLM 품질·사용자 연구 효과를 검증하지 않는다.

지속 DB를 사용할 때는 저장소 밖 경로를 직접 지정한다. `request`로 요청 ID를 받고 `batch`로 확인된 항목을 기록한 뒤 `infer`로 목표를 생성한다. 실제 참여자 자료·키를 저장소에 넣지 않는다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.cli request --help
PYTHONPATH=src python3 -m stylemate_memory.cli batch --help
PYTHONPATH=src python3 -m stylemate_memory.cli infer --help
```

create action 예시(현재 요청에만 적용, 장기 자동 저장 없음):

```json
[
  {
    "op": "create",
    "feature": "fit",
    "values": ["Slim"],
    "content": "이번 바지는 Slim을 원함",
    "scope": "short_term",
    "confirmed": true,
    "evidence_ref": "current-user-input-1",
    "selector": {"garment_type": "Pants"}
  }
]
```

### 실제 모델 연결

CLI의 Responses adapter는 명시적 model/key로 연결하며 테스트는 fake transport를 사용한다. 코드 import, demo, 기본 rule 추론은 자격 증명을 읽거나 실제 모델을 호출하지 않는다. Codex CLI로 실제 추출·목표 추론을 실행하는 [개발자 관찰 도구](#개발자-관찰-도구)는 별도 실행 경로다.

사용자가 로컬 환경에 `OPENAI_API_KEY`, `STYLEMATE_OPENAI_MODEL`을 설정하고 명시적으로 `infer --provider openai`를 실행할 때만 실제 연결을 사용한다. `--model`로 호출 모델을 지정할 수도 있다. 키를 CLI 인자·로그·오류·PR에 넣지 않는다. 모델 접근권한과 structured output 지원은 실제 호출 시 확인해야 한다.

adapter는 OpenAI Responses API에 `text.format`의 strict JSON Schema·`store=false`·출력 상한·timeout을 전달한다. [공식 Structured Outputs 이동 안내](https://developers.openai.com/api/docs/guides/migrate-to-responses#6-update-structured-outputs-definitions)를 기준으로 wire 형식을 구현했다. 응답 거부·불완전·비정상 JSON·HTTP/timeout 오류는 안전한 오류 코드로 반환하고 자동 무한 재시도·부분 성공으로 처리하지 않는다. 구조 검증은 의미 품질/공급자 전체 보관 정책의 증명이 아니다.

### 개발자 관찰 도구

텍스트 후보 → 내용 확인/별도 동의 → 기억 조회 → 목표값 변화를 확인하는 단일 로컬 테스터용 도구다. 실제 상품의 속성 추출·검색이나 보고서 3.7의 소비자 UI는 구현하지 않았다. 아래 조작은 실제 모델 호출을 포함하므로 해당 실행을 요청받았을 때만 수행한다.

#### 실행

Python 3.11 이상과 기존 로그인된 Codex CLI가 필요하다. 추가 Python/프런트엔드 패키지는 없다. 이전에 사용자가 선택한 `gpt-6-luna`를 기본 모델로 사용한다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.inspector
```

브라우저에서 [로컬 관찰 도구](http://127.0.0.1:8765)를 연다. 다른 포트/DB/대상을 지정할 수도 있다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.inspector \
  --port 8765 \
  --db /private/tmp/stylemate-inspector/memory.sqlite3 \
  --garment-type Pants \
  --model gpt-6-luna
```

기본 SQLite 경로는 OS 임시 폴더의 `stylemate-inspector/memory.sqlite3`다. DB를 저장소 밖에 둔다. Ctrl+C로 서버를 종료하며 자동 시작/예약 실행은 설치하지 않는다. CLI 로그인과 모델 이용 가능 여부는 사용 환경에 따른다. 호출 실패/제한/시간 초과를 모델 성공으로 표시하지 않으며 다른 모델이나 rule로 자동 전환하지 않는다.

#### 세 패널에서 확인할 것

| 패널 | 표시/조작 |
|---|---|
| Chat | 현재 요청의 메시지, 실제 LLM 추출 답변/질문, 입력창. 샘플 버튼은 입력만 채우고 자동 전송하지 않는다. |
| Memory | 항목별 원문 내용·canonical 값·대상 selector·범위·상태·버전·근거. 후보/이번 요청/장기 항목을 나눈다. 내용 확인과 이번 적용, 이후 활용 동의, 철회를 명시 클릭한다. |
| Feature Map | [현재 실행 중인 17개 사전](#현재-실행-중인-17개-속성)의 값·지정/추론/미정/비적용/상충 상태·source ID·제약과 연산. 이미지에서 추출한 실제 상품 속성이 아닌 원하는 아이템의 목표값이다. |
| Processing trace / raw JSON | 단계별 입력·모델 원본 출력·검증·저장 batch·유효 context·최종 프로필. model/provider·호출 시도/완료 응답·단계도 표시한다. |

상단 대상 선택은 **현재 요청에서 관찰할 아이템**을 바꾼다. 다른 대상의 기억을 지우거나 색/핏을 옮기지 않는다. New request는 이전 단기를 이월하지 않고 유효 장기만 다시 조회한다. 기존 요청의 DB 항목을 삭제하는 버튼은 아니다. Infer는 동일 기억으로 목표값만 다시 생성한다.

#### 실제 처리 경계

1. 입력과 현재 요청의 최근 대화/유효 활성 메모리·사전을 Codex에 전달해 구조화 후보를 받는다. 최신 문장의 원문 인용·허용값·대상·부정/강도/연산·범위 힌트와 조건별 인용을 검증한다.
2. 앱이 검증된 항목을 기존 `MemoryStore.apply_batch`로 **미확인 단기 후보**로만 저장한다. `baseline` 힌트도 장기 저장 승인이 아니다. 후보는 유효 목표 context에 들어가지 않는다.
3. 테스터가 `확인하고 이번 요청에 적용`을 누르면 내용 확인 이벤트로 활성화한다. `확인하고 앞으로도 사용 허용`은 내용 확인과 이후 활용 동의를 명시한 조작이며 confirm/promote를 원자적으로 실행한다. 모델이 동의·확정 상태·쓰기 명령을 만들지 않는다.
4. 현재 단기 조건을 사용자가 명확히 정정하면 모델은 같은 feature/대상의 기존 단기 ID를 교체 후보의 근거로 제안할 수 있다. 클릭 시 기존 버전을 다시 검사하고 후보 철회·기존 항목 replace를 하나의 batch로 처리한다. 장기를 모델이 직접 교체하지 않는다.
5. 실제 SQLite snapshot → 대상별 `build_context` → Codex 목표 제안 → 기존 `ShoppingApp`/`infer`의 값·대상·근거·직접 조건·최신성 검증을 거쳐 오른쪽에 표시한다. 격식 숫자의 뜻은 별도 scale로 모델에 제공한다. 이 단계는 메모리를 쓰지 않는다.

따라서 채팅 전송만으로 장기 취향이 저장되지 않는다. **후보 생성 → 테스터의 확인/동의 → 목표 반영**을 차례로 관찰한다. 모델은 빈 칸을 억지로 채우지 않으며 명시 색/핏의 Feature Map 반영은 기존 코드가 보존하는 직접 조건이다. LLM이 새로 추론한 값을 별도로 표시한다.

자연어 의도·조건 의미의 완전한 정확성을 코드로 증명하지 않는다. 원문 인용은 존재 검사이며 문장 해석이 옳다는 증거는 아니다. 조건 값은 해당 인용에 실제 등장하는 문자열로 제한한다. 사전에 없는 섬유 조성·미제공 사진 값은 저장하지 않고 질문/미지원 내용으로 남긴다. 날짜/기간 자동 해석과 여러 동일 종류 slot의 구분은 이번 입력 adapter에 없다.

#### 모델 실행과 저장 범위

[Codex 공식 비대화형 실행 문서](https://learn.chatgpt.com/docs/developer-commands#codex-exec)를 참고해 `codex exec`를 일회성 JSON 변환 모델로 호출한다. 별도의 Responses API 키는 읽지 않는다. Codex CLI가 기존 로그인을 내부적으로 사용하며 앱은 자격 증명 파일·사용자 설정 내용을 직접 읽지 않는다.

- 호출마다 별도 임시 폴더·`--ignore-user-config`·읽기 전용 sandbox·`--ephemeral`·출력 schema를 사용한다. 모델용 shell/apps/browser/computer/hooks 기능을 끄고 예상 밖의 도구 항목이 나오면 결과를 적용하지 않는다. sandbox를 우회하는 옵션은 사용하지 않는다.
- 전달하는 내용은 테스트 대화·현재 기억과 사전이다. 이는 외부 모델 호출이다. 이 도구에서는 가상 입력으로 검증했으며 실제 참여자 정보/동의서/원시 연구 응답을 저장소에 넣지 않는다.
- SQLite에는 기존 계약의 최소 메모리 내용·근거/동의 참조·버전이 저장된다. 전체 채팅·모델 원본·trace·후보 scope/교체 설명은 프로세스 메모리에만 있고 종료 시 사라진다. 장기 항목의 최소 내용/근거는 재시작 후 DB에서 읽을 수 있지만 과거 대화와 review hint를 복원하는 기능은 없다.
- 서버는 127.0.0.1만 사용하고 packaged HTML/API만 제공한다. 임의 파일 탐색/공개 인증·배포 API가 아니며 단일 신뢰된 로컬 테스터를 가정한다. Host/Origin·JSON 형식·크기를 검사하고 쓰기 작업을 순차 실행한다.
- 모델 실패 뒤 이미 성공한 저장은 되돌렸다고 주장하지 않는다. 현재 기억을 표시하고 Feature Map은 unavailable로 두며, 실제 저장 상태를 trace에서 확인한다. 호출 중에는 쓰기 버튼이 비활성화된다.

로컬 테스트의 동의 클릭은 연구용 인증/동의 수집 시스템을 대신하지 않는다. 기존 [확인·동의·기간·철회 계약](#메모리-실행-계약)은 그대로 사용한다. 별도의 저장·삭제/장기 자동화 정책을 도입하지 않았다.

### 검증 범위와 한계

테스트는 실제 SQLite와 합성 사용자·가상 모델/HTTP 응답으로 저장·동의·요청 격리·대상/상황별 context·충돌·목표값·최신성·삭제 경계를 확인한다. 위 실행 명령으로 현재 결과를 확인한다. 과거 테스트 수와 PR/임시 설치 결과는 [2026-10-14 보관 기록](../archive/docs/shopping-memory-prototype-20261014.md)에 있으며 이번 실행 결과로 재사용하지 않는다.

실제 모델의 자연어 해석 품질, 자유 표현·이미지 근거의 지속 보존, 상품 검색/매칭·추천 품질, 소비자 UI/로그인·사용자 연구는 이 오프라인 검증에 포함되지 않는다. 원격 CI도 실제 실행을 별도로 확인한다.

보관 기간·조회 예산·17개 사전은 현재 로컬 프로토타입의 설정이다. 이를 최종 서비스 정책으로 확정하거나 문서 정리만으로 변경하지 않는다. 관리 DB 삭제는 행·관련 내용/영수증·journal 정리 범위이며 사용자가 만든 사본·OS 백업·저장매체 소거는 포함하지 않는다.

기존 fixture 테스트는 후보만 저장, 확인/장기 동의, 오늘 예외→새 요청 복원, 현재 조건 교체와 장기 동의의 원자성, 원문/조건 위조 거부, stale 교체, 잘못된 모델값·호출 오류·timeout, 대상 격리와 fact 기반 추론, 철회/재시작·중복 호출, HTTP의 local-only 경계를 확인한다. 가상 gateway 테스트를 실제 모델 정확도 평가로 해석하지 않는다.

[2026-10-14 보관 기록](../archive/docs/developer-memory-inspector-20261014.md)에 당시 실제 모델·브라우저 확인과 테스트 결과를 보존했다. 과거 모델 성공·임시 파일 경로를 현재 실행 가능성이나 이번 검증 결과로 사용하지 않는다.

제품 소비자 UI, 이미지/상품 데이터·검색·추천 품질, 사용자 연구, 원격 CI·배포, 모든 브라우저/모델 조합은 이 도구의 검증 범위 밖이다. 현재 확인/동의·목표값 변화의 관찰을 제품·사용자 연구 효과로 확대하지 않는다.

문서 검사기는 코드 블록 밖의 인라인 Markdown 링크·지원하는 제목 앵커, HTML의 내장 원문 쌍, 보존된 Issue/PR 템플릿의 기본 구성을 검사한다. `archive/`는 제외한다. 이미지·참조형 링크·HTML 링크·외부 URL·Figma 연결·YAML 전체 문법·화면 품질은 검사하지 않는다. 실제 Issue 등록·PR 형식도 강제하지 않는다.

문서 검사 통과, 오프라인 모델 fixture, 실제 모델 호출, 의미 품질·추천/사용자 효과의 검증을 구분한다. 필요한 검증은 생략하거나 약화하지 않는다. 실행 결과는 통과·실패·미실행·해당 없음으로 구분하고 미실행/해당 없음의 이유를 밝힌다.

#### CI의 범위

현재 정의는 `repository-checks`의 문서·템플릿 검사와 `memory-tests`의 Python 3.11/3.14 오프라인 테스트·가상 데모다. 파일 존재나 로컬 검사만으로 실제 GitHub CI·브랜치 보호·승인 규칙이 활성화됐다고 보고하지 않는다. 원격 설정은 사용자가 관리한다.

## 다음 작업

**A0의 공통 계약과 A1의 사전·실행 자원은 구현했고, 다음 작업은 B1/C1/D1이다.** 이번 실행은 A1까지만 수행하며 후속 TASK를 시작하지 않는다. 후속 순서는 B1/C1/D1 → B2/C2/D2 → B3/C3/D3 → B4/E1 → A2 → E2/D4 → A3이며 각 병렬 묶음 뒤 A가 GATE로 통합 확인한다. 담당·함수·필드는 [공통 인터페이스](#a0-공통-인터페이스와-담당-경계)와 contracts.py를 그대로 참조한다. 아래 기능 단계는 여전히 계획이다. 자유 표현을 잃지 않는 입력→메모리→조회 경로부터 연결한다.

| 단계 | 핵심 변경 위치·책임 | 완료 기준 |
|---|---|---|
| 1. 표현·사전 이관 | `store.py`의 feature/values 필수 제약을 근거·자연어 항목·선택적 매핑으로 확장. `registry.py`는 승인 PI/FEA 사전 참조 | 매핑 없는 기억 보존, 저장/사전 버전 분리, 합성 기존 DB의 이관·재시작·실패 rollback 검증 |
| 2. 쓰기·확인 | `codex_llm.py`·`inspector.py`의 후보/가설·확인·장기 활용 선택을 기존 `apply_batch()`에 연결 | 근거와 동의 snapshot 범위 일치, 명시적 동일 요청 재개와 새 요청 분리, 모델의 확정/동의 생성 차단 |
| 3. 조회·목표 | `context.py`·`inference.py`·`app.py`의 유효성 필터·근거 묶음·사전 매핑·최신성 검사 | 직접 조건 보존, 자유 표현 검색 adapter 연결, 근거별 반영/제외 이유와 stale 응답 차단 |
| 4. 검색·관리 검증 | 같은 합성 입력으로 구조 검색 기준선과 의미 검색 후보를 비교하고 철회/삭제·재색인 경계 확인 | 관련 근거 회수·오탐·근거 묶음 완전성·목표 조건 보존·호출/토큰/지연을 구분 측정. 실제 검색 모델은 비교 결과로 선택 |
| 5. 상품 Map·비교 후보 | 보고서 3.5의 상품 속성·필수 필터·선호 랭킹에 비교할 미정 요소와 후보 묶음 연결 | 합성 상품부터 조건 준수·중복·라벨 미확인·비교 축·실제 조합 부재 검증. 실제 크롤링/이미지 품질은 별도 확인 |
| 6. 이미지·텍스트 UI | [합의한 인터랙션](#이미지텍스트-인터랙션)에 따라 초기 자유 입력·이미지 비교·상시 텍스트·필요한 확인·재탐색 연결 | 선택과 텍스트 함께 반영, 하나/여러 개·부분 선택·없음/모르겠음·수정/종료 지원. 상품 확정과 장기 저장 분리 |

이관은 원래 값·내용·근거·확인·동의·기간을 보존하고 실제 사용자 DB 대신 합성 DB부터 검증한다. 기존 `consumer-17-v1`과 확정 사전의 의미가 다르면 자동 치환하지 않는다. 특히 `Relaxed`→`Wide`, 원단 종류→소재 원료는 매핑 미정으로 보존하고 필요한 확인을 거친다. 새 의미·대상·범위로 넓어지면 기존 동의를 재사용하지 않는다. 없는 원문을 복원한 것처럼 만들지 않는다. Brand 전체 목록·Price 경계·타 품목 범위는 [확정 사전의 미정 규칙](#feature-map)을 따른다.

| 대표 시나리오 | 구현 시 확인할 결과 |
|---|---|
| “빈티지한 느낌” → 재시작 → 사용자가 같은 요청 재개 | 최소 표현·근거·가설 상태 복원. 날짜/상황 재확인. 색·소재 임의 확정 없음 |
| 평소 Navy/Wide 바지 + 이번 발표 Slim | 이번 목표 Navy/Slim, 장기 Navy/Wide 보존. 새 요청에 발표 전용 Slim·요약·가설 비이월 |
| 상의와 바지에 다른 취향, 미정인 상황 조건 | 대상 간 오적용 없음. 조건 미확인은 점수로 해소하지 않음. 미지원 품목 PI 값을 만들지 않음 |
| 이미지 전체/부분 선택, 이유 미확인·반복 선택 | 선택 근거만 확인. 전체 속성 선호·미선택 비선호·자동 장기화 없음 |
| 미정 feature를 구체화하는 이미지 비교 | 알려진 필수 조건 유지, 핵심 비교 축의 차이·상품 Map 근거 연결. 한 번의 선택에서 나온 feature별 가설과 확정 구분 |
| 이미지 선택과 “A의 색에 B의 핏” 입력 | 선택한 대상·텍스트의 참조를 함께 확인하고 해당 값만 반영. 선택 즉시 후보를 바꿔 입력을 잃지 않음 |
| 마음에 드는 후보 없음·모르겠음·선택 없이 텍스트 입력 | 선택 강요·전체 속성 비선호 추론 없음. 기능 요구를 사진 성능으로 확인하지 않음 |
| 미정/상충 유지·선호 구체화 뒤 조기 종료 | `null` 강제 채움·모든 feature 확인 요구 없음. 추론과 확정·상관없음을 구분하고 언제든 종료 가능 |
| 내용 확인·추천 확정·장기 활용 거부 | 이번 요청 반영은 가능하되 이후 활용을 위한 장기 쓰기 없음 |
| 같은 우선순위 충돌, 근거 예산 부족 | 관련성/최신성으로 필수 조건을 버리지 않고 질문·보류 |
| 수정·철회/삭제·만료 뒤 늦은 응답·오래된 색인 | 이전 목표 폐기, 파생 자료 제외/정리, 재색인·요약으로 재유입 없음 |
| 요청 삭제와 별도 동의한 장기 기억 삭제 | 요청 삭제는 제한된 독립 장기 snapshot만 유지. 장기 기억 삭제는 promote 가족·사본·관련 근거 부분·파생 자료까지 제거 |
| 저장/파생 자료 갱신 실패, 동일/충돌 batch 재시도 | 부분 확정·거짓 삭제 완료 없음. 원자성·버전·멱등 경계 유지 |

위 Navy/Wide/Slim은 확정 사전의 바지 값으로 만든 **후속 시나리오**다. [현재 테스트](../tests)의 Navy/Relaxed→Slim은 기존 17개 사전 검증이며 새 사전 이관의 통과 근거가 아니다. 기존 단위·SQLite·통합 테스트와 가상 데모를 재사용하고 새 표현·근거·검색·삭제 전파의 위험에만 회귀 검증을 추가한다. 모든 새 목표/매핑의 source가 유효 근거까지 연결되는지 확인하며 기술 검증을 실제 모델 의미 품질·상품 검색·사용자 효과로 확대하지 않는다.
