# 0013 · LangGraph 기반 의도 순환 추천으로 흐름 제어를 재구성한다

- Status: Proposed
- Date: 2026-11-18
- Related Work: 현재 대화의 파이프라인 재설계 요청, 재설계 메모(LUMI 파이프라인 재설계 메모), Issue [#7](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/7)·[#1](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/1)
- Approval: 설계 결정 Q1~Q28은 2026-11-18 대화에서 사용자 승인. 이 ADR의 Accepted 승인은 미승인
- Supersedes: [ADR 0002](0002-memory-prototype-storage.md)의 근거 예산 계산 기준(부분), [ADR 0006](0006-fea-to-pi-hypothesis-comparison.md)의 가설 생성 주체·대상 축·값 개수(부분). 다른 결정은 유지

## 맥락

현재 흐름(`app.py`의 `_extract`/`_explore`)은 추출 → 확인 → context → 목표 제안을 직렬 관문으로 잇는다. 관문 하나라도 어긋나면 요청 전체가 멈춘다. 실제 DeepSeek 점검 4회에서 카드가 나온 요청은 최대 6/8이었고, FEA→PI 가설 비교는 32회 중 0회 나왔다. 원인은 통째 거부, 확인 전 탐색 불가, 상황의 문자열 일치, 구조까지 세는 6,000자 예산, 모델 자발성에 맡긴 가설 생성이다. 결정 기준도 코드에 노드로 드러나 있지 않다.

## 결정

1. 흐름 제어만 LangGraph StateGraph로 옮긴다. 저장 계약(`store_v1.apply_batch`, 확인·동의 분리)과 `ConsumerService`의 HTTP action·`ConsumerState`는 유지하고, 새 필드는 추가만 한다. 모델 호출은 기존 `llm.py`/`model_io.py` 어댑터를 쓴다. 새 의존성은 `langgraph`(버전 고정)뿐이다.
2. 노드: parse_turn → update_intent → propose_hypotheses → route → (ask_clarify | retrieve → plan_probe) → compose_turn → interrupt → parse_turn 반복 | finalize.
3. 상태: 요청 안의 작업 상태(IntentState: PI hard/soft, FEA 요구, 상황, 값별 가중치, 질문 큐, 가설)는 checkpointer(SqliteSaver), 기억 정본은 기존 메모리 SQLite에 둔다.
4. 검증: 모델 응답은 항목별로 검증해 틀린 항목만 버리고 상태에 경고로 남긴다. 응답 전체 거부는 권한·확정·동의 주장과 인용 위조에만 적용한다. 노드 안 모델 재시도는 최대 1회다.
5. 탐색: 확인 전 조건도 soft로 탐색에 쓴다. hard 필터는 직접 말했거나 확인한 조건만 쓴다. 직접 말한 Type은 hard다. 상대 가격 표현은 Price 하위 구간 soft 선호로, 숫자 가격만 hard로 둔다. 품목만 있어도 카드를 보인다.
6. route는 코드 규칙이다. hard 충돌 → 질문, 품목 없음 → 질문, 비교 가능한 가설 있음 → 비교, 그 밖에는 → 탐색. 질문은 하나의 큐에서 한 턴에 최대 1개만 보인다.
7. 가설: propose_hypotheses는 FEA 요구가 추가·삭제될 때마다 호출한다. 모델이 FEA 요구, 근거 문장, 사전 값, 현재 후보의 축별 분포를 읽고 PI 가설을 제안한다. 가설은 축 1개(Type·Color·Fit·Fabric·Detail), 사전 값 1~3개, 이유, 근거 FEA ID로 이뤄진다. 사전 밖 값은 그 가설만 버린다.
8. 비교: 상위 K개 후보를 가장 반반에 가깝게 나누는 가설부터 묻는다. 동률이면 모델 확신도로 정한다. choose → 값 가중치 +, neither → 소폭 −, unsure → 변화 없음, 이유 → parse_turn에서 해석한다. 피드백마다 전체 후보를 다시 순위 매긴다. 가중치는 이번 요청에만 쓰고 hard로 자동 승격하지 않는다.
9. 순환은 사용자만 끊는다. 매 턴 비교쌍과 상위 카드를 함께 보이고, "비교 그만"·최종 선택·종료를 항상 제공한다.
10. 거절 기억: 사용자가 가설 아닌 쪽을 분명히 골랐거나 이유로 비선호를 밝히면, MemoryItem(polarity=avoid, strength=soft, origin=inferred)을 만든다. 조건은 품목 + 정규화한 상황 + 근거 FEA다. 상황이 없으면 품목 + FEA로 저장하고, 무조건 비선호는 만들지 않는다. neither·unsure는 저장하지 않는다. 단기 기억에는 바로 반영하고, 장기 기억은 종료 요약에서 조건을 포함한 문장으로 동의를 받는다([ADR 0007](0007-joint-feedback-and-end-consent.md) 유지). 다음 요청에서는 품목과 상황이 일치할 때만 soft 감점하고 같은 가설을 제외한다. 서로 다른 상황 2곳 이상에서 거절되면 일반화할지 사용자에게 묻는다.
11. 상황: 요청 안의 상황은 조건이 아니라 사실이다. 상황 키는 occasion·season·activity로 둔다(season 추가, goal은 매칭에서 제외). 값은 닫힌 사전으로 정규화하고, 맞는 값이 없으면 `기타`로 두고 원문을 보존하며 매칭에 쓰지 않는다. 사전은 버전이 있는 JSON으로 관리한다. 초안 값은 다음과 같다.
    - occasion: 출근·발표/미팅·면접·데이트·하객·여행·주말 외출·운동·집
    - season: 봄·여름·가을·겨울
    - activity: 걷기 많음·오래 앉음·야외·실내
12. parse_turn 모델 출력은 `situations`·`wishes`·`questions` 세 필드로 나눈다. 상황은 선호 후보 틀에 넣지 않는다.
    - `situations`: 항목마다 `id`, `key`(occasion·season·activity), `value`(11번 사전 값 또는 `기타`), `raw`(원문 표현), `quote`, `source_ids`를 둔다. 상황 항목에는 polarity·strength·binding이 없다.
    - `wishes`: 선호·요구·비선호를 담는다. `polarity`는 prefer·avoid·indifferent이고, 요구는 `prefer` + `strength=hard`로 표현한다(`require` 폐지). 모델 출력에는 `kind`를 두지 않고 코드가 polarity·strength로 유도한다. binding은 `pi`(feature·values·match)와 `fea`(category·subcategory·tag) 목록으로 나누고, polarity·strength는 wish의 값을 물려받는다.
    - 상황 연결: wish는 자유 텍스트 조건 대신 `situation_ids`로 같은 응답의 상황 항목만 참조한다. 코드가 ID 존재를 검사한다. 기본은 이번 요청의 상황에 묶고, "원래·평소·항상"처럼 일반 취향이라는 명시적 신호가 있을 때만 `situation_ids=[]`로 둔다. 빈 목록은 일반 취향(baseline)을 뜻하므로 `scope_hint`는 두지 않는다. "출근할 땐 슬랙스, 주말엔 청바지"처럼 상황별 규칙은 상황 항목 여러 개와 각 wish의 참조로 표현한다. 10번 거절 기억의 상황 조건은 wish가 참조한 상황에서 가져온다.
    - `questions`: 모델이 해석이 애매해 되묻는 질문이며 최대 3개다. 항목마다 `text`(한국어 한 문장), `about`(같은 응답의 `wish_keys`·`situation_ids`), `reason`(ambiguous_need·unclear_situation·possible_correction·unstated_reason)을 둔다. 코드가 `about`의 키 존재를 검사하고, 틀린 질문은 그 질문만 버린다. 품목 누락과 hard 충돌 질문은 route가 만들므로 모델 `reason`에 두지 않는다. 모델 질문과 코드 질문은 6번의 같은 큐에 들어가며, 답은 parse_turn이 `about`의 대상에 반영한다.
    - 코드는 이 출력을 기존 MemoryItem(상황은 `kind=situation`과 `fact`)으로 변환해 저장한다. 확인·동의·삭제 경로는 공유한다.
13. 근거 예산 6,000자는 사용자 문장과 근거 원문만 센다. ID·참조·제약 사본은 세지 않는다.
14. 이행: `src/stylemate_memory/graph/`에 구현하고 `STYLEMATE_ENGINE=graph|legacy`로 선택한다. 평가에서 기존 경로 이상이면 legacy 흐름 코드를 삭제한다.

## 대안

- 현재 직렬 구조에 임시 완화를 계속 추가: PR [#12](https://github.com/jongrionro-debug/HCI_HANDSOME/pull/12) 수정 후에도 6/8, 가설 0회로 구조적 원인이 남는다.
- LLM 라우터: 결정 기준을 테스트·연구 보고로 고정할 수 없다.
- FEA→PI 연결표를 사전에 두고 코드가 선택: 사용자 결정으로 채택하지 않았다. 모델이 FEA 맥락을 읽고 제안한다.
- 거절을 값 단위 비선호("와이드 싫음")로 저장: 상황에 따른 선호가 일반 취향으로 잘못 넓어진다.
- 거절 기억의 자동 장기 저장: ADR 0007의 종료 후 별도 동의, RQ1의 통제감과 충돌한다.
- 상황을 `kind=situation` 후보로 선호와 같은 목록에 유지: 의미 없는 고정값(polarity·strength·빈 binding)이 생기고 상황과 바람을 섞는 실수가 잦아 프롬프트 규칙이 늘어난다.
- wish마다 자유 텍스트 조건(`conditions`) 유지: 사전 밖 텍스트가 조건에 들어가 매칭이 흔들린다. 상황 ID 참조로 대체한다.
- 저장 계층까지 LangGraph store로 교체: 검증된 확인·동의·삭제 계약을 다시 만들어야 한다.

## 영향

- 이점: 관문 하나로 요청 전체가 멈추지 않는다. 가설 비교가 전용 노드로 항상 시도된다. 피드백이 값별 가중치와 조건부 거절 기억으로 누적된다. 결정 기준이 route 표 테스트로 고정된다.
- 비용·위험: 저장소의 "추가 Python 의존성 없음" 원칙을 깬다(CI 설치 단계 필요). 확인 전 soft 탐색이 틀린 해석을 카드에 반영할 수 있다. Fabric 가설은 이미지로 확인할 수 없어 상품 원문 값만 비교 근거로 쓰고 "소재 정보 기준"으로 표시한다. 상황 사전 밖 표현은 매칭되지 않는다.
- 후속 작업: Issue 등록, 상황 사전 JSON, 노드별 단위 테스트, route 표 테스트, 각본 모델 통합 테스트, 구현 후 [project.md](../project.md) 갱신.
- 검증: 점검 시나리오 약 12개 × 3회 반복을 비율로 본다(카드 노출률, 가설 비교 노출률, 버려진 항목 수·이유, 노드별 실패 위치, LangGraph trace). 기존 444개 테스트와 브라우저 검사 2종을 유지한다.
