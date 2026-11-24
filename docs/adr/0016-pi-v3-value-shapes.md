# 0016 · PI v3: 축마다 저장 값과 대화 라벨을 분리하고 값의 형태를 나눈다

- Status: Proposed
- Date: 2026-11-23
- Related Work: Issue #20(PI feature별 value 형태 확정), [ADR 0014](0014-crawled-catalog-pi-v2.md)
- Approval: 2026-11-23 사용자 결정(현재 대화, Issue #20의 "팀에서 확정할 것" 4개)
  - Fit: 0.5 단위 점수, 상대 피드백 "조금" +0.5·"훨씬" +1.0(이슈 제안대로)
  - Style: `Outdoor`를 포함한다
  - Weight: 신설하고, 29CM 계절 태그가 없으므로 판매자 문구와 고정 규칙으로 채운다
  - 대표색: 옷 영역을 떼어 내고 배경을 뺀 뒤 최대 3색을 남긴다
  - 이 ADR의 Accepted 승인은 미승인이다
- Supersedes: [ADR 0014](0014-crawled-catalog-pi-v2.md) 결정 3(PI v2 스키마)을 `lumi-pi-v3`에서 부분 대체한다. 결정 1·2·4(카탈로그 구성, 첫 이미지, 채우는 순서와 `status`)는 유지한다. v2 결과물과 실행 사전 `lumi-pi-v2-top`은 그대로 둔다.

## 맥락

인터랙션은 처음에 chat으로 PI를 묻고, chat에서 정해지지 않은 PI를 이미지 선택으로 채운다. PI v2는 모든 축을 같은 종류의 라벨로 다뤄서 다음 문제가 있었다(`data/catalog/lumi-pi-v2-report.json`, 1,748개).

- Fit: "조금 더 여유"가 `Regular`→`Relaxed`처럼 한 칸씩만 움직인다.
- Style: 값이 있는 1,346개 중 `Classic`이 828개(62%)라 구분력이 낮다.
- Silhouette: 상의는 사실상 `Boxy`(431개) 하나이고, 의미가 Fit과 겹친다.
- Color: 사용자는 색 이름으로 말하지만, 비교는 사람이 느끼는 색 차이를 따라야 한다.
- Price: 통화(GBP·KRW)가 섞여 조건으로 쓰지 못했다. 29CM 가격은 v2 빌드가 잘못된 키를 읽어 모두 비어 있었다(이번에 수정).

## 결정

1. **저장 값과 대화 라벨을 분리한다.** 상품에는 점수나 원값을 저장하고, 사용자에게는 라벨로 묻는다. 축마다 기존 `values`(라벨)와 `status`·`method`·`evidence`를 유지하고, 형태에 따라 필드를 더한다.

    | 형태 | 상품에 저장 | 대화 | 비교 | 축 |
    |---|---|---|---|---|
    | 순서형 | `score` | 라벨 | 점수 거리 | Fit, Tone, Length, Weight |
    | 연속형 | Color `colors[]`(rgb·lab·share), Price `price_krw` | 색 이름, 예산 | 색은 CIEDE2000, 가격은 범위 | Color, Price |
    | 범주형 | 라벨 1개 이상 | 같은 라벨 | 일치·겹침 | Type, Pattern, Silhouette, Texture, Fabric, Detail, Style |

2. **조건과 점수 반영을 나눈다.** 반드시 걸러내는 조건은 Type, 예산(`price_krw`), 명시적 제외만이다. 나머지 축은 점수로 반영한다. 사용자 선호는 값·`any`(상관없음)·`unknown`(아직 모름)을 구분해 저장하고, `unknown`인 축만 이미지 단계에서 묻는다.
3. **축별 규칙.** 정본은 `scripts/build_lumi_pi_v3.py`의 `SCHEMA`다.
    - **Brand·링크:** 표시용 메타데이터로만 둔다.
    - **Price:** 원래 금액과 통화를 유지하고 `price_krw`를 더한다. GBP는 기준일 환율(2026-11-20 ECB 기준 1 GBP = 1,757.97 KRW)로 바꾼다. 구간 라벨은 만들지 않는다.
    - **Color:** 첫 이미지에서 옷 영역만 떼어 대표색을 뽑는다.
        - Shopify 컷은 가장자리를 뺀 중앙, 29CM 모델 컷은 품목별 띠(상의는 위, 하의는 아래)를 쓴다.
        - 테두리 색과 가까운 픽셀(배경)은 뺀다. 29CM에서는 피부색 범위도 뺀다.
        - Lab에서 군집하고, 비율 10% 이상인 색을 최대 3개까지 비율과 함께 남긴다. Pattern이 Solid면 1개만 남긴다.
        - 라벨은 17개 색 이름 중 CIEDE2000이 가장 가까운 것이다. 기준값은 Shopify 단색 상품의 실측 중앙값이며, Grey에는 중간 회색(L\* 50)을 하나 더 둔다. 사진 속 옷은 이상적인 색 견본보다 어둡게 찍히기 때문이다. `Multi`는 없앤다.
        - 판매자 색 이름은 `seller_values`로 남긴다.
    - **Tone:** 주색의 L\*를 `score`로 둔다. 라벨은 L\* 40 미만이 Dark, 70 이상이 Light다. "이 색인데 더 밝게"는 L\*만 올린다.
    - **Fit:** Slim=1, Regular=2, Relaxed=3, Oversized=4, 0.5 단위. 판매자 라벨이 기준점이고, 라벨이 둘이면 평균을 낸다. 이미지 판단으로 ±0.5까지 조정할 자리(`image_adjustment`)는 두지만 아직 채우지 않는다. 상대 피드백은 고른 상품의 점수에서 "조금" ±0.5, "훨씬" ±1.0만큼 목표를 옮긴다. 상의와 하의는 `scale`로 구분하고 서로 비교하지 않는다.
    - **Silhouette:** 하의만 Straight·Tapered·Wide·Flare를 쓴다. 상의에서는 축을 없앤다.
    - **Length:** 상의는 소매(Sleeveless 0, Short sleeve 1, Long sleeve 2)로 점수를 매기고, `Cropped`는 점수 없는 라벨로 둔다. 하의는 Shorts 1, Cropped 2, Full 3이다.
    - **Weight(신설):** Light 1, Mid 2, Heavy 3. 채우는 순서는 다음과 같다.
        - (1) 판매자 문구의 GSM(200 미만 Light, 320 이상 Heavy)
        - (2) 두께 키워드
        - (3) 표면감·소재 규칙: Fleece·Boucle·Corduroy, 울·캐시미어 니트는 Heavy. Linen·Seersucker는 Light
        - (4) 품목 규칙: 티셔츠·폴로·셔츠·블라우스·민소매·반바지·레깅스는 Light, 나머지는 Mid
        - (1)(2)는 confirmed, (3)(4)는 derived다.
    - **Style:** Minimal, Casual, Formal, Vintage, Sporty, Workwear, Preppy, Street, Outdoor(9개). 상품당 최대 2개다.
        - `Classic`은 무늬·장식(Graphic·Logo·Stripe·Embroidery·Washed 등)이 없으면 Minimal, 있으면 Casual로 나눈다.
        - `Tailored`는 Formal로 넓힌다. Outdoor·Formal·Minimal·Casual은 판매자 문구 키워드로도 채운다.
        - 구체적인 스타일을 Minimal·Casual보다 먼저 남긴다.
    - **Texture에 `Smooth` 추가(2026-11-24 사용자 결정):** 골·짜임·기모·능선·데님이 보이지 않는 평직·매끈한 표면(슬랙스 원단, 포플린, 나일론, 새틴)이다. 하의 바지 확대 뒤 Texture 빈 칸 대부분이 "고를 값이 없음"이어서 더했다. 이미 이미지 보완을 거친 상품은 `fill_pi_v2_image.py --axes Texture`로 빈 Texture만 다시 묻는다.
4. **채우는 경로.** chat이 먼저 묻는 축은 Type, 예산, Fabric, Weight, Color다. 이미지 선택으로 채우는 축은 Fit(상대 조정), Silhouette(하의), Pattern, Texture, Detail, Style, Tone이다. Fabric은 이미지로 갱신하지 않는다(ADR 0013 결정 8 유지).
5. **드문 값 병합.** 범주형 축에서 품목군(상의·하의)별로 채워진 상품의 1% 미만인 값은 비슷한 값과 합치고, 그 품목군에 해당하지 않는 값은 뺀다. 상품에는 `merged`로 기록한다.
    - Type: Knit vest→Sleeveless, Cargo pants→Trousers(+Detail Pockets), Zip hoodie→Hoodie(+Detail Zip)
    - Fabric: Silk→Viscose. 하의는 Cashmere→Wool도 합친다
    - 하의 Pattern: Logo·Other→Graphic
    - 하의 Texture: Waffle·Boucle→Knit, Seersucker→Twill
    - 하의 Detail의 Collar·Hood, 상의 Detail의 Elastic waist는 뺀다
    - 예외: 상의의 Style `Outdoor`(1개, 0.09%)는 사용자 결정으로 남긴다.
6. **유지하는 계약.** `status`(confirmed / derived / inferred)와 근거 기록, 직접 PI와 FEA→PI 가설의 구분(ADR 0006), FEA 30개 태그를 유지한다. 모델은 새로 호출하지 않는다.

## 대안

- **v2 라벨 유지:** 상대 피드백이 라벨 단위로 건너뛰고, Classic 쏠림이 남는다.
- **RGB 거리로 색 비교:** 사람이 느끼는 차이와 맞지 않는다. Lab에서 CIEDE2000을 쓴다.
- **이상적인 색 견본을 이름 기준값으로 쓰기:** 첫 빌드에서 판매자 색과 주색 라벨 일치율이 29CM 40%, Wax London 37%였다. 사진 실측 기준값으로 바꾼 뒤 각각 43%, 64%가 됐다.
- **Weight를 29CM 계절 태그로 채우기:** 수집한 29CM 1,000개에는 계절 필드가 없다. 본문에 "계절"이 나오는 29건도 대부분 "계절에 구애받지 않는다"는 문구다.
- **Price 구간화:** 예산 조건은 범위 비교로 충분하고, 구간은 통화와 출처마다 경계가 달라진다.

## 영향

- **2026-11-23 실행 결과(`build_lumi_pi_v3.py --data data`, 모델 호출 없음, 약 35초):** 1,748개(상의 1,098, 하의 650). `price_krw`는 1,748개 모두 채웠다(중앙값 116,905원).

    | 축 | 상의 | 하의 |
    |---|---|---|
    | Color·Tone | 1,098 (대표색 2~3개 159) | 650 (2~3개 134) |
    | Fit 점수 | 1,093 (0.5 단위 값 48) | 314 |
    | Length 점수 | 1,097 | 577 |
    | Weight | 1,098 (판매자 근거 441) | 650 (판매자 근거 130) |
    | Style | 1,079 | 283 |
    | Silhouette | 없음 | 372 |

    - Style 분포(1,362개): Minimal 472(35%), Vintage 355, Casual 350, Sporty 202, Street 159, Formal 75, Workwear 71, Preppy 65, Outdoor 6
    - 병합 후 1% 미만으로 남은 값은 상의 Style `Outdoor` 하나다.
- **자동 대조(사람 판단이 아니다):** 판매자 색 이름이 하나인 상품에서 주색 라벨이 그 이름과 같은 비율과, 주색이 그 이름의 기준값과 CIEDE2000 20 안에 드는 비율이다.

    | 출처 | 라벨 일치 | ΔE 20 안 | v2 Tone 일치 |
    |---|---|---|---|
    | 29CM(기준값에 쓰지 않음) | 43% | 82% | 66% |
    | Cole Buxton | 79% | 94% | 81% |
    | Wax London | 64% | 91% | 68% |

    - Shopify 두 곳은 기준값을 만든 데이터라 실제보다 높게 나온다.
    - 불일치는 대부분 Black/Charcoal/Navy, Grey/Ecru/White처럼 경계가 모호한 이름이다. 29CM의 장면컷은 추출 자체가 틀리는 경우가 있다.
- **사람 검수(미완료):** `--review-sample 30`이 출처별 10개씩 `data/catalog/lumi-pi-v3-review.csv`와 `.html`을 만든다. 사람이 대표색·Fit 점수 열을 채운 뒤 `--score-review`로 일치율을 계산한다. 결과는 Issue #20에 남긴다.
- **위험:**
    - 29CM 모델 컷은 고정된 띠로 옷 영역을 잡아서 머리카락·소품·배경이 섞일 수 있다.
    - Weight의 절반 이상(상의 443, 하의 411)은 품목 규칙만으로 채운 값이다.
    - 환율은 고정값이라 기준일이 바뀌면 다시 빌드해야 한다.
- **후속 작업:**
    - 사람 검수 일치율 기록, 그리고 결과에 따라 29CM 영역 추출 개선
    - 추천 점수 함수와 graph 엔진의 상대 피드백 처리(별도 Issue)
    - v3 실행 사전 내보내기와 하의 연결
