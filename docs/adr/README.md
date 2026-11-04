# 결정 기록

ADR은 구조·계약·운영·연구 방향에 오래 영향을 주는 선택의 **이유**를 남긴다. 현재 동작은 [project.md](../project.md), 작업은 Issue, 변경과 검증은 PR에서 확인한다. 작은 수정마다 ADR을 만들지 않는다.

## 이름과 수명

- 파일명: `NNNN-short-title.md`. 기존 최대 번호 다음의 4자리 숫자와 소문자 영문·숫자·하이픈을 사용한다. 삭제된 번호도 재사용하지 않는다.
- 상태: `Proposed`, `Accepted`, `Superseded`. 과거 ADR의 기존 표기는 그대로 읽는다. 승인 근거 없이 `Accepted`로 쓰지 않는다.
- 기존 결정이 바뀌면 새 ADR에서 대체 범위를 적고, 이전 ADR에는 상태와 후속 링크를 남긴다. 일부만 바뀌면 기존 결정 전체가 폐기된 것처럼 표시하지 않는다.
- 승인된 본문의 당시 근거·수치를 소급 수정하지 않는다. 문서 이동에 따른 링크 정정과 상태·대체 관계 갱신은 가능하다.
- 같은 결정을 PR에 다시 풀어 쓰지 않고 ADR을 연결한다. Issue·PR 번호는 실제로 있을 때만 적는다.

## 새 결정의 형식

```md
# NNNN · 결정 제목

- Status: Proposed / Accepted / Superseded
- Date: YYYY-MM-DD
- Related Work: 요청 또는 실제 Issue·PR
- Approval: 승인 근거와 날짜, 미승인 시 미승인
- Supersedes: 없음 또는 이전 ADR과 대체 범위

## 맥락
문제·요구사항·제약

## 결정
선택과 적용 범위

## 대안
검토한 대안과 채택하지 않은 이유

## 영향
이점·비용·위험·후속 작업·검증 방법
```

## 기록

- [0001 · 요청 범위·사용자 동의와 삭제 경계](0001-memory-boundaries.md)
- [0002 · 로컬 메모리 프로토타입의 저장·검증·조회](0002-memory-prototype-storage.md)
- [0003 · 소비자용 쇼핑 메모리와 목표 feature 프로토타입](0003-consumer-shopping-prototype.md)
- [0004 · Park et al. (2025) Feature Map 차용](0004-adopt-park-2025-feature-map.md)
- [0005 · 근거와 해석을 분리하는 장단기 메모리](0005-evidence-linked-memory.md)
- [0006 · FEA→PI 가설을 이미지 비교로 구체화](0006-fea-to-pi-hypothesis-comparison.md)
- [0007 · 이미지 선택과 선택 이유의 동시 접수 및 종료 후 장기 동의](0007-joint-feedback-and-end-consent.md)
- [0008 · 현재 구현 문서 단일화와 결정 기록 분리](0008-current-implementation-source-of-truth.md)
- [0009 · 세 저장소의 맥락 문서 경로와 역할을 통일한다](0009-common-context-layout.md)
- [0010 · PI value를 수집한 상품 데이터에서 확정한다](0010-derive-pi-values-from-collected-products.md)
