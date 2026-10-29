# 개발자용 Chat → Memory → Feature Map 관찰 도구

텍스트가 후보가 되고, 확인된 기억이 목표값에 반영되는 과정을 확인하는 로컬 개발 도구다. 시스템 설계는 [Team4_mid-term_report.pdf](sources/Team4_mid-term_report.pdf), 구현 대응은 [workflow](workflow.md)를 따른다. 도구의 Feature Map은 현재 아이템의 목표값이며 실제 상품의 속성이 아니다. 이미지 선택·상품 검색/추천·소비자 UI는 미구현이다. 세 패널을 보고서 3.7의 제품 화면으로 사용하지 않는다.

**확정 설계는 Park et al. (2025)의 PI 7항목·FEA 30개 태그이며, 이 도구에는 아직 적용되지 않았다.** 관찰 화면·추출 프롬프트·검증은 기존 17개 실행 사전을 사용한다. [확정 사전과 현재 실행의 차이](shopping-memory-prototype.md#확정-feature-map), 승인 근거는 [ADR 0004](decisions/0004-adopt-park-2025-feature-map.md)를 따른다.

## 실행

Python 3.11 이상과 기존 로그인된 Codex CLI가 필요하다. 추가 Python/프런트엔드 패키지는 없다. 이전에 사용자가 선택한 `gpt-6-luna`를 기본 모델로 사용한다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.inspector
```

브라우저에서 [로컬 관찰 도구](http://127.0.0.1:8765)를 연다. 다른 포트/DB/대상을 지정할 수도 있다.

```sh
PYTHONPATH=src python3 -m stylemate_memory.inspector \
  --port 8765 \
  --db /private/tmp/stylemate-inspector/memory.sqlite3 \
  --garment-type Pants \
  --model gpt-6-luna
```

기본 SQLite 경로는 OS 임시 폴더의 `stylemate-inspector/memory.sqlite3`다. DB를 저장소 밖에 둔다. Ctrl+C로 서버를 종료하며 자동 시작/예약 실행은 설치하지 않는다. CLI 로그인과 모델 이용 가능 여부는 사용 환경에 따른다. 호출 실패/제한/시간 초과를 모델 성공으로 표시하지 않으며 다른 모델이나 rule로 자동 전환하지 않는다.

## 세 패널에서 확인할 것

| 패널 | 표시/조작 |
|---|---|
| Chat | 현재 요청의 메시지, 실제 LLM 추출 답변/질문, 입력창. 샘플 버튼은 입력만 채우고 자동 전송하지 않는다. |
| Memory | 항목별 원문 내용·canonical 값·대상 selector·범위·상태·버전·근거. 후보/이번 요청/장기 항목을 나눈다. 내용 확인과 이번 적용, 이후 활용 동의, 철회를 명시 클릭한다. |
| Feature Map | [현재 실행 중인 17개 사전](shopping-memory-prototype.md#현재-실행-중인-17개-속성)의 값·지정/추론/미정/비적용/상충 상태·source ID·제약과 연산. 이미지에서 추출한 실제 상품 속성이 아닌 원하는 아이템의 목표값이다. |
| Processing trace / raw JSON | 단계별 입력·모델 원본 출력·검증·저장 batch·유효 context·최종 프로필. model/provider·호출 시도/완료 응답·단계도 표시한다. |

상단 대상 선택은 **현재 요청에서 관찰할 아이템**을 바꾼다. 다른 대상의 기억을 지우거나 색/핏을 옮기지 않는다. New request는 이전 단기를 이월하지 않고 유효 장기만 다시 조회한다. 기존 요청의 DB 항목을 삭제하는 버튼은 아니다. Infer는 동일 기억으로 목표값만 다시 생성한다.

## 실제 처리 경계

1. 입력과 현재 요청의 최근 대화/유효 활성 메모리·사전을 Codex에 전달해 구조화 후보를 받는다. 최신 문장의 원문 인용·허용값·대상·부정/강도/연산·범위 힌트와 조건별 인용을 검증한다.
2. 앱이 검증된 항목을 기존 `MemoryStore.apply_batch`로 **미확인 단기 후보**로만 저장한다. `baseline` 힌트도 장기 저장 승인이 아니다. 후보는 유효 목표 context에 들어가지 않는다.
3. 테스터가 `확인하고 이번 요청에 적용`을 누르면 내용 확인 이벤트로 활성화한다. `확인하고 앞으로도 사용 허용`은 내용 확인과 이후 활용 동의를 명시한 조작이며 confirm/promote를 원자적으로 실행한다. 모델이 동의·확정 상태·쓰기 명령을 만들지 않는다.
4. 현재 단기 조건을 사용자가 명확히 정정하면 모델은 같은 feature/대상의 기존 단기 ID를 교체 후보의 근거로 제안할 수 있다. 클릭 시 기존 버전을 다시 검사하고 후보 철회·기존 항목 replace를 하나의 batch로 처리한다. 장기를 모델이 직접 교체하지 않는다.
5. 실제 SQLite snapshot → 대상별 `build_context` → Codex 목표 제안 → 기존 `ShoppingApp`/`infer`의 값·대상·근거·직접 조건·최신성 검증을 거쳐 오른쪽에 표시한다. 격식 숫자의 뜻은 별도 scale로 모델에 제공한다. 이 단계는 메모리를 쓰지 않는다.

따라서 채팅 전송만으로 장기 취향이 저장되지 않는다. **후보 생성 → 테스터의 확인/동의 → 목표 반영**을 차례로 관찰한다. 모델은 빈 칸을 억지로 채우지 않으며 명시 색/핏의 Feature Map 반영은 기존 코드가 보존하는 직접 조건이다. LLM이 새로 추론한 값을 별도로 표시한다.

자연어 의도·조건 의미의 완전한 정확성을 코드로 증명하지 않는다. 원문 인용은 존재 검사이며 문장 해석이 옳다는 증거는 아니다. 조건 값은 해당 인용에 실제 등장하는 문자열로 제한한다. 사전에 없는 섬유 조성·미제공 사진 값은 저장하지 않고 질문/미지원 내용으로 남긴다. 날짜/기간 자동 해석과 여러 동일 종류 slot의 구분은 이번 입력 adapter에 없다.

## 모델 실행과 저장 범위

[Codex 공식 비대화형 실행 문서](https://learn.chatgpt.com/docs/developer-commands#codex-exec)를 참고해 `codex exec`를 일회성 JSON 변환 모델로 호출한다. 별도의 Responses API 키는 읽지 않는다. Codex CLI가 기존 로그인을 내부적으로 사용하며 앱은 자격 증명 파일·사용자 설정 내용을 직접 읽지 않는다.

- 호출마다 별도 임시 폴더·`--ignore-user-config`·읽기 전용 sandbox·`--ephemeral`·출력 schema를 사용한다. 모델용 shell/apps/browser/computer/hooks 기능을 끄고 예상 밖의 도구 항목이 나오면 결과를 적용하지 않는다. sandbox를 우회하는 옵션은 사용하지 않는다.
- 전달하는 내용은 테스트 대화·현재 기억과 사전이다. 이는 외부 모델 호출이다. 이 도구에서는 가상 입력으로 검증했으며 실제 참여자 정보/동의서/원시 연구 응답을 저장소에 넣지 않는다.
- SQLite에는 기존 계약의 최소 메모리 내용·근거/동의 참조·버전이 저장된다. 전체 채팅·모델 원본·trace·후보 scope/교체 설명은 프로세스 메모리에만 있고 종료 시 사라진다. 장기 항목의 최소 내용/근거는 재시작 후 DB에서 읽을 수 있지만 과거 대화와 review hint를 복원하는 기능은 없다.
- 서버는 127.0.0.1만 사용하고 packaged HTML/API만 제공한다. 임의 파일 탐색/공개 인증·배포 API가 아니며 단일 신뢰된 로컬 테스터를 가정한다. Host/Origin·JSON 형식·크기를 검사하고 쓰기 작업을 순차 실행한다.
- 모델 실패 뒤 이미 성공한 저장은 되돌렸다고 주장하지 않는다. 현재 기억을 표시하고 Feature Map은 unavailable로 두며, 실제 저장 상태를 trace에서 확인한다. 호출 중에는 쓰기 버튼이 비활성화된다.

로컬 테스트의 동의 클릭은 연구용 인증/동의 수집 시스템을 대신하지 않는다. 기존 [확인·동의·기간·철회 계약](shopping-memory-prototype.md)은 그대로 사용한다. 별도의 저장·삭제/장기 자동화 정책을 도입하지 않았다.

## 검증과 완료 범위

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/check_repository.py
git diff --check
```

기존 fixture 테스트는 후보만 저장, 확인/장기 동의, 오늘 예외→새 요청 복원, 현재 조건 교체와 장기 동의의 원자성, 원문/조건 위조 거부, stale 교체, 잘못된 모델값·호출 오류·timeout, 대상 격리와 fact 기반 추론, 철회/재시작·중복 호출, HTTP의 local-only 경계를 확인한다. 가상 gateway 테스트를 실제 모델 정확도 평가로 해석하지 않는다.

[2026-10-14 보관 기록](../archive/docs/developer-memory-inspector-20261014.md)에 당시 실제 모델·브라우저 확인과 테스트 결과를 보존했다. 과거 모델 성공·임시 파일 경로를 현재 실행 가능성이나 이번 검증 결과로 사용하지 않는다.

제품 소비자 UI, 이미지/상품 데이터·검색·추천 품질, 사용자 연구, 원격 CI·배포, 모든 브라우저/모델 조합은 이 도구의 검증 범위 밖이다. 현재 확인/동의·목표값 변화의 관찰을 제품·사용자 연구 효과로 확대하지 않는다.
