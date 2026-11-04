# 0008 · 현재 구현 문서 단일화와 결정 기록 분리

- 후속 결정: [ADR 0009](0009-common-context-layout.md)이 공통 문서 경로·명명을, [ADR 0010](0010-derive-pi-values-from-collected-products.md)이 최종 PI value 정본 범위를 부분 대체한다. 나머지 결정은 유지한다.
- Status: Accepted (문서 경로·PI value 정본 범위는 후속 ADR에서 부분 대체)
- Date: 2026-11-04
- Related Work: 현재 대화의 문서 정리 요청
- Approval: 2026-11-04 (Asia/Seoul), 사용자가 과거 결정은 ADR 폴더에 두고 현재 구현의 source of truth는 하나의 문서로 관리하며 사용하지 않거나 최신 설명과 모순되는 HTML을 삭제하도록 요청함
- Applies to: 저장소의 구현 설명·결정 기록·폐기 문서 관리. 실행 코드·연구 설계·기존 승인 결정의 의미는 변경하지 않음
- Supersedes: 없음. 이전 문서의 포괄적 archive 보존 관행을 이번 문서 정리 범위에서 대체
- Superseded in part by: [ADR 0010](0010-derive-pi-values-from-collected-products.md). Decision 1의 Feature Map JSON은 논문 차용·현재 실행 사전의 정본으로 보존하고, 최종 PI value는 수집 데이터에서 별도로 확정한다.

## Context

master에 현재 실행 계약과 과거 작업 단계가 섞이고 별도 HTML·이전 문서 사본이 병존해 현재 구현을 판단하기 어려웠다. 결정 이유와 실행 상태를 서로 다른 역할로 관리해야 한다.

## Decision

1. 현재 구현·동작·실행·검증의 문서 정본은 [master](../project.md) 하나다. README는 진입 안내, AGENTS는 작업 규칙만 관리한다. 보고서는 연구 설계 원문, Feature Map JSON은 허용값·출처의 정본으로 유지한다.
2. 기존 `docs/decisions/`의 ADR 0001~0007은 본문을 그대로 `docs/adr/`로 옮긴다. 과거 결정의 승인·부분 대체 관계는 ADR에서 확인하며 현재 구현 여부는 master에서 확인한다.
3. 사용하지 않는 설명 HTML과 대체된 문서·통합 전 사본은 삭제한다. 삭제 전 파일 전체가 커밋 `1287063a442023c55e09c87c9299c991534c7424`의 내용과 일치함을 확인한다. 이전 내용은 Git 이력으로 복구하며 새 archive 사본을 만들지 않는다.
4. 실행 HTML 두 개는 앱 자원으로 유지한다. 원본 PDF·과제, 승인된 ADR의 직접 인용 근거(당시 구현 지시문 포함), 스키마 검증·합성 실험 재현 자료와 영상 원고/근거는 용도를 명시해 유지한다. 미승인 데이터 수집 제안은 현재 구현 정본과 구분한다.

## Alternatives

- Markdown과 설명 HTML을 병행: 같은 구현을 중복 갱신해야 하고 내용 불일치가 재발하므로 채택하지 않는다.
- 폐기 문서를 archive로 계속 이동: 현재 읽을 문서가 늘어나고 Git 이력과 중복되므로 채택하지 않는다.

## Trade-offs

현재 동작을 확인할 위치가 명확해진다. 과거 설명 페이지를 다시 읽으려면 Git 이력이 필요하다. 승인된 ADR의 본문 링크와 재현 자료가 요구하는 최소 근거는 작업 트리에 남는다.

## Consequences

master·README·AGENTS와 남긴 보관 안내의 참조를 함께 갱신한다. ADR의 기존 링크 앵커는 master의 현재 설명으로 연결한다. 이후 동작 변경은 master를 직접 고치고 승인된 ADR의 본문은 소급 수정하지 않는다. 문서·앱 자원 참조와 저장소 검사를 확인하며 문서 정리를 기능 또는 연구 효과 검증으로 확대하지 않는다.
