# 쇼핑 메모리·목표 feature 프로토타입

- Related Issue: [#2](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/2)
- 로컬 프로토타입의 승인·축소 이유: [ADR 0003](decisions/0003-consumer-shopping-prototype.md)
- 역할: `src/stylemate_memory/`의 현재 실행 계약. 보관된 [v0.2 설계](../archive/docs/memory-design.md)와 [전체 목표 feature 계획](../archive/docs/target-feature-inference-plan.md)은 역사적 설계/확장 참조이며 실행 객체와 동일한 JSON 형식이 아니다.

**보고서와의 관계:** 시스템 설계는 [Team4_mid-term_report.pdf](sources/Team4_mid-term_report.pdf)를 따른다. 이 문서는 기존 Memory Layer·목표 Item Feature Map의 실행 계약을 설명한다. 이미지 선택·상품별 Item Feature Map·상품 검색/추천은 미구현이다. 보고서 단계별 차이와 다음 개발 범위는 [workflow](workflow.md)에 있다. 기존 `stylemate_memory` 이름과 저장·확인·동의·API 계약은 유지한다.

## 1. 구현 흐름과 범위

신뢰된 로컬 호출자가 요청·기억 확인·이후 활용 동의를 전달한다. SQLite가 항목별 상태와 버전을 저장하고, 현재 요청/대상에 유효한 기억만 context로 조립한다. rule 또는 OpenAI adapter가 목표값을 제안하면 시스템이 값·대상·근거·제약과 최신 상태를 검증한다. 모델 출력은 메모리를 자동으로 바꾸지 않는다.

실제 상품 feature 추출·검색·추천/조합·구매, 일반 제품 화면·로그인·이미지 처리·자연어의 사용자 의도/동의 진위 판별은 이 실행 모듈에 없다. CLI의 사용자 ID·확인/동의 참조는 상위의 신뢰된 입력 이벤트가 제공해야 한다. 공개 API로 그대로 노출할 인증 계약이 아니다.

후속 [개발자용 관찰 도구](developer-memory-inspector.md)는 이 저장/context/목표 검증 코드 위에 Codex LLM의 자연어 **후보 추출**과 로컬 테스터의 확인·동의 버튼을 연결한다. 소비자 제품 UI·자연어 동의 진위 판별·실제 상품 추출을 구현한 것이 아니며, 기존 장기 확인/동의와 읽기 전용 목표 추론 계약을 유지한다.

### 연구 목적과 현재 구현의 경계

[연구 기준](master.md)은 보고서의 통제감·코디 적합성·표현 부담·스타일 구체화·이해받는 느낌 평가를 따른다. 이 모듈의 저장/context·목표 속성 검증은 그 시스템의 실행 기반이며 사용자 효과나 실제 상품 추천 품질의 증거가 아니다. 자유 취향 문장과 대화 맥락의 지속 보존, 이미지 선택 근거, 상품/피드백 연결은 후속 개발 범위다.

## 2. 일반 쇼핑용 17개 속성

현재 사전은 [이전 전체 feature 계획](../archive/docs/target-feature-inference-plan.md)의 item65/outfit9를 축소한 `consumer-17-v1`이다. 중간보고서는 전체 속성 수·허용값을 지정하지 않는다. 아래 표의 과거 대응과 `pdf` metadata를 중간보고서에서 정한 상품 스키마로 읽지 않는다. 기본 카테고리는 아이템 종류에서 파생하고 기장은 대상별로 통합했으며 근거 없는 값은 미정으로 남긴다.

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

## 3. 작은 메모리 입력 계약

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

## 4. Context와 목표값

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

## 5. 로컬 실행

실행 의존성은 Python 3.11+ 표준 라이브러리뿐이다. 저장소 루트에서 실행한다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.cli demo --synthetic
PYTHONPATH=src python3 -m stylemate_memory.cli features
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/check_repository.py
git diff --check
```

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

## 6. 실제 모델 연결

CLI의 Responses adapter는 명시적 model/key로 연결하며 테스트는 fake transport를 사용한다. 코드 import, demo, 기본 rule 추론은 자격 증명을 읽거나 실제 모델을 호출하지 않는다. Codex CLI로 실제 추출·목표 추론을 실행하는 [개발자 관찰 도구](developer-memory-inspector.md)는 별도 실행 경로다.

사용자가 로컬 환경에 `OPENAI_API_KEY`, `STYLEMATE_OPENAI_MODEL`을 설정하고 명시적으로 `infer --provider openai`를 실행할 때만 실제 연결을 사용한다. `--model`로 호출 모델을 지정할 수도 있다. 키를 CLI 인자·로그·오류·PR에 넣지 않는다. 모델 접근권한과 structured output 지원은 실제 호출 시 확인해야 한다.

adapter는 OpenAI Responses API에 `text.format`의 strict JSON Schema·`store=false`·출력 상한·timeout을 전달한다. [공식 Structured Outputs 이동 안내](https://developers.openai.com/api/docs/guides/migrate-to-responses#6-update-structured-outputs-definitions)를 기준으로 wire 형식을 구현했다. 응답 거부·불완전·비정상 JSON·HTTP/timeout 오류는 안전한 오류 코드로 반환하고 자동 무한 재시도·부분 성공으로 처리하지 않는다. 구조 검증은 의미 품질/공급자 전체 보관 정책의 증명이 아니다.

## 7. 검증과 남은 범위

테스트는 실제 SQLite와 합성 사용자·가상 모델/HTTP 응답으로 저장·동의·요청 격리·대상/상황별 context·충돌·목표값·최신성·삭제 경계를 확인한다. 위 실행 명령으로 현재 결과를 확인한다. 과거 테스트 수와 PR/임시 설치 결과는 [2026-10-14 보관 기록](../archive/docs/shopping-memory-prototype-20261014.md)에 있으며 이번 실행 결과로 재사용하지 않는다.

실제 모델의 자연어 해석 품질, 자유 표현·이미지 근거의 지속 보존, 상품 검색/매칭·추천 품질, 소비자 UI/로그인·사용자 연구는 이 오프라인 검증에 포함되지 않는다. 원격 CI도 실제 실행을 별도로 확인한다.

보관 기간·조회 예산·17개 사전은 현재 로컬 프로토타입의 설정이다. 이를 최종 서비스 정책으로 확정하거나 문서 정리만으로 변경하지 않는다. 관리 DB 삭제는 행·관련 내용/영수증·journal 정리 범위이며 사용자가 만든 사본·OS 백업·저장매체 소거는 포함하지 않는다.
