# 0020 · 질문 루프 v1: 방식 6개, 강도 단계 반영, 규칙+LLM 방식 선택을 기본으로 켠다

- Status: Proposed
- Date: 2026-11-28
- Related Work: Issue [#26](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/26)·[#27](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/27)·[#28](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/28)·[#29](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/29)·[#30](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/30)·[#38](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/38), 결정 문서 PR #31·#32·#40
- Approval: 미승인. 2026-11-28 사용자 요청으로 세 파트 결정 문서를 main에 병합하고 구현했다. 파일럿 결과와 함께 승인 여부를 정한다
- Supersedes: [ADR 0013](0013-langgraph-intent-loop.md)의 질문 큐(결정 6) 중 그리드 위 질문 부분만 구체화한다. 0013의 나머지와 [ADR 0017](0017-question-design-research-workspace.md)의 작업 방식은 그대로다

## 맥락

graph 엔진의 질문 루프([questions.py](../../src/stylemate_memory/graph/questions.py))는 v0에서 `text_options` 하나만 있었고 기본으로 꺼져 있었다. [질문 설계 작업 공간](../../research/question-design/README.md)의 세 파트가 방식([1-modes.md](../../research/question-design/1-modes.md)), 답 반영([2-feedback.md](../../research/question-design/2-feedback.md)), 방식 선택([3-mapping.md](../../research/question-design/3-mapping.md))을 v1으로 정했다. 세 문서를 한 계약으로 묶어 구현하고 루프를 켜야 1차 시스템이 된다.

## 결정

1. **방식 6개와 흐름 전환 1개.** 이미지 여러 장(`select_images`, 2장이면 대조 화면으로 `contrast_pair`를 흡수), 자연어 질문(`text_options`), 단어 정렬(`explain_images`), 공통점 칩(`reason_chips`), 기준 이미지 조정(`relative_adjust`), 사진 붙은 선택지(`photo_chips`)다. 비교 단계 제안(`propose_compare`)은 질문 화면을 빌린 흐름 전환이다. 싫어요 확인(`exclude_check`)은 넣지 않는다.
2. **계약(#29).** `Option.axis`, `Answer.strengths`(칩마다 `only`/`more`), `Candidate.kind`(`gap`·`reactive`·`flow`)와 `term`·`base`를 더한다. 질문에 글로 답하면 별도 `Answer.text` 없이 기존 `parse_turn`이 그 글을 해석하고 열린 질문을 닫는다.
3. **답은 신호로 정규화한 뒤 강도 단계로 반영한다.** L4 고정, L3 확인(강한 점수 + 실선 이해 칩), L2 강함, L1 비교 속 선택, L0 값 변화 없음, L−1 비교 속 미선택, L−3 제외다. 강도는 사용자가 명시한 정도로만 정하고, 물은 축에만 귀속하고, 부정은 명시로만 강해진다. 사진 붙은 선택지의 다중 선택은 L3, 단일 선택은 L4, 안 고른 값은 L0이다. 모르겠음·건너뛰기·방식 바꾸기·다 별로는 값을 바꾸지 않고 진행 신호만 낸다.
4. **질문은 반응형이 먼저, 선제형은 축 순위로.** 반응형(공통점 칩, 단어 정렬, 기준 이미지 조정)은 행동 직후 간격 규칙 없이 묻는다. 선제형 축은 중요도 × 분할력 × 불확실성으로 순위를 매긴다. 한 턴에 질문은 하나이고, 이미지 질문이 떠 있는 동안 8장 그리드를 대신한다. Type이 정해지기 전에는 사진 붙은 선택지, 한 Type 안에서는 이미지 여러 장으로 묻는다.
5. **방식 선택은 규칙이 울타리와 기본값을, LLM이 그 안의 선택을 맡는다.** 실제 모델 provider에서만 LLM이 허용 목록 안에서 후보와 방식을 고른다. 목록 밖이거나 근거 신호가 코드가 확인한 사실과 다르면 버리고 규칙 결정을 쓴다. 규칙 결정은 항상 그림자로 함께 기록한다. fake provider는 규칙만 쓴다.
6. **루프를 기본으로 켠다.** `STYLEMATE_QUESTION_LOOP=off`이면 v0 이전처럼 그리드만 쓴다.
7. **PI v3 값 형태를 반영에 쓴다.** 상대 답은 기준 상품의 v3 점수에서 ±0.5/±1.0(Tone은 L* ±5/±15) 이동한 목표로 soft 정렬한다. 기준 상품과의 색 유사도는 CIEDE2000으로 본다. 예산 hard 필터는 `price_krw`를 먼저 읽고, 가격을 모르면 통과시키지 않는다.

모든 수치(가중치 L3 = 3.0, 선제형 상한 4개, 간격 2턴, 충분 4턴, 중요도 기본표 등)는 파일럿 `가정`이다.

## 대안

- **방식마다 반영 규칙을 따로 둔다**: 방식이 늘 때마다 규칙이 갈라지고 같은 답이 방식에 따라 다르게 반영된다. 정규화 → 공통 반영 구조를 택했다.
- **LLM이 방식을 혼자 고른다**: 글 질문으로 쏠리거나 보여 줄 상품이 없는 방식을 고를 수 있다(agent-pipeline.md 보완 3). 허용 목록과 사실 확인을 코드에 둔다.
- **다중 선택 값을 L4로 고정한다**: 안 고른 값이 사실상 제외되어 "부정은 명시로만"(2-feedback P3)과 부딪힌다.
- **루프를 계속 끈 채 파일럿을 한다**: 보고서의 반복 상호작용 흐름을 확인할 수 없다. 끄는 스위치는 남긴다.

## 영향

- 질문·결정·답은 요청의 결정 로그(`question_log`)에 남고 기억을 만들지 않는다([ADR 0007](0007-joint-feedback-and-end-consent.md), 0013 결정 9).
- 검증: `tests/test_question_loop.py`(방식 build, 규칙/LLM 선택과 거절, 답마다 바뀌는 키와 안 바뀌는 경우, CIEDE2000, 예산), `tests/test_graph_engine.py`의 루프 시나리오, `tests/check_graph_browser.mjs`의 루프 on 화면 검사.
- 남은 것: 품목별 축 중요도를 오프라인 LLM으로 만들고 팀이 검토하기, 말과 선택이 부딪힐 때의 글 고정 질문, 실제 DeepSeek의 방식 선택 품질, v3 사람 검수 30개.
