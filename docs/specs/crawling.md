# 네이버 상품·PI 수집

상의·하의 상품과 상품별 **Type·Brand·Price·Color·Fit·Fabric·Detail** 값을 확보하기 위한 수집 설계다. feature 축은 유지하고 value 목록은 실제 수집 결과로 정한다는 [ADR 0010](../adr/0010-derive-pi-values-from-collected-products.md)을 따른다. 이후 수집 경로·필드·정규화·품질 기준은 이 문서를 직접 갱신한다.

**현재 상태:** 수집 설계 단계. 크롤러·판매자 API 연동·실제 상품 데이터셋은 아직 준비하지 않았다. 아래 레코드와 파일럿 규모는 구현을 위한 초안이며 실행 결과가 아니다. 현재 앱 구현은 [project.md](../project.md#상품과-이미지)를 따른다.

## 1. 목표와 대상

- 상품의 식별자·URL·상품명·분류·이미지와 PI 7개 항목의 원본 값·근거를 함께 확보한다.
- 모든 상품에 7개 항목의 수집 상태를 남긴다. 미기재 항목이 있어도 상품은 보존하고, 확보율을 측정한다.
- 기존 논문 enum에 없는 값도 수집한다. 상품 선택·필터 단계에서 기존 value 목록으로 제한하지 않는다.
- 상의와 하의를 세부 품목별로 나눈다. 티셔츠·셔츠·니트, 바지·스커트 등은 탐색을 위한 예시이며 최종 Type value나 수집 품목의 확정 목록이 아니다.
- 리뷰·구매자 정보·판매자 연락처는 PI 수집 범위에 포함하지 않는다. FEA 30개 태그를 상품별로 채우는 작업도 포함하지 않는다.

## 2. 수집 경로와 확인된 제약

2026-11-04 확인 기준이다. 경로를 선택할 때 이용 조건·접근 가능 여부를 다시 확인한다.

| 경로 | 현재 근거 | 진행 방식 |
|---|---|---|
| 기존 쇼핑 검색 API | 2026-07-31 종료. NAVER API HUB를 포함한 공식 대체 API도 제공되지 않음 | `/v1/search/shop.json`을 수집 진입점으로 사용하지 않음. [공식 종료·이관 공지](https://developers.naver.com/notice/article/32530) |
| 공개 네이버 쇼핑·스마트스토어 페이지 | 아래 세 호스트의 robots.txt에서 일반 크롤러 접근을 차단 | 수집 허용 범위가 확보된 경우에 웹 수집 경로를 적용. 현재 자동 수집 가능 경로로 확정하지 않음 |
| 커머스API | 본인 또는 관련 판매자 리소스에 대한 인증이 필요 | 접근 권한·이용 목적이 맞는 판매자의 상품 목록·상세 수집 경로로 검토. 네이버 전체 상품 검색 권한과 구분. [인증 명세](https://apicenter.commerce.naver.com/docs/commerce-api/current/exchange-sellers-auth) |
| 판매자 제공 상품 파일·이미지 | 제공 자료의 필드·이용 범위를 확인해야 함 | 원본 필드와 옵션 정보를 받아 같은 수집 레코드로 변환하는 대안 |

직접 확인한 [검색 robots.txt](https://search.shopping.naver.com/robots.txt), [쇼핑 robots.txt](https://shopping.naver.com/robots.txt), [스마트스토어 robots.txt](https://smartstore.naver.com/robots.txt)는 모두 HTTP 200으로 응답했고 `User-agent: *`에 `Disallow: /`가 있었다. 쇼핑 호스트에는 AI 학습·RAG 목적 접근 금지 안내도 있었다. 이 확인은 상품 상세 수집 성공을 의미하지 않는다.

**우선 작업은 실제 사용할 수집 경로와 표본 상품을 확보하는 것이다.** 판매자 API·제공 파일을 쓰는 경우에도 연구용 보관·이미지 표시·모델 입력에 필요한 이용 범위를 확인한다. 판매자 원자료 이용과 네이버 호스트의 웹 수집 조건은 각각 확인한다.

## 3. PI별 수집 위치

API 필드는 커머스API의 상품 구조를 기준으로 한 후보이며, 공개 HTML에 같은 필드가 노출된다는 보장은 없다. 실제 응답의 버전·경로와 판매자 입력 여부를 표본에서 확인한다. 상세 필드 경로는 응답의 `originProduct` 내부 기준이다.

| PI | 우선 확보할 원자료 | 보완 자료·처리 기준 |
|---|---|---|
| Type | 목록의 `categoryId`·`wholeCategoryName`, 상세의 `leafCategoryId`, 종류에 해당하는 상품 속성 | 카테고리가 넓으면 세부 종류를 확정하지 않는다. 상품명의 종류 표현은 별도 해석 근거로 보존 |
| Brand | 목록의 `brandName`, 상세의 `detailAttribute.naverShoppingSearchInfo.brandName`·`brandId` | 쇼핑몰명·제조사·브랜드를 분리. 브랜드가 없으면 제목에서 추정한 값과 구분 |
| Price | 목록의 `salePrice`·`discountedPrice`, 옵션 추가금, 배송비·할인 조건 | 숫자 원값·통화·가격 기준·시각을 보존. 개인별 쿠폰가나 옵션 추가금을 기본 판매가와 합쳐 기록하지 않음 |
| Color | `detailAttribute.productInfoProvidedNotice.wear.color`, 색상 옵션명·값 | 전체 판매 색상과 선택 옵션·이미지의 색상을 연결. 이미지에서 추정한 색은 별도 상태 |
| Fit | `detailAttribute.productAttributes[]` 중 해당 품목의 핏 속성 | 카테고리에 핏 속성이 있고 판매자가 입력한 경우에 직접 확보. 상세 설명·상품명·이미지 해석은 별도 상태 |
| Fabric | `detailAttribute.productInfoProvidedNotice.wear.material`, 소재 관련 상품 속성 | 원료·혼용률·겉감/안감 구분을 보존. 데님·니트·기모 같은 원단 구조·가공 표현도 원문으로 유지 |
| Detail | `detailAttribute.productAttributes[]` 중 디테일 관련 속성 | 상세 설명·이미지의 명시 표현을 보완 근거로 사용. 미기재를 ‘디테일 없음’으로 확정하지 않음 |

필드 근거: [상품 목록](https://apicenter.commerce.naver.com/docs/commerce-api/current/search-product), [원상품 조회](https://apicenter.commerce.naver.com/docs/commerce-api/current/read-origin-product-product), [채널 상품 조회의 고시·옵션 구조](https://apicenter.commerce.naver.com/docs/commerce-api/current/read-channel-product-1-product). 속성 ID의 의미는 [카테고리별 속성](https://apicenter.commerce.naver.com/docs/commerce-api/current/get-attribute-list-product)과 [속성값](https://apicenter.commerce.naver.com/docs/commerce-api/current/get-attribute-value-list-product)을 연결해 해석한다. 모든 품목에 동일한 핏·디테일 속성이 있다고 가정하지 않는다.

## 4. 수집 순서

### 4.1 경로와 표본 설정

수집 실행마다 `run_id`, 경로 유형, 허용 호스트·이용 범위, 입력 상품/검색 조건, 품목별 목표 수, 원자료 보관 위치, 수집기·파서 버전을 기록한다. 인증값은 실행 설정에서 관리하며 문서·수집 파일·로그에 넣지 않는다.

초기 파일럿은 **상의 30개·하의 30개, 총 60개 고유 상품**을 제안한다. 가능하면 각 그룹에서 3개 이상 세부 품목을 포함하고, 판매자별 편중도 기록한다. 이는 탐색용 규모이며 최종 데이터셋 수량·통계적 대표성의 기준이 아니다. 경로가 확보된 뒤 실제 범위를 조정한다.

상품별 PI 7개를 모두 채우는 것을 파일럿의 선별 조건으로 삼지 않는다. 먼저 누락 분포를 확인하고, 실제 비교에 쓸 상품은 필요한 PI와 이미지의 근거 상태로 별도 선정한다.

### 4.2 후보 상품 식별

- 판매자 API: 접근 가능한 판매자의 상품 목록을 페이지 단위로 읽고 상·하의 분류로 후보를 만든다. [목록 API](https://apicenter.commerce.naver.com/docs/commerce-api/current/search-product)는 `POST /v1/products/search`이며 네이버 전체 상품을 키워드로 검색하는 API가 아니다.
- 허용된 웹 수집: 카테고리·검색어·정렬·페이지·수집 시각과 노출 위치를 함께 기록한다. 예시 검색어는 ‘셔츠’, ‘티셔츠’, ‘바지’, ‘스커트’처럼 품목을 기준으로 시작하고, 기존 PI value로 결과를 미리 제한하지 않는다.
- 판매자 파일: 제공 파일의 레코드 ID와 원본 필드명을 보존하고 상품 URL·옵션·이미지 연결을 점검한다.

`originProductNo`, `channelProductNo`, 카탈로그 `modelId`, 옵션 ID는 서로 다른 식별자다. 원래 ID를 구분해 저장하고 `출처+판매자+출처 상품 ID`로 내부 상품 키를 만든다. 서로 다른 판매처의 같은 모델은 별도 상품으로 유지하며, 신뢰할 수 있는 연결 ID가 있을 때 모델 관계만 추가한다. 제목 일치만으로 병합하지 않는다.

### 4.3 상세·옵션·이미지 확보

판매자 API는 목록의 원상품 ID로 `GET /v2/products/origin-products/{originProductNo}`를 조회하고, 카테고리별 속성 사전을 연결한다. API별 응답 구조 차이는 경로별 adapter에서 처리한다.

허용된 웹 수집은 HTML의 구조화된 상품 데이터와 명시된 속성표·옵션·상품정보제공고시를 우선 읽는다. JavaScript 렌더링이 필요한 경우 브라우저로 표시된 내용을 읽는 경로를 검토한다. 실제 표본을 보기 전에는 특정 CSS 선택자·초기 상태 객체·비공개 내부 요청을 안정적인 인터페이스로 확정하지 않는다.

옵션은 옵션 ID·원본 옵션명/값·추가금·판매 상태와 이미지 연결을 보존한다. 상품 대표 사진에 다른 옷이 함께 보여도 판매 대상 품목에만 연결한다. 이미지에는 원본 URL, 연결 상품·색상 옵션, 로컬 상대 경로, SHA-256과 revision을 둔다. 연결을 확인하지 못한 옵션·이미지는 미확인으로 남긴다.

웹 수집의 초기 운영값은 허용 조건을 우선하여 **호스트별 동시 요청 1개·요청 간 최소 2초**를 제안한다. timeout·5xx는 최대 3회 재시도하고, 429는 `Retry-After` 또는 별도 대기 정책에 따라 재개한다. 403·418·CAPTCHA·로그인 요구가 발생하면 해당 호스트를 중단하고 차단 원인을 기록한다. 우회용 프록시·크롤러 신원 위장·인증 우회는 수집 설계에 포함하지 않는다. API는 해당 API의 호출 제한을 따른다.

처리 결과와 마지막 성공 지점을 저장해 재시작 시 이어간다. 요청 성공 코드뿐 아니라 최종 URL·콘텐츠 유형·상품 ID·필수 상품 영역을 확인하여 점검/차단 페이지를 상품으로 저장하지 않는다. 새 스키마·파서 오류는 성공 레코드와 분리한다.

## 5. 상품별 수집 레코드 초안

수집 중간 레코드는 기존 앱의 `lumi-catalog-v1`과 구분한다. 아래 `lumi-crawl-draft-v1`은 이 문서의 제안 형식이며 현재 importer가 받는 새 계약이 아니다. 파일럿에서 필드 경로를 확인한 뒤 확정한다.

| 영역 | 보관 내용 |
|---|---|
| 식별·출처 | 내부 상품 키, 출처별 ID, URL·경로 유형·수집 시각·응답/파일 revision |
| 상품 | 상품명·설명, 상/하의 그룹·원본 품목·카테고리 경로·판매 상태 |
| 원자료 | 원본 속성명·값, 관련 상세 텍스트, 옵션, 가격 조건. 근거를 재확인할 수 있는 최소 범위 |
| PI | 7개 키 각각의 `raw_values`, `capture_status`, `source_fields`, 필요 시 `missing_reason`. 근거 인용·옵션/이미지 참조도 연결 |
| 정규화 | 수집 후 `normalized_values`, 규칙 버전·변환 근거·검토 상태를 추가. 원문을 덮어쓰지 않음 |
| 이미지 | 상품/옵션 연결, 원본 URL·로컬 파일·해시·revision. 바이트는 별도 파일 |

`capture_status`는 수집용 상태다. `observed`는 명시된 원문을 확보함, `inferred`는 해석 후보, `missing`은 값 미확보, `conflict`는 같은 대상에 상충하는 근거가 있음을 뜻한다. 서로 다른 옵션의 색상은 정상적인 복수 값이며 상충으로 취급하지 않는다. 현재 상품 Map의 `confirmed` 등과 자동 치환하지 않는다.

아래는 실제 네이버 상품이 아닌 합성 예시다. 원본 value를 담으며 영어 enum으로 바꾸지 않았다. 예시의 중첩 필드 경로는 제공 파일을 변환한 내부 경로다.

```json
{
  "schema_version": "lumi-crawl-draft-v1",
  "product_key": "synthetic:store-a:product-001",
  "source": {
    "mode": "seller_export",
    "url": "https://example.invalid/products/001",
    "collected_at": "2026-11-04T12:00:00+09:00"
  },
  "ids": {
    "origin_product_no": null,
    "channel_product_no": null,
    "catalog_model_id": null
  },
  "title": "합성 예시 바지",
  "garment": {"group": "하의", "type_raw": "바지"},
  "raw_attributes": {
    "종류": "슬랙스",
    "브랜드": "합성브랜드",
    "판매가": 49900,
    "통화": "KRW",
    "색상": "네이비",
    "핏": "와이드",
    "소재": "면 97%, 폴리우레탄 3%"
  },
  "pi": {
    "Type": {"raw_values": ["슬랙스"], "capture_status": "observed", "source_fields": ["raw_attributes.종류"]},
    "Brand": {"raw_values": ["합성브랜드"], "capture_status": "observed", "source_fields": ["raw_attributes.브랜드"]},
    "Price": {"raw_values": [49900], "capture_status": "observed", "source_fields": ["raw_attributes.판매가", "raw_attributes.통화"]},
    "Color": {"raw_values": ["네이비"], "capture_status": "observed", "source_fields": ["raw_attributes.색상"]},
    "Fit": {"raw_values": ["와이드"], "capture_status": "observed", "source_fields": ["raw_attributes.핏"]},
    "Fabric": {"raw_values": ["면 97%, 폴리우레탄 3%"], "capture_status": "observed", "source_fields": ["raw_attributes.소재"]},
    "Detail": {"raw_values": [], "capture_status": "missing", "source_fields": [], "missing_reason": "not_provided"}
  },
  "variants": [],
  "images": []
}
```

빈 `variants`·`images` 배열은 미확보 상태다. 실제로 옵션·이미지가 없다는 주장으로 해석하지 않는다. 값이 없는 이유는 미기재, ‘상세페이지 참조’, 파싱 실패, 접근 실패 등을 구분해 집계한다. 같은 응답의 관련 필드를 함께 보존해 속성 ID만 남거나 근거 경로가 끊기지 않게 한다.

## 6. value 정리와 확정

1. **원문 집계:** feature·상/하의·세부 품목별 원본 값, 고유 상품 수, 옵션 수, 직접 확보/추론/누락 비율을 계산한다. 옵션이 많은 상품 때문에 상품 빈도가 부풀지 않도록 상품 수와 옵션 수를 분리한다.
2. **정규화:** 공백·표기·동의어를 정리한다. `네이비/NAVY`, `면/코튼`은 통합 검토 예시이며 최종 표기·enum 확정은 수집 결과를 따른다. 이름이 같아도 품목별 의미가 다르면 분리한다.
3. **소재·가격 처리:** 소재는 원료·혼용률과 겉감/안감을 연결하고 데님이라는 이유로 면을 추정하지 않는다. 가격은 숫자·통화·조건을 유지한 뒤 분포와 비교 용도에 따라 구간화 여부·경계를 정한다.
4. **품질 검토:** 서로 다른 근거의 충돌과 모호한 정규화는 검토 대상으로 남긴다. 드문 값도 빈도와 근거를 보존하고, 낮은 빈도만으로 삭제하거나 기존 논문 enum에 강제로 맞추지 않는다.
5. **사전 확정:** 품목별 value 목록·동의어 대응·가격 처리 규칙·출처·사전 버전을 확정한다. 해당 버전을 상품 Map과 목표 Map에 함께 연결한다. 모델 해석 후보는 직접 확보된 값과 따로 표시한다.

## 7. 저장 위치와 LUMI 연결

실제 수집 파일·이미지·DB는 **저장소 밖** 작업 디렉터리에 둔다. 수집 산출물은 역할에 따라 상품별 원문/PI JSONL, value 분포 CSV, 정규화 규칙·사전 JSON, 실행 설정·체크포인트로 관리한다. 이미지 바이트는 별도 디렉터리에 둔다. 저장소에는 이 계약과 작은 합성 fixture만 둔다. 같은 역할의 날짜별 백업·요약 파일을 정본으로 늘리지 않는다.

앱 공급 시에는 기존 [CatalogRecord](../../src/stylemate_memory/contracts.py)의 `format_version/product_id/source/title/description/garment_type/raw_metadata/images/labels`로 변환한다. 원자료는 `raw_metadata`에, 근거 있는 PI 해석은 `labels`에 연결하며 사용자 기억과 섞지 않는다. 원자료 가져오기와 실행 사전의 PI 매핑 지원은 별개다.

현재 [매퍼](../../src/stylemate_memory/catalog_mapping.py)·[사전](../../src/stylemate_memory/registry.py)은 고정된 `park-2025-source-v1`의 Pants 값만 지원한다. 수집 후 새 value 사전·품목 매핑·한국어 정규화·상품/목표 검증을 연결해야 한다. 수집 성공만으로 상의 검색이나 새 value가 동작한다고 보고하지 않는다.

기존 [가져오기 검증](../../src/stylemate_memory/catalog_validation.py)의 레코드 256 KiB, 제목·설명 각각 4,000자, 이미지 참조 최대 32개 제한을 고려한다. 전체 상세 HTML·이미지 바이트를 CatalogRecord 안에 넣지 않는다. 원격 이미지 참조는 현재 소비자 화면에 자동 표시되지 않으므로 실제 비교에는 로컬 이미지 공급이 필요하다. 형식·크기 등 현재 이미지 계약은 [상품과 이미지](../project.md#상품과-이미지)를 따른다.

## 8. 파일럿 완료와 확대 기준

| 확인 항목 | 완료 기준 |
|---|---|
| 접근 경로 | 실제 사용할 경로·이용 범위·입력 조건이 기록돼 있고 상품 원자료를 확보함 |
| 상품 단위 | ID·URL·품목·시각이 있으며 재시작·재수집 시 같은 상품이 중복 추가되지 않음 |
| PI 상태 | 모든 상품에 7개 항목이 있고 각각 원문 근거 또는 누락 이유가 있음. 7개 모두 값이 있어야 한다는 뜻은 아님 |
| 원문 검증 | 파일럿 전체 상품의 추출값·원문 경로를 대조하고 파싱 오류·해석 후보·상충을 구분함 |
| 이미지·옵션 | 비교에 사용할 이미지가 열리고 판매 대상·색상 옵션 연결이 확인됨. 미확보 상품은 별도 집계 |
| value 분포 | feature·품목별 상품 수·값 종류·빈도·누락률과 판매자 편중을 확인함 |
| 실행 연결 | 확정 사전으로 가져오기→Map→검색→이미지 표시를 별도 검증함. 수집 완료와 구분 |

확보율은 ‘직접 확보된 고유 상품 수 / 해당 품목의 수집 상품 수’로 계산하고 추론값은 별도 집계한다. 정확도는 원문 대조 결과로 측정한다. 파일럿 결과를 보고 최종 품목·상품 수·feature별 허용 누락률과 보완 방식을 정한다. 현재 이 수치와 최종 value 목록은 미확정이다.

다음 실행은 **경로·표본 확보 → 수집 adapter와 레코드 검증 → 파일럿 및 value 집계 → 정규화·사전 확정 → LUMI 연결** 순서로 진행한다. 차단된 경로는 완료로 표시하지 않으며, 파일럿 검증과 실제 추천·사용자 효과 평가를 구분한다.
