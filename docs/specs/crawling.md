# 상품·PI 수집

현재 카탈로그를 만드는 수집 경로와 정규화 계약이다. 카탈로그는 29CM(카테고리 수집)과 Shopify 두 곳(Cole Buxton·Wax London)의 상·하의 상품이다. PI 축과 값 형태는 [ADR 0016](../adr/0016-pi-v3-value-shapes.md)(v3), value는 수집 데이터에서 정한다는 [ADR 0010](../adr/0010-derive-pi-values-from-collected-products.md)을 따른다. v2 → v3 빌드 순서는 [project.md](../project.md#수집)에 있다.

네이버 SmartStore는 [#8](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/8)에서 제외했다. 당시의 네이버 수집 계획과 유니클로·자라 원문 파일럿 기록은 Git 이력에 있다. [crawl_naver.mjs](../../scripts/crawl_naver.mjs)는 공용 함수(`prepareOutputRoot`)를 29CM 수집기와 사이트 비교 스크립트가 쓰기 때문에 남아 있다.

공통 실행 조건: Node.js 22+와 이미 설치된 `playwright`·Chromium을 쓴다. 스크립트가 패키지·브라우저를 자동 설치하지 않는다. 앱의 Python 의존성은 늘리지 않는다.

## 29CM 카테고리 수집과 PI 보완

29CM은 robots.txt가 일반 크롤러에 상품·카테고리 경로를 허용한다(2026-11-17 확인, `/order/`·`/auth/` 등만 차단). [29CM 수집기](../../scripts/crawl_29cm.mjs)는 무작위 sitemap 대신 공개 카테고리 목록(여성 상의·니트웨어·바지·스커트, 남성 상의·니트웨어·하의의 세부 품목 1페이지)에서 상품을 찾고, 세부 품목을 번갈아 골라 상품 페이지를 하나씩 읽는다. 카디건·베스트 세부 품목은 제외한다. 로그인·프로필 재사용·모델 호출은 없다.

```sh
node scripts/crawl_29cm.mjs --out "$HOME/Documents/LUMI-data/29cm-catalog" --per-group 115
OPENCODE_API_KEY=... python3 scripts/fill_pi_deepseek.py \
  --data "$HOME/Documents/LUMI-data/29cm-catalog" --max-calls 300 \
  --export "$HOME/Documents/LUMI-data/29cm-catalog/lumi-catalog-v1.jsonl"
```

- 요청 간격 최소 2초, 동시 요청 1개. 401·403·418·429·CAPTCHA·접속 제한 화면에서 즉시 멈추며 재시도·우회하지 않는다. 같은 `--out`으로 다시 실행하면 저장된 상품을 건너뛴다(`discovery.json`의 목록을 재사용).
- 설치된 Playwright와 Chromium 버전이 다르면 `--browser-path` 또는 `LUMI_CHROMIUM_PATH`로 Chromium 실행 파일을 지정한다.
- 상품별 `products/<id>.json`: URL·ID·그룹·breadcrumb·상품명·브랜드·가격(숫자·통화·정가)·PI 7축 원문과 출처(`structured`/`text`/`referred`/`none`)·상품정보 고시표·상품설명 텍스트·수집 시각. 고시표의 판매자정보(사업자번호·대표자·주소)와 리뷰는 저장하지 않는다. 대표 이미지 최대 3장(JSON-LD, `img.29cm.co.kr`, PNG/JPEG/WebP, 10 MiB 이하)은 `images/<id>/`에 둔다.
- [PI 보완](../../scripts/fill_pi_deepseek.py)은 출처가 `none`·`referred`인 축만, 상품당 1회 DeepSeek([ADR 0011](../adr/0011-use-deepseek-api-for-real-model.md))에 상품명·설명·고시표 텍스트만 보낸다. 근거 문장(`evidence_quote`)이 입력에 그대로 없거나 ‘상세 페이지 참고’류이면 버린다. 결과는 `pi_fills/<id>.json`에 `model_interpretation`·모델명과 함께 따로 두고 원문 값을 덮어쓰지 않는다.
- 내보낸 `lumi-catalog-v1`은 원문 PI를 `raw_metadata`의 `color`·`fit`·`fabric`·`detail`(출처가 structured/text일 때만)에, 모델 값을 `raw_metadata.pi_model_interpretation`에 둔다. `labels`는 비운다(value 사전 확정 전). 이미지는 `STYLEMATE_IMAGE_ROOT=<out>/images` 기준 상대 경로다.

## Shopify 첫 이미지

Cole Buxton·Wax London은 Shopify `products.json` 목록을 `data/raw/<출처>/`에 둔 뒤, [fetch_shopify_first_images.py](../../scripts/fetch_shopify_first_images.py)가 상·하의 상품의 첫 이미지만 받는다(CDN 너비 1200, 재시도 포함, 이미 받은 파일은 건너뜀). 상품마다 품목군·이미지 파일·첫 이미지 변형의 색을 manifest에 남긴다([ADR 0014](../adr/0014-crawled-catalog-pi-v2.md) 결정 2).

```sh
python3 scripts/fetch_shopify_first_images.py --catalog data/raw/waxlondon/catalog.json --source waxlondon --out data
```

## value 정리와 확정

1. **원문 집계:** feature·상/하의·세부 품목별 원본 값, 고유 상품 수, 옵션 수, 직접 확보/추론/누락 비율을 계산한다. 옵션이 많은 상품 때문에 상품 빈도가 부풀지 않도록 상품 수와 옵션 수를 분리한다.
2. **정규화:** 공백·표기·동의어를 정리한다. `네이비/NAVY`, `면/코튼`은 통합 검토 예시이며 최종 표기·enum 확정은 수집 결과를 따른다. 이름이 같아도 품목별 의미가 다르면 분리한다.
3. **소재·가격 처리:** 소재는 원료·혼용률과 겉감/안감을 연결하고 데님이라는 이유로 면을 추정하지 않는다. 가격은 숫자·통화·조건을 유지한다. PI v3([ADR 0016](../adr/0016-pi-v3-value-shapes.md))부터는 구간화하지 않고, 원래 금액·통화에 기준일 환율로 계산한 `price_krw`를 더한다.
4. **품질 검토:** 서로 다른 근거의 충돌과 모호한 정규화는 검토 대상으로 남긴다. 드문 값도 원문 빈도와 근거를 보존하고 기존 논문 enum에 강제로 맞추지 않는다. 다만 PI v3 실행 값에서는 품목군별로 1% 미만인 값을 비슷한 값과 합치고, 상품의 `merged`에 원래 값을 남긴다.
5. **사전 확정:** 품목별 value 목록·동의어 대응·가격 처리 규칙·출처·사전 버전을 확정한다. 해당 버전을 상품 Map과 목표 Map에 함께 연결한다. 모델 해석 후보는 직접 확보된 값과 따로 표시한다.

**PI v3에 필요한 수집 필드.** [ADR 0016](../adr/0016-pi-v3-value-shapes.md)의 값 형태를 채우려면 출처마다 다음을 확보한다.

| 필드 | 쓰는 곳 |
|---|---|
| 첫 이미지(옷 단독 컷 우선) | Color `colors[]`(rgb·lab·share)·Tone L\* |
| 판매가 숫자와 통화 | `price_krw`(기준일 환율) |
| 판매자 핏 라벨 | Fit 점수의 기준점(상·하의 별도) |
| 원단 중량(GSM)·두께 문구 | Weight. 29CM 수집 데이터에는 계절 필드가 없어 계절 태그로는 채우지 못한다 |
| 혼용률·소재 문구 | Fabric과 Weight 규칙 |

새 출처는 단독 컷이 있는지 먼저 확인한다. 모델 컷은 고정된 띠로 옷 영역을 잡기 때문에 배경과 소품이 섞일 수 있다.

## 저장 위치와 LUMI 연결

수집 원본·첫 이미지는 저장소 안 `data/`(커밋 제외, [ADR 0014](../adr/0014-crawled-catalog-pi-v2.md))에 두고, 실행 DB와 이미지 root는 저장소 밖에 둔다. 수집 산출물은 역할에 따라 상품별 원문/PI JSONL, value 분포 CSV, 정규화 규칙·사전 JSON, 실행 설정·체크포인트로 관리한다. 이미지 바이트는 별도 디렉터리에 둔다. 저장소에는 이 계약과 작은 합성 fixture만 둔다. 같은 역할의 날짜별 백업·요약 파일을 정본으로 늘리지 않는다.

앱 공급 시에는 기존 [CatalogRecord](../../src/stylemate_memory/contracts.py)의 `format_version/product_id/source/title/description/garment_type/raw_metadata/images/labels`로 변환한다. 원자료는 `raw_metadata`에, 근거 있는 PI 해석은 `labels`에 연결하며 사용자 기억과 섞지 않는다. 원자료 가져오기와 실행 사전의 PI 매핑 지원은 별개다.

[매퍼](../../src/stylemate_memory/catalog_mapping.py)·[사전](../../src/stylemate_memory/registry.py)은 실행 사전 `lumi-pi-v5.1`(통합 map, [ADR 0021](../adr/0021-pi-v5-1-runtime.md))의 값으로 상품 Map을 만든다. 새 출처나 새 값은 통합 빌드와 `--export-runtime`으로 사전을 다시 만든 뒤에만 실행에 쓰인다. 수집 성공만으로 검색에 반영됐다고 보고하지 않는다.

기존 [가져오기 검증](../../src/stylemate_memory/catalog_validation.py)의 레코드 256 KiB, 제목·설명 각각 4,000자, 이미지 참조 최대 32개 제한을 고려한다. 전체 상세 HTML·이미지 바이트를 CatalogRecord 안에 넣지 않는다. 원격 이미지 참조는 현재 소비자 화면에 자동 표시되지 않으므로 실제 비교에는 로컬 이미지 공급이 필요하다. 형식·크기 등 현재 이미지 계약은 [상품과 이미지](../project.md#상품과-이미지)를 따른다.
