# LUMI · HCI_HANDSOME

> **`jaehyun_work` 브랜치 안내** — main(`dd75945`)에서 갈라진 개인 개선 작업 브랜치다. main에 병합하지 않은 상태로 개선안(기능 F1~F12, 화면 U1~U9)의 구현만 따로 쌓는다.
>
> - 범위: graph 엔진(`STYLEMATE_ENGINE=graph`)의 추천 흐름·화면. 저장 계약(`store_v1.apply_batch`, 확인·동의 분리)은 바꾸지 않는다.
> - 반영: 기능 F1·F2·F3(설정, 기본 켜짐)·F4·F5·F8~F11, 화면 U1~U7·U9. 내용은 [project.md](docs/project.md#29cm-완전-채움-상품으로-실행)의 `jaehyun_work` 문단에 있다. 상의(`lumi-pi-v2-top`)로만 확인했다.
> - 팀 합의·ADR이 필요한 항목(F3 프로필 다시 쓰기 끄기, F12/U8 이미지 기반 온보딩, F7 수치 확정)은 합의 전까지 구현하지 않거나 설정으로 끌 수 있게 둔다.
> - 개발 중 기본 provider는 `fake`이고, 실제 DeepSeek 호출은 명시적으로 실행할 때만 한다.
> - 변경 내역은 `git log main..jaehyun_work`, main과의 차이는 `git diff main...jaehyun_work`로 확인한다. 이 안내 블록은 main 병합 전에 지운다.

LUMI는 장·단기 메모리와 이미지 선택·대화를 활용해 사용자의 평소 취향과 현재 상황을 함께 반영하는 패션 추천 에이전트 연구 프로젝트다.

현재 구현·동작·실행·검증의 유일한 문서 정본은 [docs/project.md](docs/project.md)다. 과거 결정과 승인·대체 관계는 [docs/adr/](docs/adr/), 개발 작업 규칙은 [AGENTS.md](AGENTS.md)에서 관리한다. 연구 설계 원문인 중간보고서와 현재 구현의 범위도 project.md에서 구분한다.

## 시작하기

- [현재 구현](docs/project.md#현재-구현과-실행): 소비자 서비스와 구현 범위
- [메모리 계약](docs/project.md#메모리-실행-계약) · [Feature Map](docs/project.md#feature-map): PI 7개 축·수집 데이터 기반 value 확정 방향과 현재 실행 사전
- [로컬 실행](docs/project.md#로컬-실행): 외부 DB·상품·이미지 설정과 시작 명령
- [검증](docs/project.md#오프라인-실행과-검증): 오프라인·브라우저 검사와 한계
- [연구와 평가](docs/project.md#연구와-평가): 보고서의 RQ·과제·측정 기준
- [다음 작업](docs/project.md#다음-작업): 미구현·미검증 범위

폐기한 설명 HTML·중복 문서는 Git 이력에서 확인한다. 실행 화면인 `src/stylemate_memory/consumer.html`·`inspector.html`은 앱 자원으로 유지한다.

## 검증

```sh
python3 scripts/check_repository.py
git diff --check
```

기능별 오프라인 검사·브라우저 검사와 실제 품질의 구분은 [현재 검증 안내](docs/project.md#오프라인-실행과-검증)를 따른다.

## 문서

[문서 안내](docs/README.md) · [현재 프로젝트](docs/project.md) · [작업 규칙](AGENTS.md) · [결정 기록](docs/adr/README.md)

작업 요청은 [Issue 템플릿](.github/ISSUE_TEMPLATE/task.yml), 변경·검증 결과는 [PR 템플릿](.github/pull_request_template.md)을 사용한다.
