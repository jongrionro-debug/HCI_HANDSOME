# 0002 · 로컬 메모리 프로토타입의 저장·검증·조회

- Status: Accepted
- Date: 2026-10-13
- Related Issue: [#1](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/1)
- Approval: 2026-10-13 · 현재 채팅의 승인 질문(D01–D12·ADR 0001/0002·보관 기간·Python+SQLite 최소안)에 사용자가 **“권고안 전체 승인”**으로 응답했다.
- Related Decision: [0001](0001-memory-boundaries.md)

## Context

현재 저장소에는 실행 앱·제품 스택·DB가 없다. 보관 초안은 LLM 제안과 시스템 쓰기를 나누지만 명령별 부분 성공을 허용하고 조회/검색은 미정이다. 하나의 저장 화면에서 성공한 범위와 실제 상태가 달라지는 문제, 동시 수정·늦은 응답·재시도를 다루는 최소 기술을 정해야 한다.

## Decision

[메모리 설계](../../archive/docs/memory-design.md) D06–D09·D11의 최소안은 **Python 3.11 이상 단일 프로세스 메모리 모듈 + SQLite + JSON Schema 2020-12**다. 일반 제품 UI·인증·추천 모델 프레임워크는 선택하지 않는다.

SQLite는 별도 서버 없이 로컬 저장이 가능하고 Python 표준 `sqlite3` 인터페이스를 제공한다. SQLite 트랜잭션의 원자성을 item·event·성공 result 동시 반영에 사용할 계획이다. 이는 저장소 선택의 근거이며 이번에 DB 원자성을 검증했다는 뜻은 아니다. [Python 3.11 문서](https://docs.python.org/3.11/library/sqlite3.html), [SQLite 트랜잭션](https://www.sqlite.org/transactional.html).

모델은 후보·의도 제안만 만들고 시스템이 실제 입력·소유권·동의·버전·전이를 확인한다. 처음에는 가상/규칙 adapter로 실행하며 외부 모델을 기본 사용하지 않는다. 단일 UI 확정의 다중 actions를 한 배치로 검증·확정한다. 일부 성공은 제공하지 않는다. `user_id+batch_id`의 동일 본문 재시도는 최초 result, 다른 본문은 충돌이다. request/profile revision과 item version을 쓰기·응답 표시 전에 재검사한다.

조회는 소유권·요청·상태·기간·조건의 필터 뒤 결정적 key/태그 랭킹을 사용한다. 현재 단기의 명시 예외가 장기를 일시 대체하며 같은 우선순위 충돌은 보류한다. 관련성 초기 점수 3/2/1, 장기 12개·단기 20개·문자 예산 6,000을 승인된 초기값으로 사용한다. 별도 벡터 저장소·검색 서비스·공개 HTTP API는 최소안에 도입하지 않는다.

검증 자료는 [단일 스키마](../../archive/schemas/memory-contract.schema.json), [가상 사례](../../archive/schemas/examples/memory-cases.json), [검증기](../../archive/scripts/validate_memory_design.py)다. 스키마는 형식과 필드 간 제약, 정책 모델은 가상 전이/조회/실패 기대값을 검사한다. 동의 진위·자연어/이미지 판단은 사람이 만든 fixture oracle로 대신하며 실제 모델 품질과 구분한다. Draft 2020-12 validator와 format 검사를 사용한다. [JSON Schema 2020-12](https://json-schema.org/draft/2020-12), [jsonschema 검증 문서](https://python-jsonschema.readthedocs.io/en/stable/validate/).

삭제는 SQL 행 제거만으로 완료 선언하지 않는다. 후속 SQLite 구현은 `secure_delete=ON`, 지속 WAL·디스크 캐시를 쓰지 않는 최소 설정, 삭제 후 DB 정리와 journal/파생 파일 확인을 포함한다. SQLite 문서는 삭제 흔적 제거 방법과 제한을 설명한다. 완료의 범위는 시스템이 관리하는 DB/파일/캐시이며 저장매체·사용자 외부 사본의 복구 불가를 약속하지 않는다. 실데이터 수집·자동 백업 도입은 추가 운영 승인과 삭제 검증이 필요하다. [secure_delete](https://www.sqlite.org/pragma.html#pragma_secure_delete), [VACUUM](https://www.sqlite.org/lang_vacuum.html).

## Alternatives

| 대안 | 장점 | 선택하지 않은 이유 |
|---|---|---|
| JSON 파일만 저장 | 준비가 빠르고 읽기 쉬움 | 객체·이벤트·receipt 동시 쓰기, 동시 수정·삭제 복구를 직접 구현해야 함. fixture 교환 형식으로만 사용 |
| SQLite+Python | 로컬 실행·트랜잭션·운영 단순성 | 이번 최소안. 단일 프로세스·작은 가상 기억 집합으로 범위 제한 |
| PostgreSQL+별도 서버/API | 다중 사용자·운영 확장 | 아직 앱·동시 사용자 요구가 없고 인증/배포 경계가 늘어남 |
| 임베딩·벡터 검색 | 자유문 관련성 회수 가능 | 품질 평가·색인 삭제·외부 모델/서비스 비용이 추가됨. 구조 검색의 누락이 확인되면 별도 검토 |
| 모델 직접 DB 변경 | 구현 경로가 짧음 | 동의·소유권·멱등·전이 권한을 검증할 경계가 사라짐 |
| 명령별 commit | 일부 항목을 먼저 저장 가능 | 하나의 사용자 선택이 부분 반영되어 UI/재시도 의미가 복잡해짐 |

## Trade-offs

자유문 관련성이 낮거나 key 매핑이 불명확하면 질문이 더 필요할 수 있다. SQLite는 이 최소 규모의 선택이며 다중 서버 운영의 결정이 아니다. 전체 배치 실패는 성공 가능한 항목까지 재검토하게 하지만 실제 성공 범위가 명료하다. 삭제 후 저장소 정리에는 추가 시간·실패 복구가 필요하다.

JSON Schema를 통과한 제안도 내용·권한 검증을 통과해야 한다. 독립된 정책 모델의 fixture 통과는 실제 DB 트랜잭션이나 LLM 성능 증거가 아니다. 자동 백업·외부 모델·실제 참여자 정보는 이 최소안 범위 밖이다.

## Consequences

후속 모듈은 request 관리 → evidence/의도 → 정책/CAS/배치 → SQLite 저장 → 조회/결합 → 삭제/보관 → UI adapter·가상 연구 비교 순으로 구현한다. 각 단계의 입력·출력·테스트·오류·예정 파일과 명령은 [구현 계획](../../archive/docs/memory-implementation-plan.md)에 둔다. 이번 브랜치에는 제품 DB·외부 호출·API를 생성하지 않는다.

이번 승인으로 스키마 v0.2·운영 파라미터를 설계 기준으로 고정했다. fixture 검증은 수행했고 CI 연결은 후속 구현 계획이다. 실제 스택 확장은 새 근거·승인·ADR로 추적한다.
