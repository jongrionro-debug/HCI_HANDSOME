---
template: doc
theme: shadcn
style: 80
title: 우리 메모리와 Feature Map은 어떻게 연결되는가
subtitle: 현재 구현 기준으로 읽는 기억 구조 · 조회 · 목표값 생성 · 사용자 제어
checked: 2026-10-14
basis: 로컬 HEAD 6ca871a · 기존 미커밋 문서 포함
registry: consumer-17-v1
---

현재 구조는 **장·단기 기억 → 대상별 Context → 목표 Feature Map**이다. 이번 요청에 유효한 기억만 사용한다. 사용자 지정값은 시스템이 보존한다. 모델은 근거가 있는 추가값만 제안한다. 모르는 값은 미정으로 남긴다.

## A 전체 구조는 무엇인가

### 서로 다른 세 가지 데이터를 구분한다

| 구분 | 답하는 질문 | 현재 역할 |
|---|---|---|
| 메모리 | 사용자가 무엇을 확인했고, 언제까지 어디에 적용하기로 했는가? | SQLite에 저장하는 사용자 조건의 정본 |
| Context | 그중 이번 바지·셔츠에 무엇을 적용할 수 있는가? | 대상·상황·기간·상태를 검사한 요청별 입력 묶음 |
| 목표 Feature Map | 이번에 어떤 속성의 아이템을 원하는가? | 직접 조건과 추론 제안을 합친 요청별 결과 |

```flow
[(장기 기억)] -> 대상별 Context: 기본 취향
[(이번 요청의 단기 기억)] -> 대상별 Context: 현재 조건과 예외
확인된 상황 -> 대상별 Context: 목적과 활동
대상별 Context -> 직접값 보존 및 추가 제안
직접값 보존 및 추가 제안 -> 시스템 검증
시스템 검증 -> 목표 Feature Map
```

장기 기억의 “바지는 Relaxed 선호”와 이번 요청의 “오늘은 Slim”은 별개 항목이다. 이번 목표에는 Slim을 적용할 수 있다. 다음 요청의 기본 취향은 Relaxed로 유지한다.

### 여기서 Feature Map은 목표값을 뜻한다

**사용자 목표의 속성**과 **실제 상품의 속성**은 구분한다. `functions=Waterproof` 목표는 방수 상품을 원한다는 뜻이다. 어떤 상품이 실제 방수라는 증거는 아니다. 사진에서 핏·색·원단을 추출하는 기능과 상품 검색·매칭은 현재 구현 범위 밖이다.

```callout info 현재 실행 범위
Python 3.11+와 SQLite로 메모리 저장·조회·목표값 검증을 구현했다. CLI와 오프라인 rule adapter가 동작한다. 실제 LLM 연결 코드는 있으나 실제 호출과 의미 품질 평가는 남아 있다.
```

근거: [현재 실행 계약](../docs/shopping-memory-prototype.md), [축소·구현 결정 ADR 0003](../docs/decisions/0003-consumer-shopping-prototype.md).

## B 기억 하나에는 무엇이 들어가는가

### 한 항목에 하나의 속성 조건을 담는다

기억은 긴 대화 요약 하나가 아니다. 항목마다 `feature`와 `values`를 가진다. 같은 말에서 핏과 색을 확인했다면 각각의 항목으로 표현한다. `content`는 의미를 이해할 최소 문장이다. 실행에는 구조화된 값과 조건을 함께 사용한다.

| 필드 묶음 | 주요 필드 | 의미와 예 |
|---|---|---|
| 소유자와 범위 | `user_id`, `request_id`, `scope` | 단기는 해당 요청 ID를 가진다. 장기의 request_id는 null이다. |
| 속성과 값 | `feature`, `values` | fit / [Slim], color / [Navy]처럼 사전의 값을 사용한다. |
| 선호 방향 | `polarity` | prefer=선호, avoid=회피, require=필수 |
| 강도 | `strength` | soft=선호 수준, hard=강한 제약. 장·단기 우선순위와는 별개다. |
| 값의 연산 | `match` | any=목록 중 하나, all=모두, range=격식의 양끝 포함 범위 |
| 적용 대상 | `selector` | garment_type=Pants 또는 이번 요청의 slot_id=pants-1 |
| 적용 상황 | `conditions` | occasion·activity·goal의 확인된 값과 AND로 비교한다. |
| 최소 내용 | `content` | “이번 바지는 Slim을 원함” |
| 출처와 확인 | `origin`, `confirmed`, `evidence_ref` | explicit/inferred, 내용 확인 여부, 확인 이벤트 참조 |
| 이후 활용 동의 | `consent_ref` | 장기 기억에 필요한 별도의 동의 참조 |
| 상태와 변경 추적 | `status`, `id`, `version`, `family_id` | 후보·활성·철회·교체와 항목/승격 가족을 식별한다. |
| 시간 경계 | `created_at`, `valid_from`, `valid_until`, `retention_until` | 유효 시작은 포함하고 종료는 제외한다. 보관 기한도 검사한다. |

다음은 **구조 설명용 입력 예시**다. 저장 완료 객체가 아니라 `create` action이다. ID·version·family_id 등은 저장 계층이 관리한다.

```json
{
  "op": "create",
  "feature": "fit",
  "values": ["Slim"],
  "polarity": "require",
  "strength": "hard",
  "match": "any",
  "selector": {"garment_type": "Pants"},
  "conditions": {},
  "content": "이번 바지는 Slim이어야 함",
  "scope": "short_term",
  "origin": "explicit",
  "confirmed": true,
  "evidence_ref": "synthetic-current-confirmation"
}
```

### 장기·단기는 같은 테이블에서 scope로 나눈다

| SQLite 구성 | 책임 |
|---|---|
| `requests` | 요청 소유자·열림/종료 상태·revision·보관 기간 |
| `profiles` | 사용자별 장기 프로필 revision. 완성된 17칸 표를 저장하는 테이블은 아니다. |
| `memories` | 위 항목의 실제 내용·값·범위·상태·버전 |
| `batch_receipts`, `events` | 일괄 명령의 재시도 결과와 최소 변경 기록 |
| `deletion_receipts`, `request_tombstones`, `batch_tombstones` | 내용 없이 삭제 후 재시도를 구분하는 한시적 경계 |

전체 대화·원본 이미지·모델 응답을 별도 기억 저장소로 쌓지 않는다. 현재 구현에는 벡터 DB나 임베딩 검색 계층이 없다. 기억 항목의 최소 내용과 근거 참조를 저장한다.

근거: [MemoryStore와 실제 테이블](../src/stylemate_memory/store.py).

## C 기억은 어떻게 생성·확인·변경되는가

### 내용 확인과 장기 동의는 서로 다른 행동이다

```flow
미확인 단기 후보 -> 확인된 단기 기억: confirm과 내용 확인
확인된 단기 기억 -> 장기 기억: promote와 이후 활용 동의
확인된 단기 기억 -> 철회: withdraw
장기 기억 -> 철회: withdraw
철회 -> 물리 삭제: delete 또는 보관 정리
```

명시적으로 확인한 조건은 처음부터 활성 단기로 만들 수 있다. 추론한 후보는 미확인 단기로만 생성한다. 후보를 `confirm`하면 사용자 확인을 근거로 explicit·confirmed·active가 된다. 이 확인만으로 장기로 바뀌지는 않는다.

장기는 **내용 확인 + 이후 요청에서도 활용하겠다는 동의**가 모두 필요하다. 확인된 단기를 승격하거나, 두 조건을 갖춘 장기를 직접 생성한다. 목표 Feature Map의 추론 결과가 자동으로 이 경계를 통과하지는 않는다.

### 지원하는 여섯 명령

| 명령 | 결과와 제약 |
|---|---|
| `create` | 새 기억을 생성한다. 장기 직접 생성에는 확인과 동의가 필요하다. |
| `confirm` | 후보의 내용을 확인한다. 단기를 장기로 자동 이동시키지 않는다. |
| `promote` | 확인된 단기에서 새 장기 ID를 만든다. 원본과 family_id를 공유한다. |
| `replace` | 같은 scope에서 새 의미를 새 ID로 저장하고 이전 항목을 superseded로 바꾼다. |
| `withdraw` | 같은 승격 가족의 활용을 중단한다. 내용은 제한된 기간 뒤 정리한다. |
| `delete` | 같은 가족과 관련 내용·기록을 관리 DB에서 제거한다. |

승격 가족은 context에서 한 번만 적용한다. 단기와 장기로 두 번 세지 않는다. 요청 전용 `slot_id`는 그대로 장기로 승격할 수 없다. 이후 활용할 대상과 내용을 다시 확인하고 새 동의를 받아야 한다.

### 쓰기와 보관 경계

- 쓰기는 `MemoryStore.apply_batch()`로 처리한다. 한 batch는 전체 성공 또는 전체 rollback이다.
- 같은 batch ID와 같은 본문은 최초 결과를 반환한다. 같은 ID와 다른 본문은 충돌로 처리한다.
- request/profile revision과 항목 version을 검사해 오래된 수정의 덮어쓰기를 막는다.
- 요청 보관은 비활동 30일과 생성 후 90일 중 이른 시한이다. 활성 장기는 동의 후 365일이 상한이다.
- 철회·교체 내용은 기존 기한과 비활성 후 30일 중 이른 시한을 적용한다.
- 삭제 재시도 경계는 내용 없이 24시간 유지한다. 영구 멱등성이나 외부 백업 소거를 뜻하지 않는다.
- `prune_expired()`는 호출자가 실행한다. 자동 예약 정리 작업은 설치하지 않았다.

```callout warn 현재 확인·동의의 한계
상위의 신뢰된 로컬 호출자가 사용자 ID와 확인·동의 참조를 제공한다. 현재 모듈이 실제 로그인, 자연어 동의 진위, 확인 화면을 구현한 것은 아니다.
```

## D 저장한 기억 중 무엇을 Context에 넣는가

### 전체 기억을 그대로 모델에 보내지 않는다

1. 현재 사용자와 열린 요청의 snapshot을 가져온다.
2. 활성·확인됨·유효 기간·보관 기간을 검사한다.
3. 장기 기억과 현재 요청의 단기를 고른다. 다른 요청의 단기는 제외한다.
4. 대상 selector와 해당 대상의 상황 조건을 비교한다.
5. 대상별로 승격 가족의 중복, 현재 예외, 같은 우선순위 충돌을 처리한다.
6. 유효 기억·직접 bindings·상황 facts·질문·속성 사전을 분리해 context를 만든다.

### 먼저 대상을 나누고 충돌을 판단한다

목표 대상은 `pants-1 / Pants`, `shirt-1 / Shirt`처럼 선언한다. 이 ID는 실제 상품 ID가 아니다. 이번 요청에서 찾고 싶은 아이템의 위치를 식별한다.

| 기억 조합 | 적용 결과 |
|---|---|
| 바지 fit=Slim + 셔츠 fit=Relaxed | 서로 다른 대상이므로 공존한다. |
| 바지의 장기 Relaxed + 현재 명시 Slim | 이번 바지에는 Slim을 적용한다. 장기 Relaxed를 수정하지 않는다. |
| 같은 바지에 같은 우선순위 Slim + Oversized | conflict로 남기고 확인 질문을 만든다. |
| 검정 회피 + 흰색 회피 | 두 회피 조건을 보존할 수 있다. |
| 미팅 때만 적용하는 기억 + 미팅 여부 미확인 | 조건을 실행하지 않고 필요한 확인을 남긴다. |

`hard`라고 장기 기억이 현재 명시 예외보다 우선하지 않는다. 강도와 적용 범위는 별개의 축이다. 새 요청에는 이전 단기를 자동 이월하지 않는다.

### 상황은 별도의 사실로 전달한다

`occasion`, `activity`, `goal`은 17개 목표 feature가 아니다. “고객 미팅”, “걷는 시간이 많음”, “smart casual” 같은 확인된 상황이다. 공통 facts와 대상별 `facts_by_target`을 구분한다. 같은 우선순위의 상충하는 fact는 실행 맥락에서 빼고 질문으로 남긴다.

### Context는 검증 가능한 묶음이다

| 구성 | 용도 |
|---|---|
| `memories` | 현재 사용할 최소 기억 내용과 근거 |
| `bindings` | 사용자 확인에서 직접 이어지는 속성 조건 |
| `facts`, `facts_by_target`, `fact_sources` | 확인된 상황과 적용 대상·출처 |
| `questions` | 충돌·미확인 조건에서 필요한 확인 |
| `excluded`, `overridden` | 제외되거나 현재 예외에 가려진 항목의 이유 |
| `registry`, `targets` | 허용된 속성·값·적용 category와 목표 대상 |
| `context_id`, `context_hash` | 같은 상태의 입력인지 식별하는 내부 근거 |

기본 항목 한도는 장기 12개·단기 20개다. 내용·조건의 문자 예산은 6,000자다. 사전 metadata는 별도다. 이는 DB 보관 한도가 아니라 이번 조회의 예산이다. 문자 예산 때문에 필수·현재 binding을 유지할 수 없으면 추론을 보류한다.

외부 adapter는 필요한 필드만 다시 고른다. 사용자 ID와 내부 request/profile revision 묶음은 모델 전송에서 제외한다. 기억의 source ID는 제안 근거를 연결하는 용도로 사용한다.

근거: [Context 조립](../src/stylemate_memory/context.py), [외부 payload 정리](../src/stylemate_memory/llm.py).

## E 현재 Feature Map에는 어떤 칸이 있는가

### 일반 쇼핑에 필요한 17개로 줄였다

원래 계획은 아이템 65개·코디 9개 속성을 참조했다. 현재 실행 사전은 소비자용 **17개 속성**이다. 모든 디자인 디테일을 입력받거나 채우는 구조가 아니다. 아이템 종류에서 category를 파생하고, 대상별 기장을 하나의 key로 통합했다.

아래 값은 **허용값의 예시**다. 전체 값 목록과 적용 규칙의 정본은 registry다.

| 속성 | Key | 값 예시와 적용 규칙 |
|---|---|---|
| 아이템 종류 | `garment_type` | Pants, Shirt, Jacket, Dress. 선언된 target의 종류를 보존한다. |
| 기본 색상 | `color` | Navy, Black, White. 패턴색·그래픽색은 별도 구현하지 않았다. |
| 전체 핏 | `fit` | Slim, Regular, Relaxed, Oversized |
| 기장 | `length` | Cropped, Ankle-length 등. 아이템 종류별 허용값이 다르다. |
| 소매 길이 | `sleeve_length` | Short, Long 등. 상의·아우터·드레스에 적용한다. |
| 넥라인 | `neckline` | Crew, V-neck 등. 상의·아우터·드레스에 적용한다. |
| 무늬 | `pattern` | Solid, Stripe, Check 등 |
| 로고 크기 | `logo` | None, Small, Medium, Large. 로고 유무·크기를 축약했다. |
| 원단 | `fabric` | Denim, Jersey, Knit 등. 섬유 혼용률은 제외했다. |
| 표면 질감 | `texture` | Smooth, Ribbed, Quilted 등 |
| 스타일 | `style` | Minimal, Classic, Casual 등. 복수 라벨을 허용한다. |
| 분위기 | `mood` | Clean, Refined, Relaxed 등. 복수 라벨을 허용한다. |
| 격식 정도 | `formality` | 정수 1~5. Very Casual → Casual → Smart Casual → Business Casual → Formal |
| 계절 | `season` | Spring, Summer, Autumn, Winter. 복수 라벨을 허용한다. |
| 두께 | `thickness` | Thin, Medium, Thick |
| 보온성 | `warmth` | Low, Medium, High |
| 기능 | `functions` | Waterproof, Breathable, Stretch 등. 복수 라벨을 허용한다. |

소매·넥라인 외의 위 속성은 상의·하의·아우터·드레스 category에 적용한다. 기장은 같은 값이라도 종류별 적용 여부를 다시 검사한다. category가 같다고 모든 세부값을 허용하지 않는다.

`registry.py` 한 곳이 한국어 label·허용값·적용 category·원본 대응을 관리한다. 모델에 줄 사전도 여기서 만든다. `None`은 로고가 없다는 실제 값이다. 미정이나 비적용 상태와 혼동하지 않는다.

원본 상품 추출 source의 Image·Metadata·Inference는 상품 속성을 얻는 방법이다. 이번 목표의 근거인 사용자 기억/source_ids와는 다른 정보다.

근거: [17개 실행 사전](../src/stylemate_memory/registry.py), [전체 계획과 확장 참조](../docs/target-feature-inference-plan.md).

## F Feature Map은 어떤 순서로 채우는가

### 직접값은 시스템이 채우고, 추가값은 adapter가 제안한다

```flow
직접 bindings -> 직접 조건 보존
Context와 속성 사전 -> adapter 제안
adapter 제안 -> 형식과 의미 제약 검사
직접 조건 보존 -> 최종 프로필 조립
형식과 의미 제약 검사 -> 최종 프로필 조립
최종 프로필 조립 -> 최신 Context 재검사
최신 Context 재검사 -> 요청별 목표 Feature Map
```

1. 시스템이 target의 아이템 종류를 지정한다.
2. 확인된 fit=Slim, color=Navy 등의 bindings를 직접값으로 만든다.
3. adapter가 상황·기억을 보고 관련 추가값과 질문을 제안한다.
4. 시스템이 허용값, 대상, 근거, 사용자 조건을 검사한다.
5. 시스템이 직접값과 검증된 제안을 합친다. 출력하지 않은 모든 속성에도 상태를 부여한다.
6. 저장소를 다시 조회한다. 호출 중 기억·요청·기간이 바뀌어 context가 달라졌으면 stale_context로 폐기한다.

**모델이 직접값을 누락해도 시스템이 보존한다.** 모델이 explicit·confirmed·hard를 만들어낼 수는 없다. 새 모델 제안은 inferred·soft로 해석한다. 목표를 생성·실패·재시도했다고 기억을 자동 수정하지 않는다.

### 모델이 반환할 수 있는 suggestion은 여섯 필드다

| 필드 | 의미 |
|---|---|
| `target_id` | 어느 목표 아이템에 적용할 것인가 |
| `feature` | 어떤 지원 속성인가 |
| `values` | 사전에 있는 어떤 값을 제안하는가 |
| `match` | any, all, range 중 어떤 연산인가 |
| `source_ids` | 현재 context의 어떤 기억·상황을 근거로 삼았는가 |
| `reason` | 왜 제안했는가 |

최상위 결과는 `suggestions`와 `questions`다. 존재하지 않는 source, 다른 대상의 source, 적용 불가한 값은 거부한다. 사용자 지정값·회피값·필수값·연산을 바꾸는 제안도 거부한다. 충돌 중인 속성을 모델이 임의로 해결할 수 없다.

이 검사는 근거의 현재성·대상·구조와 명시 제약을 확인한다. 인용한 기억이 의미적으로 제안을 충분히 뒷받침하는지는 실제 모델 평가와 사용자 검토가 필요하다.

### 최종 칸에는 값뿐 아니라 상태가 있다

| 상태 | 의미 | 예 |
|---|---|---|
| `specified` · 지정됨 | 사용자 확인 조건이나 target 선언에서 직접 확보 | 바지, Slim, Navy |
| `inferred` · 추론 제안 | 확인된 맥락에서 adapter가 제안 | smart casual 목표에서 격식 3 제안 |
| `unspecified` · 미정 | 적용할 수 있지만 긍정 목표값은 확보하지 못함 | 기장·원단을 말하지 않음 |
| `not_applicable` · 비적용 | 해당 target에 속성이 적용되지 않음 | 바지의 소매 길이 |
| `conflict` · 상충 | 같은 우선순위의 조건을 함께 실행할 수 없음 | 같은 바지의 Slim과 Oversized |

17개 칸의 상태를 만드는 것과 17개 값을 모두 확정하는 것은 다르다. 빈 값 목록도 상태와 함께 읽어야 한다. 미정이라고 저장된 회피 조건까지 없는 것은 아니다.

### 목표는 단일값뿐 아니라 제약도 보존한다

| 사용자 조건 예시 | 표현 | 해석 |
|---|---|---|
| 검정은 피하고 싶다 | color=[Black], avoid/soft | 긍정 색상은 미정일 수 있다. Black 회피는 constraints에 남긴다. |
| Slim이어야 한다 | fit=[Slim], require/hard | 다른 핏으로 바꾸는 모델 제안을 거부한다. |
| Minimal 또는 Classic | style=[Minimal, Classic], any | 둘 중 하나 이상을 원하는 대안 조건 |
| 방수와 통기성을 모두 원한다 | functions=[Waterproof, Breathable], all | 두 기능을 모두 원하는 조건 |
| 격식은 3~4 | formality=[3, 4], range | 3과 4를 포함하는 범위 |

복수 조건의 any/all이 섞이면 평탄한 feature.match는 null일 수 있다. 실제 연산은 개별 suggestions와 `constraints`를 따라야 한다. 표시용 values만 합쳐 실행하면 의미를 잃는다.

근거: [제안 검증과 프로필 조립](../src/stylemate_memory/inference.py), [최신 상태 재검사](../src/stylemate_memory/app.py).

## G 오늘과 다음 요청에서는 실제로 무엇이 달라지는가

### 오프라인 가상 데모를 이번에 실행했다

가상 사용자가 기본 바지 취향으로 Relaxed와 Navy를 확인하고 이후 활용에 동의한다. 오늘 요청에는 Slim을 확인한다. smart casual 목표도 확인한다. Slim에는 오늘이 끝나는 시각을 유효 종료로 둔다.

```sequence
사용자 -> 저장소: 기본 Relaxed와 Navy 확인 및 장기 동의
사용자 -> 저장소: 이번 Slim과 smart casual 확인
앱 -> 저장소: 오늘 요청의 유효 snapshot 조회
앱 -> RuleAdapter: 대상별 Context 전달
RuleAdapter --> 앱: smart casual에서 격식 3 제안
앱 --> 사용자: Slim + Navy + 격식 3
사용자 -> 앱: 새 바지 요청
앱 --> 사용자: Relaxed + Navy
```

### 17개 칸을 모두 보면 이렇다

| 속성 | 오늘 요청 | 다음 요청 | 이유 |
|---|---|---|---|
| 아이템 종류 | specified · Pants | specified · Pants | target 선언 |
| 기본 색상 | specified · Navy | specified · Navy | 유효한 장기 직접값 |
| 전체 핏 | specified · Slim | specified · Relaxed | 오늘 예외 적용, 새 요청에서는 기본 유지 |
| 기장 | unspecified | unspecified | 근거 없음 |
| 소매 길이 | not_applicable | not_applicable | 바지에 비적용 |
| 넥라인 | not_applicable | not_applicable | 바지에 비적용 |
| 무늬 | unspecified | unspecified | 근거 없음 |
| 로고 크기 | unspecified | unspecified | 근거 없음 |
| 원단 | unspecified | unspecified | 근거 없음 |
| 표면 질감 | unspecified | unspecified | 근거 없음 |
| 스타일 | unspecified | unspecified | 데모는 스타일 라벨을 자동 생성하지 않음 |
| 분위기 | unspecified | unspecified | 데모는 분위기를 자동 생성하지 않음 |
| 격식 정도 | inferred · 3 | unspecified | 이번 smart casual에서 rule fixture가 제안 |
| 계절 | unspecified | unspecified | 근거 없음 |
| 두께 | unspecified | unspecified | 근거 없음 |
| 보온성 | unspecified | unspecified | 근거 없음 |
| 기능 | unspecified | unspecified | 근거 없음 |

**다음 요청이 오늘 종료 전에 시작해도**, 이전 요청의 단기 조건은 자동 이월하지 않는다. 요청 경계와 시간 경계는 각각 검사한다.

### 이번 실행으로 확인한 것

| 관찰 항목 | 실제 결과 |
|---|---|
| 실행 속성 개수 | 17개 |
| 오늘 fit | Slim |
| 다음 요청 fit | Relaxed |
| 두 요청의 color | Navy |
| 추론 전후 기억 내용·장기 revision | 변경 없음 |
| 실제 LLM 호출 | false |

실행 명령은 `PYTHONPATH=src python3 -m stylemate_memory.cli demo --synthetic`이다. RuleAdapter의 정확한 smart casual 문구 규칙을 확인한 결과다. 실제 모델이 모든 자연어를 이해한다는 증거는 아니다.

## H 어디까지 확정·구현됐고 무엇이 남았는가

### 현재 구현과 다음 제품 작업을 구분한다

| 항목 | 현재 상태 |
|---|---|
| SQLite 장·단기 저장과 확인·승격·교체·철회·삭제 | ok 구현 |
| 대상·조건·기간별 context와 충돌/제외 이유 | ok 구현 |
| 17개 사전과 직접값·추론·미정·비적용·상충 조립 | ok 구현 |
| 제안 값·근거·사용자 제약 검증과 늦은 결과 폐기 | ok 구현 |
| OpenAI Responses adapter와 가상 HTTP 테스트 | ok 연결 코드와 오프라인 검증 |
| 실제 모델 호출·자연어 추론 품질 | warn 후속 검증 필요 |
| 대화·이미지에서 기억 후보를 자동 추출하는 제품 입력 흐름 | no 현재 모듈에 없음 |
| 사용자 확인·동의 UI, 로그인·서버 인증 | no 현재 모듈에 없음 |
| 실제 상품 속성 추출·검색·목표와의 매칭·코디 추천 | no 현재 모듈에 없음 |
| item65/outfit9 전체 구현과 사용자 연구 효과 검증 | no 현재 완료 범위 아님 |

### 이렇게 나눈 이유

- 기억은 사용자가 확인한 조건을 보존한다. 모델의 추정이 반복 추천에서 기본 취향으로 굳어지는 것을 막는다.
- 대상별 context는 셔츠와 바지의 다른 조건을 함께 다룬다. 현재 예외는 해당 요청에서만 적용한다.
- 17개 사전은 일반 쇼핑에 필요한 표현으로 범위를 줄인다. 미정 칸을 남겨 과도한 입력과 허구 채우기를 줄인다.
- 사용자 확인과 이후 활용 동의를 나누어 이번 조건과 기본 취향의 변경을 구분한다.

이는 [연구 기준의 RQ1·RQ2](../docs/master.md)에 맞춘 구조다. 실제 사용자 주도성이나 의도 표현 부담이 개선됐다는 연구 결과는 아직 별도 검증 대상이다.

### 실제 사용 시 목표로 하는 흐름과 남은 연결

사용자는 자연어·선택으로 의도를 표현하고, 필요한 조건만 확인하는 흐름을 목표로 한다. 제품은 이를 기억 항목과 확인 이벤트로 연결해야 한다. **현재 CLI는 이 상위 흐름을 대신해 구조화된 action을 받는다.** 사용자가 17개 필드를 직접 작성해야 한다고 확정한 제품 UX는 아니다.

Feature Map 생성 뒤 수정할 때도 같은 경계를 따른다. 이번 조건 수정은 단기 쓰기로, 기본 취향 변경은 새 확인과 장기 동의를 갖춘 쓰기로 처리한다. 목표 프로필에 값을 표시한 것만으로 장기 저장하지 않는다. 이 규칙을 실제 화면에 연결하는 작업은 남아 있다.

### 이 페이지의 확인 범위

2026-10-14, 로컬 `codex/1-memory-design`의 HEAD `6ca871a878782a6ece8932ad0d1451d818972445`와 기존 미커밋 문서를 읽었다. 현재 코드·실행 계약·ADR 0003·연구 기준을 대조했다. 가상 데모는 이번에 직접 실행했다. 기존 79개 테스트 기록은 [현재 실행 문서](../docs/shopping-memory-prototype.md)에 있으며 이번 설명 작업에서 재실행하지 않았다.

이 페이지는 현재 구현을 설명하는 파생 자료다. 메모리 정책·제품 계약·연구 기준을 새로 변경하지 않는다. 실행 계약은 [프로토타입 문서](../docs/shopping-memory-prototype.md)와 코드, 결정 이유는 [ADR 0003](../docs/decisions/0003-consumer-shopping-prototype.md)이 정본이다.
