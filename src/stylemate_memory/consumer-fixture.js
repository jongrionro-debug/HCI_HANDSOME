/** E1 UI-only simulator. No storage, HTTP, model, catalog or trusted events.
 * Public state/command results use contracts.py's ConsumerService boundary.
 * Synthetic pictures are colored test regions, never product photographs.
 */
const copy = value => structuredClone(value);
const ref = (type, id, version = 1) => ({ type, id, version });
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const fingerprint = command => JSON.stringify([
  command.contract_version, command.request_id, command.action,
]);
export const FIXTURE_SCENARIOS = {
  normal: "기본 흐름", pending: "접수 후 해석 대기", model_error: "접수 후 모델 오류",
  stale: "오래된 후보", no_results: "상품 없음", no_images: "이미지 없음",
  broken_images: "이미지 읽기 실패", running: "처리 중", blocked: "조건 확인 필요",
};

function picture(name, color) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="360" height="450" viewBox="0 0 360 450">
    <rect width="360" height="450" fill="#eeece6"/>
    <rect x="55" y="44" width="250" height="130" rx="8" fill="#dad4c4"/>
    <rect x="55" y="190" width="118" height="200" rx="8" fill="${color}"/>
    <rect x="187" y="190" width="118" height="200" rx="8" fill="${color}"/>
    <text x="180" y="424" text-anchor="middle" font-family="sans-serif" font-size="15" fill="#545b60">SYNTHETIC ${name}</text>
  </svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

export function createFixtureAdapter({ delay = 180, scenario = "normal" } = {}) {
  let serial = 0;
  let stateVersion = 1;
  let profileRevision = 0;
  let current = null;
  let selectedScenario = scenario;
  let longMemories = [];
  const sessions = new Map();
  const receipts = new Map();
  const trace = [];
  const id = prefix => `fixture-${prefix}-${++serial}`;
  const initial = () => ({
    contract_version: "lumi-memory-v1", state_version: stateVersion,
    request: null, requests: [], expected: null, phase: "onboarding", operation: "idle",
    memories: copy(longMemories), cards: [], reviews: [], questions: [], error: null,
  });

  function meaning(content, target, scope = "short_term") {
    return {
      kind: "preference", content, fact: null,
      selector: { garment_type: target.garment_type, slot_id: target.target_id },
      conditions: {}, polarity: "prefer", strength: "soft", valid_from: null,
      valid_until: null, scope,
    };
  }
  function addMemory(session, text) {
    const memory = {
      ref: ref("memory", id("memory")), content: text, scope: "short_term",
      confirmed: false, status: "candidate",
    };
    session.state.memories.push(memory);
    session.meanings.set(memory.ref.id, meaning(text, session.state.request.targets[0]));
  }
  function cards(session) {
    session.round = ref("round", id("round"));
    session.set = ref("candidate_set", id("set"));
    return ["A", "B", "C"].map((name, index) => ({
      candidate_id: id(`card-${name}`), target_id: session.state.request.targets[0].target_id,
      product_id: `synthetic-${name}`, product_map_version: 1, image_id: index === 2 ? null : `synthetic-image-${name}`,
      image_version: index === 2 ? null : 1, position: index,
      title: `합성 비교 ${name}`, image_url: index === 2 ? null : picture(name, index === 0 ? "#354a63" : "#b9a789"),
    }));
  }
  function expected(session) {
    const s = session.state;
    s.expected = {
      request_revision: s.request.revision, profile_revision: profileRevision,
      object_versions: [session.round, session.set, session.feedback,
        ...s.memories.map(memory => memory.ref), ...s.reviews.map(review => review.ref),
        ...s.questions.map(question => question.ref)].filter(Boolean).map(copy),
    };
  }
  function advance(session) {
    stateVersion += 1;
    session.state.state_version = stateVersion;
    session.state.request.revision += 1;
    expected(session);
  }
  function applyScenario(session) {
    const s = session.state;
    if (s.request.status !== "open") return;
    s.error = null;
    s.operation = session.pending ? "interpretation_pending" : "idle";
    if (selectedScenario === "stale") s.operation = "stale";
    if (selectedScenario === "blocked") s.operation = "blocked";
    if (selectedScenario === "running") s.operation = "running";
    if (selectedScenario === "no_results") {
      s.cards = [];
      s.operation = "no_results";
    } else if (!s.cards.length) {
      s.cards = cards(session);
    }
    for (const card of s.cards) {
      if (selectedScenario === "no_images") {
        card.image_id = null; card.image_version = null; card.image_url = null;
      } else if (card.position < 2) {
        card.image_id = `synthetic-image-${card.position === 0 ? "A" : "B"}`;
        card.image_version = 1;
        card.image_url = selectedScenario === "broken_images" ? "data:image/png;base64,aW52YWxpZA==" :
          picture(card.position === 0 ? "A" : "B", card.position === 0 ? "#354a63" : "#b9a789");
      }
    }
    if (selectedScenario === "model_error" && session.pending) {
      s.error = { code: "provider_timeout", message: "합성 오류: 접수한 입력의 해석이 끝나지 않았습니다." };
    }
    expected(session);
  }
  function completePending(session) {
    if (!session.pending || selectedScenario !== "normal" || Date.now() < session.pending.readyAt) return;
    const feedback = session.pending.action;
    if (feedback.text && !["unsure", "question_skipped"].includes(feedback.reaction)) {
      addMemory(session, feedback.text); // Echo only: no selection reason is invented.
    }
    if (feedback.selections?.length) {
      session.state.questions = [{
        ref: ref("question", id("question")), text: "어떤 점이 원하는 느낌에 가까웠나요?",
        target_id: session.state.request.targets[0].target_id,
        options: ["색", "형태", "다른 이유", "잘 모르겠어요"], status: "open",
      }];
    }
    session.pending = null;
    session.state.operation = "idle";
    session.state.error = null;
    advance(session);
  }
  function view(session) {
    if (!session) return initial();
    completePending(session);
    const s = copy(session.state);
    s.state_version = stateVersion;
    s.memories = [...s.memories.filter(memory => memory.scope !== "long_term"), ...copy(longMemories)];
    s.requests = [...sessions.values()].map(item => copy(item.state.request));
    // Include only the active comparison and latest pending feedback references.
    s.expected.profile_revision = profileRevision;
    s.expected.object_versions = [...s.expected.object_versions.filter(item => !longMemories.some(m => m.ref.id === item.id)),
      ...longMemories.map(memory => copy(memory.ref))];
    return s;
  }
  function rejected(session, code, message) {
    return { outcome: "rejected", state: view(session), error: { code, message } };
  }
  function accept(session, outcome = "applied") {
    advance(session);
    return { outcome, state: view(session), error: null };
  }
  function beginPending(session, action) {
    session.feedback = ref("feedback", id("feedback"));
    session.pending = { action: copy(action), readyAt: Date.now() + Math.max(400, delay * 2) };
    session.state.operation = "interpretation_pending";
    applyScenario(session);
  }
  function perform(command) {
    const action = command.action;
    let session = sessions.get(command.request_id);
    if (command.contract_version !== "lumi-memory-v1") return rejected(session, "unsupported_contract", "지원하지 않는 화면 계약입니다.");
    if (action.op === "start_request") {
      if (command.request_id !== null || command.expected !== null || !action.targets.length) return rejected(null, "invalid_input", "새 요청 입력을 확인하세요.");
      const request = { id: id("request"), revision: 1, status: "open", mode: action.mode, targets: copy(action.targets), final_selection: null };
      session = { state: { ...initial(), request, phase: "exploring" }, meanings: new Map(), pending: null, feedback: null, round: null, set: null };
      sessions.set(request.id, session);
      current = request.id;
      session.state.cards = cards(session);
      if (action.text) beginPending(session, { text: action.text, reaction: "text_only", selections: [] });
      applyScenario(session);
      return accept(session, action.text ? "accepted" : "applied");
    }
    if (!session) return rejected(null, "not_found", "요청을 찾을 수 없습니다.");
    if (!command.expected || command.expected.request_revision !== session.state.request.revision || command.expected.profile_revision !== profileRevision) {
      return rejected(session, "version_conflict", "표시한 내용이 바뀌었습니다. 최신 화면을 확인하세요.");
    }
    current = command.request_id;
    if (session.state.request.status !== "open" && !["resume_request", "prepare_review", "respond_review"].includes(action.op)) return rejected(session, "request_closed", "종료한 요청입니다.");
    if (["submit_feedback", "select_final", "explore"].includes(action.op) && selectedScenario === "stale") return rejected(session, "stale_context", "후보가 변경되었습니다.");
    switch (action.op) {
      case "resume_request": return accept(session, "unchanged");
      case "submit_feedback": {
        if (action.selections.length && (action.candidate_set_id !== session.set.id || action.round_id !== session.round.id)) return rejected(session, "stale_context", "후보가 변경되었습니다.");
        if (action.question_id) {
          const question = session.state.questions.find(q => q.ref.id === action.question_id);
          if (question) question.status = action.reaction === "question_skipped" ? "skipped" : "answered";
        }
        beginPending(session, action);
        return accept(session, "accepted");
      }
      case "retry_extraction":
        if (!session.pending || action.feedback_ref.id !== session.feedback.id) return rejected(session, "not_found", "대기 중인 입력을 찾을 수 없습니다.");
        session.pending.readyAt = Date.now() + 400;
        applyScenario(session);
        return accept(session, "accepted");
      case "explore":
        session.state.cards = cards(session);
        session.state.phase = "exploring";
        applyScenario(session);
        return accept(session);
      case "prepare_review": {
        const subject = action.subject_refs[0];
        const memory = [...session.state.memories, ...longMemories].find(m => m.ref.id === subject?.id && m.ref.version === subject.version);
        if (!memory) return rejected(session, "not_found", "확인할 내용을 찾을 수 없습니다.");
        if (action.purpose === "future_reuse" && !memory.confirmed) return rejected(session, "confirmation_required", "내용을 먼저 확인하세요.");
        const snapshotMeaning = copy(session.meanings.get(memory.ref.id) ?? meaning(memory.content, session.state.request.targets[0], memory.scope));
        if (action.proposed_text !== null) snapshotMeaning.content = action.proposed_text;
        if (action.purpose === "replace" && memory.scope === "long_term") snapshotMeaning.scope = "short_term";
        if (action.purpose === "future_reuse") snapshotMeaning.scope = "long_term";
        session.state.reviews = [{ ref: ref("display", id("display")), purpose: action.purpose,
          snapshot: { meaning: snapshotMeaning, bindings: [], subject_refs: copy(action.subject_refs) } }];
        session.state.phase = "review";
        return accept(session);
      }
      case "respond_review": {
        const review = session.state.reviews.find(r => r.ref.id === action.display_ref.id && r.ref.version === action.display_ref.version);
        if (!review) return rejected(session, "stale_context", "검토 내용이 변경되었습니다.");
        const memory = [...session.state.memories, ...longMemories].find(m => m.ref.id === review.snapshot.subject_refs[0]?.id);
        if (action.decision === "accept" && memory) {
          if (review.purpose === "future_reuse") {
            longMemories.push({ ...copy(memory), ref: ref("memory", id("long")), scope: "long_term", confirmed: true, status: "active" });
            profileRevision += 1;
          } else if (["confirm_content", "replace"].includes(review.purpose)) {
            // An edit never silently inherits the old long-term reuse choice.
            let updated = memory;
            if (memory.scope === "long_term") {
              addMemory(session, review.snapshot.meaning.content);
              updated = session.state.memories.at(-1);
            }
            updated.content = review.snapshot.meaning.content;
            updated.confirmed = true; updated.status = "active"; updated.ref.version += 1;
            session.meanings.set(updated.ref.id, copy(review.snapshot.meaning));
          }
        }
        session.state.reviews = [];
        session.state.phase = session.state.request.status === "closed" || session.state.request.final_selection ? "wrap_up" : "exploring";
        return accept(session);
      }
      case "select_final": {
        const card = session.state.cards.find(item => item.candidate_id === action.candidate_id);
        if (!card || action.candidate_set_ref.id !== session.set.id) return rejected(session, "stale_context", "선택할 후보가 변경되었습니다.");
        session.state.request.final_selection = { candidate_set_ref: copy(session.set), candidate_id: card.candidate_id, product_id: card.product_id, target_id: card.target_id, product_map_version: card.product_map_version };
        session.state.phase = "wrap_up";
        return accept(session);
      }
      case "end_request":
        session.state.request.status = "closed"; session.state.phase = "wrap_up";
        session.state.operation = "idle"; session.pending = null;
        return accept(session);
      default: return rejected(session, "invalid_input", "지원하지 않는 화면 조작입니다.");
    }
  }
  return {
    async state(request_id = null) {
      await pause(delay);
      return view(sessions.get(request_id ?? current));
    },
    async command(command) {
      trace.push(copy(command));
      await pause(delay);
      const previous = receipts.get(command.command_id);
      const key = fingerprint(command);
      if (previous) return previous.key === key ? copy(previous.result) : rejected(sessions.get(command.request_id), "idempotency_conflict", "다른 입력에 같은 명령을 사용할 수 없습니다.");
      const result = perform(command);
      receipts.set(command.command_id, { key, result: copy(result) });
      return copy(result);
    },
    // Fixture controls, deliberately outside the ConsumerService wire objects.
    async setScenario(name) {
      if (!Object.hasOwn(FIXTURE_SCENARIOS, name)) throw new Error("unknown fixture");
      selectedScenario = name;
      const session = sessions.get(current);
      if (session) { applyScenario(session); advance(session); }
      return this.state();
    },
    get scenario() { return selectedScenario; },
    get commands() { return copy(trace); },
  };
}
