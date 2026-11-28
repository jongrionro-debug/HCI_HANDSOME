# LUMI · HCI_HANDSOME

LUMI는 장·단기 메모리와 이미지 선택·대화를 활용해 사용자의 평소 취향과 현재 상황을 함께 반영하는 패션 추천 에이전트 연구 프로젝트다.

현재 구현·동작·실행·검증의 유일한 문서 정본은 [docs/project.md](docs/project.md)다. 과거 결정과 승인·대체 관계는 [docs/adr/](docs/adr/), 개발 작업 규칙은 [AGENTS.md](AGENTS.md)에서 관리한다. 연구 설계 원문인 중간보고서와 현재 구현의 범위도 project.md에서 구분한다.

## 시작하기

- [현재 시스템](docs/project.md#현재-시스템): graph 엔진 흐름·구현 범위·질문 루프
- [메모리 계약](docs/project.md#메모리-실행-계약) · [Feature Map](docs/project.md#feature-map): PI 축과 실행 사전 `lumi-pi-v5.1`(상·하의·아우터·스커트), FEA 30개 태그
- [로컬 실행](docs/project.md#로컬-실행): 외부 DB·상품·이미지 설정과 시작 명령
- [검증](docs/project.md#오프라인-실행과-검증): 오프라인·브라우저 검사와 한계
- [연구와 평가](docs/project.md#연구와-평가): 보고서의 RQ·과제·측정 기준
- [다음 작업](docs/project.md#다음-작업): 미구현·미검증 범위

폐기한 설명 HTML·중복 문서와 지운 실행 경로는 Git 이력에서 확인한다. 실행 화면인 `src/stylemate_memory/consumer.html`은 앱 자원이다.

## 검증

```sh
python3 scripts/check_repository.py
git diff --check
```

기능별 오프라인 검사·브라우저 검사와 실제 품질의 구분은 [현재 검증 안내](docs/project.md#오프라인-실행과-검증)를 따른다.

## 문서

[문서 안내](docs/README.md) · [현재 프로젝트](docs/project.md) · [작업 규칙](AGENTS.md) · [결정 기록](docs/adr/README.md)

작업 요청은 [Issue 템플릿](.github/ISSUE_TEMPLATE/task.yml), 변경·검증 결과는 [PR 템플릿](.github/pull_request_template.md)을 사용한다.
