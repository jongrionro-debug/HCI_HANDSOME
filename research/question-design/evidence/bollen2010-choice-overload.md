---
id: bollen2010-choice-overload
claim: 한 번에 보여 주는 후보가 많고 비슷하게 매력적이면 고르기 어려워진다
parts: [1, 2]
stance: 지지
source: Bollen, Knijnenburg, Willemsen, Graus, RecSys 2010 (Understanding choice overload in recommender systems)
url: https://dblp.org/rec/conf/recsys/BollenKWG10
domain: 추천 목록 (도메인은 본문 확인 필요)
status: 수집
author: 경호 (초안)
---

## 핵심 결과

추천 시스템은 비슷하게 매력적인 항목을 모아 보여 주기 때문에 선택 과부하가 생기기 쉽다. 상위 5개와 상위 20개 추천 목록을 비교해, 목록 크기가 체감 다양성·품질·고르기 어려움에 어떻게 작용하는지 봤다. 구체적인 결과 수치는 본문 확인이 필요하다.

## 우리 설계에 쓰는 곳

- ① 선택용 이미지의 장수 N, 지금 그리드 8장의 적정성.
- ③ "다 별로"가 반복되거나 막힌 사용자에게 장수를 줄이는 규칙.

## 적용 한계

- 선택 과부하가 늘 생기지는 않는다는 메타분석도 있다(Scheibehenne et al., JCR 2010). 반대 카드로 따로 만들 만하다.
- 텍스트 목록 기준인지 이미지 기준인지 본문 확인이 필요하다.
- 초록과 발표 자료만 확인했다.

## 검증 방법

그리드 장수별(예: 4장 vs 8장) 선택 시간, "다 별로" 비율, 선택 만족 문항을 비교한다.
