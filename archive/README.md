# Archive

현재 [중간보고서](../docs/sources/Team4_mid-term_report.pdf) 기준에서 제외한 과거 설계·계획·과제·설명·검증 자료다. **현재 개발 기준이 아니며 본문을 갱신하지 않는다.** 원문 우선순위는 [자료 안내](../docs/sources/README.md), 현재 구현은 [workflow](../docs/workflow.md)를 따른다.

- 내용의 StyleMate/LUMI 이름, 당시 계약·승인·제안·검증 결과를 그 시점의 기록으로 보존한다. 현재 구현이나 평가 완료의 근거로 확대하지 않는다.
- 보관 문서의 상대 링크·실행 경로는 이동 전 위치 기준이라 깨질 수 있다. 원래 맥락은 Git 히스토리와 아래 원래 위치에서 확인한다.
- `scripts/check_repository.py`는 이 폴더를 검사하지 않는다. 보관 스크립트·스키마는 현재 테스트·CI에서 실행하지 않는다.

## 2026-10-28 보고서 기준 정리

아래 파일은 정리 시작 시의 기존 수정까지 포함해 그대로 보존했다. 활성 `docs/master.md`·`docs/workflow.md`는 현재 보고서 안내로 갱신했다.

| 원래 위치 | 보관 위치·내용 |
|---|---|
| `LUMI_system_design.html` | [docs/LUMI_system_design.html](docs/LUMI_system_design.html) · 이전 User Preference Map·Candidate Look·5개/2:1:2·Agent 설계 |
| `docs/master.md` | [docs/lumi-master-20261014.md](docs/lumi-master-20261014.md) · 이전 연구 목적·RQ 정렬 검토안 |
| `docs/workflow.md` | [docs/lumi-workflow-20261014.md](docs/lumi-workflow-20261014.md) · 이전 HTML 설계와 당시 구현 대응 |
| `Assignment/` | [Assignment/](Assignment/) · 개발 기준에서 제외했던 과제 PDF 두 개·이전 Figma 링크·안내 |
| `docs/shopping-memory-prototype.md` | [docs/shopping-memory-prototype-20261014.md](docs/shopping-memory-prototype-20261014.md) · 이전 실행 문서와 당시 검증/PR 기록 |
| `docs/developer-memory-inspector.md` | [docs/developer-memory-inspector-20261014.md](docs/developer-memory-inspector-20261014.md) · 이전 도구 문서와 실제 모델/화면 확인 기록 |

## 기존 보관 자료

| 원래 위치 | 보관 내용 |
|---|---|
| `docs/archive/stylemate-workflow.*` → [docs/stylemate-workflow.md](docs/stylemate-workflow.md) | LUMI 이전 Figma 화면·흐름 |
| `docs/memory-design.md` · `docs/memory-implementation-plan.md` | 메모리 v0.2 설계와 Issue #1 구현 계획·검증 기록 |
| `docs/target-feature-inference-plan.md` | item65/outfit9 전체 목표 feature 확장 계획 |
| `docs/research-landscape.*` | 이전 RQ 기준의 선행 연구 조사 |
| [docs/master-before-lumi-cleanup.md](docs/master-before-lumi-cleanup.md) | 2026-10-04 기존 RQ 비교·평가 기록 |
| `schemas/` · `scripts/validate_memory_design.py` · `scripts/requirements-memory-design.txt` | v0.2 JSON Schema·가상 사례와 설계 검증기 |
| `artifacts/` | StyleMate 설명 페이지·영상·자막과 Luna 합성 사전 실험 |

현재 코드에서 사용하는 동의·저장·삭제 결정의 ADR은 활성 `docs/decisions/`에 적용 범위를 명시해 남겼다. 그 본문이 인용하는 보관 자료는 당시 결정의 근거이며 새 요구사항의 정본이 아니다.
