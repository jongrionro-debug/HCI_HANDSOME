# 보고서·논문·설명 산출물

이 폴더는 `codex/reports-and-assignments` 브랜치에서 관리한다. 보고서·과제 제출을 위한 원고, 그림, 설명 페이지와 그림 생성 스크립트를 보존하며 이 브랜치를 `main`으로 병합하지 않는다.

## 자료 지도

| 자료 | 용도 |
|---|---|
| [시스템 디자인 본문 초안](lumi-memory-system-design/system-design-main-text-ko.md) | 사용자 제공 파이프라인에 맞춘 논문 본문 수준의 다섯 절과 그림 캡션 |
| [메모리 구현 설명 원고](lumi-memory-system-design/system-design-ko.md) | 기억 스키마·갱신·역할 분담을 포함한 중간보고서 원고 |
| [메모리 구조·사례 그림](lumi-memory-system-design/figure-1-lumi-memory.pdf) | 벡터 PDF. 같은 폴더에 SVG·PNG와 생성 스크립트 보존 |
| [시스템 파이프라인 그림](lumi-memory-system-design/figure-2-lumi-system-pipeline.pdf) | 벡터 PDF. 같은 폴더에 SVG·PNG 보존 |
| [연구용 전체 흐름 설명](lumi-research-implementation.html) · [원고](lumi-research-implementation.md) | 연구 프로토타입의 사용자 흐름·구현 범위·한계를 설명하는 페이지 |
| [과제 제출 자료](../Assignment/Readme.md) | 개발 기준에서 제외한 과제 PDF와 기존 Figma 링크 |

## 개발 브랜치와의 관계

시스템 구현·현재 설계 및 실행 계약은 `codex/lumi-research-loop`에서 관리한다. 기존 구현 설명 산출물은 해당 개발 브랜치의 2026-10-14~15 로컬 구현 상태를 바탕으로 작성했다. 이 보고서 브랜치는 공통 기반인 `main`의 `8c4387b`에서 분기했으므로, 같은 경로에 남아 있는 기반 코드·문서가 설명 당시의 미커밋 구현과 일치한다고 간주하지 않는다.

이 브랜치에 없는 개발 파일은 설명 자료에서 링크 대신 개발 브랜치 경로로 표시한다. 구현 사실과 당시 검증 기록은 개발 브랜치의 실제 코드·실행 계약과 함께 확인한다. 시스템 디자인 본문 초안은 설계 설명이며 구현 완료나 사용자 연구 효과를 입증하는 자료가 아니다.

새 보고서와 그림은 이 브랜치에 추가하고, 시스템의 동작이나 계약을 바꿀 때에는 개발 브랜치에서 별도로 작업한다. 과거 자료인 `archive/`와 시스템 정본인 루트 `LUMI_system_design.html`은 보고서 작업을 이유로 옮기거나 다시 작성하지 않는다.
