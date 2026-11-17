# 0011 · 실제 모델 provider로 DeepSeek API를 사용한다

- Status: Accepted
- Date: 2026-11-12
- Related Work: 현재 대화의 작업 현황 정리·user study 전 남은 작업 반영 요청
- Approval: 사용자가 “딥시크 api로 할거야 luna 말고”라고 정함
- Supersedes: [ADR 0005](0005-evidence-linked-memory.md) 결정 8의 “명시적 OpenAI Responses 설정의 기본 모델 후보 gpt-6-luna” 범위만 부분 대체. 기본 fake·provider 자동 fallback 금지·실제 호출의 별도 승인은 유지

## 맥락

기존 코드는 OpenAI Responses adapter와 기본 모델 gpt-6-luna만 실제 provider로 지원한다. 사용자는 실제 모델 평가와 user study에서 gpt-6-luna 대신 DeepSeek API를 사용하기로 정했다.

## 결정

1. 실제 모델 provider는 **OpenCode Go 구독으로 접근하는 DeepSeek 모델**이다(사용자 확정: “open go 기반 딥시크”). DeepSeek 직접 API는 쓰지 않는다. 기존 OpenAI 어댑터는 호환 경로로 남기되 새 평가에는 사용하지 않는다.
   구현: `OpenCodeGoChatGateway`(OpenAI 호환 chat/completions, JSON 모드, 스키마는 시스템 메시지에 명시). `--provider opencode-go`, 키는 `OPENCODE_API_KEY`, 기본 모델 `deepseek-v4.1-flash`(비용·한도상 Pro보다 여유가 큼). **endpoint는 기본값 없이 명시해야 한다.** 2026-11-12 합성 입력 1건 실호출로 확인한 사항: `https://opencode.ai/inference/go/openai/v1/chat/completions`와 `https://opencode.ai/zen/go/v1/chat/completions` 모두 HTTP 200, Bearer 인증과 `response_format: json_object`가 동작했고 `deepseek-v4.1-flash`로 응답했다. 구현 gateway로도 JSON 변환 1건이 성공했다. 응답에는 `reasoning_content`와 reasoning 토큰이 포함되며 `max_tokens`에 합산되므로(1건에서 완성 토큰 85개 중 70개) 긴 추출은 `max_output_tokens`(기본 1200) 부족으로 `provider_incomplete`가 날 수 있다. 공식 문서 확인 항목: 모델명(V4.1 Flash·V4 Pro)·한도·요금, `x-opencode-session` 헤더·고유 User-Agent 권고, DeepSeek 사용에 Privacy의 Global 리전 선택 필요. 이 1건은 연결 확인이며 한국어 추출·가설 품질은 별도 평가(아래)로 다뤘다.
2. 기본 provider는 계속 fake이며 provider 자동 fallback은 하지 않는다. 실제 호출은 사용자가 요청한 범위에서만 실행하고 키는 로컬 환경에서만 읽는다. 키를 CLI 인자·파일·로그에 넣지 않는다.
3. DeepSeek adapter는 `ModelGateway`의 `complete/extract/propose` 경계를 유지한다. 출력 형식 보장 방식이 OpenAI의 strict `json_schema`와 다를 수 있으므로, 응답은 기존처럼 JSON 형식·인용·alias·사전·대상 검증을 모두 통과해야 하며 모델 출력만으로 확인·동의·쓰기 command를 만들지 않는다.
4. 사용자 ID·raw DB·동의 원문을 보내지 않는 최소 입력 원칙과 안전한 오류 이름은 유지한다. 모델 이름·endpoint·요금·데이터 취급 조건은 구현 시점에 공식 문서로 확인한다.

## 대안

- gpt-6-luna(OpenAI Responses) 유지: 사용자가 사용하지 않기로 정해 채택하지 않는다.
- 여러 provider 자동 전환: 결과 비교·재현이 어려워지고 기존 “자동 fallback 금지”와 충돌해 채택하지 않는다.

## 영향

DeepSeek adapter·settings(`--provider`, 키·모델 환경변수)·테스트가 아직 없다. 구현 전까지 실제 모델 평가는 시작할 수 없다. 한국어 추출·선택 이유 해석·가설 품질은 DeepSeek로 새로 평가해야 하며 fake transport 통과를 실제 품질로 보고하지 않는다. 구독 사용량 한도(자료상 5시간·주·월 한도)가 있어 참가자 수·세션 수에 맞는지 확인해야 한다. 참가자 입력이 OpenCode를 거쳐 외부 API로 전송되므로 동의서·안내문에 해당 사실과 보관·학습 사용 조건을 반영해야 한다.

현재 구현 상태와 남은 범위는 [project.md](../project.md)에서 관리한다.

## 첫 한국어 추출 평가 (2026-11-12, 합성 발화 16개×2회, deepseek-v4.1-flash)

사용 가능한 후보가 나오는지 보기 위한 소규모 탐색이며 통계적 결론이 아니다. 발화는 합성이고 참가자 자료를 쓰지 않았다. 원시 결과는 저장소 밖에 있다. `max_output_tokens`는 4000으로 실행했다.

- **검증 통과 20/32(62.5%).** 실패 12회는 `provider_invalid_response` 6, `invalid_extraction` 4, `provider_incomplete` 2였다. 통과한 호출에서 기대한 후보는 24개 중 23개가 나왔다.
- **`invalid_extraction`:** 모델이 검증 규칙을 어겼다. 상황(situation) 후보에 `polarity=indifferent`를 쓰거나(상황은 prefer/soft만 허용), 상황 후보에서 `fact`를 null로 두거나, 이미지 선택만 있는데 `explicit`를 붙였다. 지시문에 이 제약을 명시하면 줄 가능성이 크지만 아직 시도하지 않았다.
- **`provider_incomplete`/길이 초과:** reasoning 토큰이 `max_tokens`를 대부분 차지한다(응답 한 건에서 2,776토큰 중 2,381). 길이가 긴 발화(출근 상황, 선택+이유)는 4000에서도 `finish_reason=length`로 잘렸다.
- **`provider_invalid_response` 6회는 원인을 확인하지 못했다.** 같은 입력(c01)을 다시 3회 돌리자 모두 성공했고 같은 형식의 응답은 정상 해석됐다. 일시적인 provider 응답 문제일 수 있다. 응답 본문을 보관하지 않는 설계 때문에 이 오류의 세부 원인은 로그에 남지 않는다.
- **지연:** 성공 호출의 중앙값 약 19초, 최대 약 55초(reasoning 때문). 실시간 사용성 평가에 영향이 크다.
- **의미 품질:** 와이드핏·스키니 회피·네이비/블랙·린넨+구김·청바지 대신 슬랙스·가격 상한(Price를 숫자로 매핑하지 않음)·사전 밖 브랜드(Brand 매핑 없음)·프롬프트 인젝션 무시는 기대대로 나왔다. 일부 선호에 `strength=hard`를 부여한 경우가 있었고(가격 케이스 2회째), "아무거나 좋아요"에서는 `indifferent` 후보가 만들어졌다. 이는 후속 확인 화면에서 사용자가 걸러야 하는 후보다.
- **후속 조치 후보:** (1) 지시문에 situation·selection-only 제약을 명시 (2) `max_output_tokens` 상향, 필요 시 provider가 허용하는 reasoning 조절 확인 (3) `provider_invalid_response` 재현·원인 확인 (4) 일시 오류에 한해 재시도 정책 검토(자동 provider 전환은 하지 않음) (5) 발화·반복 수를 늘린 재평가.

## 보강 후 재평가 (2026-11-12, 같은 합성 16개×2회)

| 단계 | 검증 통과 | 성공 호출 중앙 지연 | 주요 실패 |
|---|---|---|---|
| 첫 평가 | 20/32 | 약 19초 | provider 응답 6, 검증 규칙 위반 4, 길이 초과 2 |
| 지시문 보강+토큰 8000 | 20/32 | 약 16초 | provider 응답 12(검증 규칙 위반·길이 초과는 0) |
| thinking 끔 | 26/32 | 약 5초 | 검증 규칙 위반 6(Brand 매핑, 값 없는 PI binding) |
| binding 규칙 보강 | **31/32** | **약 3초(최대 6초)** | 검증 규칙 위반 1(c09 2회째) |

- **`provider_invalid_response`의 원인을 확인했다.** OpenCode Go가 reasoning이 켜진 긴 응답(약 17 KB)을 약 37% 확률로 본문 중간에서 끊었다(`Content-Length`보다 적게 도착, `IncompleteRead`). `Connection: close`·`Accept-Encoding: identity`로도 해결되지 않았다. 요청에 `thinking: {"type":"disabled"}`를 넣으면 reasoning 토큰 0, 본문 약 3 KB, 3회 모두 정상이었다. `reasoning_effort: low`는 효과가 없었고, `stream: true`는 응답이 정상 도착하나 약 200 KB로 늘어 채택하지 않았다.
- **결정:** `OpenCodeGoChatGateway`는 기본 `thinking=False`(요청에 `thinking: disabled`)이다. 대신 모델의 규칙 준수가 떨어져 지시문에 코드가 검사하는 제약을 명시했다(상황 후보 형식, 인용, `explicit`/`inferred`, `indifferent`·`hard` 사용 조건, PI binding에는 사전 값 필수, Brand·숫자 Price binding 금지).
- **품질(통과 31회):** 기대한 후보가 모두 나왔고(36/36), 나오면 안 되는 후보(가격 수치 매핑, Brand 매핑, 인젝션 반영, 근거 없는 회피·hard, 의미 없는 발화의 후보)는 없었다. 남은 실패 1건은 c09의 한 후보가 검증 규칙을 어긴 것이다.
- **한계:** 표본은 합성 16개×2회이며 같은 발화로 지시문을 고쳐서 과적합했을 수 있다. 새 발화·참가자 말투로 다시 평가해야 한다. 일시 오류 재시도 정책은 이번에 필요하지 않아 넣지 않았다. 선택 이유 해석과 FEA→PI 가설 품질은 아직 평가하지 않았다.
