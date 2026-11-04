# LUMI 현재 시스템 구현과 실행

현재 시스템의 구현 범위·동작·실행·검증을 설명하는 **유일한 문서 정본**이다. 과거 선택의 이유·승인·대체 관계는 [ADR](adr), 개발 작업 규칙은 [AGENTS.md](../AGENTS.md)에서 관리한다. 다른 설명 문서나 HTML 사본을 함께 유지하지 않는다. 문서 관리 기준은 [ADR 0009](adr/0009-common-context-layout.md)을 따른다.

- [기준과 자료](#기준과-자료)
- [현재 구현과 실행](#현재-구현과-실행)
- [메모리 실행 계약](#메모리-실행-계약)
- [Feature Map](#feature-map)
- [상품과 이미지](#상품과-이미지)
- [로컬 실행](#로컬-실행)
- [기존 CLI와 개발자 관찰 도구](#기존-cli와-개발자-관찰-도구)
- [연구와 평가](#연구와-평가)
- [오프라인 실행과 검증](#오프라인-실행과-검증)
- [다음 작업](#다음-작업)

## 기준과 자료

시스템 이름은 **LUMI**다. **현재 구현 설명은 이 문서**, 시스템·연구 설계의 원문은 **중간보고서**, 설계 변경의 이유와 승인 범위는 **ADR**에서 확인한다. 구현 여부는 연결된 코드와 검증으로 확인하며 미구현 내용을 완료된 동작으로 읽지 않는다. 후속 결정은 보고서 원문에 소급하지 않고 RQ·평가 계획은 유지한다.

| 자료 | 역할 |
|---|---|
| [Team4_mid-term_report.pdf](sources/Team4_mid-term_report.pdf) | 시스템·연구 설계 원문. 3.2~3.6: 메모리·조회·목표 Map·상품 검색·피드백, 3.7: UI, 2장·4~5장: RQ·평가 |
| [Team4_mid-term_presentation.pdf](sources/Team4_mid-term_presentation.pdf) | 발표용 보조 자료. 보고서와 승인된 결정을 덮어쓰지 않음 |
| [Feature Map JSON](../output/feature-map/park-2025-feature-map.json) | 논문에서 차용한 값·FEA 분류·출처·라이선스와 현재 실행 사전의 기계 판독 정본. 수집 후 확정할 PI value 사전과 구분. [CSV](../output/feature-map/park-2025-feature-map.csv)는 보기용 |
| [ADR 0001](adr/0001-memory-boundaries.md)·[0002](adr/0002-memory-prototype-storage.md)·[0003](adr/0003-consumer-shopping-prototype.md) | 로컬 메모리·저장·기존 17개 사전의 결정 기록 |
| [ADR 0004](adr/0004-adopt-park-2025-feature-map.md)·[0005](adr/0005-evidence-linked-memory.md) | Park 사전 차용, 자연어 기억·근거·확인/동의 분리의 결정 기록 |
| [ADR 0006](adr/0006-fea-to-pi-hypothesis-comparison.md)·[0007](adr/0007-joint-feedback-and-end-consent.md) | PI 중심 상품 비교·FEA→PI 가설, 선택 사항인 이유와 종료 후 장기 동의의 결정 기록 |
| [ADR 0010](adr/0010-derive-pi-values-from-collected-products.md) | PI 7개 feature 축을 유지하고 value를 상·하의 수집 데이터에서 정하는 후속 결정 |

두 PDF는 인계된 원본을 보존한다. 중간보고서는 20쪽·737,007 bytes·SHA-256 `97cdd6791d4aed737d3faae93d46e26ef112d06346ecef34b3a3c3af4b8a69f5`, 발표자료는 14쪽·41,281,335 bytes·SHA-256 `5b708cbef817a999fec1b1ee5ba0c2119ed7d07e9d08164b53146521bf1d2248`다.

[Figma · LUMI.WEB · 298:2](https://www.figma.com/design/LAU2SC2gHCR1jlCh41K7PD/?node-id=298-2)는 화면 배치·조작의 보조 자료다. 이번 정리에서 Figma의 현재 화면은 새로 검증하지 않았다. [남긴 보관 자료](../archive/README.md)는 ADR의 직접 인용 근거·원본 과제·재현 자료에 한정하며 현재 구현 기준으로 사용하지 않는다. 삭제한 설명과 작업 스냅샷은 Git 이력에서 확인한다.

## 현재 구현과 실행

현재 주 실행 경로는 **`lumi-memory-v1` 로컬 소비자 서비스**다. Python 3.11+ 표준 라이브러리, 메모리 SQLite와 별도 상품 SQLite, 로컬 HTML/CSS/JavaScript로 구성한다. 기본 provider는 외부 호출 없는 `fake`다. 기존 `ShoppingApp`·CLI·개발자 관찰 서버는 `consumer-17-v1` 호환 경로로 남아 있다. 패키지·환경변수의 `stylemate_memory`·`STYLEMATE_` 이름도 유지한다.

```text
입력/이미지 선택 + 이유(선택 사항)
→ 최소 근거·Feedback 접수 → 모델 후보 추출 → 내용·binding 확인
→ 유효한 현재 요청 기억 + 동의한 장기 기억 조회
→ 직접 PI·FEA 요구 + 별도 FEA→PI 가설
→ 사용자 목표 PI와 상품 PI 비교 → 가설 포함/비포함 이미지 비교 ↺
→ 최종 상품 선택(선택 사항) → 세션 종료
→ 종료 요약에서 기존 후보 확인 → 별도 이후 활용 동의 → 장기 기억
```

### 구현 상태

| 경계 | 현재 코드·동작 | 남은 범위 |
|---|---|---|
| 입력 해석 | [model_io.py](../src/stylemate_memory/model_io.py)·[llm.py](../src/stylemate_memory/llm.py): complete/extract/propose, 인용·출처 alias 검사, pending 재처리 | 실제 한국어·선택 이유 해석 품질, 실제 provider 검증 |
| 메모리 저장 | [store.py](../src/stylemate_memory/store.py)·[store_v1.py](../src/stylemate_memory/store_v1.py)·[store_feedback.py](../src/stylemate_memory/store_feedback.py)·[store_cleanup.py](../src/stylemate_memory/store_cleanup.py): 근거·문장·선택적 binding, 확인·동의·교체·철회·삭제 | 실제 사용자 DB 이관·운영 자료 검증 |
| 조회·목표 생성 | [retrieval.py](../src/stylemate_memory/retrieval.py)·[inference.py](../src/stylemate_memory/inference.py): 유효성/대상/요청 필터, 구조+키워드 검색, PI/FEA 목표·최신성 검사 | 실제 의미 검색 모델 선정·관련성 평가 |
| 상품·이미지 비교 | [catalog.py](../src/stylemate_memory/catalog.py)·[catalog_mapping.py](../src/stylemate_memory/catalog_mapping.py)·[product_search.py](../src/stylemate_memory/product_search.py)·[comparison.py](../src/stylemate_memory/comparison.py)·[hypotheses.py](../src/stylemate_memory/hypotheses.py): 가져오기·PI Map·필수 조건 필터·가설 비교 | 실제 상·하의 수집, 수집 기반 value 사전 확정·실행 연결, 검증·추천 품질 |
| 서비스·소비자 UI | [app.py](../src/stylemate_memory/app.py)의 `ConsumerService`, [consumer.py](../src/stylemate_memory/consumer.py)·[consumer.js](../src/stylemate_memory/consumer.js)·[consumer-http.js](../src/stylemate_memory/consumer-http.js): 온보딩·피드백·확인·재탐색·종료·별도 장기 동의·삭제 | 공개 인증/배포, 실제 참가자 사용성·기기 검증 |

### 이미지·텍스트 인터랙션

- 온보딩과 쇼핑 요청을 구분한다. 같은 요청 재개는 SQLite 상태를 복원하고, 새 요청에는 이전 단기·가설을 자동 적용하지 않는다.
- 초기 입력과 일반 선택·부분 선택은 근거로 접수한 뒤 기억 후보를 만든다. 현재 서비스의 초기 추출은 명시적 검토 전까지 단기 미확인 후보이며, 직접 발화라는 이유로 자동 확인하지 않는다.
- 이미지 선택은 로컬 초안이다. 이유·수정 사항을 적거나 비운 채 같은 반영 버튼으로 제출한다. 후보 없음·모르겠음·텍스트만 응답도 가능하며 이유 입력은 필수가 아니다.
- 일반 이미지 선택만으로 모든 속성 선호·미선택 후보 비선호를 만들지 않는다. 가설 비교의 명확한 응답과 일반 선택 근거의 해석을 구분한다.
- 확인한 조건으로 재탐색할 수 있고, 모든 속성을 채우거나 상품을 고르기 전에 종료할 수 있다. `select_final`은 최종 선택만 기록하며 요청을 닫지 않는다. `end_request`가 별도로 세션을 닫는다.
- 장기 활용 선택은 종료 요약에서만 노출한다. 종료 전에 접수·해석한 후보는 종료 후에도 내용/binding을 확인할 수 있다. 종료 후 새 입력·늦은 추출은 거부한다. 항목 선택과 동의 체크는 기본 해제다.

## 메모리 실행 계약

### 장단기 메모리 핵심 설계안

현재 구현에서 장단기는 **적용·활용 범위**, 취향·요구·상황은 **기억의 내용 종류**다. 기억의 정본은 최소 자연어 문장과 근거·대상·조건·확인/동의 상태다. PI/FEA 매핑은 선택 사항이므로 사전 밖 표현도 `bindings=[]`인 기억으로 보존할 수 있다. 요약·반복 선택·목표 생성은 장기 활용 권한을 만들지 않는다.

| 저장 객체 | 역할 |
|---|---|
| `Evidence`·`Feedback`·`InterpretationState` | 실제 발화/선택의 최소 근거, 같은 응답의 연결, pending/complete 해석 상태 |
| `MemoryItem` | 독립적으로 확인·수정할 문장, kind·scope·selector·conditions·polarity/strength·origin·기간·상태 |
| `FeatureBinding` | 문장을 사전의 PI 또는 FEA에 연결한 해석. 문장 확인과 binding 확인을 따로 관리 |
| `ReviewDisplay`·`TrustedUserEvent`·`Confirmation`·`Consent` | 서버가 표시한 범위와 실제 사용자 조작, 내용 확인과 별도 `future_reuse` 동의 |
| `CandidateSet`·`ComparisonRound`·`consumer_comparisons` | 불변 카드 목록·상품/이미지 버전·가설 질문·표시 의미와 응답의 연결 |

`origin=explicit|inferred`와 `confirmed`는 별개다. 추론에서 시작한 문장은 확인 후에도 `origin=inferred`를 유지한다. 상태는 `candidate|active|superseded|withdrawn`이며 삭제는 원문을 둔 상태 표시 대신 실제 제거한다. `short_term`은 해당 요청에만 속하고, `long_term`은 내용 확인과 별도 동의가 필요하다. 요청 slot을 자동 제거해 일반 취향으로 넓히지 않는다.

### 저장·입출력 계약 v1

현재 실행의 저장 계약은 `lumi-memory-v1`, 사전 버전은 `park-2025-source-v1`, 상품 공급 형식은 `lumi-catalog-v1`이다. 수집 기반 PI value 사전의 버전·실행 연결은 아직 확정하지 않았다. 정확한 Python/JSON 필드·포트·action은 [contracts.py](../src/stylemate_memory/contracts.py), 오류 이름은 [errors.py](../src/stylemate_memory/errors.py)가 정의한다. TypedDict는 런타임 검증기가 아니며 각 담당 모듈이 형식·소유권·권한을 검사한다.

- 참조는 `{type, id, version}`, 시각은 timezone이 있는 ISO 8601이다. nullable 필드는 `null`, 매핑 없음은 `[]`로 표현한다. version/revision은 bool을 제외한 정수다.
- `MemoryStore.apply_batch(..., contract_version=..., expected=...)`가 쓰기 경계다. expected의 request/profile revision과 객체 version, action별 기대 version을 검사하고 batch 전체를 적용하거나 rollback한다.
- 같은 사용자·batch ID·동일 본문은 최초 영수증을 반환하고 본문이 다르면 `idempotency_conflict`다. 본문 fingerprint는 정규 JSON의 계약·요청·actions 기준이며 expected는 제외한다. 서비스 command도 command ID로 중복 반영을 막는다.
- `submit_feedback`은 단독 batch로 근거·Feedback·pending을 함께 접수한다. 해석 실패는 접수 실패와 다르다. `retry_extraction`은 같은 feedback 근거를 재처리하며 새 원문이나 중복 후보를 만들지 않는다.
- `create`, `confirm`, `propose_bindings`, `confirm_bindings`, `promote`, `create_long_term`, `replace`, `withdraw`, `delete`와 내부 추출/비교·최종 선택/종료 action을 구분한다. 모델 출력으로 쓰기 command·확정 상태·동의를 받지 않는다.
- `issue_display`가 서버 snapshot과 basis를 저장한다. `respond_review`는 표시 참조와 accept/decline/skip만 받고, 서비스가 목적별 사용자 이벤트를 발행한다. UI가 보낸 임의 snapshot이나 모델 bool을 확인·동의로 사용하지 않는다.
- `promote`는 단기 행의 scope 수정이 아니라 새 장기 항목·독립 최소 Evidence/Confirmation/Consent snapshot을 같은 batch로 만드는 전이다. 원 요청 삭제 후에도 동의한 최소 범위만 독립 근거로 유지한다.
- 소비자 서비스는 `future_reuse` 준비와 수락을 closed 요청에서만 허용한다. 범용 저장 계층의 기존 직접 장기 생성 호출은 호환 경로로 유지한다. 최종 선택·내용 확인·세션 종료만으로 장기 동의가 생기지 않는다.

공통 입력 상한은 [저장 검증](../src/stylemate_memory/store_v1.py)과 contracts를 따른다. 내부 JSON은 UTF-8 기준 256 KiB, 사용자 텍스트는 최대 4,000자다. HTTP body의 별도 24,000-byte 상한을 늘리는 근거가 아니다.

### 조회와 목표값

`build_context_v1`은 소유권·활성/확인·장기 동의·요청/대상·기간·조건을 먼저 검사한 뒤 직접 조건과 관련 근거를 묶는다. 상황의 `occasion|activity|goal`은 확인된 facts로 취급하고 미확인 조건은 충족으로 보지 않는다. 같은 우선순위 충돌은 임의로 한 값을 고르지 않고 질문으로 남긴다. 현재 요구가 장기 취향과 충돌하면 이번 목표에서만 우선하고 장기 원본은 보존한다.

구조·키워드 검색과 교체 가능한 의미 검색 포트가 있으며 실제 임베딩 모델은 연결하지 않았다. 기본 문자 예산은 6,000자이고 근거 참조 상한도 검사한다. 필수 조건을 담지 못하면 조용히 누락하지 않고 context를 보류한다. 장기12/단기20개 예산은 아래 기존 17개 사전 경로의 설정이며 v1의 고정 항목 수로 적용하지 않는다.

모델에는 최소 근거의 호출별 source alias와 사전·대상만 제공한다. 실제 사용자 ID·raw DB snapshot·동의 원문·내부 basis를 보내지 않는다. 목표 `TargetMap`은 직접 constraints와 검증된 soft 제안을 조합한 파생 결과이며 새 사용자 발화나 장기 취향으로 재저장하지 않는다.

모델 계산은 DB executor 밖에서 실행하고 적용 직전에 request/profile revision·사용 객체·시각·사전/색인·카탈로그 버전을 다시 검사한다. 후보 발행과 쓰기 직전에는 선택 카드뿐 아니라 묶음 전체의 raw/map/image 버전을 대조한다. 수정·철회·삭제·만료·종료 뒤 늦은 응답은 `stale_context` 등으로 거부한다.

### 보관·철회·삭제

| 대상 | 현재 보관 상한 |
|---|---|
| 요청 | 마지막 사용자 활동+30일과 생성+90일 중 이른 시한 |
| 활성 장기 | 명시 동의+365일 |
| 교체·철회한 내용 | 기존 시한과 비활성+30일 중 이른 시한 |
| 내용 없는 삭제 재시도 경계 | 24시간 |

적용 유효 기간 `[valid_from, valid_until)`과 보관 시한은 별개다. 만료 내용은 조회에서 제외하며 `prune_expired()`는 호출자가 실행한다. 예약 정리 작업은 설치하지 않는다.

철회는 활용 제외, 삭제는 관리 DB의 관련 내용·사본·근거·파생 자료·영수증/journal 정리다. 같은 promote 가족을 함께 처리하며 무관한 supports 관계까지 연쇄 삭제하지 않는다. 요청 삭제는 독립 동의한 장기 snapshot과 구분한다. 삭제한 내용을 과거 모델 출력·요약·재색인으로 되살리지 않는다. 삭제 재시도에는 원문·대상 ID·일반 payload digest 대신 내용 없는 단방향 fingerprint/opaque nonce를 사용한다.

이 기간과 정리 범위는 로컬 프로토타입 계약이다. 사용자 사본·OS 백업·저장매체 완전 소거를 포함하지 않는다. 참여자 자료·실행 DB·원시 응답은 저장소 밖에서 관리한다.

## Feature Map

PI는 **Type·Brand·Price·Color·Fit·Fabric·Detail의 7개 feature 축을 유지하고, 각 value는 실제 수집한 상품 데이터를 바탕으로 확정한다.** [ADR 0010](adr/0010-derive-pi-values-from-collected-products.md)이 기존 논문 목록을 최종 PI 허용값으로 고정한 결정을 부분 대체한다. FEA의 Functional 8·Expressive 13·Aesthetic 9, 총 30개 태그와 PI/FEA 역할은 유지한다. 두 영역을 37개의 동등한 상품 속성으로 합치지 않는다.

PI 7개 축과 FEA 분류를 차용한 출처는 Park, H., Kim, S., Choi, Y., & An, H. (2025), *Application of the FEA consumer needs model in e-commerce: a conversational recommendation system for fashion products*, Fashion and Textiles, 12, 24의 Table 1·2다. [논문 원문](https://doi.org/10.1186/s40691-025-00435-w), 출처·CC BY 4.0·변환/승인 메타데이터는 JSON에 기록한다.

### 수집 데이터 기반 PI value 확정

네이버 쇼핑의 **상의·하의**에서 원본 속성명·값·출처를 수집하고, 품목별 분포·누락 확인→동의어 정규화→PI value·사전 버전 확정 순서로 진행한다. 기존 논문 enum 밖의 값도 보존하고 미기재·추론값·직접 근거를 구분한다. 가격은 숫자 원값과 조건을 확보한 뒤 구간화 여부를 정한다.

수집 경로·PI별 필드·중간 레코드·정규화·파일럿 검증의 상세 계약은 [crawling.md](specs/crawling.md)에서 관리한다. 현재는 설계 단계이며 크롤러·실제 상품 데이터셋·수집 기반 실행 사전은 미구현이다. 실제 접근 경로·수량·품질 기준과 최종 value 목록은 아직 확정하지 않았다.

### 현재 실행 사전

[JSON](../output/feature-map/park-2025-feature-map.json)의 PI 값은 논문 차용 및 현재 코드의 실행 기준이며, 수집 후 확정할 최종 PI value 목록은 아직 없다. 기존 JSON·CSV와 출처·라이선스는 보존하고 전체 enum을 이 문서에 복제하지 않는다.

[registry.py](../src/stylemate_memory/registry.py)의 `load_registry("park-2025-source-v1")`가 실행 사전을 공급한다. [패키지 JSON](../src/stylemate_memory/resources/park-2025-feature-map.json)은 정본의 생성 사본이다. `python3 scripts/sync_feature_registry.py`로 동기화하며 수동 편집하지 않는다.

현재 코드의 값 있는 매핑은 **Pants만 지원**한다. 원문의 값은 무신사 여성 바지 기준이며 이 실행 한계가 수집 대상을 바지로 제한하지는 않는다. Brand는 원문의 전체 419개 값이 미공개여서 현재 실행 enum을 지원하지 않는다. Price는 원문 구간 문자열 일치만 지원하고 수치 변환·통화·경계 포함·range는 미정이다. 다른 품목, `Relaxed→Wide`, 원단 종류→섬유 원료 같은 자동 치환은 지원하지 않는다. 수집 기반 사전·상의 매핑·한국어 값 정규화는 아직 실행 코드에 반영하지 않았다.

### 직접 PI와 FEA→PI 가설

사용자 목표 Map은 **직접/확인 PI + FEA 요구 + 별도 FEA→PI 가설**, 소비자 상품 Map은 **PI**를 사용한다. 직접 표현한 PI는 원래 근거·대상·조건·방향·강도와 함께 반영하며 FEA를 거쳐 재생성하지 않는다.

`infer_with_hypotheses`는 TargetMap과 별도 가설 목록을 반환한다. FEA 기반 제안은 같은 target의 긍정 FEA 제약·source IDs를 참조하고 **Type·Color·Fit·Detail 중 한 값, prefer/soft**만 허용한다. 직접 PI가 있는 축의 가설은 제외한다. 예를 들어 “편하게”에서 `Fit=Wide`를 제안해도 그 연결은 해당 사용자·요청의 미확인 가설이며 필수 조건이 아니다.

### 가설 비교 실행 확장

[hypotheses.py](../src/stylemate_memory/hypotheses.py)와 ConsumerService가 다음 흐름을 연결한다.

1. 실제 로컬 이미지가 있고 가설 PI 값의 포함/비포함이 확인된 상품을 비교한다. 미확인 PI를 비포함 사례로 사용하지 않는다. 비교 가능한 가설부터 하나 제시하고 대안이 없으면 일반 탐색을 유지한다.
2. `consumer_comparisons`를 CandidateSet에 FK로 연결해 가설·질문·옵션별 표시 의미와 binding을 저장한다. 사용자 응답은 서버의 표시 snapshot을 기준으로 처리한다.
3. `respond_comparison`은 `candidate_set_ref`, `candidate_id`(없으면 null), `decision=choose|neither|unsure`, 선택적인 `text`를 받는다. 비교 선택과 이유는 내부 `record_comparison` 한 batch의 Feedback/Evidence로 접수한다.
4. 텍스트 없이 명확하게 고르면 표시된 PI 해석만 확인하며 `origin=inferred`, `strength=soft`를 보존한다. 이유가 있으면 수정·상충 가능성을 함께 해석해 독립 미확인 후보를 만들고 원래 PI를 즉시 확정하지 않는다. 실패 시 같은 근거를 pending으로 재처리한다.
5. 없음·모르겠음·건너뛰기는 확정이나 다른 속성의 비선호가 아니다. 내용/binding 확인과 장기 활용 동의도 별개다. 종료 후 후보 확인에는 당시 상품/이미지 버전을 다시 검사한다.

PI 7항목이 모든 FEA 성능을 검증하지는 못한다. Wide를 골라도 실제 착용 편안함을 입증한 것은 아니다. 미해결 필수 FEA가 있으면 비교는 허용하되 현재 소비자 서비스의 최종 상품 선택을 보류한다. 추가 상품 근거나 사용자 조정 없이 충족 처리하지 않는다.

### PI·FEA binding과 목표 출력

PI binding은 canonical `values` 배열과 any/all 연산, FEA binding은 category/subcategory/tag 경로와 요구 방향을 가진다. 같은 문장 안의 독립 선호·회피는 항목을 나누고 값·방향·강도를 보존한다. 상품의 관찰값과 사용자의 요구 방향을 같은 객체로 저장하지 않는다.

TargetMap은 사전의 모든 PI/FEA 항목을 반환하며 미정 PI `values`와 FEA `preference`는 `null`이다. 필드별 `constraint_ids`가 가리키는 개별 constraints가 연산 정본이다.

| status | 의미 |
|---|---|
| unspecified | 원하는 값 미정. 알려진 회피 제약은 별도로 보존 |
| inferred | 시스템의 soft 제안이며 사용자 지정·hard 조건과 구분 |
| specified | 직접 지정 또는 해당 binding을 확인한 근거가 있음 |
| indifferent | 사용자가 해당 soft 선호 축에 명시적으로 상관없다고 응답 |
| not_applicable | 해당 대상에 적용되지 않는다는 근거가 있음 |
| unsupported | 실행 사전/매핑 지원 범위 밖 |
| conflict | 같은 우선순위 상충. 대안·근거·질문 보존 |

문장 확인만으로 모든 binding을 specified로 올리지 않는다. 미정·상관없음·회피·비적용·미지원·상충을 같은 의미로 합치지 않는다. 종료까지 관련 없는 항목은 미정이어도 된다.

## 상품과 이미지

### 가져오기와 provenance

[CatalogRecord](../src/stylemate_memory/contracts.py)는 format_version/product_id/source/title/description/garment_type/raw_metadata/images/labels를 가진다. JSON은 레코드 배열, JSONL은 줄마다 레코드 하나다. [합성 fixture](../tests/fixtures/catalog/valid.jsonl)를 형식 예시로 사용한다. 실제 상품·이미지는 저장소 밖에서 공급한다.

- source에는 출처 ID·원문 URL·수집 시각을 둔다. 비어 있는 설명은 null, 없는 이미지/라벨은 []다. 가져오기는 product_id별 추가/갱신이며 파일에 빠진 상품을 자동 삭제하지 않는다.
- 원자료 변경은 raw_version, Map 변경은 map_version, 이미지 revision/해시/ref 변경은 image version, 공개 상태 변경은 catalog_version으로 구분한다. 같은 자료의 재공급은 멱등이며 출처 정체성이 다른 동일 product_id는 거부한다.
- 상품 Map의 provenance는 raw_metadata·provided_label·verified_label·model_interpretation·unknown을 구분한다. 정확한 사전 값의 원문 정규화와 공급 주장·검증 라벨·모델 추정을 구별한다. 사진·모델 추정만으로 기능 성능을 confirmed로 만들지 않는다.
- 소비자 `build_catalog_maps()`·CLI `catalog-map`과 소비자 검색은 `pi_only=True`다. 범용 PI·FEA Map/검색 함수의 기본 동작은 기존 호출과 데이터 호환을 위해 유지한다.
- 검색은 목표의 직접/필수 조건을 보존한다. unknown/inferred/conflict는 hard 충족이 아니며 조건을 임의로 완화하지 않는다. blocked와 실제 결과 0건인 no_results를 구분한다.

이미지는 외부 image root 아래 상대 경로의 PNG/JPEG/WebP/GIF(각 10 MiB 이하)로 공급한다. 바이트·영역 변경 시 source_revision을 갱신하고 선택적 SHA-256을 제공한다. 최신성은 공급 revision/해시 기준이며 원격 바이트의 실시간 검사가 아니다. remote ref는 가져올 수 있지만 소비자 서버가 다운로드·표시하지 않으며 image_url=null이다.

전체 선택과 부분 선택을 구분한다. 부분 선택은 제공된 region 또는 정규화 box `[x0,y0,x1,y1]`를 이미지 ID/version과 연결한다. 좌표는 0~1, 면적은 양수여야 한다. 없는 영역·다른 이미지·이미지 없는 카드의 부분 선택은 거부한다. 선택 위치의 모든 속성을 확인한 것으로 해석하지 않는다.

상품 공급 갱신은 서버를 중지한 뒤 가져오기/Map 생성 후 다시 시작한다. Python 서비스의 `import_catalog`·`build_catalog_maps`는 같은 DB executor에서 직렬화한다. 실행 중 별도 프로세스의 카탈로그 쓰기와 서로 다른 상품 DB의 version 계보를 기존 요청에 혼용하는 운영은 지원하지 않는다. 카탈로그 참조에는 상품·이미지 ID 각각 256개 상한이 있어 큰 데이터셋 연결 전 범위 검토가 필요하다.

## 로컬 실행

저장소 루트에서 Python 3.11+로 실행한다. 추가 Python 의존성은 없다. 메모리 DB·상품 DB는 서로 다른 **저장소 밖** 파일이어야 하며 이미지 root도 저장소 밖에 둔다.

```sh
export STYLEMATE_DB=/private/tmp/lumi-local/memory.sqlite3
export STYLEMATE_CATALOG_DB=/private/tmp/lumi-local/catalog.sqlite3
# 로컬 이미지를 준비한 경우 STYLEMATE_IMAGE_ROOT를 해당 외부 디렉터리로 설정

PYTHONPATH=src python3 -m stylemate_memory.cli catalog-import --file tests/fixtures/catalog/valid.jsonl
PYTHONPATH=src python3 -m stylemate_memory.cli catalog-map
PYTHONPATH=src python3 -m stylemate_memory.consumer --provider fake
```

소비자 화면은 [http://127.0.0.1:8766](http://127.0.0.1:8766)이다. `python3 -m stylemate_memory.cli serve`도 같은 서버를 실행한다. 합성 fixture의 이미지 바이트는 자동 공급하지 않는다. 기본 fake는 빈 추출/제안을 반환하는 연결용 adapter이므로 자연어 해석·상품 추천 데모로 사용하지 않는다. 확인된 기억이 없는 context는 blocked이며 통합 검사는 별도의 명시적 합성 추출을 공급한다.

### 설정

| 환경변수 | CLI / 기본값 |
|---|---|
| STYLEMATE_DB | `--db`, 필수 메모리 SQLite 경로 |
| STYLEMATE_CATALOG_DB | `--catalog-db`, 필수 상품 SQLite 경로 |
| STYLEMATE_IMAGE_ROOT | `--image-root`, 선택적 로컬 이미지 root |
| STYLEMATE_USER_ID | `--user`, 기본 local-tester; 서버 생성 시 고정 |
| STYLEMATE_PROVIDER | `--provider fake / openai`, 기본 fake |
| STYLEMATE_OPENAI_MODEL | `--model`, 소비자 기본 gpt-6-luna |
| STYLEMATE_PORT | `--port`, 기본 8766 |
| OPENAI_API_KEY | openai를 명시적으로 선택할 때만 조회 |

[settings.py](../src/stylemate_memory/settings.py)가 경로·설정·gateway를 구성한다. 실제 API 실행이 요청된 경우에만 사용자가 로컬 환경에 키를 설정하고 `PYTHONPATH=src python3 -m stylemate_memory.consumer --provider openai --model gpt-6-luna`로 시작한다. 키를 CLI 인자·예제 파일·로그에 넣지 않는다. import·기본 fake·상품 가져오기/Map 생성·읽기 관찰에는 키가 필요 없다.

### 서비스·HTTP 경계

서버는 루프백 단일 테스터용이다. `GET /api/state[?request_id=...]`, `POST /api/command`, `GET /api/images/{image_id}?version=N`과 패키지 자산 allowlist만 제공한다. Host/동일 Origin·JSON·24,000-byte body 상한을 검사한다. 이미지 ID/version은 설정 root 안에서 해석하며 traversal/symlink escape를 거부한다. 사용자 ID·provider·파일 경로·임의 StoreAction을 HTTP 입력으로 받지 않는다.

`ConsumerCommand`는 contract_version/command_id/request_id/expected/action을 가진다. start_request만 request_id/expected=null이며 나머지는 서버가 반환한 state의 참조와 expected를 사용한다.

| UI action | 역할 |
|---|---|
| start_request / resume_request | 온보딩·쇼핑 새 요청 / 같은 요청 복원 |
| submit_feedback / respond_comparison | 일반 텍스트·전체/부분 선택 / 가설 선택과 선택 사항인 이유 접수 |
| retry_extraction / explore | 같은 pending 근거 재해석 / 유효 조건으로 재탐색 |
| prepare_review / respond_review | 서버 표시 준비 / 표시 참조에 대한 명시적 응답 |
| select_final / end_request | 최종 상품 선택 / 상품·저장 없이도 세션 종료 |

`ConsumerState`는 요청·phase·operation·기억·카드·가설 비교·검토·질문·안전한 오류를 반환한다. interpretation_pending·blocked·no_results·stale·error는 성공과 구분한다. provider 실패를 다른 provider나 rule 성공으로 대체하지 않는다. 수정 문장은 새 근거로 추출·재확인하고 기존 장기 동의를 자동 승계하지 않는다.

요청·근거·후보·확인·동의는 SQLite에서 복원한다. 서비스 journal은 명령 본문·전체 대화·전체 화면 대신 fingerprint·참조·처리 상태를 저장한다. 삭제 시 관련 journal을 비우고 재시도 응답은 현재 화면을 다시 조회해 삭제 전 내용을 되살리지 않는다.

## 기존 CLI와 개발자 관찰 도구

### 현재 실행 중인 17개 속성

기존 CLI의 인자 없는 `features`, 기본 추론과 기존 관찰 서버는 `consumer-17-v1`이다. 현재 소비자 서비스의 Park 사전과 구분한다. 17개 속성과 허용값은 [registry.py](../src/stylemate_memory/registry.py) 또는 아래 명령으로 확인한다. metadata의 과거 `pdf`/source 표시는 중간보고서·Park 사전의 상품 스키마가 아니다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.cli features
PYTHONPATH=src python3 -m stylemate_memory.cli features --registry park-2025-source-v1
PYTHONPATH=src python3 -m stylemate_memory.cli request --help
PYTHONPATH=src python3 -m stylemate_memory.cli batch --help
PYTHONPATH=src python3 -m stylemate_memory.cli infer --help
```

기존 `apply_batch`는 feature/values·polarity·strength·match·selector·conditions·content·scope·origin/confirmed·확인/동의 참조를 받는다. formality의 range는 양끝 포함이며 any/all 연산을 보존한다. v1 계약을 생략한 호출은 이 경로를 사용하고 자동으로 Park 값에 대응시키지 않는다.

기존 `build_context`는 장기12/단기20개·사용자 내용/조건6,000자 예산과 대상별 facts를 적용한다. 직접 조건을 모델이 누락해도 보존하며 혼합 any/all은 표시용 match=null과 개별 constraints로 구분한다. 이 null을 v1의 값 미정과 혼동하지 않는다. `ShoppingApp.infer_request()`는 모델 응답 후 최신 snapshot으로 재검사하며 목표 추론은 기억을 자동 저장하지 않는다.

### 개발자 관찰 도구

소비자 서비스의 상태·snapshot/context를 모델 호출 없이 읽으려면, 같은 외부 DB 설정에서 다음을 사용한다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.inspector --consumer-state
# 특정 요청은 --request REQUEST_ID 추가
```

기존 관찰 서버는 별도 `consumer-17-v1` 도구다. 아래 실행 뒤 텍스트 추출·목표 추론 조작에는 실제 Codex 모델 호출이 발생하므로 해당 실행을 요청받았을 때만 사용한다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.inspector \
  --port 8765 \
  --db /private/tmp/stylemate-inspector/memory.sqlite3 \
  --garment-type Pants \
  --model gpt-6-luna
```

[로컬 관찰 도구](http://127.0.0.1:8765)는 Chat·Memory·Feature Map과 processing trace/raw JSON을 보여준다. 미확인 후보→테스터 확인→현재 적용/별도 장기 활용을 관찰하며 이 도구의 장기 조작은 소비자 서비스의 종료 요약 UI와 구분한다. 대상 변경은 다른 대상의 기억을 옮기지 않고 새 요청은 이전 단기를 이월하지 않는다. Infer는 목표값만 재생성한다.

[codex_llm.py](../src/stylemate_memory/codex_llm.py)는 기존 로그인된 Codex CLI를 일회성 JSON 변환으로 사용한다. 별도 임시 폴더·읽기 전용 sandbox·ephemeral·출력 schema와 도구 제한을 적용하며 앱이 로그인 파일을 직접 읽지 않는다. 전체 채팅·모델 원본·trace는 프로세스 메모리에 있고 최소 기억·참조·버전만 SQLite에 남는다. 실패한 모델 결과를 성공이나 저장 rollback으로 표시하지 않는다.

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

## 오프라인 실행과 검증

아래는 합성 입력·실제 SQLite·가상 모델/HTTP 응답으로 확인하는 명령이다. 실제 외부 모델을 호출하지 않는다.

```sh
python3 scripts/check_repository.py
git diff --check
python3 scripts/sync_feature_registry.py --check
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 -m stylemate_memory.cli demo --synthetic
PYTHONPATH=src python3 scripts/evaluate_offline.py
node tests/check_consumer_http_browser.mjs
node tests/check_hypothesis_browser.mjs
```

브라우저 검사는 설치된 Node·Playwright·Chromium을 사용하며 의존성을 자동 설치하지 않는다. [서비스 검사](../tests/test_consumer_service.py)·[HTTP 검사](../tests/test_consumer_http.py)·[가설 검사](../tests/test_hypotheses.py)와 두 브라우저 검사는 접수·후보 확인·PI 비교·선택+이유·종료 후 동의·재시작·새 요청·삭제·늦은 응답을 검사한다. 브라우저 그림과 상품은 합성 자료다.

[오프라인 평가](../scripts/evaluate_offline.py)는 [기억 fixture](../tests/fixtures/evaluation/memory_cases.jsonl)와 상품 fixture의 회수·오탐·근거 완전성·필수 조건·unknown 오인·중복/없는 비교를 검사한다. `--fixtures DIR`로 입력, `--output FILE`로 저장소 밖 출력 파일을 지정할 수 있다. 의미 검색은 각본 fake이며 실제 API 토큰·비용은 관측하지 않는다. CLI 데모의 Relaxed/Navy→이번 Slim→새 요청 Relaxed는 기존 17개 사전 호환 검증이다. v1의 Navy/Wide→이번 Slim→새 요청 Wide는 [목표 테스트](../tests/test_inference.py)의 별도 합성 사례다.

### 검증 범위와 한계

- 구조·상태·원자성·최신성·삭제 경계의 합성 통과와 실제 모델 의미 품질·상품 추천 품질·사용자 효과를 구분한다. 실제 모델·실제 상품·참여자 연구는 별도 검증이다.
- 실제 provider의 계정 접근권한·응답 호환성은 별도로 확인해야 한다. [Responses adapter](../src/stylemate_memory/llm.py)의 strict schema·store=false·timeout·안전한 오류는 fake transport 검사와 구분해 읽는다.
- 문서 검사기는 코드 블록 밖 인라인 Markdown 링크·지원하는 제목 앵커·남아 있는 HTML 내장 원문 쌍·Issue/PR 템플릿 기본 구성을 검사한다. archive는 제외하며 이미지·참조형/HTML 링크·외부 URL·화면 품질은 검사하지 않는다.
- 현재 CI 정의는 repository-checks의 문서/템플릿 검사, memory-tests의 Python 3.11/3.14 오프라인 테스트·가상 데모다. 로컬 통과만으로 원격 CI·브랜치 보호·승인 규칙 활성화를 주장하지 않는다.
- 과거 작업 단계·테스트 개수·실행 결과는 해당 Git 커밋·PR에서 확인한다. 이 문서는 현재 실행 계약을 갱신하고 매 작업의 검사 보고서를 누적하지 않는다.

## 다음 작업

| 미구현·미검증 범위 | 필요한 확인 |
|---|---|
| 실제 상·하의 상품·로컬 이미지 | [수집 계약](specs/crawling.md)에 따라 네이버 쇼핑 접근 경로·표본 확보 후 원문·이미지·근거 수집. 크롤러·원격 수집은 미구현 |
| 수집 기반 PI value 사전 | [value 정리·확정](specs/crawling.md#6-value-정리와-확정) 후 registry·상품/목표 Map·모델 입출력·검증 연결. 기존 사전 버전과 자료 보존 |
| 실제 모델·가설 비교 | 명시적 실행 후 한국어 표현·선택 이유·실제 비교 축과 대안·FEA 성능 판단 경계 평가 |
| 실제 의미 검색 | 모델 선정 후 관련 근거 회수·오탐·근거 완전성·삭제/재색인·비용 비교 |
| 운영 자료 이관 | 원래 의미·대상·동의·기간 보존, 합성 이관/rollback과 실제 자료 승인을 구분 |
| 사용자 연구 | 보고서 기준 파일럿·동의/과제 안내·설문·분석 준비. 참여자 자료는 저장소 밖 관리 |

수집 대상은 상·하의이며 PI value를 수집 데이터에서 정하는 방향은 확정했다. 구체적인 상품 수집 경로·수량·품질 기준과 최종 value 목록은 미확정이다. 실제 수집·실행 코드 변경은 후속 작업 범위로 정한다.

### 선행연구에서 가져오는 범위

메모리 연구의 적용 관점과 대안은 [ADR 0005](adr/0005-evidence-linked-memory.md)의 결정 맥락이다. 실제 학습형 관리자·임베딩 모델·자동 장기화를 구현한 것으로 보지 않는다. 현재 연결 상태는 [구현 상태](#구현-상태)를 따른다.

### A0 공통 인터페이스와 담당 경계

기존 ADR에서 연결한 A0 작업 분담은 과거 구현 단계다. 현재 타입·포트는 [contracts.py](../src/stylemate_memory/contracts.py), 실제 모듈 연결은 [구현 상태](#구현-상태)를 따른다. 단계별 프롬프트·작업 기록을 현재 실행 계약으로 중복 유지하지 않는다.
