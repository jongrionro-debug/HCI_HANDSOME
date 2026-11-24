---
id: guo2018-natural-language-feedback
claim: 정해진 선택지보다 자유 텍스트 피드백이 더 많은 정보를 담을 수 있다
parts: [1]
stance: 반대
source: Guo et al., NeurIPS 2018 (Dialog-based Interactive Image Retrieval)
url: https://papers.nips.cc/paper/7348-dialog-based-interactive-image-retrieval
domain: 대화형 이미지(신발) 검색
status: 수집
author: 경호 (초안)
---

## 핵심 결과

기존 대화형 이미지 검색은 "비슷함/다름" 같은 이진 피드백이나 정해진 상대 속성으로만 피드백을 받았다. 사용자가 자연어로 피드백하게 했더니 검색 결과가 더 좋아졌고 소통도 더 자연스러웠다.

## 우리 설계에 쓰는 곳

- ① "이미지·선택지가 항상 낫다"에 대한 반대 근거. 텍스트 방식을 남기는 이유가 된다.
- ① 이미지 질문에도 입력창을 열어 두는 근거.

## 적용 한계

- 머릿속에 찾는 목표 이미지가 있는 검색 과제다. 자기 취향을 잘 모르는 LUMI 사용자와 다르다.
- 성과 지표가 검색 순위라서 표현 부담이나 이해받는 느낌(H2)은 재지 않았다.
- 초록만 확인했다. 본문 확인 후 검토로 올린다.

## 검증 방법

user study에서 이미지 질문 중에 입력창을 쓴 비율과, 글로 덧붙인 턴 뒤 추천이 나아졌는지 본다.
