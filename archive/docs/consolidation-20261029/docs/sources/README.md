# LUMI 개발 기준 자료

**2026-10-28 사용자 지정: [Team4_mid-term_report.pdf](Team4_mid-term_report.pdf)가 시스템·연구 설계의 source of truth다.** 이 안내는 원문 위치와 적용 범위를 연결하며 보고서를 대체하는 별도 설계 정본이 아니다.

## 원본과 보조 자료

| 자료 | 역할 | PDF 쪽수 | 바이트 | SHA-256 |
|---|---|---:|---:|---|
| [Team4_mid-term_report.pdf](Team4_mid-term_report.pdf) | 시스템·연구 설계 기준 | 20 | 737,007 | `97cdd6791d4aed737d3faae93d46e26ef112d06346ecef34b3a3c3af4b8a69f5` |
| [Team4_mid-term_presentation.pdf](Team4_mid-term_presentation.pdf) | 발표용 보조 자료 | 14 | 41,281,335 | `5b708cbef817a999fec1b1ee5ba0c2119ed7d07e9d08164b53146521bf1d2248` |

두 PDF는 기존에 인계된 원본을 보존한다. 쪽수는 표지·목차를 포함한 PDF 페이지다.

[Figma · LUMI.WEB · 298:2](https://www.figma.com/design/LAU2SC2gHCR1jlCh41K7PD/?node-id=298-2)는 화면 배치·조작을 구체화할 때 참고하는 UI 자료다. 보고서 3.7의 동작과 충돌하면 보고서를 우선하고 구현 전에 차이를 확인한다. 이번 정리에서 Figma의 현재 화면을 새로 검증하지 않았다.

## 확정 Feature Map의 출처

**2026-10-29 사용자 승인으로 Park et al. (2025)의 속성 체계를 LUMI의 고정 매핑 사전으로 차용한다.** 보고서가 구체화하지 않은 feature-value를 정한 결정이며, 시스템 흐름·RQ·평가 계획을 변경하지 않는다.

- Park, H., Kim, S., Choi, Y., & An, H. (2025). *Application of the FEA consumer needs model in e-commerce: a conversational recommendation system for fashion products*. Fashion and Textiles, 12, 24. [논문 원문](https://doi.org/10.1186/s40691-025-00435-w).
- Table 1, PDF pp. 8–10: FEA 소비자 요구 30개 태그(Functional 8·Expressive 13·Aesthetic 9).
- Table 2, PDF p. 10: 상품정보 7항목(Type·Brand·Price·Color·Fit·Fabric·Detail).
- [확정 사전 JSON](../../output/feature-map/park-2025-feature-map.json)은 원문 이름·허용값·분류와 승인 메타데이터를 관리한다. [CSV](../../output/feature-map/park-2025-feature-map.csv)는 같은 목록의 표 형식이다. 적용 규칙·원문의 미공개/미정 부분은 [실행 문서의 확정 사전](../shopping-memory-prototype.md#확정-feature-map), 결정 근거는 [ADR 0004](../decisions/0004-adopt-park-2025-feature-map.md)를 따른다.

원문의 상품정보 값은 무신사 여성 바지 기준이다. 다른 의류의 값이 원문에 포함됐다고 보거나, 미공개 브랜드 목록·가격 경계 규칙을 임의로 복원하지 않는다. 원문은 CC BY 4.0이며, 사전에 출처·라이선스·한국어 표시명 추가 사실을 기록했다.

## 읽을 위치

| 작업 | 보고서 위치 |
|---|---|
| 목표·연구 질문 | 1~2장 · pp. 3–4 |
| 입력 해석·장단기 메모리 | 3.2 · pp. 5–6 |
| 현재 요청에 관련된 기억 조회 | 3.3 · p. 6 |
| 목표 Item Feature Map·충돌 처리 | 3.4 · pp. 6–7 |
| 실제 상품 속성·필수 조건 필터·선호 랭킹 | 3.5 · p. 7 |
| 선택 이유·확인·메모리 갱신 | 3.6 · p. 7 |
| 온보딩·새 요청·이미지 탐색·저장/종료 UI | 3.7 · pp. 8–9 |
| 사용자 연구·측정·분석 계획 | 4~5장 · pp. 10–16 |
| 후속 구현·평가 | 6장 · p. 16 |
| 설문 원문 | 7장 · pp. 17–20 |

## 적용 원칙

- **설계는 보고서, 현재 구현은 코드·테스트·실행 문서로 확인한다.** 설계가 코드와 다르면 [구현 대응](../workflow.md)에 차이를 명시하고 담당 개발 작업에서 해소한다.
- 보고서는 전체 속성 사전·DB 스키마·보관 기간·조회 예산·모델·제품 스택을 확정하지 않는다. 속성 사전은 이후 사용자 승인인 [ADR 0004](../decisions/0004-adopt-park-2025-feature-map.md)로 구체화했다. 기존 코드의 17개 속성이나 로컬 운영 파라미터는 현재 프로토타입의 선택이며, 확정 사전으로의 이관은 아직 미구현이다.
- 목표 Item Feature Map은 이번에 찾을 옷의 조건이고 상품별 Item Feature Map은 실제 상품에서 확인한 속성이다. 허용값 사전이나 모델의 목표 추론을 실제 상품 관측으로 취급하지 않는다.
- 발표자료·Figma·이전 문서로 보고서의 요구사항을 덮어쓰지 않는다. 예전 후보 5개·2:1:2 전략, 독립 User Preference Map, 별도 Agent 구성은 새 필수 요구사항으로 승계하지 않는다.
- 보고서의 평가 계획·저충실도 UI는 구현 완료·평가 수행·효과 입증의 증거가 아니다. 연구 안내는 [master](../master.md), 실제 실행 계약은 [프로토타입 문서](../shopping-memory-prototype.md)를 따른다.

## 과거 자료와 결정

이전 LUMI HTML, RQ 검토안·구현 대응 기록, 개발 기준에서 제외했던 과제 PDF·이전 Figma 링크는 [archive](../../archive/README.md)에 보관한다. 당시 본문·승인·검증 기록을 보존하며 현재 개발 요구사항으로 사용하지 않는다. 과제 작성 브랜치 전체를 개발 브랜치로 가져오지 않는다.

[ADR 0001](../decisions/0001-memory-boundaries.md)·[0002](../decisions/0002-memory-prototype-storage.md)·[0003](../decisions/0003-consumer-shopping-prototype.md)은 현재 로컬 프로토타입의 동의·저장·삭제·추론 경계의 근거로 남긴다. 보고서가 구체화하지 않은 운영값을 폐기하거나 바꾸려면 실제 코드·데이터 영향과 새 결정을 함께 다룬다. 이번 정리에서는 실행 계약을 변경하지 않는다.

[ADR 0004](../decisions/0004-adopt-park-2025-feature-map.md)는 확정한 속성 사전과 후속 이관의 기준이다. 이전 ADR의 승인 본문과 원본 PDF는 보존한다.
