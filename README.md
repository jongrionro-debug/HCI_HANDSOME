# LUMI · HCI_HANDSOME

LUMI는 장·단기 메모리와 이미지 선택·대화를 활용해 사용자의 평소 취향과 현재 상황을 함께 반영하는 패션 추천 에이전트 연구 프로젝트다.

**개발 기준은 [Team4_mid-term_report.pdf](docs/sources/Team4_mid-term_report.pdf)다.** 시스템·연구 설계는 이 보고서를 따르고, 발표자료·Figma는 보조 자료로 사용한다. 원문 위치·쪽수·우선순위는 [자료 안내](docs/sources/README.md)에 있다.

## 설계 흐름

```text
사용자 입력 → Input-to-Memory Model → 단기 메모리
                              └→ 내용 확인 + 별도 이후 활용 동의 → 장기 메모리
현재 요청 + 관련 단기·장기 메모리 조회 → 목표 Item Feature Map
→ 상품별 Item Feature Map과 비교·검색 → 추천 → 선택·수정·필요한 확인 ↺
→ 사용자 최종 선택·종료 / 별도 장기 저장 선택
```

보고서 3장의 설계 요약이다. 현재 요청의 명시 조건이 기존 취향과 충돌하면 이번 목표에 우선 반영하고 장기 취향은 보존한다. 이미지 선택·반복 선택·최종 확정만으로 장기 메모리를 바꾸지 않는다.

## 문서 지도

| 경로 | 역할 |
|---|---|
| [docs/sources/README.md](docs/sources/README.md) | 보고서 원문·보조 자료·기준 적용 범위 |
| [docs/workflow.md](docs/workflow.md) | 보고서 단계별 구현 상태·차이·다음 메모리 개발 범위 |
| [docs/shopping-memory-prototype.md](docs/shopping-memory-prototype.md) | 현재 메모리 저장·context·목표 속성의 실행 계약 |
| [docs/developer-memory-inspector.md](docs/developer-memory-inspector.md) | 개발자 관찰 도구 실행·모델 호출·한계 |
| [docs/master.md](docs/master.md) | 보고서의 RQ·평가 계획 안내 |
| [docs/decisions/](docs/decisions/) | 기존 로컬 프로토타입의 결정 근거 |
| [AGENTS.md](AGENTS.md) · [docs/engineering-workflow.md](docs/engineering-workflow.md) | 작업 원칙·개발 및 검증 절차 |
| [archive/](archive/README.md) | 이전 설계·RQ·과제·설명 자료. 개발 기준에서 제외 |

## 현재 구현과 다음 작업

Python 3.11+·SQLite·표준 라이브러리로 장·단기 메모리 저장, 확인·별도 장기 활용 동의, 요청/아이템/상황별 context, **17개 아이템 목표 속성**의 추론·검증을 구현했다. 개발자 관찰 도구에는 Codex CLI를 통한 텍스트 후보 추출과 수동 확인이 연결돼 있다.

**보고서 전체 시스템은 아직 구현되지 않았다.** 자유로운 취향 표현과 원문 맥락의 지속 보존, 이미지 선택 근거, 실제 상품 속성·검색, 추천/피드백 통합, 소비자 UI가 남아 있다. 다음 개발은 [메모리 개발의 출발점](docs/workflow.md#다음-메모리-개발의-출발점)에서 시작한다. 기존 Python 패키지·CLI·환경 변수의 `stylemate_memory`/`STYLEMATE_` 이름은 호환성을 위해 유지한다.

| 경로 | 역할 |
|---|---|
| [src/stylemate_memory/](src/stylemate_memory/) | 저장·context·목표 추론·개발자 관찰 도구 |
| [tests/](tests/) | 오프라인 단위·SQLite·가상 모델/HTTP 테스트 |
| [scripts/check_repository.py](scripts/check_repository.py) | 문서 링크·HTML 내장 원문·템플릿 검사 |

## 실행과 검증

저장소 루트에서 Python 3.11 이상으로 실행한다. 아래 명령은 합성 입력과 가상 adapter를 사용하며 실제 모델을 호출하지 않는다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.cli demo --synthetic
PYTHONPATH=src python3 -m stylemate_memory.cli features
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/check_repository.py
git diff --check
```

개발자 관찰 도구는 채팅 전송·추론·확인 등의 조작에서 **실제 외부 모델을 호출**한다. 실행 방법과 호출 시점은 [관찰 도구 문서](docs/developer-memory-inspector.md)를 따른다. 기본 주소는 `http://127.0.0.1:8765`, DB는 저장소 밖 OS 임시 폴더다.

브랜치 관리는 사용자가 맡고 Codex는 현재 체크아웃에서 로컬 작업을 수행한다. Commit·Push·PR 생성·병합·배포는 요청 범위에서만 진행한다.
