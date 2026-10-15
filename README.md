# LUMI · HCI_HANDSOME

> **보고서·과제 전용 브랜치:** `codex/reports-and-assignments`. [원고·그림·설명 산출물](artifacts/README.md)과 [과제 자료](Assignment/Readme.md)를 관리한다. 시스템 개발은 `codex/lumi-research-loop`에서 진행하며, 이 브랜치를 `main`으로 병합하지 않는다. 아래 시스템 설명은 공통 기반의 문서 지도다.

**LUMI — Long&short-term User Memory with Image-selection.** 장기·세션 기억과 현재 요청, 이미지 선택을 활용해 자신의 패션 취향을 말로 정확히 설명하기 어려운 사용자도 적은 질문으로 선호를 발견하고 만족스러운 코디에 도달하도록 돕는 추천 에이전트 연구 프로젝트다.

## 시스템 파이프라인

[LUMI 시스템 설계 보고서](LUMI_system_design.html)가 **현재 시스템 설계 정본**이다. 다른 자료와 다르면 이 보고서를 우선한다.

```text
현재 요청 + Memory Layer(장기·세션) → LLM 선호 해석 → User Preference Map(확정·추론·Unknown)
→ Candidate Look 5개(기본 2:1:2) → Recommendation Engine(Product Feature Map 기반 실제 상품)
→ 이미지 선택(0~5개·부분 선택) → 필요 시 원탭 확인/이미지 비교 → 세션 선호 갱신·재추천 ↺
→ Agent 종료 제안 → 사용자 확정 → (선택) 장기기억 저장 동의
```

초기 LOOK 5개·2:1:2, 이유 가설 확인·이미지 비교 Fallback, Hybrid 종료 제안은 구현·사용자 실험으로 검증할 **설계 제안**이다. 완성된 제품이나 입증된 효과를 뜻하지 않는다.

## 문서 지도

| 문서 | 역할 |
|---|---|
| [LUMI_system_design.html](LUMI_system_design.html) | 시스템 설계 정본 |
| [docs/workflow.md](docs/workflow.md) | 보고서 단계별 현재 구현 대응과 남은 범위 |
| [docs/master.md](docs/master.md) | 연구 목적·문제 정의·RQ(Proposed) |
| [docs/shopping-memory-prototype.md](docs/shopping-memory-prototype.md) | 현재 메모리·context·목표 속성 실행 계약 |
| [docs/developer-memory-inspector.md](docs/developer-memory-inspector.md) | 개발자 관찰 도구 실행·한계 |
| [docs/decisions/](docs/decisions/) | 현재 프로토타입의 근거가 되는 ADR |
| [docs/engineering-workflow.md](docs/engineering-workflow.md) · [AGENTS.md](AGENTS.md) | 개발 절차·승인·검증 규칙 |
| [Assignment/Readme.md](Assignment/Readme.md) | 과제 제출 자료 안내 |

LUMI 이전(StyleMate 시기)의 설계·계획·설명 영상·사전 실험은 [archive/](archive/README.md)에 보관한다. 작업 기준으로 사용하지 않는다.

## 현재 구현

Python 3.11+·SQLite·표준 라이브러리로 Memory Layer의 기반(장·단기 메모리, 확인·별도 장기 활용 동의, 대상별 context)과 **17개 아이템 목표 속성**의 추론·검증을 구현했다. 개발자 관찰 도구는 Codex CLI로 실제 LLM을 호출한다. 오프라인 demo/rule과 가상 HTTP로 검증하는 Responses adapter는 이 호출과 구분한다.

**Candidate Look 설계, Product Feature Map/DB, 실제 상품 검색·코디 구성, 이미지·부분 선택, Decision Agent와 소비자 UI는 아직 구현하지 않았다.** 현재 목표 속성 출력은 User Preference Map의 일부를 준비하는 실행 기반이다. 코드의 `stylemate_memory` 패키지·CLI·환경 변수 이름은 이전 명칭을 유지하며, LUMI 이름 변경은 후속 작업이다.

| 경로 | 역할 |
|---|---|
| [src/stylemate_memory/](src/stylemate_memory/) | 메모리 저장·context·목표 추론·관찰 도구 |
| [tests/](tests/) | 오프라인 단위·SQLite·adapter 테스트 |
| [scripts/check_repository.py](scripts/check_repository.py) | 문서 링크·HTML 원문 쌍·양식 검사 |

## 실행과 검사

저장소 루트에서 Python 3.11 이상으로 실행한다. 아래 demo와 테스트는 실제 모델이나 참여자 자료를 사용하지 않는다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.cli demo --synthetic
PYTHONPATH=src python3 -m stylemate_memory.cli features
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/check_repository.py
git diff --check
```

개발자 관찰 도구는 기존 Codex 로그인·모델 권한이 필요하며 **실제 모델을 호출**한다. 기본 주소는 `http://127.0.0.1:8765`, DB는 OS 임시 폴더다. [상세 실행과 한계](docs/developer-memory-inspector.md)를 따른다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.inspector
```

현재 실행 계약은 코드와 실행 문서, 연구 기준은 `master.md`, 개발 절차는 `engineering-workflow.md`에서 관리한다. Commit·Push·원격 PR·배포는 명시적인 요청이 있을 때만 수행한다.
