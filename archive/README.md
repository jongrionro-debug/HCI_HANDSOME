# 남긴 근거·재현 자료

현재 구현의 정본은 [docs/master.md](../docs/master.md), 결정 기록은 [docs/adr/](../docs/adr/)다. 이 폴더의 당시 설계·결과를 현재 구현이나 연구 효과의 근거로 확대하지 않는다.

| 남긴 자료 | 유지 이유 |
|---|---|
| [lumi-master-20261014.md](docs/lumi-master-20261014.md)·[lumi-workflow-20261014.md](docs/lumi-workflow-20261014.md) | 승인된 ADR 0001 본문이 직접 인용한 당시 맥락 |
| [memory-design.md](docs/memory-design.md)·[memory-implementation-plan.md](docs/memory-implementation-plan.md) | ADR 0001·0002가 승인 범위와 구현 순서의 근거로 인용 |
| [target-feature-inference-plan.md](docs/target-feature-inference-plan.md) | ADR 0003이 인용한 기존 사전과 축소 결정의 근거 |
| `schemas/`·`scripts/` | 위 v0.2 설계의 합성 사례·스키마·검증기와 실행 의존성 |
| [Assignment/](Assignment/) | 인계된 원본 과제 PDF와 출처 안내 |
| [artifacts/](artifacts/README.md) | 합성 실험 재현 입력·코드·결과, 영상과 원고·검증 근거 |

별도로 [과거 구현 지시문](../output/lumi-implementation-session-prompts.txt)은 ADR 0005의 승인 맥락을 보존하는 원문이며 현재 실행 절차가 아니다.

사용하지 않는 설명 HTML, 대체된 안내, 통합 전 문서·ADR 중복 사본은 삭제했다. 삭제 직전의 모든 파일 내용은 커밋 `1287063a442023c55e09c87c9299c991534c7424`와 일치함을 확인했다. 이전 파일은 `git show 1287063a442023c55e09c87c9299c991534c7424:원래/경로`로 확인하며 별도 보존 사본을 만들지 않는다.

남긴 문서의 본문은 당시 기록이며 상대 링크·실행 경로는 이동 전 위치 기준일 수 있다. 이번에 삭제한 파일을 직접 가리키던 링크는 해당 커밋의 파일로 연결했다. `scripts/check_repository.py`는 이 폴더를 제외하며, 보관 스키마·스크립트는 현재 테스트/CI에서 실행하지 않는다.
