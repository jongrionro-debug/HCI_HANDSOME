# 0012 · 29CM 완전 채움 상품으로 수집 기반 실행 사전(lumi-29cm-v1)을 만든다

- Status: Accepted
- Date: 2026-11-18
- Related Work: 현재 대화의 “feature 맵에 채워야 하는 값들이 다 채워져있는 데이터만 가지고 전체 시스템을 개발” 요청, PR #11(29CM 수집·DeepSeek 보완)
- Approval: 완전 채움 상품으로 전체 시스템을 만드는 방향은 사용자 요청. 결정 3(모델 보완값을 상품 비교에 사용)은 2026-11-18 사용자가 “그냥 계속 넣으면 될거 같은데”라고 승인
- Supersedes: 없음. [ADR 0010](0010-derive-pi-values-from-collected-products.md)의 수집 기반 value 확정을 처음 실행 코드에 연결한다. Park 사전과 그 규칙은 그대로 둔다

## 맥락

29CM 상·하의 230개를 수집하고 DeepSeek로 빈 PI를 보완했다. 원문에는 “상세설명참조”, 본문 조각, “DETAIL” 같은 값이 섞여 있고, Fit·Detail은 대부분 모델 보완값이다. 현재 실행 사전은 Park 바지 영어 enum뿐이어서 수집 값을 실행에 쓸 수 없었다.

## 결정

1. `scripts/build_29cm_registry.py`의 고정 규칙으로 7개 PI 축을 정규화한다. Type은 29CM 소분류(일반 분류는 제외), Brand는 표시 브랜드, Price는 고정 KRW 구간(하한 포함·상한 미포함), Color·Fit·Fabric·Detail은 키워드 규칙에 맞는 값만 쓴다. 규칙에 맞지 않는 원문은 빈 값이다.
2. 7개 축이 모두 값을 가진 상품만 카탈로그로 내보내고, 그 상품들의 분포로 `lumi-29cm-v1` 사전을 만든다. FEA 30개 태그는 Park 사전을 그대로 쓴다. 사전은 품목별 Type을 구분하고 상·하의 10개 품목을 지원한다. 실행은 `--registry lumi-29cm-v1`로 명시적으로 고른다. 기본값은 Park 사전이다.
3. 공급 원문에서 정규화한 값은 `confirmed`(exact canonical metadata), DeepSeek 보완값은 `inferred`·`model_interpretation`으로 상품 Map에 남긴다. 이 사전 버전에 한해 `accept_inferred_product_pi=true`로 inferred 상품 값도 조건 비교·가설 비교에 사용한다. 화면은 이 값을 “추정”으로 표시한다.

## 대안

- inferred 상품 값을 기존처럼 비교에서 제외: Fit 86개 중 84개가 모델 값이라 핏 조건·FEA→Fit 가설이 실제 데이터에서 동작하지 않는다.
- 모델 값을 검증 라벨로 승격: 사람 검증이 없으므로 출처를 왜곡한다.
- 원문을 그대로 value로 사용: 표기 차이와 잡음이 그대로 사전에 들어간다.

## 영향

실제 상품으로 적재→Map→검색→가설 비교→종료·동의 흐름을 실행할 수 있다. 대신 상품 사실에 모델 오류가 섞일 수 있고, 키워드 규칙에 없는 표현은 상품을 제외시킨다(230개 중 86개 사용). 규칙·사전 갱신은 스크립트를 다시 실행하고 `--check`와 `sync_feature_registry.py`로 확인한다. 모델 보완값의 정확도 표본 검수와 사용자 Brand·숫자 가격 조건 지원은 후속 작업이다.
