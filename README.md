# HCI_HANDSOME

메인 시스템의 기술 설계·코드·실행·검증 방법(HOW)을 관리하는 레포입니다.

## 문서 위치

| 위치 | 관리하는 내용 |
| --- | --- |
| [Team Notion](https://app.notion.com/p/607f30f64d9383e5af900109fb2d7277) | 프로젝트 목표·요구사항·연구·핵심 결정·일정·자료의 기준 원본(source of truth) |
| [1차 과제 Google Docs](https://docs.google.com/document/d/1MaW_9vJGbHlYNbxHaxpytrAZveWOvUVX6nPDb04W8zE/edit?tab=t.0) | 과제 본문·페르소나·시나리오·클레임 분석과 제출용 자료 |
| 이 레포 | 시스템 구성·인터페이스·데이터 흐름 등 기술 설계, 구현 코드, 실행·검증 방법 |

문서 위치는 관리 기준이며, 기존 자료의 외부 이전 완료를 뜻하지 않습니다. Notion에서는 과제 문서를 링크하고, 레포에서는 필요한 Notion 요구사항을 링크합니다. 같은 본문을 여러 곳에서 관리하지 않습니다.

## 현재 상태

현재 제품 코드와 실행·테스트 환경은 없습니다. 메인 시스템의 요구사항을 Notion에서 확인한 뒤 기술 설계와 구현을 추가합니다.

- [AGENTS.md](AGENTS.md): 문서 역할과 작업 규칙.
- [.github/ISSUE_TEMPLATE/task.md](.github/ISSUE_TEMPLATE/task.md): 구현 작업과 완료 기준.
- [.github/pull_request_template.md](.github/pull_request_template.md): 변경 이유와 검증 결과.

## 구현 문서 원칙

- 기술 설계가 생기면 `docs/`에 실제 시스템 구성·모듈 책임·인터페이스·데이터 흐름을 기록하고 관련 Notion 요구사항을 링크합니다.
- 구현을 시작하면 실제 코드 위치와 설치·실행·검증 명령을 이 문서에 추가합니다.
- 구현 작업과 디버깅은 코드·Issue·PR에 기록합니다.
- 교안 원본·과제 초안·연구 자료·중단된 탐색 자료는 레포에 보관하지 않습니다. 제품에서 사용하는 이미지와 테스트 데이터는 해당 코드와 함께 관리합니다.
