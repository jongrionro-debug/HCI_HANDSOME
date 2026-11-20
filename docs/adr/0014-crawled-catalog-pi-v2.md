# 0014 · 29CM와 Shopify 크롤링 상품으로 PI v2(11축) 카탈로그를 만든다

- Status: Proposed
- Date: 2026-11-19
- Related Work: 현재 대화의 graph 엔진 벤치마크 설계(“쓸수록 마음에 드는 아이템을 더 빨리 찾는다”), [ADR 0013](0013-langgraph-intent-loop.md)
- Approval: 2026-11-19 사용자 결정
  - 데이터: 크롤링(Cole Buxton·Wax London)과 29CM를 함께 쓰고 H&M은 쓰지 않는다
  - 이미지: 상품당 첫 이미지 1장만 다시 받는다
  - 위치: 저장소 안 `data/`에 두고 커밋하지 않는다
  - 비용: 이미지 기반 추출은 후순위로 둔다
  - 라벨·가격: 값 라벨은 영어로 먼저 쓰고, 가격은 이번 범위에서 조건에서 뺀다
  - 스키마: 이 문서 결정 3의 11축 구성(“이대로 확정”)
  - 이 ADR의 Accepted 승인은 미승인이다
- Supersedes:
  - [ADR 0010](0010-derive-pi-values-from-collected-products.md) 결정 1의 “PI 7개 축 유지”를 `lumi-pi-v2`에 한해 부분 대체한다. value를 수집 데이터에서 확정한다는 원칙은 유지한다.
  - [ADR 0012](0012-collected-29cm-value-dictionary.md)의 실행 사전(한국어 7축)을 이 카탈로그의 정본에서 대체한다. 29CM 원본과 정규화 규칙은 입력으로 재사용한다.

## 맥락

연구에서 보이려는 것은 짧은 대화 뒤 이미지 선택만으로 원하는 상품에 수렴하고, 칩으로 사용자가 자신의 취향을 확인하는 것이다. 기존 29CM 완전 채움 카탈로그에는 세 가지 한계가 있었다.

- 상품 수: 187개(이미지 있는 것 179개)뿐이라 8장 그리드와 대조 칸을 채우지 못했다.
- 축 구성: 7축만으로는 컨셉·색 톤·기장을 칩으로 설명할 수 없었다.
- 축의 의미: Fit 한 축에 모양(와이드·스트레이트)과 여유(루즈·레귤러)가 섞여 있었다. 표면감(코듀로이·리브)도 Detail과 Fabric에 흩어져 있었다.

Cole Buxton·Wax London의 Shopify 상품 데이터는 옷걸이에 건 단독 상품컷 위주다. 모든 상품에 판매자 설명 텍스트가 있어, 이미지 모델 없이도 많은 축을 채울 수 있다.

## 결정

1. **카탈로그 구성:** 29CM 상·하의와 Cole Buxton·Wax London의 상·하의 의류를 합쳐 카탈로그를 만든다. 원본과 이미지는 저장소 안 `data/`에 두고 `.gitignore`로 커밋에서 뺀다.
    - `data/raw/<출처>/`: 원본
    - `data/images/<출처>/<상품ID>.jpg`: 이미지
    - `data/catalog/`: 결과
    - 저장소에는 스크립트와 이 결정만 올린다. 성별은 메타데이터로 남기고 아직 걸러내지 않는다.
2. **이미지:** 상품당 첫 이미지 1장만 쓴다. 그리드에 보이는 이미지와 속성 근거로 쓰는 이미지를 같게 둔다. Shopify 이미지는 `scripts/fetch_shopify_first_images.py`로 받는다. 상·하의만 받고, CDN 너비는 1200, 재시도를 포함한다.
3. **PI v2 스키마(`lumi-pi-v2`):** 값 라벨은 영어다. 축과 값은 `scripts/build_lumi_pi_v2.py`의 `SCHEMA`가 정본이다.

    | 축 | 값 |
    |---|---|
    | Type | T-shirt, Long-sleeve T-shirt, Polo, Shirt, Overshirt, Blouse, Sweater, Cardigan, Knit vest, Sleeveless, Sweatshirt, Hoodie, Zip hoodie / Trousers, Jeans, Sweatpants, Cargo pants, Shorts, Skirt, Leggings |
    | Color | Black, White, Ecru, Grey, Charcoal, Navy, Blue, Light blue, Brown, Beige, Khaki, Green, Red, Pink, Purple, Yellow, Orange, Multi |
    | Tone | Dark, Medium, Light |
    | Pattern | Solid, Stripe, Check, Graphic, Logo, Floral, Jacquard, Other |
    | Fit | Slim, Regular, Relaxed, Oversized (여유만) |
    | Silhouette | Straight, Tapered, Wide, Flare (하의), Boxy (상의) |
    | Length | Short sleeve, Long sleeve, Sleeveless, Cropped, Shorts, Full |
    | Texture | Jersey, Knit, Ribbed, Fleece, Denim, Corduroy, Twill, Seersucker, Waffle, Boucle |
    | Fabric | Cotton, Wool, Cashmere, Linen, Polyester, Nylon, Viscose, Elastane, Acrylic, Silk |
    | Detail | Pockets, Zip, Buttons, Collar, Hood, Drawcord, Elastic waist, Pleats, Embroidery, Patch, Washed, Distressed, Slit |
    | Style | Vintage, Sporty, Workwear, Tailored, Classic, Preppy, Street |

    - Price와 Brand는 원값(GBP·KRW, 브랜드명)만 보존한다. 조건과 탐색에는 쓰지 않는다.
    - Fabric은 사진으로 확인할 수 없으므로 이미지 선택으로 갱신하지 않는다(ADR 0013 결정 8 유지).
4. **채우는 순서(비용이 낮은 순):**
    - (1) 구조화 필드: Shopify `product_type`·색 옵션·상품명의 색, 29CM 정규화 값의 영어 매핑
    - (2) 고정 파생 규칙: 색 → Tone, 품목 → 대표 소매·기장, 단색 → Solid, 니트·청바지 → Texture
    - (3) 판매자 텍스트의 영어·한국어 키워드 규칙
    - (4) 이미 있는 29CM DeepSeek 보완 문장의 재사용(새 호출 없음)
    - 텍스트 모델과 이미지 모델 호출은 후속 단계로 두고, 실행할 때 별도로 요청받는다.
    - 축마다 `status`를 남긴다.
        - confirmed: 원문·구조화 근거
        - derived: 고정 규칙 파생. Style 키워드도 여기에 속한다
        - inferred: 모델 해석
    - `method`와 근거 문구도 함께 남긴다.

## 대안

- **H&M Kaggle 데이터:** 고객 반복 구매 이력이 장점이었다. 그러나 사용자 결정으로 쓰지 않는다. 반복 사용 효과는 인터뷰 기반 가상 사용자로 측정한다.
- **29CM만 확대 수집:** 수집과 이미지 속성 추출에 시간과 구독 사용량이 든다.
- **Fashionpedia·K-Fashion:** 살 수 있는 상품이 아니거나 접근 절차가 있다. 값 사전 설계의 참고 자료로만 쓴다.
- **7축 유지:** 컨셉·톤·기장·표면감을 칩으로 설명할 수 없고, Fit 값의 귀속이 흐려진다.
- **원본을 저장소 밖에 유지:** 사용자가 저장소 안 `data/`(커밋 제외)를 택했다.

## 영향

- **2026-11-19 실행 결과:** 1,016개 상품(Cole Buxton 280, Wax London 515, 29CM 221 / 상의 732, 하의 284)을 만들었다. 축별 채움 수는 다음과 같다.

    | 축 | 채움 |
    |---|---|
    | Type | 1016 |
    | Color·Tone | 1001 |
    | Pattern | 899 |
    | Fit | 707 |
    | Silhouette | 230 (상의는 Boxy만 해당) |
    | Length | 986 |
    | Texture | 494 |
    | Fabric | 879 |
    | Detail | 785 |
    | Style | 542 |

    - 비어 있는 곳이 많은 축: Cole Buxton 상의의 Fit(27%), 상의 Texture(약 40%), 29CM Style(약 20%)
    - 키워드 규칙의 정확도는 표본만 눈으로 봤고, 체계적 검수는 하지 않았다.
- **2026-11-20 상의 우선 실행(사용자 요청: 상의부터 완성):**
    - 상의 1,098개(29CM 476, Wax London 396, Cole Buxton 226)의 빈 축을 DeepSeek(`deepseek-v4.1-flash`)로 첫 이미지+판매자 텍스트를 함께 보내 채웠다(`scripts/fill_pi_v2_image.py`, 1,094회 호출, 오류 0). 값은 inferred·`image_model`로 남고 Fabric은 텍스트 원문 인용이 있을 때만 받는다.
    - 상의 채움률: Color·Pattern·Fit·Silhouette(Straight·Boxy)·Length 100%, Style 98%, Fabric 87%, Texture 86%, Detail 78%. Detail·Texture·Fabric의 빈칸은 모델이 "근거 없음"으로 답한 경우다.
    - 표본은 눈으로 몇 개만 봤고 체계적 검수는 하지 않았다.
    - 실행 사전 `lumi-pi-v2-top`(품목 `Top` 1개, 11축+Brand, Price 제외)과 가져오기 파일(`data/catalog/lumi-pi-v2-top-import.jsonl`)을 `build_lumi_pi_v2.py --export-top`으로 만든다. graph 엔진의 가설·이유 칩 축은 사전의 축을 읽는다.
- **위험:**
    - 29CM 상품은 변형 색상이 모두 Color에 들어가 첫 이미지의 색과 다를 수 있다(3색 이상 55개).
    - Shopify 두 곳은 남성복, 29CM는 여성복이 섞여 있다.
    - 키워드 규칙은 판매자 문구에 의존한다.
    - Style은 근사치다.
- **코드 영향:** 7축이 고정된 코드는 사전에서 축을 읽도록 바꿔야 이 카탈로그를 실행할 수 있다.
    - [registry.py](../../src/stylemate_memory/registry.py)의 7축 검증
    - [graph/hypotheses.py](../../src/stylemate_memory/graph/hypotheses.py)·[graph/engine.py](../../src/stylemate_memory/graph/engine.py)·[comparison.py](../../src/stylemate_memory/comparison.py)·[model_io.py](../../src/stylemate_memory/model_io.py)의 축 목록
- **Accepted 전에 정할 것:** 성별 범위, 29CM 다색 상품의 색 처리, 키워드 규칙 표본 검수의 합격선, 비어 있는 축을 텍스트 모델로 채울지 여부
- **후속 작업:**
    - 실행 사전·카탈로그 가져오기 연결(상의는 2026-11-20 연결, 하의는 남음)
    - 빈 축 텍스트 모델 파일럿(실제 호출은 별도 요청)
    - G1 벤치마크 시나리오를 이 스키마로 다시 쓰기
    - 이전 데이터 폴더(`~/Documents/LUMI-data/29cm-catalog`, `~/Downloads/크롤링`) 정리. 사용자 승인 후 진행한다
