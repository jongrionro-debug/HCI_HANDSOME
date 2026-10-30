/** Consumer UI for the local HTTP service and the separate E1 practice fixture.
 * Both adapters use the same state(request_id) / command(command) contract.
 */
const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
const clone = value => structuredClone(value);
const blankDraft = () => ({ text: "", selections: [], reaction: "text_only", question: null, version: 0 });
const purposeLabel = {
  confirm_content: "이번 내용이 맞는지 확인", confirm_bindings: "이 속성 해석이 맞는지 확인",
  future_reuse: "이후 요청에서도 활용할 내용", replace: "수정할 내용 확인",
  withdraw: "이후 활용 철회 확인", delete: "기억 삭제 확인", delete_request: "요청 삭제 확인",
};
const safeError = code => ({
  stale_context: "후보나 반영 내용이 바뀌었어요. 최신 화면을 확인한 뒤 다시 반영해 주세요.",
  version_conflict: "확인할 내용이 변경됐어요. 최신 화면을 다시 확인해 주세요.",
  request_closed: "이미 종료한 요청이에요. 새 요청을 시작할 수 있어요.",
  request_expired: "보관 기간이 지난 요청이에요. 새 요청을 시작해 주세요.",
  confirmation_required: "내용이 맞는지 먼저 확인해 주세요.",
  consent_required: "이후 활용 여부는 별도로 선택해 주세요.",
  provider_timeout: "해석 처리가 지연됐어요. 접수 상태를 확인하고 다시 시도해 주세요.",
  provider_unavailable: "해석을 잠시 진행할 수 없어요. 잠시 후 다시 시도해 주세요.",
  context_blocked: "확인이 더 필요한 조건이 있어요. 반영 내용을 살펴보거나 요청을 수정해 주세요.",
}[code] ?? "처리를 마치지 못했어요. 최신 화면을 확인하고 다시 시도해 주세요.");
const sameRef = (left, right) => left?.id === right?.id && left?.version === right?.version;
const questionLabel = text => /unconfirmed_hypothesis|\[q\d+\]|"(?:garment_type|slot_id)"/.test(text)
  ? "확인 중인 해석이 이번 요청에 맞나요? 글로 보완하거나 건너뛸 수 있어요."
  : text;

export function mountConsumer(root, adapter, { fixture = false, scenarios = {} } = {}) {
  let state = null;
  let busy = false;
  let panel = null;
  let startMode = "onboarding";
  let detailsOpen = false;
  let disposed = false;
  let pollTimer = null;
  let generation = 0;
  let readSequence = 0;
  let localError = null;
  let notice = "";
  let uncertain = null;
  let lastReceipt = null;
  let part = null;
  let editing = null;
  let finalPreview = null;
  const drafts = new Map();
  const initialText = { onboarding: "", shopping: "" };
  const agreed = new Set();
  const saveItems = new Set();
  const failedImages = new Set();
  const loadedImages = new Set();
  const imageKey = card => `${card.image_id}:${card.image_version}:${card.image_url}`;
  const requestId = () => state?.request?.id ?? null;
  const draft = () => {
    const key = requestId() ?? "initial";
    if (!drafts.has(key)) drafts.set(key, blankDraft());
    return drafts.get(key);
  };
  // A2 exposes only the current comparison and latest feedback in expected.
  // Never guess from ambiguous historical references or card positions.
  const uniqueRef = type => {
    const refs = state?.expected?.object_versions.filter(item => item.type === type) ?? [];
    return refs.length === 1 ? clone(refs[0]) : null;
  };
  const comparison = () => ({ round: uniqueRef("round"), set: uniqueRef("candidate_set") });
  const isOpen = () => state?.request?.status === "open";
  const disabled = () => busy || Boolean(uncertain) || state?.operation === "running";
  const canFeedback = () => isOpen() && !disabled() && state.operation !== "interpretation_pending";
  const button = (action, label, extra = "", off = disabled()) => `<button type="button" data-action="${action}" ${off ? "disabled" : ""} ${extra}>${label}</button>`;
  const safeImage = card => {
    if (!card.image_id || !card.image_version || !card.image_url || failedImages.has(imageKey(card))) return null;
    try {
      const url = new URL(card.image_url, location.href);
      if (["http:", "https:"].includes(url.protocol) || (fixture && url.protocol === "data:" && /^data:image\//.test(card.image_url))) return url.href;
    } catch { /* Show the missing-image fallback. */ }
    return null;
  };
  function image(card, box = null, editor = false) {
    const url = safeImage(card);
    const overlay = box ? `<span class="crop-box" style="left:${box[0] * 100}%;top:${box[1] * 100}%;width:${(box[2] - box[0]) * 100}%;height:${(box[3] - box[1]) * 100}%"></span>` : "";
    return `<div class="image-stage" ${editor ? 'data-crop-stage="true"' : ""}>
      ${url ? `<img src="${esc(url)}" alt="${esc(card.title)}${fixture ? " · 합성 조작 연습 이미지" : ""}" data-image="${esc(card.candidate_id)}" draggable="false">${overlay}` :
        `<div class="image-placeholder"><strong>${card.image_id ? "이미지를 불러오지 못했어요" : "준비된 이미지가 없어요"}</strong>글과 전체 후보 선택으로 계속할 수 있어요.</div>`}
    </div>`;
  }
  function memories() {
    const active = state.memories.filter(m => !["withdrawn", "superseded"].includes(m.status));
    const groups = [
      ["이번 요청", active.filter(m => m.scope === "short_term" && m.confirmed)],
      ["평소 취향", active.filter(m => m.scope === "long_term")],
      ["확인 중인 해석", active.filter(m => m.scope === "short_term" && !m.confirmed)],
    ];
    return groups.map(([name, items]) => `<section class="memory-group"><h3>${name}</h3>${items.length ? items.map(m => `
      <div class="memory-item"><p>${esc(m.content)}</p>
        ${!m.confirmed ? '<p class="hint">아직 확인하지 않은 내용이에요.</p>' : ""}
        <div class="actions">
          ${!m.confirmed && isOpen() ? button("confirm", "내용 확인", `data-memory="${esc(m.ref.id)}"`) : ""}
          ${m.confirmed && isOpen() ? button("bindings", "속성 해석 검토", `data-memory="${esc(m.ref.id)}"`) : ""}
          ${m.confirmed && isOpen() ? button("edit", m.scope === "long_term" ? "평소 취향 수정" : "내용 수정", `data-memory="${esc(m.ref.id)}"`) : ""}
        </div>
        ${editing?.id === m.ref.id ? `<form class="edit-form" data-form="edit"><label for="memory-edit">수정할 내용을 적어주세요</label>
          ${m.scope === "long_term" ? '<p class="hint">변경할 내용과 적용 범위를 다시 검토해요. 이후 활용 동의도 별도로 확인해요.</p>' : ""}
          <textarea id="memory-edit" maxlength="4000" ${busy ? "readonly" : ""}>${esc(editing.text)}</textarea><div class="actions"><button class="primary" ${disabled() ? "disabled" : ""}>수정 내용 검토</button>${button("cancel-edit", "취소")}</div></form>` : ""}
      </div>`).join("") : '<p class="hint">아직 없어요.</p>'}</section>`).join("");
  }
  function reviewMarkup() {
    return state.reviews.map(review => {
      const meaning = review.snapshot.meaning;
      const future = review.purpose === "future_reuse";
      const fields = meaning ? `<p><strong>${esc(meaning.content)}</strong></p><dl>
        <dt>적용 범위 · 대상</dt><dd>${meaning.scope === "long_term" ? "이후 요청에서 참고할 평소 취향" : "이번 요청만"} · ${esc(meaning.selector.garment_type === "Pants" ? "바지" : meaning.selector.garment_type ?? "전체 대상")}${meaning.selector.slot_id ? " · 지정한 아이템" : ""}</dd>
        <dt>조건</dt><dd>${Object.entries(meaning.conditions).map(([key, value]) => `${esc({occasion: "상황", activity: "활동", goal: "목적"}[key] ?? key)}: ${esc(value)}`).join(" / ") || "추가 조건 없음"}</dd>
        <dt>방향 · 강도</dt><dd>${esc({ prefer: "선호", avoid: "피하고 싶음", require: "필요함", indifferent: "상관없음" }[meaning.polarity])} · ${meaning.strength === "hard" ? "필수" : "선호 조건"}</dd>
        <dt>기간</dt><dd>${esc(meaning.valid_from ?? "시작일 지정 없음")} / ${esc(meaning.valid_until ?? "종료일 지정 없음")}</dd>
        ${meaning.fact ? `<dt>상황 정보</dt><dd>${esc(meaning.fact.key)}: ${esc(meaning.fact.value)}</dd>` : ""}</dl>` : "";
      const bindings = review.snapshot.bindings.map(binding => `<p class="hint">${esc(binding.domain === "PI" ? binding.feature : `${binding.category} / ${binding.subcategory} / ${binding.tag}`)}: ${esc(binding.values?.join(", ") ?? binding.polarity)} · ${esc(binding.polarity)} · ${esc(binding.strength)}</p>`).join("");
      return `<section class="review" aria-label="${esc(purposeLabel[review.purpose])}"><h3>${esc(purposeLabel[review.purpose])}</h3>${fields}${bindings}
        ${future ? `<label class="check-label"><input type="checkbox" data-consent="${esc(review.ref.id)}" ${agreed.has(review.ref.id) ? "checked" : ""}>이 내용을 이후 요청에서 활용하는 데 동의해요.</label>` : '<p class="hint">이 확인은 이후 활용 동의와 별개예요.</p>'}
        <div class="actions">${button("respond", future ? "동의하고 이후 활용" : "이 내용 확인", `class="primary" data-review="${esc(review.ref.id)}" data-decision="accept"`, disabled() || (future && !agreed.has(review.ref.id)))}
          ${button("respond", future ? "이후 활용 안 함" : "맞지 않아요", `data-review="${esc(review.ref.id)}" data-decision="decline"`)}
          ${button("respond", "지금은 건너뛰기", `class="quiet" data-review="${esc(review.ref.id)}" data-decision="skip"`)}</div>
      </section>`;
    }).join("");
  }
  function statusMarkup() {
    let text = notice;
    let tone = "";
    if (busy || state?.operation === "running") { text = "처리 중이에요. 적고 있던 내용은 그대로 둘게요."; tone = "pending"; }
    if (state?.operation === "interpretation_pending") {
      text = "입력은 접수됐어요. 해석을 기다리고 있으며, 아직 선호를 확인한 상태가 아니에요."; tone = "pending";
    }
    if (state?.operation === "stale") { text = safeError("stale_context"); tone = "error"; }
    if (state?.operation === "blocked") { text = safeError("context_blocked"); tone = "error"; }
    if (state?.operation === "error") { text = "처리를 완료하지 못했어요. 최신 화면을 확인해 주세요."; tone = "error"; }
    const error = localError ?? state?.error;
    if (error) {
      text = error.local ? error.message : `${state?.operation === "interpretation_pending" ? "입력은 접수됐지만 해석이 끝나지 않았어요. " : ""}${safeError(error.code)}`;
      tone = "error";
    }
    if (uncertain) { text = "접수 여부를 아직 확인하지 못했어요. 같은 입력으로 접수를 확인해 주세요. 초안은 보존했어요."; tone = "error"; }
    const retryRef = uniqueRef("feedback");
    const controls = uncertain ? button("retry-command", "같은 입력 접수 확인", "", busy) :
      `${state?.operation === "interpretation_pending" && retryRef ? button("retry-extraction", "접수한 입력 해석 재시도", "", busy) : ""}
       ${["stale", "error", "blocked"].includes(state?.operation) || error ? button("refresh", "최신 화면 확인", "", busy) : ""}`;
    return `<div id="operation-status" class="status" data-tone="${tone}" role="status" aria-live="polite" aria-atomic="true">${esc(text)}${controls.trim() ? `<div class="actions">${controls}</div>` : ""}</div>`;
  }
  function startMarkup() {
    const onboarding = startMode === "onboarding";
    const requests = state.requests.filter(r => r.mode === "shopping" && r.status !== "expired");
    return `<section class="start"><h1>${onboarding ? "평소 어떤 옷을 좋아하세요?" : "이번에는 어떤 옷이 필요하세요?"}</h1>
      <p>${onboarding ? "짧게 적거나, 이미지부터 살펴봐도 좋아요. 내용을 확인한 뒤 이후 활용 여부를 따로 선택할 수 있어요." : "아이템과 입을 상황을 짧게 알려주세요. 이전 요청의 조건은 자동으로 이어지지 않아요."}</p>
      <form class="start-form" data-form="start"><div><label for="target">찾을 아이템</label><select id="target" name="target"><option value="Pants">바지${fixture ? " · 화면 연습 대상" : ""}</option></select></div>
        <div><label for="initial-text">${onboarding ? "평소 취향 한마디 (선택)" : "입을 상황과 원하는 느낌 (선택)"}</label>
          <textarea id="initial-text" maxlength="4000" placeholder="${onboarding ? "예: 평소에는 여유 있는 바지를 자주 입어요." : "예: 이번 회사 발표에 입을 단정한 바지를 찾고 있어요."}">${esc(initialText[startMode])}</textarea></div>
        <div class="actions"><button class="primary" ${disabled() ? "disabled" : ""}>${onboarding ? "취향 살펴보기" : "새 요청 시작"}</button>
          ${onboarding ? button("skip-onboarding", "저장 없이 요청 시작", 'class="quiet"') : ""}
          ${state.request ? button("cancel-start", "기존 요청으로 돌아가기", 'class="quiet"') : ""}</div>
        <p class="hint">${fixture ? "합성 이미지와 문장으로 조작을 연습합니다. 실제 상품 검색이나 저장은 하지 않아요." : "처음부터 모든 조건을 정할 필요는 없어요."}</p>
      </form>
      ${requests.length ? `<section class="request-list"><h2>기존 요청 다시 보기</h2><p class="hint">열린 요청은 이어서 탐색하고, 종료한 요청은 요약을 볼 수 있어요.</p>${requests.map((r, index) => button("resume", `바지 요청 ${index + 1} · ${r.status === "open" ? "탐색 이어하기" : "종료 요약"}`, `data-request="${esc(r.id)}"`)).join("")}</section>` : ""}
    </section>`;
  }
  function partMarkup() {
    const card = state.cards.find(c => c.candidate_id === part?.cardId);
    if (!card) return "";
    return `<section class="part-editor" aria-label="이미지 부분 선택"><h2>마음에 드는 부분만 지정해 주세요</h2>
      <p class="hint">이미지 위에서 드래그하거나 아래 좌표를 입력할 수 있어요. 부분의 모든 속성을 선호한다는 뜻은 아니에요.</p>
      <div class="part-grid">${image(card, part.box, true)}<form data-form="part"><p>이미지 안의 비율 (0–1)</p>
        <div class="coordinate-grid">${["왼쪽", "위쪽", "오른쪽", "아래쪽"].map((label, i) => `<label>${label}<input type="number" data-coordinate="${i}" min="0" max="1" step="0.01" value="${part.box[i]}" required></label>`).join("")}</div>
        <p class="hint">왼쪽은 오른쪽보다, 위쪽은 아래쪽보다 작아야 해요.</p><div class="actions"><button class="primary" ${disabled() ? "disabled" : ""}>이 부분 선택</button>${button("cancel-part", "부분 선택 취소")}</div></form></div>
    </section>`;
  }
  function wrapMarkup() {
    const request = state.request;
    const final = request.final_selection;
    const selected = state.cards.find(c => c.candidate_id === final?.candidate_id);
    const confirmed = state.memories.filter(m => m.scope === "short_term" && m.confirmed && m.status === "active");
    const show = request.status !== "open" || final || request.mode === "onboarding";
    if (!show && !finalPreview) return "";
    const previewCard = state.cards.find(c => c.candidate_id === finalPreview);
    return `<section class="wrap-up" aria-label="선택과 마무리"><h2>${request.status === "closed" ? "탐색을 마쳤어요" : previewCard ? "이 상품으로 결정할까요?" : final ? "상품을 선택했어요" : "평소 취향을 확인해 주세요"}</h2>
      <p class="section-intro">${previewCard ? esc(previewCard.title) : final ? `${esc(selected?.title ?? "선택한 상품")} · ${request.status === "open" ? "탐색은 아직 열려 있어요." : "선택 내용은 요약에 남아요."}` : request.status === "closed" ? "상품 선택 없이 종료했어요." : "내용 확인과 이후 활용 선택을 각각 진행할 수 있어요."}</p>
      ${previewCard ? `<div class="actions">${button("confirm-final", "이 상품 확정", 'class="primary"', !canFeedback() || !comparison().set)}${button("cancel-final", "계속 탐색")}</div>` : ""}
      ${final && isOpen() ? button("explore", "계속 탐색") : ""}
      ${confirmed.length ? `<h3>이후에도 활용할 내용이 있나요?</h3><p class="hint">원하는 항목을 고른 뒤 활용 범위와 동의를 따로 확인해요.</p>${confirmed.map(m => `<div class="save-item"><label class="check-label"><input type="checkbox" data-save="${esc(m.ref.id)}" ${saveItems.has(m.ref.id) ? "checked" : ""}>${esc(m.content)}</label>${button("future", "이 항목의 이후 활용 검토", `data-memory="${esc(m.ref.id)}"`, disabled() || !saveItems.has(m.ref.id))}</div>`).join("")}` : '<p class="hint">확인한 내용이 없으면 저장하지 않고 마칠 수 있어요.</p>'}
      <div class="actions">${isOpen() ? button("end", request.mode === "onboarding" ? "온보딩 마치기" : "탐색 종료", 'class="primary"') : ""}
      ${request.mode === "onboarding" ? button("start-after-onboarding", "저장 없이 새 요청", 'class="quiet"') : ""}
      ${request.status === "closed" ? button("new", "새 요청 시작") : ""}</div>
      <p class="hint">최종 선택과 탐색 종료는 평소 취향을 저장하거나 이후 활용에 동의한 것으로 처리되지 않아요.</p>
    </section>`;
  }
  function workspaceMarkup() {
    const d = draft();
    const refs = comparison();
    const activeQuestion = state.questions.find(q => q.ref.id === d.question && q.status === "open");
    const cards = state.cards.map(card => {
      const selection = d.selections.find(s => s.candidate_id === card.candidate_id);
      return `<article class="card ${selection ? "selected" : ""}">${image(card, selection?.part_ref?.box)}<div class="card-body"><h3 class="card-title">${esc(card.title)}</h3>
        ${selection ? `<p class="selected-label">${selection.part_ref ? "부분 선택 중" : "전체 선택 중"} · 반영 전</p>` : ""}
        ${button("select", selection ? "선택 해제" : "전체 선택", `data-card="${esc(card.candidate_id)}" aria-pressed="${Boolean(selection)}"`, !canFeedback() || !refs.set || !refs.round)}
        ${button("part", "부분 선택", `data-card="${esc(card.candidate_id)}"`, !canFeedback() || !safeImage(card) || !loadedImages.has(imageKey(card)) || !refs.set || !refs.round)}
        ${state.request.mode === "shopping" ? button("preview-final", "최종 상품으로 살펴보기", `data-card="${esc(card.candidate_id)}" class="quiet"`, !canFeedback() || !refs.set) : ""}</div></article>`;
    }).join("");
    const noCards = `<div class="empty-state"><h2>${state.operation === "no_results" ? "조건에 맞는 상품이 없어요" : "아직 비교할 후보가 없어요"}</h2><p>조건을 그대로 두거나 글로 조정할 수 있어요. 상품을 고르지 않고 탐색을 마쳐도 괜찮아요.</p></div>`;
    const questionItems = state.questions.filter(q => q.status === "open").map(q => `<section class="question"><h3>${esc(questionLabel(q.text))}</h3>
      <p class="hint">답을 고르거나 자유롭게 적어주세요. 반영하기 전까지 바꿀 수 있어요.</p><div class="actions">${q.options.map((option, index) => button("answer", esc(option), `data-question="${esc(q.ref.id)}" data-option="${index}"`, !canFeedback())).join("")}
      ${button("skip-question", "질문 건너뛰기", `data-question="${esc(q.ref.id)}" class="quiet"`, !canFeedback())}</div></section>`);
    const questions = (questionItems[0] ?? "") + (questionItems.length > 1
      ? `<details><summary>다른 확인 질문 ${questionItems.length - 1}개</summary>${questionItems.slice(1).join("")}</details>` : "");
    return `<div class="page-heading"><div><h1>${state.request.mode === "onboarding" ? "평소 취향을 찾아볼까요?" : state.request.status === "closed" ? "이번 요청의 탐색 요약" : "원하는 느낌에 가까운 쪽을 골라주세요"}</h1><p>하나만 골라도, 여러 장을 골라도 좋아요. 이유는 글로 덧붙일 수 있어요.</p></div></div>
      <div class="workspace ${isOpen() ? "open" : "closed"}"><section aria-label="이미지 비교"><h2>나란히 보고 선택하기</h2><p class="section-intro">${fixture ? "색 영역으로 만든 합성 자료예요. 실제 상품이나 추천 결과가 아니에요." : "선택만으로 후보가 바뀌지 않아요. 글과 함께 반영할 수 있어요."}</p>
        <div class="candidates">${cards}</div>${cards ? "" : noCards}
        ${cards && (!refs.round || !refs.set) ? `<p class="selection-note">비교 회차 정보를 확인할 수 없어 이미지 응답을 보류했어요. 글로 계속하거나 최신 화면을 확인해 주세요.</p>${button("refresh", "최신 화면 확인")}` : ""}
        ${isOpen() ? `<div class="candidate-actions"><fieldset class="reactions"><legend>고르기 어려울 때</legend><div class="actions">
          ${[["none", "마음에 드는 게 없어요"], ["unsure", "잘 모르겠어요"], ["text_only", "텍스트만 보낼게요"]].map(([reaction, label]) => button("reaction", label, `data-reaction="${reaction}" aria-pressed="${d.reaction === reaction && !d.selections.length}"`, !canFeedback() || (reaction !== "text_only" && (!refs.round || !refs.set)))).join("")}
        </div></fieldset><p class="selection-note">${d.selections.length ? `${d.selections.length}개를 선택했어요.` : "이미지 선택 없이도 이야기할 수 있어요."} 개별 속성이나 선택하지 않은 후보의 비선호를 확정하지 않아요.</p>
        <div class="actions">${button("explore", "다른 후보 보기", "", !canFeedback() || Boolean(d.text || d.selections.length))}${button("end", "상품 선택 없이 종료", 'class="quiet"')}</div>
        ${d.text || d.selections.length ? '<p class="hint">작성 중인 선택과 글을 먼저 반영하거나, 그대로 둔 채 탐색을 마칠 수 있어요.</p>' : ""}</div>` : ""}
        ${partMarkup()}${wrapMarkup()}</section>
        <aside class="conversation" aria-label="대화와 반영 내용">${reviewMarkup()}${questions}
          <section><details id="reflected-info" ${detailsOpen ? "open" : ""}><summary>반영 내용 보기</summary><p class="hint">이번 요청과 평소 취향은 구분해요. 평소 취향 수정은 별도 검토가 필요해요.</p>${memories()}</details></section>
          <section class="composer"><form data-form="feedback"><label for="free-text">${activeQuestion ? "질문에 대한 답과 덧붙일 이야기" : "선택에 덧붙이거나, 글로 이야기해 주세요"}</label>
            <textarea id="free-text" maxlength="4000" placeholder="예: A의 색은 좋지만, 더 여유 있는 형태가 좋아요." ${isOpen() ? "" : "readonly"}>${esc(d.text)}</textarea>
            <div class="actions"><span class="hint">${d.reaction === "selected" ? "선택 + 글 함께 반영" : {none: "후보 없음으로 응답", unsure: "판단 보류로 응답", text_only: "글만 반영", question_skipped: "질문 건너뛰기"}[d.reaction]}</span>
              <button class="primary" ${canFeedback() && (d.selections.length || d.text.trim() || ["none", "unsure", "question_skipped"].includes(d.reaction)) ? "" : "disabled"}>선택과 글 반영</button></div>
            <p class="hint">${isOpen() ? "반영하기 전까지 자유롭게 고칠 수 있어요." : "종료한 요청이에요. 작성하던 초안은 이 화면에 남겨 두었어요."}</p>
            ${lastReceipt?.requestId === requestId() ? `<p class="hint">${fixture ? "화면 연습에서 접수한 입력" : "접수한 입력"}: ${esc(lastReceipt.text ?? "이미지·질문 반응")} · 내용 확인과 이후 활용 동의는 별도예요.</p>` : ""}
          </form></section>
        </aside></div>`;
  }
  function render() {
    if (disposed) return;
    cancelDrag();
    const focused = root.contains(document.activeElement) ? document.activeElement : null;
    const focusId = focused?.id;
    const focusAction = focused?.dataset.action;
    const focusData = focused ? { ...focused.dataset } : {};
    const selection = focused?.selectionStart !== undefined ? [focused.selectionStart, focused.selectionEnd] : null;
    root.innerHTML = `<header class="topbar"><span class="wordmark" aria-label="LUMI">LUMI</span><nav aria-label="주요 메뉴">${button("new", "새 요청")}${button("preferences", "평소 취향")}</nav></header>
      ${fixture ? `<div class="fixture-strip"><strong>화면 연습</strong><span>합성 자료 · 실제 저장·모델 호출 없음 · 새로고침하면 초기화</span><label>상태 연습<select id="fixture-scenario" ${busy ? "disabled" : ""}>${Object.entries(scenarios).map(([key, label]) => `<option value="${key}" ${adapter.scenario === key ? "selected" : ""}>${esc(label)}</option>`).join("")}</select></label></div>` : ""}
      <main class="shell" id="workspace" tabindex="-1" aria-busy="${busy || state?.operation === "running"}">${statusMarkup()}${state ? panel === "start" || !state.request ? startMarkup() : workspaceMarkup() : '<p class="boot-message">화면을 불러오고 있어요.</p>'}</main>`;
    root.querySelectorAll("img[data-image]").forEach(img => {
      const card = state?.cards.find(c => c.candidate_id === img.dataset.image);
      if (!card) return;
      const loaded = () => {
        if (img.naturalWidth) {
          loadedImages.add(imageKey(card));
          img.parentElement.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`;
          root.querySelectorAll(`[data-action="part"]`).forEach(b => {
            if (b.dataset.card === card.candidate_id) b.disabled = !canFeedback() || !comparison().set || !comparison().round;
          });
        }
      };
      img.addEventListener("load", loaded);
      img.addEventListener("error", () => {
        failedImages.add(imageKey(card));
        const stage = img.parentElement;
        stage.innerHTML = '<div class="image-placeholder"><strong>이미지를 불러오지 못했어요</strong>글과 전체 후보 선택으로 계속할 수 있어요.</div>';
        root.querySelectorAll('[data-action="part"]').forEach(b => { if (b.dataset.card === card.candidate_id) b.disabled = true; });
        if (part?.cardId === card.candidate_id) { part = null; render(); }
      });
      if (img.complete && img.naturalWidth) loaded();
    });
    root.querySelector("#reflected-info")?.addEventListener("toggle", event => { if (event.target.isConnected) detailsOpen = event.target.open; });
    if (focusId) {
      const target = document.getElementById(focusId);
      if (target && !target.disabled) {
        target.focus({ preventScroll: true });
        if (selection && target.setSelectionRange && target.type !== "number") target.setSelectionRange(...selection);
      }
    } else if (focusAction) {
      [...root.querySelectorAll('button[data-action]')].find(b => !b.disabled &&
        Object.entries(focusData).every(([key, value]) => b.dataset[key] === value))?.focus({ preventScroll: true });
    }
  }
  function announce(message) { notice = message; localError = null; render(); }
  function focusMain() { root.querySelector("#workspace")?.focus(); }
  function updateState(next) {
    if (state && next.state_version < state.state_version) return;
    const previousSet = uniqueRef("candidate_set");
    const previousRequest = requestId();
    if (JSON.stringify(state?.reviews ?? []) !== JSON.stringify(next.reviews)) agreed.clear();
    for (const id of saveItems) {
      const previous = state?.memories.find(m => m.ref.id === id);
      const updated = next.memories.find(m => m.ref.id === id);
      if (!previous || !updated || !sameRef(previous.ref, updated.ref) || previous.content !== updated.content) saveItems.delete(id);
    }
    state = next;
    if (previousRequest !== requestId()) { generation += 1; part = null; editing = null; finalPreview = null; }
    const nextSet = uniqueRef("candidate_set");
    if (!sameRef(previousSet, nextSet)) {
      const d = draft();
      if (d.selections.length) notice = "후보가 바뀌어 이미지 선택을 해제했어요. 작성하던 글은 그대로예요.";
      d.selections = []; if (d.reaction === "selected") d.reaction = "text_only";
      part = null; finalPreview = null;
    }
    const d = draft();
    const validSelections = d.selections.filter(selection => {
      const card = state.cards.find(c => c.candidate_id === selection.candidate_id && c.target_id === selection.target_id);
      return card && (!selection.part_ref || (selection.part_ref.image_id === card.image_id && selection.part_ref.image_version === card.image_version));
    });
    if (validSelections.length !== d.selections.length) {
      d.selections = validSelections;
      if (!d.selections.length && d.reaction === "selected") d.reaction = "text_only";
      part = null; notice = "이미지가 바뀌어 해당 선택을 해제했어요. 작성하던 글은 그대로예요.";
    }
    if (draft().question && !state.questions.some(q => q.ref.id === draft().question && q.status === "open")) {
      draft().question = null;
      if (draft().reaction === "question_skipped") draft().reaction = "text_only";
    }
  }
  async function refresh(id = requestId(), quiet = false) {
    const marker = generation;
    const sequence = ++readSequence;
    try {
      const next = await adapter.state(id);
      if (disposed || sequence !== readSequence || marker !== generation || (id && next.request?.id !== id)) return;
      updateState(next); localError = null;
      render(); schedulePoll();
    } catch {
      if (disposed || sequence !== readSequence || marker !== generation) return;
      localError = { local: true, message: "화면을 불러오지 못했어요. 작성한 내용은 그대로예요. 최신 화면 확인을 다시 눌러주세요." };
      render();
    }
  }
  function schedulePoll() {
    clearTimeout(pollTimer);
    if (!disposed && ["running", "interpretation_pending"].includes(state?.operation) && !state.error && !localError) {
      pollTimer = setTimeout(() => { if (!busy) refresh(requestId(), true); else schedulePoll(); }, 650);
    }
  }
  async function send(action, { command = null, submitted = null } = {}) {
    if (busy || (uncertain && !command)) return null;
    const id = requestId();
    const previousFocus = root.contains(document.activeElement) ? document.activeElement?.id : null;
    const outgoing = command ?? {
      contract_version: state.contract_version, command_id: crypto.randomUUID(),
      request_id: action.op === "start_request" ? null : id,
      expected: action.op === "start_request" ? null : clone(state.expected), action: clone(action),
    };
    readSequence += 1;
    busy = true; localError = null; notice = ""; clearTimeout(pollTimer); render();
    try {
      const result = await adapter.command(clone(outgoing));
      if (disposed) return null;
      uncertain = null;
      updateState(result.state);
      if (result.outcome === "rejected") localError = result.error ?? result.state.error ?? { code: "invalid_input" };
      else {
        notice = fixture ? "화면 연습에 반영했어요. 실제 저장이나 처리는 하지 않았어요." : result.outcome === "accepted" ? "입력을 접수했어요. 해석 완료와 내용 확인은 별도예요." : "변경 내용을 반영했어요.";
        if (outgoing.action.op === "start_request") {
          panel = null;
          const mode = outgoing.action.mode;
          if (initialText[mode] === (outgoing.action.text ?? "")) initialText[mode] = "";
        }
        if (outgoing.action.op === "select_final") finalPreview = null;
        if (outgoing.action.op === "submit_feedback") {
          const d = drafts.get(outgoing.request_id);
          if (d && submitted?.version === d.version) drafts.set(outgoing.request_id, blankDraft());
          lastReceipt = { requestId: outgoing.request_id, text: outgoing.action.text };
        }
      }
      return result;
    } catch {
      uncertain = { command: clone(outgoing), submitted };
      return null;
    } finally {
      busy = false;
      render(); schedulePoll();
      if (document.activeElement === document.body) {
        const target = previousFocus ? document.getElementById(previousFocus) : root.querySelector(".review input, .review button, #free-text, #workspace");
        target?.focus({ preventScroll: true });
      }
    }
  }
  function feedbackAction() {
    const d = draft();
    const refs = comparison();
    const needsComparison = d.selections.length || ["none", "unsure"].includes(d.reaction) || Boolean(d.question && state.cards.length);
    if (needsComparison && (!refs.round || !refs.set)) {
      localError = { local: true, message: "지금 비교 중인 후보를 확인할 수 없어요. 최신 화면을 확인해 주세요. 글은 보존했어요." }; render(); return null;
    }
    // A pending confirmation can hide the cards while its comparison question
    // remains open. Keep that question attached to the current comparison.
    const attachedComparison = (state.cards.length || d.question || needsComparison) && refs.round && refs.set;
    return {
      op: "submit_feedback", round_id: attachedComparison ? refs.round.id : null,
      candidate_set_id: attachedComparison ? refs.set.id : null,
      reaction: d.selections.length ? "selected" : d.reaction, selections: clone(d.selections),
      text: d.reaction === "question_skipped" ? null : d.text.trim() ? d.text : null,
      question_id: d.question,
    };
  }
  async function prepare(memoryId, purpose, proposed = null) {
    const memory = state.memories.find(m => m.ref.id === memoryId);
    if (!memory) return;
    const result = await send({ op: "prepare_review", purpose, subject_refs: [clone(memory.ref)], proposed_text: proposed });
    if (result && result.outcome !== "rejected") {
      agreed.clear(); editing = null; detailsOpen = true; render();
      root.querySelector(".review button, .review input")?.focus();
    }
  }
  async function onClick(event) {
    const b = event.target.closest("button[data-action]");
    if (!b || b.disabled) return;
    if (!state) { if (b.dataset.action === "refresh") await refresh(null); return; }
    const d = draft();
    const card = state.cards.find(c => c.candidate_id === b.dataset.card);
    switch (b.dataset.action) {
      case "new": panel = "start"; startMode = "shopping"; part = null; render(); focusMain(); break;
      case "preferences":
        if (panel === "start" || !state.request) { announce(state.memories.filter(m => m.scope === "long_term").map(m => m.content).join(" / ") || "이후 활용하기로 한 평소 취향이 아직 없어요."); }
        else { detailsOpen = true; render(); root.querySelector("#reflected-info summary")?.focus(); }
        break;
      case "skip-onboarding": startMode = "shopping"; render(); root.querySelector("#initial-text")?.focus(); break;
      case "cancel-start": panel = null; render(); focusMain(); break;
      case "resume": {
        generation += 1; readSequence += 1; busy = true; clearTimeout(pollTimer); render();
        try { updateState(await adapter.state(b.dataset.request)); panel = null; }
        catch { localError = { local: true, message: "요청을 다시 불러오지 못했어요. 잠시 후 다시 시도해 주세요." }; }
        finally { busy = false; render(); }
        if (requestId() === b.dataset.request) await send({ op: "resume_request" });
        focusMain(); break;
      }
      case "select": {
        if (!card) return;
        const selected = d.selections.findIndex(s => s.candidate_id === card.candidate_id);
        if (selected >= 0) d.selections.splice(selected, 1);
        else d.selections.push({ target_id: card.target_id, candidate_id: card.candidate_id, part_ref: null });
        d.reaction = d.selections.length ? "selected" : "text_only"; d.version += 1; render();
        root.querySelectorAll('[data-action="select"]').forEach(button => { if (button.dataset.card === card.candidate_id) button.focus({ preventScroll: true }); });
        break;
      }
      case "reaction": d.reaction = b.dataset.reaction; d.selections = []; d.question = null; d.version += 1; render(); root.querySelector("#free-text")?.focus(); break;
      case "part": part = { cardId: card.candidate_id, imageId: card.image_id, imageVersion: card.image_version, box: [0.15, 0.4, 0.85, 0.9] }; render(); root.querySelector('[data-coordinate="0"]')?.focus(); break;
      case "cancel-part": part = null; render(); break;
      case "confirm": await prepare(b.dataset.memory, "confirm_content"); break;
      case "bindings": await prepare(b.dataset.memory, "confirm_bindings"); break;
      case "edit": { const m = state.memories.find(item => item.ref.id === b.dataset.memory); editing = { id: m.ref.id, text: m.content }; detailsOpen = true; render(); root.querySelector("#memory-edit")?.focus(); break; }
      case "cancel-edit": editing = null; render(); break;
      case "future": await prepare(b.dataset.memory, "future_reuse"); break;
      case "respond": {
        const review = state.reviews.find(r => r.ref.id === b.dataset.review);
        if (!review || (review.purpose === "future_reuse" && b.dataset.decision === "accept" && !agreed.has(review.ref.id))) return;
        await send({ op: "respond_review", display_ref: clone(review.ref), decision: b.dataset.decision }); break;
      }
      case "answer": {
        const q = state.questions.find(q => q.ref.id === b.dataset.question);
        const answer = q?.options[Number(b.dataset.option)];
        if (!answer) return;
        d.text = d.text ? `${d.text}\n${answer}` : answer; d.question = q.ref.id;
        d.reaction = answer === "잘 모르겠어요" ? "unsure" : d.selections.length ? "selected" : "text_only";
        if (d.reaction === "unsure") d.selections = [];
        d.version += 1; render(); root.querySelector("#free-text")?.focus(); break;
      }
      case "skip-question":
        d.question = b.dataset.question; d.reaction = "question_skipped"; d.selections = []; d.version += 1;
        announce("질문 건너뛰기를 골랐어요. 반영 버튼으로 보낼 수 있어요. 작성 중인 글은 별도 초안으로 남겨요."); break;
      case "preview-final": finalPreview = card.candidate_id; render(); root.querySelector('[data-action="confirm-final"]')?.focus(); break;
      case "cancel-final": finalPreview = null; render(); break;
      case "confirm-final": {
        const set = comparison().set;
        if (set && finalPreview) await send({ op: "select_final", candidate_set_ref: set, candidate_id: finalPreview }); break;
      }
      case "explore": await send({ op: "explore" }); break;
      case "end": await send({ op: "end_request" }); break;
      case "start-after-onboarding": {
        const result = isOpen() ? await send({ op: "end_request" }) : { outcome: "unchanged" };
        if (result && result.outcome !== "rejected") { panel = "start"; startMode = "shopping"; render(); focusMain(); } break;
      }
      case "retry-extraction": { const feedback = uniqueRef("feedback"); if (feedback) await send({ op: "retry_extraction", feedback_ref: feedback }); break; }
      case "retry-command": if (uncertain) await send(uncertain.command.action, { command: uncertain.command, submitted: uncertain.submitted }); break;
      case "refresh": await refresh(); break;
    }
  }
  function onInput(event) {
    const t = event.target;
    if (t.id === "free-text") {
      const d = draft(); d.text = t.value; d.version += 1;
      const submit = root.querySelector('[data-form="feedback"] button[type="submit"], [data-form="feedback"] button.primary');
      if (submit) submit.disabled = !canFeedback() || !(d.selections.length || d.text.trim() || ["none", "unsure", "question_skipped"].includes(d.reaction));
      root.querySelectorAll('[data-action="explore"]').forEach(b => { b.disabled = !canFeedback() || Boolean(d.text || d.selections.length); });
    }
    if (t.id === "initial-text") initialText[startMode] = t.value;
    if (t.id === "memory-edit" && editing) editing.text = t.value;
    if (t.dataset.coordinate && part) {
      part.box[Number(t.dataset.coordinate)] = t.value === "" ? NaN : Number(t.value);
      positionCrop();
    }
  }
  async function onChange(event) {
    const t = event.target;
    if (t.dataset.consent) { t.checked ? agreed.add(t.dataset.consent) : agreed.delete(t.dataset.consent); render(); root.querySelector(`[data-consent="${CSS.escape(t.dataset.consent)}"]`)?.focus(); }
    if (t.dataset.save) { t.checked ? saveItems.add(t.dataset.save) : saveItems.delete(t.dataset.save); render(); root.querySelector(`[data-save="${CSS.escape(t.dataset.save)}"]`)?.focus(); }
    if (t.id === "fixture-scenario" && fixture && !busy) {
      busy = true; clearTimeout(pollTimer); render();
      try { updateState(await adapter.setScenario(t.value)); localError = null; }
      finally { busy = false; render(); schedulePoll(); root.querySelector("#fixture-scenario")?.focus(); }
    }
  }
  async function onSubmit(event) {
    const form = event.target.closest("form[data-form]");
    if (!form) return;
    event.preventDefault();
    if (busy || uncertain) return;
    if (form.dataset.form === "start") {
      const mode = startMode;
      const result = await send({ op: "start_request", mode, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul",
        targets: [{ target_id: "item-1", garment_type: form.querySelector("#target").value }], text: initialText[mode].trim() ? initialText[mode] : null });
      if (result && result.outcome !== "rejected") focusMain();
    }
    if (form.dataset.form === "feedback" && canFeedback()) {
      const action = feedbackAction();
      if (!action || (!action.text && !action.selections.length && action.reaction === "text_only")) return;
      // A skipped question sends no text; preserve any separately drafted text.
      const version = draft().reaction === "question_skipped" && draft().text ? -1 : draft().version;
      await send(action, { submitted: { version } });
    }
    if (form.dataset.form === "edit" && editing?.text.trim()) await prepare(editing.id, "replace", editing.text);
    if (form.dataset.form === "part" && part) {
      const box = part.box;
      const card = state.cards.find(c => c.candidate_id === part.cardId);
      if (!card || card.image_id !== part.imageId || card.image_version !== part.imageVersion || !safeImage(card) || box.some(v => !Number.isFinite(v) || v < 0 || v > 1) || box[0] >= box[2] || box[1] >= box[3]) {
        localError = { local: true, message: "이미지와 부분 좌표를 다시 확인해 주세요. 초안은 그대로예요." }; render(); return;
      }
      const d = draft();
      d.selections = d.selections.filter(s => s.candidate_id !== card.candidate_id);
      d.selections.push({ target_id: card.target_id, candidate_id: card.candidate_id,
        part_ref: { image_id: part.imageId, image_version: part.imageVersion, region_id: null, box: clone(box) } });
      d.reaction = "selected"; d.version += 1; part = null; render(); root.querySelector("#free-text")?.focus();
    }
  }
  let drag = null;
  function point(event, stage) {
    const rect = stage.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))];
  }
  function positionCrop() {
    const stage = root.querySelector("[data-crop-stage]");
    const overlay = stage?.querySelector(".crop-box");
    if (!overlay || !part || part.box.some(v => !Number.isFinite(v))) return;
    const [x0, y0, x1, y1] = part.box;
    Object.assign(overlay.style, { left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${Math.max(0, x1 - x0) * 100}%`, height: `${Math.max(0, y1 - y0) * 100}%` });
    if (drag) root.querySelectorAll("[data-coordinate]").forEach(input => { input.value = part.box[Number(input.dataset.coordinate)]; });
  }
  function onPointer(event) {
    const stage = event.target.closest("[data-crop-stage]");
    if (!stage || !part) return;
    if (event.type === "pointerdown") {
      if (drag || event.button !== 0) return;
      event.preventDefault(); drag = { start: point(event, stage), id: event.pointerId, stage }; stage.setPointerCapture(event.pointerId);
    }
    if (event.type === "pointermove" && drag?.id === event.pointerId) {
      const end = point(event, stage);
      part.box = [Math.min(drag.start[0], end[0]), Math.min(drag.start[1], end[1]), Math.max(drag.start[0], end[0]), Math.max(drag.start[1], end[1])].map(v => Math.round(v * 1000) / 1000);
      positionCrop();
    }
    if (["pointerup", "pointercancel", "lostpointercapture"].includes(event.type) && drag?.id === event.pointerId) {
      cancelDrag();
    }
  }
  function cancelDrag() {
    const previous = drag;
    drag = null;
    if (previous?.stage.hasPointerCapture(previous.id)) previous.stage.releasePointerCapture(previous.id);
  }
  const listeners = { click: onClick, input: onInput, change: onChange, submit: onSubmit, pointerdown: onPointer, pointermove: onPointer, pointerup: onPointer, pointercancel: onPointer, lostpointercapture: onPointer };
  Object.entries(listeners).forEach(([name, handler]) => root.addEventListener(name, handler));
  window.addEventListener("blur", cancelDrag);
  render();
  const ready = refresh(null);
  return { ready, refresh, destroy() { disposed = true; cancelDrag(); clearTimeout(pollTimer); window.removeEventListener("blur", cancelDrag); Object.entries(listeners).forEach(([name, handler]) => root.removeEventListener(name, handler)); } };
}

const root = typeof document === "undefined" ? null : document.querySelector('#consumer-app[data-adapter="fixture"]');
if (root) {
  import("./consumer-fixture.js").then(({ createFixtureAdapter, FIXTURE_SCENARIOS }) => {
    mountConsumer(root, createFixtureAdapter(), { fixture: true, scenarios: FIXTURE_SCENARIOS });
  }).catch(() => { root.textContent = "화면 자산을 불러오지 못했어요. 로컬 정적 서버에서 다시 열어주세요."; });
}
