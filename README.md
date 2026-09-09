# HCI_HANDSOME

코드와 구현 방법(HOW)을 관리하는 작업 공간입니다. 프로젝트 목표·요구사항·연구·핵심 결정·일정(WHY / WHAT / WHEN)은 [Team Notion](https://app.notion.com/p/607f30f64d9383e5af900109fb2d7277)에서 관리합니다.

현재 제품 코드와 실행·테스트 환경은 없습니다. 구현을 시작할 때 실제 코드 위치, 설치·실행·검증 명령과 필요한 제약만 이 문서에 추가합니다.

- `scripts/import_lectures.py`: 기존 교안 복사 유틸리티. 아래 사용법을 참고합니다.
- `.github/`: 구현 작업 Issue와 PR 양식.
- [AGENTS.md](AGENTS.md): repo와 Notion을 확인하는 최소 규칙.

구현 작업과 debugging은 코드·Issue·PR에 기록합니다. 요구사항이나 프로젝트 결정이 필요하면 해당 Notion 페이지를 링크하고 내용을 복제하지 않습니다.

## 교안 복사 유틸리티

Python 3.8 이상에서 실행합니다. Notion에 수동 첨부할 파일을 repo 밖의 지정 폴더로 복사합니다. 하위 구조를 유지하고 기존 파일을 덮어쓰지 않습니다. Notion 업로드는 수행하지 않습니다.

```sh
python3 scripts/import_lectures.py '/교안/원본' '/repo-밖/첨부-준비'
```

동일 파일은 건너뛰며 다른 내용의 동명 파일은 유지하고 종료 코드 1을 반환합니다. 인자 오류는 종료 코드 2입니다. 이전의 인자 1개 사용법은 더 이상 지원하지 않습니다.
