---
id: xie2022-relative-feedback
claim: 상대 피드백은 받기 쉽지만 점수로 옮길 때 척도를 맞춰야 한다
parts: [3]
stance: 지지
source: Xie et al., arXiv 2208.09837 (Comparison-based Conversational Recommender System with Relative Bandit Feedback)
url: https://arxiv.org/abs/2208.09837
domain: 대화형 추천 (속성 피드백)
status: 수집
author: 경호 (초안)
---

## 핵심 결과

기존 대화형 추천은 대부분 속성에 대한 절대 피드백만 받는다. 비교로 묻는 상대 피드백이 더 실용적이지만, 사용자의 절대 선호와 척도가 맞지 않아 그대로 반영하기 어렵다. 이를 다루는 비교 기반 대화형 추천을 제안했다.

## 우리 설계에 쓰는 곳

- ② 대조 2장·다중 선택의 결과를 Beta 점수(절대 척도)로 옮기는 규칙의 근거와 주의점.
- ② "갱신 크기"를 파일럿으로 정한다는 ADR 0013의 미정 사항과 연결.

## 적용 한계

- 게재처와 실험 도메인은 본문 확인이 필요하다.
- 이미지 비교가 아니라 속성 비교일 수 있다.
- 초록만 확인했다.

## 검증 방법

같은 선택 로그를 갱신 크기만 바꿔 다시 돌려(오프라인 재생), 최종 선택 상품의 순위가 어떻게 달라지는지 본다.
