# 기억에서 목표 Feature Map까지 — 근거와 상세 설명

확인일: **2026-10-14**. 사용자 요청으로 `answer-me-with-html 0.5.2`의 `3b1b` 테마를 사용한 한국어 설명 영상을 만들었다. 이 문서는 영상의 근거와 세부 계약을 찾기 위한 안내다. 현재 실행 계약의 정본은 [프로토타입 문서](../../docs/shopping-memory-prototype.md)와 코드다.

- [영상 플레이어](stylemate-memory-feature-map.html) · [MP4](stylemate-memory-feature-map.mp4)
- [원고](stylemate-memory-feature-map.md) · [시간표와 대사](narration-ko.md) · [SRT](narration-ko.srt)
- [로컬 근거 파일의 해시](sources/source-manifest.json) · [전체 GitHub 조회 사본](sources/github-issues-and-prs.json)

## 조사한 이슈와 PR

저장소의 모든 페이지를 조회한 결과 이슈 2건과 PR 1건이 있었다. Issue #2의 timeline에서도 PR #3의 연결과 종료를 확인했다. 상태는 이 작업에서 읽은 GitHub 응답을 기준으로 한다.

| 자료 | 역할 | 이번에 확인한 상태 |
|---|---|---|
| [Issue #1](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/1) | D01–D12의 메모리 설계·구현 계획 | OPEN. 공개 본문의 AC는 미체크이며, 로컬 설계와 ADR에는 승인 기록이 있음 |
| [Issue #2](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/2) | 17개 feature·SQLite·context·목표 추론·LLM adapter | CLOSED. AC1–AC9 체크, 실제 호출과 상품 추출은 범위 밖 |
| [PR #3](https://github.com/jongrionro-debug/HCI_HANDSOME/pull/3) | Issue #2 구현, Issue #1 참조 | MERGED. 2026-10-14 11:41:02 KST 병합, 코드·문서 32개 파일 |

PR head는 `6ca871a878782a6ece8932ad0d1451d818972445`, 병합 커밋은 `02b6b90bd43991ca101cacf6701ebe0d56f0cef2`다. 현재 로컬 작업 브랜치의 HEAD는 PR head와 같다. 기존 AGENTS·workflow Markdown/HTML 변경과 설명 artifacts를 보존하고 이번 설명 산출물만 새 폴더에 추가했다.

조회된 이슈·PR 댓글과 GitHub 게시 리뷰는 없다. PR 본문의 독립 리뷰·회귀 수정은 작성자가 기록한 검증 내역이며, GitHub 승인 리뷰와 구분한다. [PR 응답 사본](sources/pr-3.json), [Issue #1 응답](sources/issue-1.json), [Issue #2 연결 이력](sources/issue-2-timeline.json)에 원래 근거를 남겼다.

## 설계가 현재 구현으로 이어진 과정

| 단계 | 내용 | 현재 해석 |
|---|---|---|
| Issue #1 · Accepted v0.2 | 기억 단위·확인/동의·요청 경계·조회·보관/삭제·Python+SQLite | 승인된 역사적 설계. 현재 실행 DTO와 동일한 JSON 형식은 아님 |
| 목표 feature 계획 | item 65개와 outfit 9개, 대상별 projection·F0–F5 | 전체 설계와 확장 참조. 모두 구현됐다는 완료표가 아님 |
| ADR 0003 · Issue #2 · PR #3 | 일반 쇼핑용 17개·작은 실행 DTO·실제 SQLite·read-only adapter | 현재 로컬 프로토타입의 범위 |

[메모리 설계](../../docs/memory-design.md), [초기 구현 계획](../../docs/memory-implementation-plan.md), [전체 목표 feature 계획](../../docs/target-feature-inference-plan.md), [ADR 0001](../../docs/decisions/0001-memory-boundaries.md), [ADR 0002](../../docs/decisions/0002-memory-prototype-storage.md), [ADR 0003](../../docs/decisions/0003-consumer-shopping-prototype.md)를 대조했다. 원본 PDF를 이번 작업에서 다시 분석하지 않았으며, 65+9와 대응·제외 근거는 이 문서들과 현재 registry를 따른다.

## 무엇이 기억이고 무엇이 목표인가

| 정보 | 예시 | 범위와 사용 |
|---|---|---|
| 기본 취향 | 평소 바지는 Relaxed 선호 | 내용 확인과 이후 활용 동의를 받은 장기 기억 |
| 조건부 취향 | 고객 미팅일 때 정장 같은 느낌 회피 | 상황 조건이 맞을 때만 적용. 장기이면 별도 동의 필요 |
| 반복 상황 | 출퇴근 때 많이 걸음 | 확인·동의 후 장기로 둘 수 있음. 활동과 소재·기능 목표를 분리 |
| 현재 요청 | 오늘 발표, 이번 바지는 Slim | 현재 request의 단기 조건. 새 요청에 자동 이월 없음 |
| 확인 전 해석 | 사진의 어떤 요소가 좋은지 불명 | 단기 candidate. 확정 조건과 추론 근거에서 제외 |
| 목표 Feature Map | 이번 바지의 핏 Slim, 격식의 추론 제안 | 읽은 기억에서 만들어진 요청별 결과. 세 번째 memory scope가 아님 |
| 실제 상품 Feature Map | 상품의 색·핏·원단·방수 성능 | 상품 사진·메타데이터 등의 별도 근거가 필요. 실제 추출기 미구현 |

장기/단기, 명시/추정, 확인 여부, 이후 활용 동의, soft/hard는 서로 다른 축이다. 오래 보관했다는 이유로 필수 조건이 되지 않으며, 모델의 높은 confidence가 확인·동의를 대신하지 않는다.

현재 코드는 자연어를 읽어 기억 항목이나 동의 진위를 자동 판별하는 제품 UI가 아니다. **신뢰된 로컬 호출자가 구조화한 입력, user ID, 확인/동의 참조와 상황 facts를 제공한다.** 초기 설정·이미지 선택·저장 모달의 상세 UX는 설계 기록이며 현재 실행 화면으로 해석하지 않는다.

## 기억은 어떤 필드로 저장하나

한 기억은 독립적으로 확인·수정할 하나의 주장이다. 네이비 재킷과 흰 셔츠는 대상이 다른 두 항목으로 표현한다. 적용 대상이나 조건을 지워 하나의 전역 취향으로 확대하지 않는다.

| 필드 | 보존할 의미 |
|---|---|
| content, feature, values | 최소 사용자 문장과 지원 속성·값. 전체 대화·이미지 원문을 저장하지 않음 |
| polarity | prefer / avoid / require. 선호·회피·요구를 구분 |
| strength | soft / hard. 적용 범위의 우선순위와 별개 |
| match | any / all / range. formality 범위의 양끝 포함 |
| selector | garment_type / slot_id. 빈 selector는 공통 적용 |
| conditions | 확인된 상황과 대조할 AND 조건 |
| scope, request_id | short_term의 현재 요청 또는 long_term의 이후 활용 범위 |
| origin, confirmed, status | explicit/inferred, 확인 여부, candidate/active/withdrawn/superseded |
| evidence_ref, consent_ref | 현재 내용 확인과 이후 활용 동의의 참조. 장기에는 둘 다 필요 |
| valid_from, valid_until | 시간대가 있는 절대 적용 시각, 시작 포함·끝 제외 |
| retention_until | 물리 보관 한계. 적용 기간과 구분 |
| id, version, family_id | 항목·객체 변경·승격 가족. 저장 계층이 관리 |

현재 실행 저장소는 requests, profiles, memories, batch_receipts, events, deletion_receipts, request_tombstones, batch_tombstones의 8개 테이블이다. [store.py](../../src/stylemate_memory/store.py)의 실제 테이블과 `apply_batch()`를 확인했다. 입력 전체를 감사 로그에 복제하지 않으며 결과·변경 참조를 최소화한다. 별도 벡터 저장소·검색 인덱스·영구 목표 프로필 저장을 도입하지 않았다.

| 조작 | 현재 계약 |
|---|---|
| create | 확인된 단기, 미확인 inferred 단기 후보, 확인+동의가 있는 직접 장기 생성 |
| confirm | 제시된 항목의 내용 확인. 자동 장기화 없음 |
| promote | 확인된 단기를 새 장기 ID로 승격. 가족은 context에서 한 번만 반영 |
| replace | 같은 scope 안에서 새 의미를 새 ID로 생성. 필요한 새 확인·동의 사용 |
| withdraw | 추천 활용에서 제외. 승격 가족은 함께 처리 |
| delete | 관리 DB의 내용·관계·관련 결과를 정리. 승격 가족 함께 처리 |

요청 전용 slot_id가 있는 단기를 그대로 장기로 승격하지 않는다. 재사용할 대상과 내용을 다시 확인하고 새 consent로 장기를 생성한다. 의미가 다른 replace 관계와 동일 의미의 promote 가족을 구분한다.

쓰기 한 묶음은 `BEGIN IMMEDIATE` 트랜잭션에서 항목·이벤트·결과를 함께 반영한다. 기대 revision/version을 검사하고 중간 실패는 전체 rollback한다. 같은 batch ID와 같은 본문은 최초 결과를 돌려주며, 다른 본문은 충돌이다. 삭제는 삭제 조작만 있는 별도 batch로 처리한다. 외부 모델 호출을 이 저장 트랜잭션에 넣지 않는다.

## 기억으로부터 목표 Feature Map을 만드는 순서

1. 호출자가 이번 대상 목록을 정한다. `pants-1` 같은 target ID는 요청 안의 목표 슬롯이며 상품 ID가 아니다. garment_type은 대상 선언에서 유지하고 기본 category를 파생한다.
2. 사용자·요청·활성/확인·적용/보관 기간으로 기억을 거른다. 다른 요청의 단기, candidate, 철회/삭제/만료 기억은 실행 조건이 아니다.
3. 대상 selector와 대상별 facts를 먼저 평가한다. 셔츠 White와 재킷 Navy는 공존한다. 조건이 불명확하면 보류·질문하며, facts가 상충하면 입력 순서로 고르지 않는다.
4. 같은 대상·속성의 현재 예외가 기본 조건을 일시 대체한다. 같은 우선순위 상충은 conflict/질문이다. hard는 강도이며 오래된 장기 조건이 현재의 명시 예외보다 우선한다는 뜻이 아니다.
5. 시스템이 직접 bindings를 만든다. Slim은 fit에 대응하고 기본 색을 패턴색으로, fit을 바짓단 모양으로 확대하지 않는다. avoid Black만 있는 경우 다른 색을 자동 확정하지 않는다.
6. 확인된 상황, 직접값, 유효 기억, source ID/version, 미정 질문과 registry를 context로 분리해 조립한다. selector가 있는 facts는 해당 target에만 전달한다.
7. 장기 12개·단기 20개, 사용자 내용/조건 6,000자 예산을 적용한다. 사전과 지시문 크기는 별도다. 필수 조건을 담지 못하면 보류한다.
8. 규칙 또는 모델 adapter는 suggestions와 questions만 제안한다. suggestion의 6개 필드는 target_id, feature, values, match, source_ids, reason이다. 시스템이 inferred/soft 의미를 부여한다.
9. 허용값·타입·대상·근거·부정·강도·연산을 검사한다. 모델이 explicit/confirmed/hard를 주장하거나 직접값을 바꾸면 거부한다. 모델이 직접값을 누락해도 시스템에서 보존한다.
10. 모든 속성에 specified, inferred, unspecified, not_applicable, conflict 상태를 보충한다. `None` 같은 허용값과 미정/비적용을 구분한다. 회피만 있으면 양의 목표값은 미정이면서 회피 constraint는 남을 수 있다.
11. 응답 뒤 최신 SQLite snapshot으로 context를 다시 만든다. 수정·철회·삭제·기간·요청 종료 등으로 context가 바뀌면 stale_context로 폐기한다.
12. 반환 프로필에 request/profile/사용한 memory version과 context/registry 식별자를 붙인다. 내부 user ID/버전 묶음을 모델이 만들어내게 하지 않으며, 목표값을 자동 저장하지 않는다.

복수 스타일의 any/all 의미가 섞이면 표시용 feature.match는 null이다. 개별 suggestions와 constraints가 연산의 정본이며, 표시용 values만으로 조건을 실행하지 않는다. 모델에 source ID가 있다는 사실은 자연어 의미가 올바르다는 증명이 아니다.

구현 연결: [context.py](../../src/stylemate_memory/context.py) → [inference.py](../../src/stylemate_memory/inference.py) → [app.py](../../src/stylemate_memory/app.py). 최종 앱 연결은 `ShoppingApp.infer_request()`다.

## 실제 데모에서 확인한 값

[가상 데모의 원본 출력](sources/synthetic-demo.json)을 이번 작업에서 새로 생성했다.

| 결과 | 실제 출력 | 해석 |
|---|---|---|
| 오늘 바지 fit | Slim · specified · explicit · short_term | 확인한 현재 예외 |
| 다음 요청 바지 fit | Relaxed · specified · explicit · long_term | 기본 취향 유지, 단기 이월 없음 |
| color | Navy · specified | 별도 색 조건 유지 |
| 오늘 formality | 3 · inferred | smart casual에 대한 규칙 fixture의 제안. 일반 상황의 정답 규칙이 아님 |
| 추론 전후 메모리 | memory_unchanged_by_inference=true | 목표 생성이 메모리를 쓰지 않음 |
| 실제 모델 호출 | live_llm_called=false | 규칙 데모이며 LLM 의미 품질 평가가 아님 |

## 철회·삭제·기간과 외부 모델의 경계

- 저장하지 않음: 장기로 추가하지 않는다. 확인된 현재 단기는 그 요청에서 사용 가능하다.
- 활용 철회: context에서 제외한다. 물리 삭제와 구분하며 내용은 기존 기한과 비활성 최대 30일 중 이른 시한까지 제한한다.
- 실제 삭제: 관리 DB의 행·관계·이벤트/영수증·journal 정리와 SQLite 정리를 수행한다. 사용자 사본·OS 백업·SSD의 복구 불가를 보장하지 않는다.
- 삭제 재시도: 내용 없는 삭제 명령 fingerprint와 opaque nonce/tombstone을 24시간 유지한다. 과거 content·일반 생성 payload digest·삭제 항목 ID를 남기지 않는다. 24시간 뒤 ID 재사용을 허용하므로 영구 멱등성은 아니다.
- 요청 보관: 비활동 30일과 생성 후 90일 중 이른 시한. 같은 요청 재개와 새로운 요청 시작을 구분한다.
- 활성 장기: 명시 동의 기준 365일. 비활성 내용: 기존 시한과 최대 30일 중 이른 시한. 이 숫자는 승인된 프로토타입 운영 정책이며 연구 결과나 법적 의무가 아니다.
- 적용 기간: 별도의 valid_from/valid_until을 사용한다. 이미 지난 내용을 다시 사용하지 않고 `prune_expired()`는 호출자가 실행한다. 예약 정리 서비스는 설치하지 않는다.
- 모델 연결: [llm.py](../../src/stylemate_memory/llm.py)는 Responses adapter·strict structured output·store=false·출력 상한·timeout과 거부/불완전/JSON/HTTP 오류 처리 경계를 갖는다. 이번 확인은 가상 transport이며 실제 키·모델 호출은 하지 않았다. store=false를 공급자 전체 로그/보관 제거의 보장으로 해석하지 않는다.

## 실제 검증과 남은 범위

이번 작업에서 실행한 코드 검증:

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 -m stylemate_memory.cli demo --synthetic
PYTHONPATH=src python3 -m stylemate_memory.cli features
~~~

단위·SQLite·context·목표/가상 adapter·앱 통합 **79개 PASS**를 확인했고, 데모와 registry 원본도 보존했다. [테스트 실제 출력](sources/runtime-tests.txt)을 읽을 수 있다. PR head의 repository-checks와 Python 3.11/3.14 두 CI job은 GitHub 응답에서 SUCCESS로 확인했으며, 이번에 해당 원격 CI를 새로 실행한 것은 아니다.

영상 검증은 [브라우저 확인](sources/browser-check.json)과 [음성 확인](sources/audio-check.json)에 기록했다. 6장면·31개 대사, 한국어 lang, 실제 재생·챕터 이동·속도 조절, 화면 내 자막과 런타임 예외 없음, 비무음 음성과 타임라인 길이를 확인했다. 문서 링크 검사와 최종 MP4 확인은 [최종 검증 결과](sources/final-validation.json)를 따른다.

실제 자연어/이미지 입력과 확인·동의 UI, 로그인/서버, 실제 LLM 의미 품질, 실제 상품 feature 추출·검색·매칭/추천, 전체 코디 9개 속성, 참여자 연구 효과는 남아 있다. [연구 기준](../../docs/master.md)의 RQ1은 기본/일시적 선호의 분리와 사용자 주도성, RQ2는 필요한 정보에 따른 텍스트·이미지 상호작용과 의도 표현이다. 이 구현과 영상은 그 연구 효과를 검증한 결과가 아니다.

재생성은 설치된 스킬 CLI로 실행한다. 자동으로 브라우저 창을 열지 않으며 로컬 시스템 음성을 사용한다. 기존 산출물이 있으면 해당 HTML을 --replace로 지정한다.

~~~sh
AM_HOME=/private/tmp/stylemate-issue2-render-am node /Users/nojonghyeon/.codex-account-b/skills/answer-me-with-html/scripts/am.mjs video artifacts/issue-2-memory-feature-map-explainer/stylemate-memory-feature-map.md --voice system --no-open --mp4 --replace artifacts/issue-2-memory-feature-map-explainer/stylemate-memory-feature-map.html -o artifacts/issue-2-memory-feature-map-explainer/stylemate-memory-feature-map.html
~~~

## 현재 17개 속성의 원본 대응

아래 표는 이번에 실행한 registry `consumer-17-v1`에서 생성했다. 허용값 전체와 category·source·축소 메타데이터는 [registry 원본](sources/feature-registry.json)과 [registry.py](../../src/stylemate_memory/registry.py)에 있다. 여기서 Image/Metadata/Inference는 상품 추출용 출처 분류이며 사용자 목표의 근거 ID와 구분한다.

| key | 표시 | 타입 | 원본 attribute |
|---|---|---|---|
| garment_type | 아이템 종류 | enum | Garment Type |
| color | 기본 색상 | enum | Primary Color |
| fit | 전체 핏 | enum | Visual Fit |
| length | 기장 | enum | Garment-specific Length |
| sleeve_length | 소매 길이 | enum | Sleeve Length |
| neckline | 넥라인 | enum | Neckline Type |
| pattern | 무늬 | enum | Pattern Type |
| logo | 로고 크기 | enum | Logo Visibility + Logo Size |
| fabric | 원단 | enum | Fabric Type |
| texture | 표면 질감 | enum | Surface Texture |
| style | 스타일 | multi-label | Item Style Affinity |
| mood | 분위기 | multi-label | Visual Mood |
| formality | 격식 정도 | ordinal | Formality Level |
| season | 계절 | multi-label | Suitable Seasons |
| thickness | 두께 | enum | Thickness |
| warmth | 보온성 | enum | Thermal Insulation |
| functions | 기능 | multi-label | Functional Properties |

## 영상 장면과 근거

| 시작 | 장면 | 주요 근거 |
|---|---|---|
| 00:13 | 1. 오늘의 예외와 평소 취향 | memory-design 1·3절, Issue 1·2와 PR 3 |
| 01:08 | 2. Feature Map은 무엇을 표현하나 | registry.py, shopping-memory-prototype 2절, ADR 0003 |
| 02:15 | 3. 기억 하나를 저장하는 과정 | store.py, 프로토타입 3절, ADR 0001/0002 |
| 03:24 | 4. 저장된 기억을 context로 좁히기 | context.py, 프로토타입 4절 |
| 04:36 | 5. context에서 목표값을 만드는 과정 | inference.py/app.py/llm.py, 프로토타입 4·6절 |
| 05:48 | 6. 활용과 삭제, 검증의 경계 | store.py, 프로토타입 3·7절, tests 및 master RQ1/RQ2 |
