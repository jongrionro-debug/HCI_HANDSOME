# 네이버 상품·PI 수집

상의·하의 상품과 상품별 **Type·Brand·Price·Color·Fit·Fabric·Detail** 값을 확보하기 위한 수집 설계다. feature 축은 유지하고 value 목록은 실제 수집 결과로 정한다는 [ADR 0010](../adr/0010-derive-pi-values-from-collected-products.md)을 따른다. 이후 수집 경로·필드·정규화·품질 기준은 이 문서를 직접 갱신한다.

**현재 상태:** [수집 스크립트](../../scripts/crawl_naver.mjs)는 SmartStore 상품 URL 목록 또는 사용자가 연 Chromium 상품 탭에서 PI 원문·옵션·이미지를 저장한다. 앞선 상품 1건 추출과 합성 페이지의 자동 수집은 확인했지만, 새 스크립트의 실제 URL 직접 접근은 HTTP 429로 종료했다. 새 스크립트의 실제 상품 전체 수집·수동 시작의 사용자 탐색·다른 스토어/상의·60건 파일럿은 미검증이다. 판매자 API·앱 사전 연결·검색 목록 자동 탐색은 아직 구현하지 않았다. 현재 앱 구현은 [project.md](../project.md#상품과-이미지)를 따른다.

## 실행

Node.js 22+와 기존 설치된 `playwright`·Chromium을 사용한다. 앱의 Python 의존성은 늘리지 않는다. 설치가 없는 환경에서는 [공식 설치 안내](https://playwright.dev/docs/library)를 따라 Node 작업 환경에 Playwright와 Chromium을 준비한다. 스크립트가 패키지·브라우저를 자동 설치하지는 않는다.

Chromium에서 상품을 직접 연 뒤 나머지 수집을 자동으로 진행하려면 저장소 루트에서 다음을 실행한다.

```sh
node scripts/crawl_naver.mjs \
  --manual-start \
  --out "$HOME/Documents/LUMI-data/naver-crawl"
```

화면이 보이는 Chromium의 네이버 홈이 열리면 그 창에서 상품을 탐색한다. 정상적인 상품 탭을 하나 이상 연 뒤 **실행 중인 터미널에서 Enter**를 누르면 열린 SmartStore 상품 URL을 수집한다. 로그인이 필요할 때는 사용자가 Chromium 창에서 직접 진행한다. 개인 브라우저 프로필·인증 파일은 재사용하거나 저장하지 않는다. 이 명령은 이전 수동 테스트 창에 연결하는 것이 아니라 새 Chromium을 연다.

상품 URL을 이미 가지고 있다면 직접 순회할 수 있다. `--url`은 반복 가능하며 추적 인자는 자동 제거한다.

```sh
node scripts/crawl_naver.mjs \
  --url 'https://smartstore.naver.com/3_9seconds/products/5089022523' \
  --out "$HOME/Documents/LUMI-data/naver-crawl"

node scripts/crawl_naver.mjs \
  --urls-file "$HOME/Documents/LUMI-data/product-urls.txt" \
  --out "$HOME/Documents/LUMI-data/naver-crawl" \
  --limit 60
```

URL 파일은 한 줄에 상품 URL 하나이며 빈 줄·`#`로 시작하는 줄은 무시한다. 네이버 검색 URL·다른 쇼핑몰·상품 목록 URL은 지원하지 않는다. `--manual-start`와 URL 목록을 함께 주면, 그 Chromium에서 이미 열린 동일 상품 탭은 새로 이동하지 않고 읽는다.

| 옵션 | 기본값·동작 |
|---|---|
| `--out` | 필수. 저장소 밖 디렉터리. 심볼릭 링크가 저장소 안을 가리키는 경우도 거부 |
| `--manual-start` | 사용자가 Chromium에서 상품을 연 뒤 터미널 Enter로 수집 시작. 입력 가능한 터미널 필요 |
| `--limit` | 최대 20개 상품. 목록을 늘릴 때 명시적으로 변경 |
| `--interval-ms` | 2,000ms. 옵션 선택·이미지 이동·이미지 다운로드·상품 간 간격, 최소 2,000ms |
| `--max-option-states` | 100개. 이전 옵션 선택과 다음 그룹의 원문 목록을 한 상태로 계산. 초과하면 `truncated=true` |
| `--max-images` | 상품당 최대 32개. 썸네일·리뷰 이미지를 제외하고 확대 상품 이미지를 읽음 |
| `--no-images` | 이미지 URL만 보관. 나중에 같은 출력 경로로 이미지 다운로드를 재개 가능 |
| `--headless` | 화면 없이 실행. `--manual-start`와 함께 사용 불가 |
| `--timeout-ms` | 개별 탐색·요소 대기 10,000ms |

출력은 `<out>/<store>-<product-id>/product.json`과 `images/<sha256>.<확장자>`, 최근 실행 결과인 `<out>/run.json`이다. 같은 출력 폴더에는 수집기 프로세스 하나만 실행한다. 데이터는 **앱 importer와 별개인 수집용 JSON**이며 기존 앱에 바로 넣지 않는다. `run.json`은 재실행하면 최신 결과로 갱신한다.

- 완료 상품은 저장 파일과 이미지 해시를 확인한 뒤 `skipped`로 건너뛴다. 수집값을 갱신하려면 별도 출력 폴더를 지정한다.
- 이미지 다운로드 실패는 `partial`로 기록하며 같은 명령을 다시 실행하면 브라우저 상품 재추출 없이 이미지 다운로드를 재개한다. 다운로드 전 원문을 먼저 저장한다.
- 옵션·고시·갤러리 추출 오류는 `validation.warnings`와 `extraction_status=partial`로 남긴다. 이 부분을 다시 추출하려면 페이지/파서를 확인한 뒤 새 출력 폴더로 실행한다. 기존 데이터를 조용히 덮어쓰지 않는다.
- 401·403·418·429 또는 접속 제한·CAPTCHA·로그인 화면이면 배치를 중단하고 남은 URL은 `not_attempted`로 기록한다. 이미지 호스트의 동일 상태 코드는 나머지 이미지 다운로드를 중단하고 `partial`로 기록한다. 현재 스크립트는 차단·timeout·5xx에 자동 재시도하지 않으며, 문서 후반의 재시도 설계와 구분한다.
- 종료 코드는 전부 완료/skip이면 0, 실패·부분 실패가 있으면 1이다. `truncated`는 설정한 탐색 상한으로서 별도 표시하며 전체 옵션·재고 확인을 뜻하지 않는다. 선택 가능한 마지막 옵션 그룹은 목록만 읽고 선택하지 않는다.

검증 명령은 `node --test tests/test_naver_crawler.mjs`다. 외부 네트워크 대신 합성 페이지·이미지로 PI 보존·옵션 분기·상한·차단 중단·재개·기존 파일 보호를 검사한다. 실제 사이트의 DOM 호환성·접근 성공과 구분한다.

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
| 공개 네이버 쇼핑·스마트스토어 페이지 | 아래 세 호스트의 robots.txt에서 일반 크롤러 접근을 차단. 최초 검색 418·새 브라우저의 상품 접근 429와, 기존 상품 탭의 DOM 추출 성공을 각각 확인 | Playwright로 렌더링된 목록·상세를 읽는 수집 방안은 4.4절을 따름. 실제 상품 표시·접근 조건을 확인한 경로에 적용 |
| 커머스API | 본인 또는 관련 판매자 리소스에 대한 인증이 필요 | 접근 권한·이용 목적이 맞는 판매자의 상품 목록·상세 수집 경로로 검토. 네이버 전체 상품 검색 권한과 구분. [인증 명세](https://apicenter.commerce.naver.com/docs/commerce-api/current/exchange-sellers-auth) |
| 판매자 제공 상품 파일·이미지 | 제공 자료의 필드·이용 범위를 확인해야 함 | 원본 필드와 옵션 정보를 받아 같은 수집 레코드로 변환하는 대안 |

직접 확인한 [검색 robots.txt](https://search.shopping.naver.com/robots.txt), [쇼핑 robots.txt](https://shopping.naver.com/robots.txt), [스마트스토어 robots.txt](https://smartstore.naver.com/robots.txt)는 모두 HTTP 200으로 응답했고 `User-agent: *`에 `Disallow: /`가 있었다. 쇼핑 호스트에는 AI 학습·RAG 목적 접근 금지 안내도 있었다. 이 확인은 상품 상세 수집 성공을 의미하지 않는다.

**우선 작업은 실제 사용할 수집 경로와 표본 상품을 확보하는 것이다.** 판매자 API·제공 파일을 쓰는 경우에도 연구용 보관·이미지 표시·모델 입력에 필요한 이용 범위를 확인한다. 판매자 원자료 이용과 네이버 호스트의 웹 수집 조건은 각각 확인한다.

## 3. PI별 수집 위치

웹 위치는 [3.9세컨즈 상품 5089022523](https://smartstore.naver.com/3_9seconds/products/5089022523)에서 확인한 항목을 포함한다. 다른 스토어·품목에서도 같은 구조와 값이 제공되는지는 추가 표본으로 검증해야 한다. API 필드는 별도의 연결 후보이며 상세 경로는 응답의 `originProduct` 내부 기준이다.

| PI | Playwright에서 읽을 원자료 | API 후보·처리 기준 |
|---|---|---|
| Type | 페이지 내 Product JSON-LD의 `category`, 카테고리 표시·종류 속성 | API는 `categoryId`·`wholeCategoryName`·`leafCategoryId`. 넓은 분류와 상품명에서 해석한 세부 종류를 구분 |
| Brand | 상품정보의 ‘브랜드’ 값 | API는 `brandName`, `detailAttribute.naverShoppingSearchInfo.brandName`·`brandId`. 쇼핑몰명·제조사와 분리 |
| Price | Product JSON-LD의 `offers.price`·`priceCurrency`, 화면 가격·묶음 수량·옵션 추가금 | API는 `salePrice`·`discountedPrice` 등. 숫자·통화·조건·시각을 보존하고 묶음 가격을 한 벌 가격으로 바꾸지 않음 |
| Color | 상품 고시의 색상, 색상/디자인 옵션 원문 | API는 `detailAttribute.productInfoProvidedNotice.wear.color` 등. 고시가 ‘상세페이지참고’면 그 값을 색상으로 사용하지 않음. 디자인명에서 색을 분리하면 해석 후보로 표시 |
| Fit | 상품정보를 펼친 뒤 ‘하의핏’ 등 해당 품목의 핏 값 | API는 `detailAttribute.productAttributes[]`의 해당 속성. 상품명·이미지 해석은 별도 상태 |
| Fabric | 상품정보의 ‘주요소재’, 고시의 제품소재 | API는 `detailAttribute.productInfoProvidedNotice.wear.material`·관련 속성. 원문 원료명·혼용률·겉감/안감을 구분하고 미기재 비율을 추정하지 않음 |
| Detail | 상품정보를 펼친 뒤 ‘디테일’ 값 | API는 `detailAttribute.productAttributes[]`의 해당 속성. 상품명·이미지 해석과 구분하고 미기재를 ‘없음’으로 확정하지 않음 |

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

허용된 웹 수집은 **Playwright + Chromium**을 구현 후보로 삼아 JavaScript가 렌더링한 구조화된 상품 데이터·속성표·옵션·상품정보제공고시를 읽는다. 실제 표본을 보기 전에는 특정 CSS 선택자·초기 상태 객체·비공개 내부 요청을 안정적인 인터페이스로 확정하지 않는다.

옵션은 옵션 ID·원본 옵션명/값·추가금·판매 상태와 이미지 연결을 보존한다. 상품 대표 사진에 다른 옷이 함께 보여도 판매 대상 품목에만 연결한다. 이미지에는 원본 URL, 연결 상품·색상 옵션, 로컬 상대 경로, SHA-256과 revision을 둔다. 연결을 확인하지 못한 옵션·이미지는 미확인으로 남긴다.

웹 수집의 초기 운영값은 허용 조건을 우선하여 **호스트별 동시 요청 1개·요청 간 최소 2초**를 제안한다. timeout·5xx는 최대 3회 재시도하고, 429는 `Retry-After` 또는 별도 대기 정책에 따라 재개한다. 403·418·CAPTCHA가 발생하면 해당 호스트의 자동 수집을 중단하고 원인을 기록한다. 로그인 화면은 사용자에게 직접 진행하도록 맡기며, 로그인만으로 접근 제한이 풀린다고 가정하지 않는다. 우회용 프록시·크롤러 신원 위장·인증 우회는 수집 설계에 포함하지 않는다. API는 해당 API의 호출 제한을 따른다.

처리 결과와 마지막 성공 지점을 저장해 재시작 시 이어간다. 요청 성공 코드뿐 아니라 최종 URL·콘텐츠 유형·상품 ID·필수 상품 영역을 확인하여 점검/차단 페이지를 상품으로 저장하지 않는다. 새 스키마·파서 오류는 성공 레코드와 분리한다.

### 4.4 Playwright로 수집하는 방식

Playwright는 실제 브라우저에서 페이지를 열고 렌더링된 요소를 읽거나 클릭할 수 있다. 상품 목록의 페이지 이동·추가 로딩, 상세 탭 열기, 옵션 펼치기처럼 JavaScript 상호작용이 필요한 수집에 사용할 수 있다. [브라우저 실행](https://playwright.dev/python/docs/library)과 [locator](https://playwright.dev/python/docs/locators)를 사용하며, 고정 시간 대기만으로 로딩 완료를 판단하지 않는다.

1. **접근 확인:** Playwright가 띄운 화면 있는 독립 Chromium에서 상품 표시를 확인한다. 사용자가 그 창에서 직접 탐색해 정상적으로 연 상품 탭이 있으면 같은 탭을 유지해 읽는다. 개인 브라우저 프로필·쿠키 파일을 복사하지 않는다. 새 탐색은 응답 상태·최종 URL·차단 문구를 검사하고 검색 접근과 상세 접근을 구분한다. 열린 탭의 기존 DOM을 읽을 때는 최초 HTTP 상태를 새로 확인했다고 기록하지 않는다.
2. **목록 추출:** 상품 카드·URL·출처 ID·제목·가격·이미지 참조를 읽고 중복 URL/ID를 제거한다. 페이지 이동·스크롤 후 새 상품 수와 종료 조건을 확인한다.
3. **상세 추출:** 상품별 페이지에서 판매 대상·카테고리·브랜드·가격을 읽고, ‘상품정보’·‘상세정보’·고시 등 실제 표시된 영역을 펼쳐 원본 속성명·값을 확보한다.
4. **옵션 연결:** 색상·사이즈 옵션을 펼쳐 값·추가금·판매 상태·이미지 대응을 수집한다. 옵션 조작 전후의 선택 상태를 기록한다. 장바구니·구매·리뷰 작성은 수행하지 않는다.
5. **근거 추출:** DOM의 속성표와, 존재하는 경우 JSON-LD·페이지 내 구조화 데이터의 값을 수집 레코드에 연결한다. 정상 페이지가 자체 요청한 상품 응답은 [네트워크 관찰](https://playwright.dev/python/docs/network)로 구조를 확인할 수 있지만, 쿠키·인증 헤더를 저장하거나 비공개 요청의 직접 재호출을 전제로 설계하지 않는다. 상세 이미지 안의 텍스트는 DOM에서 바로 확보되는 값과 분리하여 OCR/해석 보완 대상으로 남긴다.
6. **저장·재개:** PI 7개 수집 상태·원문 근거·옵션/이미지 연결을 보관하고 처리 위치를 기록한다. 현재 스크립트는 상품별 `product.json`과 `run.json`을 사용한다. 요청 속도·오류 처리의 구현 범위는 실행 절을 따른다. 다른 품목·페이지 유형의 parser는 추가 표본으로 검증한다.

2026-11-04에 로그인 없는 독립 Playwright 브라우저로 [‘셔츠’ 검색 페이지](https://search.shopping.naver.com/search/all?query=%EC%85%94%EC%B8%A0)를 한 번 열었다. 응답은 **HTTP 418**, 표시 내용은 **‘쇼핑 서비스 접속이 일시적으로 제한되었습니다’**였으며 상품을 추출하지 못했다. 이 결과는 현재 연결된 브라우저 환경의 관측이다. 다른 이용 환경의 접속 가능 여부나 모든 상품 상세의 상태까지 확정하지 않는다. Playwright의 렌더링·클릭 기능만으로 서버의 접근 제한이 해소되지는 않는다.

현재 직접 검증한 웹 구조와 범위는 다음과 같다.

- 사용자가 같은 Chromium에서 연 상품 `5089022523`은 로그인 링크가 표시된 상태에서도 읽을 수 있었다. 상품정보는 `li`의 속성명·값 두 영역, 옵션은 `role="button"`·`role="option"`과 옵션 그룹명, 상품 분류·가격은 Product JSON-LD에서 추출했다. 변하는 CSS 클래스와 전체 페이지 텍스트를 수집 기준으로 삼지 않았다.
- 사이즈 30·32·34·36·38별 첫 번째 바지의 선택 가능 디자인을 읽었고, 두 번째 바지는 한 조건만 확인했다. 모든 조합의 재고·추가금은 미검증이다. 제목의 ‘10종’과 실제 선택 가능 디자인 수가 같다고 가정하지 않는다.
- 표본의 49,600원은 1+1 두 벌 묶음 기본 표시 가격이다. 일부 두 번째 바지 옵션은 4,000원 추가금이 있었다. 색상은 옵션명에서 분리한 해석값이며 소재 혼용률·이미지별 색상 대응은 미확인이다.
- 이미지 확대 보기의 상품 이미지 10개를 추출·다운로드했다. 상품 캐러셀에는 리뷰 항목도 함께 있으므로 리뷰 이미지와 상품 이미지, 같은 이미지의 썸네일·확대본을 구분해야 한다.
- 별도 새 Chromium에서 같은 상품 URL을 연 시도는 HTTP 429로 종료했다. 기존 탭의 단일 상품 추출 성공을 새 세션·상품 목록 순회·대량 수집의 성공으로 확대하지 않는다.

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
