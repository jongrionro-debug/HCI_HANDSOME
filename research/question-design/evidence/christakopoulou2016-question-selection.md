---
id: christakopoulou2016-question-selection
claim: 무엇을 물을지는 탐색과 활용의 균형(bandit)으로 고를 수 있다
parts: [2, 3]
stance: 지지
source: Christakopoulou, Radlinski, Hofmann, KDD 2016 (Towards Conversational Recommender Systems)
url: https://www.microsoft.com/en-us/research/publication/towards-conversational-recommender-systems/
domain: 식당 추천, 새 사용자(cold start)
status: 수집
author: 경호 (초안)
---

## 핵심 결과

새 사용자의 선호를 빨리 알아내기 위해 어떤 질문을 할지 정하는 선호 도출 틀을 만들었다. 질문 고르기에 bandit 방식의 탐색·활용 전략(Thompson sampling 포함)이 효과적이었고, 질문 2개만으로 개인화 추천이 정적 모델보다 25% 나아졌다.

## 우리 설계에 쓰는 곳

- ② 질문 후보의 순위(어느 축을 먼저 물을지)를 정하는 근거.
- ③ 답을 Beta 점수로 갱신하는 지금 방식(ADR 0013 결정 8)과 같은 계열.

## 적용 한계

- 속성이 아니라 아이템에 대한 선호를 묻는다.
- 질문 방식(글·이미지)은 다루지 않는다.
- 초록만 확인했다.

## 검증 방법

질문 순서 규칙을 바꾼 시뮬레이션에서 몇 턴 만에 최종 선택에 이르는지 비교한다.
