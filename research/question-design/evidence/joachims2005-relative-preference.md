---
id: joachims2005-relative-preference
claim: 선택은 절대 평가보다 상대 선호로 읽을 때 정확하다
parts: [1, 3]
stance: 지지
source: Joachims, Granka, Pan, Hembrooke, Gay, SIGIR 2005 (Accurately interpreting clickthrough data as implicit feedback)
url: https://www.sigir.org/wp-content/uploads/2017/06/p003.pdf
domain: 웹 검색 결과 클릭 (시선 추적 포함)
status: 수집
author: 경호 (초안)
---

## 핵심 결과

검색 결과 클릭은 정보가 있지만 편향돼 있어서 절대적인 관련도 판단으로 읽기 어렵다. 반면 클릭에서 뽑은 상대 선호는 평균적으로 꽤 정확했다. 클릭은 보여 준 순서와 함께 보인 다른 결과를 기준으로 해석해야 한다.

## 우리 설계에 쓰는 곳

- ① 대조 2장(한 축만 다른 두 장)을 채택하는 근거.
- ② 이미지 선택을 고른 상품의 모든 값에 대한 가점이 아니라, 선택·미선택 사이에 다른 축에 대한 상대 선호로만 반영(ADR 0013 결정 8의 값 귀속).
- ② 그리드 안 위치가 선택에 영향을 줄 수 있으므로 배치 순서를 기록한다.

## 적용 한계

- 순위 목록의 클릭이지 일부러 고른 이미지 비교가 아니다.
- 패션의 미적 판단에도 같은지는 확인되지 않았다.

## 검증 방법

대조 2장 뒤 사용자가 방식을 바꾼 비율, 고른 축이 이후 선택·최종 선택과 이어지는 비율을 본다. 그리드 위치별 선택률도 로그로 본다.
