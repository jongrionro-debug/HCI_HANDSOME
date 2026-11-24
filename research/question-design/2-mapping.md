# ② 상황 매핑

- 주인: 킥오프에서 정함
- 상태: **v0** (확인 지점 B 전). v0은 2026-11-22에 정리한 상황별 기본 방식과 결정 3단계다.
- 방식 이름은 [1-modes.md](1-modes.md)의 코드 이름을 쓴다. 새 방식이 필요하면 1-modes.md의 "새 방식 후보"에 행을 추가하는 PR을 낸다.

## 결정 구조

**코드는 "이 방식이 가능한가, 꼭 이 방식이어야 하나"를 정하고, LLM은 "지금 이 사용자에게 어떤 방식이 나은가"를 고른다.** 사용자는 언제든 방식을 바꿀 수 있다.

1. **코드가 허용 방식을 정한다.** 질문 후보마다 아래 표에서 기본 방식을 가져오고, 이미지 방식은 카탈로그에 보여 줄 상품이 있을 때만 남긴다.
2. **글로만 묻는 경우는 고정한다.** 동의, 조건 충돌, 품목 없음은 LLM이 바꿀 수 없다.
3. **LLM은 허용 방식 안에서만 고른다.** 사용자 상태를 보고 고르고, 발화 해석과 같은 호출에서 `{방식, 물을 축, 이유}`를 함께 받는다.

허용 밖을 고르면 그 호출은 버리고 기본 방식으로 묻는다. 매 질문마다 `{질문 후보, 방식, 결정 주체(규칙/LLM/사용자 전환), 이유, 허용 목록}`을 로그로 남긴다.

## 상황별 기본 방식

| 상황 | 기본 방식 | 허용 방식 | 글 고정 | 판단 주체 | 근거 |
|---|---|---|---|---|---|
| 품목·상황·예산·사이즈 같은 사실·제약 | `text_options` | `text_options` | | 규칙 | `가정` |
| 꼭 지킬 조건, 말과 선택이 부딪힐 때 | `text_options` | `text_options` | 예 | 규칙 | `가정` |
| 기억 동의·변경 | `text_options` | `text_options` | 예 | 규칙 | `가정` (ADR 0007의 명시적 동의) |
| 왜 찾는지(목적, FEA) | `text_options` | `text_options` → 다음 턴 이미지 | | 규칙 | `가정` |
| 핏·실루엣·기장·표면감·분위기·디테일 | `select_images` | `select_images`, `contrast_pair`, `text_options` | | LLM | `가정` |
| "꾸안꾸", "깔끔한" 같은 모호한 미적 표현 | `select_images` | `select_images`, `text_options` | | LLM | `가정` |
| FEA→PI 가설 확인 ("편하게" = 여유 핏?) | `contrast_pair` | `contrast_pair`, `select_images`(2~4장) | | LLM | `joachims2005-relative-preference` |
| 값 이름이 낯선 용어 | `explain_images` | `explain_images`, `text_options` | | LLM | `가정` |
| 고른 상품들의 공통점이 여러 개라 이유가 애매할 때 | `text_options` ([핏][색][둘 다][건너뛰기]) | `text_options` | | 규칙 | `가정` |
| 고른 상품들에 공통점이 없을 때 | `text_options` (분위기 가설 확인) | `text_options` | | 규칙 | `가정` |
| 색 | `text_options` (색 견본 칩) | `text_options`, `select_images` | | LLM | `가정` |
| 정보가 충분하거나 "그냥 보여 줘" | `propose_compare` | `propose_compare` | | 규칙 | `가정` |

## PI 축별 기본 방식 (초안)

위 표를 PI 11축에 적용한 초안이다.

| 축 | 기본 방식 | 비고 |
|---|---|---|
| Type | `text_options`(품목) / `contrast_pair`(세부 종류) | "상의"는 사실이지만 셔츠 vs 니트 폴로는 이미지가 낫다 |
| Color | `text_options` (색 견본 칩) | |
| Tone | `select_images` | |
| Pattern | `select_images` | |
| Fit | `select_images` / `contrast_pair` | |
| Silhouette | `select_images` / `contrast_pair` | |
| Length | `select_images` | |
| Texture | `explain_images` | 값 이름이 낯설다 |
| Fabric | `text_options` 또는 `explain_images` | 사진으로 확인할 수 없다(ADR 0013). 이미지 선택으로 점수를 바꾸지 않는다 |
| Detail | `select_images` | |
| Style | `select_images` | 모호한 미적 표현과 같다 |

## 이미지 방식이 허용되는 조건

이미지로 물을 수 있는지는 카탈로그만 안다. 조건을 못 채우면 그 방식은 허용 목록에서 빠지고 텍스트로 물러난다.

| 방식 | 필요한 상품 |
|---|---|
| `contrast_pair` | 그 축만 값이 다르고 나머지 확인된 PI가 같은 적격 상품 쌍. 비포함은 상품 정보로 확인된 값만 쓴다 |
| `select_images` | 그 축의 값이 서로 다른 적격 상품 N장 이상 (N은 1-modes.md에서 정함) |
| `explain_images` | 보여 줄 값마다 대표 이미지 1장 이상 |
| 공통 | 현재 hard 조건·시각 조건·숨김을 통과한 상품만 |

## LLM이 보는 사용자 신호

허용 방식이 2개 이상일 때만 LLM이 고른다.

| 신호 | 쪽으로 | 근거 |
|---|---|---|
| "잘 모르겠어요", 짧은 답 반복, 건너뛰기 반복 | 이미지 | `knijnenburg2011-user-type-interaction` |
| 모호한 미적 표현 | 이미지 | `가정` |
| 구체적으로 길게 말하는 사용자 | 텍스트 | `knijnenburg2011-user-type-interaction`, `guo2018-natural-language-feedback` |
| "사진으로 보여 줘" / "그냥 말로 할게" | 사용자가 말한 방식 | `가정` |
| 같은 축을 이미지로 두 번 물었는데 신호가 애매함 | 텍스트(이유 묻기) | `가정` |

## 사용자가 방식을 바꾸기

- 이미지 질문에도 입력창은 항상 열어 둔다.
- 텍스트 질문에는 [사진으로 볼게요]를 둔다. 그 축의 이미지 방식이 허용될 때만 보인다.
- 사용자가 바꾼 방식을 어디까지 유지할지(그 축만 / 요청 전체)는 B 전에 정한다.

## B 전에 답할 것

- [ ] "무엇을 물을지"(질문 후보 순위)를 이 파트에서 정할지 (`christakopoulou2016-question-selection`)
- [ ] 사용자 상태 신호를 무엇으로 판정할지 (규칙 신호 vs LLM 판단)
- [ ] 위 표의 `가정` 중 근거를 찾을 것과 user study로 넘길 것 구분
