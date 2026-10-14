# Archive

LUMI 정본 채택(2026-10-14) 이전의 StyleMate 시기 설계·계획·설명·검증 자료를 모아 둔 폴더다. **현재 작업 기준이 아니며 갱신하지 않는다.** 현재 시스템 설계는 [LUMI 시스템 설계 보고서](../LUMI_system_design.html), 문서 지도는 [README](../README.md)를 따른다.

- 파일은 원래 저장소 경로를 유지한 채 옮겼다(`docs/…` → `archive/docs/…`). 내부의 상대 링크·실행 경로는 이동 전 위치 기준이라 깨질 수 있다. 원래 맥락은 git 히스토리에서 확인한다.
- `scripts/check_repository.py`는 이 폴더를 검사하지 않는다. 보관 스크립트(`archive/scripts/`)는 현재 테스트·CI에서 실행하지 않는다.
- 내용의 StyleMate 이름, 당시 계약·결정·검증 결과는 그 시점의 기록이다. 현재 사실로 인용하지 않는다.

| 원래 위치 | 보관 내용 |
|---|---|
| `docs/archive/stylemate-workflow.*` → [docs/stylemate-workflow.md](docs/stylemate-workflow.md) | LUMI 이전 Figma 화면·흐름 |
| `docs/memory-design.md` · `docs/memory-implementation-plan.md` | 메모리 v0.2 설계와 Issue #1 구현 계획·검증 기록 |
| `docs/target-feature-inference-plan.md` | item65/outfit9 전체 목표 feature 확장 계획 |
| `docs/research-landscape.*` | 이전 RQ 기준의 선행 연구 조사 |
| [docs/master-before-lumi-cleanup.md](docs/master-before-lumi-cleanup.md) | 정리 직전 연구 기준 전문(2026-10-04 기존 RQ 비교·평가 포함) |
| `schemas/` · `scripts/validate_memory_design.py` · `scripts/requirements-memory-design.txt` | v0.2 JSON Schema·가상 사례와 설계 검증기 |
| `artifacts/` | StyleMate 설명 페이지·영상·자막과 Luna 합성 사전 실험 |
