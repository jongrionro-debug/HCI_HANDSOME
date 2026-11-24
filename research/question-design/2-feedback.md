# ② 답 해석·반영

- 주인: 파트 2 담당 (Issue "질문 설계 2 · 답 해석·반영")
- 상태: **v0** (확인 지점 A 전). 코드에서는 [graph/questions.py](../../src/stylemate_memory/graph/questions.py)의 `interpret`가 이 표를 구현한다. v0에는 `text_options` 선택 → 값 고정만 있다. v0은 지금 graph 엔진과 제안안에 이미 있는 반영 규칙을 방식별로 모은 것이다. 새로 정한 규칙이 아니라 출발점이다.
- 방식 이름은 [1-modes.md](1-modes.md)의 코드 이름을 쓴다.

## 반영 규칙

"출처"는 지금 규칙이 적힌 곳, "근거"는 그 규칙을 뒷받침하는 카드 ID다. 근거가 없으면 `가정`이다.

| 방식 | 답 | 무엇이 어떻게 바뀌나 | 바뀌지 않는 경우 | 출처 | 근거 |
|---|---|---|---|---|---|
| `contrast_pair` | 한 장 선택 | 두 장이 다른 축만 갱신: 고른 쪽 값 α↑, 안 고른 쪽 값 β 약하게↑ | 반대편 값이 상품 정보로 확인되지 않으면 값 점수 그대로 | [ADR 0013](../../docs/adr/0013-langgraph-intent-loop.md) 결정 8 | `joachims2005-relative-preference`, `xie2022-relative-feedback` |
| `contrast_pair` | 둘 다 아님 / 모르겠음 | 없음 | 확정도 다른 속성의 비선호도 아니다 | [project.md](../../docs/project.md) 가설 비교 5 | `가정` |
| `select_images` | 여러 장 선택 | 선택·미선택 사이 값 차이가 확인된 축만: 선택 쪽에만 있는 값 α↑, 미선택 쪽에만 있는 값 β 약하게↑ | 전부 선택, 전부 미선택, 반대편 값 미확인 → 값 점수 그대로, 상품 순위 신호로만 | ADR 0013 결정 8 | `joachims2005-relative-preference` |
| `select_images` | 좋았던 점 칩 | 사용자가 고른 축에만 반영 | | ADR 0013 결정 8 | `가정` |
| `select_images` | 다 별로 | 수렴 칸↓, 탐색·대조 칸↑. 반복되면 FEA 해석을 글로 묻는다 | 값 점수 그대로, 숨김 횟수에 안 셈 | ADR 0013 결정 8 | `가정` |
| `select_images` | 상품 "별로"(이유 없음) | 그 상품 순위↓, 서로 다른 노출에서 2회면 이번 요청에서 숨김 | 값 점수 그대로 | ADR 0013 결정 8 | `가정` |
| 모든 이미지 방식 | Fabric 관련 선택 | 없음 | 사진으로 소재를 확인할 수 없으므로, 이유 칩·텍스트로 지목했을 때만 갱신 | ADR 0013 결정 8 | `가정` |
| `text_options` | 선택지 탭 | 그 값 고정 | | [agent-scenario.md](../../docs/specs/agent-scenario.md) T5 | `가정` |
| `text_options` | 분위기 가설 [맞아요] / [조금 달라요] | 맞아요 → 확인된 인상. 조금 달라요 → 제안안에 정해지지 않음 | 확인 전 가설은 점수에 넣지 않는다 | [agent-pipeline.md](../../docs/specs/agent-pipeline.md) | `가정` |
| `explain_images` | 값 선택 | 그 값 고정 | | agent-scenario.md T4~T5 | `가정` |
| 글(모든 방식) | 원문 인용이 있는 PI | 그 PI 고정 또는 교체 | 인용이 없으면 거절하고 로그에 남김 | agent-pipeline.md `update_pi` | `가정` |
| 이해 칩 | 칩 고정 / x | 고정 → 이번 요청의 hard 조건. x → 이번 요청 탐색 범위에서 빠짐 | 기억은 만들지 않는다 | ADR 0013 결정 9 | `가정` |
| 가설 칩(점선) | 확인 / x | 확인 → 고정. x → 제거, 같은 가설은 다시 만들지 않음 | | agent-pipeline.md | `가정` |

## B 전에 답할 것

- [ ] 1-modes.md v1에서 바뀐 방식·답 형태에 맞게 행을 고치기
- [ ] 갱신 크기(α, β를 얼마나 올릴지)를 근거로 정할지, 파일럿으로 정할지 (`xie2022-relative-feedback`)
- [ ] 그리드 위치가 선택에 주는 영향을 어떻게 다룰지 (`joachims2005-relative-preference`)
- [ ] 방식을 바꾼 것(전환) 자체를 신호로 쓸지
