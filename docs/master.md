# LUMI 프로젝트 기준과 실행 안내

설계·연구·현재 구현·실행 방법은 이 문서에서 관리한다. 개발 작업 규칙은 [AGENTS.md](../AGENTS.md), 허용값의 정본은 [Feature Map JSON](../output/feature-map/park-2025-feature-map.json)이다. CSV는 JSON에서 생성하는 보기용 자료로 사용하고 별도로 수정하지 않는다. 각 주제는 해당 절에서만 갱신하며 다른 문서는 링크로 연결한다.

- [기준과 자료](#기준과-자료)
- [시스템 설계](#시스템-설계)
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

이 절은 현재 코드의 실행 계약이다. **확정한 Park et al. 사전으로의 코드·저장 데이터 이관은 아직 미구현**이다. 현재 실행 사전의 값과 확정 사전의 값을 혼용하지 않는다. 기존 Python 패키지·CLI·환경 변수의 `stylemate_memory`/`STYLEMATE_` 이름은 호환성을 위해 유지한다.

### 구현 상태

| 보고서 | 현재 코드·검증의 범위 | 남은 범위 |
|---|---|---|
| 3.2 · Input-to-Memory Model | [codex_llm.py](../src/stylemate_memory/codex_llm.py)의 텍스트 후보 추출·형식/인용 검사, [inspector.py](../src/stylemate_memory/inspector.py)의 수동 확인·동의 | 사전으로 표현되지 않는 취향과 대화 맥락의 지속 보존, 이미지 선택 입력·근거 연결, 소비자 입력 흐름 |
| 3.2 · Memory Layer | [store.py](../src/stylemate_memory/store.py)의 장·단기 항목, 대상/상황/근거 참조, 확인·동의·교체·철회·삭제, SQLite 원자성 | 자유 표현·선택 사실·미확인 이유를 함께 다룰 표현과 확인 흐름. 현재 메모리는 지원 feature/fact와 values가 필요함 |
| 3.3 · Context-Aware Memory Retrieval | [context.py](../src/stylemate_memory/context.py)의 요청/대상/조건/기간 필터, 단기 예외·장기 보존, 출처·제외 이유 | 자연어·이미지 선택 근거까지 포함하는 조회와 관련성 평가. 현재 미확인 후보는 확정 binding에서 제외됨 |
| 3.4 · 목표 Item Feature Map | [registry.py](../src/stylemate_memory/registry.py)의 기존 17개 사전, [inference.py](../src/stylemate_memory/inference.py)의 지정/추론/미정/상충 구분, [app.py](../src/stylemate_memory/app.py)의 최신성 재검사 | 확정한 PI 7항목·FEA 30개 태그로 사전·추출·저장·목표 검증 이관, 확인 질문·검색 입력 연결 |
| 3.5 · Item Retrieval / Final Suggestion | 미구현 | 상품 수집·속성 검증, 필수 조건 필터, 선호 랭킹, 결과 없음과 사용자 조건 조정, 최종 제안 |
| 3.6 · Feedback / Memory Update | 확인·승격·교체의 저장 기반과 개발자 도구의 텍스트 수정 | 이미지/부분 선택·선택 이유 가설·필요한 확인·재검색·최종 확정/장기 저장 통합 |
| 3.7 · UI | 개발자 관찰 도구만 존재 | 보고서의 온보딩·새 요청·이미지 탐색·반영 정보 확인·최종 선택·별도 저장 UI |

코드의 `stylemate_memory`는 이전 명칭을 유지하는 실행 패키지다. 개발자 관찰 도구의 세 패널을 보고서의 소비자 UI로 보지 않는다. 목표 Item Feature Map과 상품별 Item Feature Map도 구분한다.

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

**첫 작업은 보고서 3.2~3.3의 입력→메모리→조회 경로를 기존 프로토타입에 연결하는 것이다.** 아래는 후속 작업의 범위와 완료 조건이며 이번 문서 정리로 구현됐다는 뜻은 아니다.

1. **입력·근거 표현:** 현재 `MemoryStore._validate_memory_payload()`는 feature/values를 요구한다. 추출 프롬프트는 사전에 없는 내용을 `unmapped`로 반환하도록 지시하고, `validate_extraction()`은 미지원 후보값을 거부한다. 확정한 PI/FEA 사전을 추출·저장·검증에 연결하면서, 사전으로 표현되지 않는 취향 문장·선택 사실·추정 이유는 원문과 함께 보존·확인할 표현을 정한다. 기존 17개와 새 사전의 의미 차이를 검토하고 항목·근거·동의·사전 버전의 마이그레이션을 함께 다룬다.
2. **확정 내용과 해석 분리:** `Inspector.chat()` → `MemoryStore.apply_batch()`의 후보·확인·장기 동의를 유지하며, 발화/선택 근거와 가설의 상태를 연결한다. 현재 전체 대화와 후보의 scope/교체 설명은 프로세스 메모리에만 있어 재시작 후 맥락이 복원되지 않는다.
3. **요청별 조회와 목표 연결:** `build_context()` → `ShoppingApp.infer_request()`에서 현재 대상·상황에 맞는 근거를 전달한다. 미확인 해석은 사용자 확정 조건과 구분하고 필수 조건·장기 취향을 자동 변경하지 않는다.
4. **동작 확인 후 연결:** 메모리 흐름의 회귀 검증을 먼저 완료한 뒤 3.6의 이미지 피드백과 3.5의 실제 상품 조회를 연결한다. 상품 Map과 목표 Map은 확정한 PI/FEA 사전을 공유한다. 원문의 미공개 브랜드 목록·가격 경계와 적용 품목 범위를 처리하고, 제품 UI·스택은 담당 작업에서 정한다. 대화 중 사전의 속성·허용값을 추가하지 않는다.

| 완료 조건 | 확인할 결과 |
|---|---|
| 평소 네이비·여유핏 바지 + 이번 발표에는 슬림핏 | 이번 목표는 Navy/Slim, 장기 원본은 Navy/Relaxed 유지 |
| 이후 새 요청 | 발표 전용 Slim이 자동 이월되지 않고 유효한 장기 취향만 참조 |
| “빈티지한 느낌” | 원래 표현·맥락을 보존하고 특정 색·원단은 임의 확정하지 않음 |
| 이미지 선택 후 이유 미확인 | 선택 사실과 미확인 이유를 구분하며 전체 속성 선호·미선택 비선호를 만들지 않음 |
| 내용 확인·추천 확정·반복 선택 | 별도 이후 활용 동의 없이는 장기 쓰기 없음 |
| 조건 수정·기억 철회 뒤 늦은 모델 응답 | 이전 근거의 응답을 적용하지 않고 다시 조회/추론하도록 처리 |

Navy/Relaxed→Slim→새 요청, 동의·요청 격리·최신성은 **기존 17개 사전**으로 [현재 테스트](../tests)와 가상 데모가 일부 검증한다. `Relaxed`는 확정한 논문의 Fit 허용값이 아니므로 새 사전의 동작 예시로 그대로 승계하지 않는다. 이관 시 기존 표현·근거를 보존하면서 미지원 값을 처리하고, 자유 표현의 지속 보존과 이미지 근거를 추가할 때 새 회귀 테스트가 필요하다. 모델의 의미 해석과 실제 추천 품질은 별도 평가다.

확정 사전의 실행 적용에는 `registry.py`뿐 아니라 후보 추출·저장 payload·context·목표 검증·관찰 도구·기존 데이터의 사전 버전 이관이 필요하다. 기존 값·원문·근거·확인·동의를 보존하고 의미가 다른 값을 임의 변환하지 않는다. 이번 문서 반영은 이 구현·이관을 완료한 것이 아니다.
