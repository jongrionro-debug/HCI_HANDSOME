# 0004 · Park et al. (2025) Feature Map 차용

- Status: Accepted
- Date: 2026-10-29
- Related Work: 현재 대화의 Feature Map 확정 및 문서 반영 요청
- Approval: 사용자가 “현재 이 feature map으로 확정하니까 이제 이에 따라서 문서에 반영해줘”라고 승인했다. 앞선 요청에서 연구 주장을 바꾸지 않고 논문의 Feature Map만 차용한다고 범위를 정했다.
- Applies to: LUMI의 고정 feature-value 사전과 후속 상품·목표 Map 매핑. 현재 `consumer-17-v1` 실행 코드에는 아직 미적용
- Related Decisions: [0003](0003-consumer-shopping-prototype.md). 기존 17개 로컬 실행 계약의 기록은 보존하며 이번 결정으로 그 구현이 대체됐다고 보지 않는다.

## Context

[중간보고서](../sources/Team4_mid-term_report.pdf) 3.4–3.6은 목표·상품 Map의 공통 속성 비교와 피드백 흐름을 정하지만 전체 허용값은 정하지 않는다. 현재 코드는 이전 로컬 결정인 17개 사전을 사용한다. 사용자는 속성·허용값을 사후 확장하는 방식 대신 처음부터 고정된 사전을 요구했고, 선행연구의 속성 체계를 차용하기로 확정했다.

출처는 Park, H., Kim, S., Choi, Y., & An, H. (2025), *Application of the FEA consumer needs model in e-commerce: a conversational recommendation system for fashion products*, Fashion and Textiles, 12, 24이다. [논문 원문](https://doi.org/10.1186/s40691-025-00435-w)의 Table 1(PDF pp. 8–10)과 Table 2(PDF p. 10)를 차용한다.

## Decision

1. 상품정보(PI)는 **Type·Brand·Price·Color·Fit·Fabric·Detail의 7항목**, 소비자 요구(FEA)는 **Functional 8·Expressive 13·Aesthetic 9의 30개 태그**로 고정한다. 두 수준을 합쳐 37개의 동등한 상품 속성으로 취급하지 않는다.
2. 이름·허용값·분류와 승인 메타데이터의 정본은 [JSON 사전](../../output/feature-map/park-2025-feature-map.json)이다. [CSV](../../output/feature-map/park-2025-feature-map.csv)는 같은 목록의 표 형식이며, 사람이 읽는 적용 계약은 [확정 Feature Map](../shopping-memory-prototype.md#확정-feature-map)에 둔다. 영문 원문은 보존하고 한국어 표시명은 구분한다.
3. 상품 Map과 목표 Map은 같은 사전을 참조한다. 기존 대화·이미지 선택·부분 선택·관련 메모리를 여기에 매핑하고 대화 중 새 속성·허용값을 추가하지 않는다. 근거 부족은 미정/미확인으로 남긴다. 사용자 확인·별도 장기 활용 동의·현재 요청 우선 원칙을 유지한다.
4. 이 결정은 보고서가 정하지 않은 사전을 구체화한다. **기존 RQ·평가 계획·비교 조건·과제·설문·이미지 선택·메모리 흐름은 변경하지 않는다.** 이미지 효과를 분리하는 추가 실험이나 턴 감소 주장을 도입하지 않는다.
5. 원문 PI 값은 무신사 여성 바지 기준이다. 다른 의류 값이 원문에 포함됐다고 보거나 기존 연구 과제를 바지로 변경하지 않는다. 다른 품목의 실행 매핑은 아직 제공하지 않으며, 대화 중 허용값을 만들어 보완하지 않는다.
6. Brand 전체 419개 목록은 미공개이고 Price 경계 포함 방식·통화 코드는 Table 2만으로 확정할 수 없다. 이 누락을 임의로 복원하지 않는다. 사전 승인과 아직 미정인 실행 규칙을 구분한다.

## Alternatives

| 대안 | 판단 |
|---|---|
| 기존 17개 사전을 최종 사전으로 유지 | 현재 실행 계약으로 보존하되 이번 사용자 확정의 기준으로 사용하지 않음 |
| 자체 25개 재구성안 채택 | 속성 선택·통합·제외의 직접 근거가 부족하여 철회됨. 기존 Withdrawn 자료는 검토 이력으로 보존 |
| Park et al.의 PI/FEA 체계 차용 | 원문 이름·값·분류를 추적할 수 있어 채택. 원문 범위와 미공개 부분은 함께 기록 |

## Trade-offs

논문에서 실제 사용한 속성 체계를 출처와 함께 고정할 수 있다. 다만 이 조합이 LUMI 전체 품목의 최적 사전이거나 이미지 선택의 효율을 입증했다고 해석하지 않는다. 원문의 팬츠 중심 범위, 미공개 브랜드 목록, 가격 경계는 실행 적용 시 남은 제약이다.

논문 Fit은 바지 형태이며 Fabric은 섬유 원료다. 기존 17개 사전의 전체 핏·원단 종류와 이름만으로 치환할 수 없다. FEA는 소비자 요구 분류이므로 리뷰의 체감·사용자의 희망·확인된 상품 성능을 구분해야 한다.

## Consequences

문서와 사전의 승인 상태를 갱신한다. 원본 보고서 PDF·기존 승인 ADR 본문·연구 계획은 보존한다. 이번 작업은 문서 반영이며 실행 코드와 DB를 바꾸지 않는다.

후속 구현은 registry·추출·저장 payload·context·목표 검증·관찰 도구의 사전 참조를 함께 이관해야 한다. 기존 원문·값·근거·동의를 보존하고 의미가 다른 값의 자동 변환을 피한다. 이관 시 적절한 오프라인 회귀 검증과 가상 데모를 갱신하며 실제 상품·모델·사용자 효과 검증과 구분한다.
