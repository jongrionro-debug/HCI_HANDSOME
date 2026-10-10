# StyleMate · HCI_HANDSOME

StyleMate는 평소 취향을 유지하면서 고객 미팅·발표 등 현재 상황에 맞게 코디를 조정하도록 돕는 대화형 추천 연구 프로젝트다. 사용자가 기본 취향과 이번 요청의 조건을 구분해 확인·수정하고, 필요한 정보에 따라 텍스트 질문과 이미지 선택을 제공하는 상호작용을 연구한다.

## 현재 상태와 기술 스택

- 연구 문제와 RQ1·RQ2는 [연구 기준](docs/master.md)에 정의되어 있다.
- [시스템 동작 설계](docs/workflow.md)는 Figma 화면에서 확인한 구성, 구현 제안, 미정 사항을 구분한다. 실행 중인 앱의 명세로 해석하지 않는다.
- 현재 저장소에는 실행 앱, API, 데이터베이스, 패키지 매니페스트, 제품 테스트가 없다. 제품 기술 스택도 확정되지 않았다.
- 기존 산출물은 Markdown과 HTML 문서다. HTML에는 CSS·JavaScript와 Markdown 원문이 포함되어 있으며, 생성기 표기는 `Answer me with HTML 0.4.6`이다. 재생성 도구와 명령은 저장소에 포함되어 있지 않다.
- 개발 절차 검증에는 Python 3.11 이상과 GitHub Actions를 사용한다. 제품 스택 선택은 관련 Issue에서 제안·승인하고 필요한 경우 ADR로 기록한다.

## 문서와 폴더

| 경로 | 역할 |
|---|---|
| [AGENTS.md](AGENTS.md) | Codex의 작업·승인·검증 규칙 |
| [docs/engineering-workflow.md](docs/engineering-workflow.md) | Issue → 계획 → 구현 → 테스트 → PR → 리뷰 → 병합 절차 |
| [docs/master.md](docs/master.md) | 확정된 연구 문제와 RQ |
| [docs/workflow.md](docs/workflow.md) · [HTML](docs/workflow.html) | 제품의 화면·상태 흐름과 구현 제안 |
| [docs/research-landscape.md](docs/research-landscape.md) · [HTML](docs/research-landscape.html) | 선행 연구 조사와 평가 제안 |
| [Assignment/Readme.md](Assignment/Readme.md) | 과제 자료의 사용 범위. 이 문서가 제외한 PDF는 개발 기준으로 사용하지 않는다. |
| [Assignment/Figma.url](Assignment/Figma.url) | 기존 디자인 참조 |
| [.github/ISSUE_TEMPLATE/](.github/ISSUE_TEMPLATE/) | Feature Request·Bug Report 입력 양식 |
| [.github/pull_request_template.md](.github/pull_request_template.md) | 변경·검증·위험·리뷰 기록 |
| [.github/workflows/repository-checks.yml](.github/workflows/repository-checks.yml) | 저장소 문서·워크플로 구성 검사 CI |
| [scripts/check_repository.py](scripts/check_repository.py) | 같은 검사를 로컬에서 실행하는 도구 |

Markdown을 문서 내용의 정본으로 사용한다. 대응 HTML이 있으면 같은 작업에서 본문과 내장 원문을 함께 갱신하고 브라우저로 확인한다. 개발 절차는 `engineering-workflow.md`, 제품 동작 설계는 `workflow.md`에서 관리한다.

## 개발 시작

1. GitHub에서 Feature Request 또는 Bug Report를 작성하고 검증 가능한 Acceptance Criteria를 정한다.
2. GitHub Desktop에서 최신 기준 브랜치를 확인하고 `codex/<Issue번호>-<설명>` 작업 브랜치를 준비한다.
3. Codex에 Issue 내용과 관련 문서를 전달한다. Codex는 영향받는 파일·구현 계획·테스트 계획을 제시한 뒤 구현한다. 중요한 설계 변경은 사용자 승인 후 진행한다.
4. 테스트와 diff 검토를 마치면 사용자가 GitHub Desktop에서 Commit·Push를 수행하고 GitHub에서 PR을 연다.
5. Codex 리뷰와 사용자 검토를 반영한 최신 변경을 다시 검증하고, 사용자가 병합한다.

단계별 완료 기준, ADR 기준, 리뷰 요청 예시는 [개발 워크플로](docs/engineering-workflow.md)를 따른다.

## 로컬 검사

저장소 루트에서 실행한다. 추가 Python 패키지는 필요하지 않다.

```sh
python3 scripts/check_repository.py
git diff --check
```

검사 범위와 한계는 [테스트 절차](docs/engineering-workflow.md#4-testing)에 설명되어 있다. 제품 기능 테스트와 HTML 화면 검토는 별도로 수행한다.

## GitHub 적용 상태

Issue·PR 양식과 CI 정의는 저장소 파일로 제공한다. GitHub에서의 활성화에는 사용자의 Commit·Push 및 기본 브랜치 반영이 필요하다. 원격의 Actions 실행 결과, 브랜치 보호, 권한·요금제 설정은 이번 로컬 작업에서 확인하거나 변경하지 않았다.

브랜치 보호로 PR과 검사 통과를 필수화하는 방법 및 1인 개발의 리뷰 제한은 [최초 적용](docs/engineering-workflow.md#최초-적용과-github-설정)에 정리되어 있다.
