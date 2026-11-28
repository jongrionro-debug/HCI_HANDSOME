/** Consumer UI for the local HTTP service and the separate E1 practice fixture.
 * Both adapters use the same state(request_id) / command(command) contract.
 */
const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
const clone = value => structuredClone(value);
// Question loop seam: label of the "다른 방식으로 볼게요" buttons per mode (graph/questions.py MODE_NAMES).
const MODE_SWITCH_LABEL = { text_options: "글로 고를게요", photo_chips: "사진 선택지로 볼게요", select_images: "사진으로 비교할게요" };
// Image questions take the place of the 8-card grid while they are open (3-mapping 9절).
const IMAGE_ASK_MODES = ["select_images", "photo_chips", "explain_images", "relative_adjust"];
const imageAsk = ask => Boolean(ask && IMAGE_ASK_MODES.includes(ask.mode));
const blankDraft = () => ({ text: "", selections: [], reaction: "text_only", question: null, hypothesis: null,
  dislikes: [], similar: null, allBad: false, liked: {}, version: 0 });
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
  // ADR 0015 graph engine: start options and end-summary choices (local until sent).
  let startGender = "";
  let startSituation = null;
  let freeSituation = "";
  let summaryHidden = false;
  // jaehyun_work UI: composer on demand (U2), previous grid while the next is computed (U9),
  // chips that appeared on the latest turn (U3).
  let composerOpen = false;
  let askPick = { id: null, picks: [], strengths: {} };  // draft of a multi-select question answer
  let ghostCards = null;
  let seenChips = { request: null, keys: new Set() };
  let freshChips = new Set();
  const storedGender = () => { try { return localStorage.getItem("lumi.gender") ?? ""; } catch { return ""; } };
  const storeGender = value => { try { localStorage.setItem("lumi.gender", value); } catch { /* per-viewer convenience only */ } };
  startGender = storedGender();
  const summaryChoices = new Map();
  const profileChoices = new Map();
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
  // ADR 0013 graph engine: 8-card multi-select grid with product-level "별로".
  const graphMode = () => Boolean(state?.graph) && isOpen();
  const isKept = id => state?.graph?.slots?.[id] === "kept";
  const keptIds = () => Object.keys(state?.graph?.slots ?? {}).filter(isKept);
  const gridSignal = d => d.selections.some(s => !isKept(s.candidate_id)) || keptIds().some(id => !d.selections.some(s => s.candidate_id === id))
    || Object.values(d.liked).some(axes => axes.length) || d.dislikes.length || d.similar || d.allBad;
  const LIKE_HIDDEN = new Set(["Brand", "Price"]);
  const canSubmit = d => canFeedback() && (graphMode() && state.graph.set_id ? Boolean(gridSignal(d) || d.text.trim())
    : Boolean(d.selections.length || d.text.trim() || ["none", "unsure", "question_skipped"].includes(d.reaction)));
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
          ${!m.confirmed ? button("confirm", "내용 확인", `data-memory="${esc(m.ref.id)}"`) : ""}
          ${m.confirmed && (isOpen() || m.scope === "short_term") ? button("bindings", "속성 해석 검토", `data-memory="${esc(m.ref.id)}"`) : ""}
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
        <dt>적용 범위 · 대상</dt><dd>${meaning.scope === "long_term" ? "이후 요청에서 참고할 평소 취향" : "이번 요청만"} · ${esc(meaning.selector.garment_type ? garmentLabel(meaning.selector.garment_type) : "전체 대상")}${meaning.selector.slot_id ? " · 지정한 아이템" : ""}</dd>
        <dt>조건</dt><dd>${Object.entries(meaning.conditions).map(([key, value]) => `${esc({occasion: "상황", activity: "활동", goal: "목적", season: "계절"}[key] ?? key)}: ${esc(value)}`).join(" / ") || "추가 조건 없음"}</dd>
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
    if (state?.graph && state.request?.mode === "shopping" && !panel) return graphStatusMarkup();
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
  function graphStatusMarkup() {
    let text = notice;
    let tone = "";
    if (state.operation === "interpretation_pending") { text = "읽고 있어요…"; tone = "pending"; }
    if (["stale", "blocked", "error"].includes(state.operation)) { text = "화면이 바뀌었어요. 최신 화면을 불러와 주세요."; tone = "error"; }
    const error = localError ?? state.error;
    if (error) { text = error.local ? error.message : safeError(error.code); tone = "error"; }
    if (uncertain) { text = "보낸 내용이 반영됐는지 확인하지 못했어요. 다시 보내 확인해 주세요."; tone = "error"; }
    const retryRef = uniqueRef("feedback");
    const controls = uncertain ? button("retry-command", "다시 보내기", "", busy) :
      `${state.operation === "interpretation_pending" && retryRef && state.error ? button("retry-extraction", "다시 읽기", "", busy) : ""}
       ${["stale", "error", "blocked"].includes(state.operation) || error ? button("refresh", "최신 화면 불러오기", "", busy) : ""}`;
    return `<div id="operation-status" class="status" data-tone="${tone}" role="status" aria-live="polite" aria-atomic="true">${esc(text)}${controls.trim() ? `<div class="actions">${controls}</div>` : ""}</div>`;
  }
  const valueLabel = (feature, value) => state?.graph?.value_labels?.[feature]?.[value] ?? value;
  function graphChipsMarkup(g) {
    const off = !canFeedback();
    const chips = g.chips.map(chip => `<li class="chip ${chip.pinned ? "pinned" : ""} ${freshChips.has(chip.key) ? "fresh" : ""}">
      ${button("adjust", `${chip.pinned ? '<span class="pin" aria-hidden="true">●</span>' : ""}${esc(chip.value_label_ko ?? chip.value)}${freshChips.has(chip.key) ? ' <span class="new-mark">새로</span>' : ""}`,
        `data-adjust="${chip.pinned ? "unpin" : "pin"}" data-key="${esc(chip.key)}" aria-pressed="${chip.pinned}" class="chip-main" title="${chip.pinned ? "고정 풀기" : "누르면 고정해요"}"`, off)}
      ${button("adjust", "×", `data-adjust="remove" data-key="${esc(chip.key)}" class="chip-x" aria-label="${esc(chip.value_label_ko ?? chip.value)} 빼기"`, off)}</li>`);
    const memory = (g.memory?.chips ?? []).map(chip => `<li class="chip memory ${chip.enabled ? "" : "off"}">
      ${button("adjust", `<span class="memory-tag">기억</span>${esc(chip.text)}`, `data-adjust="${chip.enabled ? "memory_off" : "memory_on"}" data-key="${esc(chip.memory_id)}" class="chip-main" aria-pressed="${chip.enabled}" title="${chip.enabled ? "누르면 이번 요청에서 꺼요" : "누르면 다시 켜요"}"`, off)}</li>`);
    const evidence = g.chips.filter(chip => freshChips.has(chip.key) && chip.evidence).slice(0, 2)
      .map(chip => `<p class="evidence">고르신 ${chip.evidence.of}장 중 ${chip.evidence.with}장이 ${esc(chip.value_label_ko ?? chip.value)}</p>`).join("");
    if (!chips.length && !memory.length) return "";
    return `<div class="g-understood" aria-label="LUMI가 이해한 것"><ul class="chips">${chips.join("")}${memory.join("")}</ul>${evidence}</div>`;
  }
  function graphBannerMarkup(g) {
    const off = !canFeedback();
    const m = g.memory ?? {};
    const banners = [];
    if (g.reason_prompt) {
      const options = g.reason_prompt.options ?? g.reason_prompt.axes.map(a => ({ feature: a.feature, label: a.label_ko }));
      banners.push(`<section class="banner" aria-label="좋았던 점"><p>${esc(g.reason_prompt.question ?? "고르신 옷의 어떤 점이 좋았나요?")}</p>
        <div class="actions">${options.map(o => button("adjust", esc(o.label), `data-adjust="reason" data-feature="${esc(o.feature)}"`, off)).join("")}${button("adjust", "건너뛰기", 'data-adjust="reason_skip" class="quiet"', off)}</div></section>`);
    }
    if (m.novelty_prompt) banners.push(`<section class="banner" aria-label="새로운 스타일"><p>이번엔 새로운 스타일로 볼까요?</p>
      <div class="actions">${button("adjust", "네", 'data-adjust="novelty_yes"', off)}${button("adjust", "아니요", 'data-adjust="novelty_no" class="quiet"', off)}</div></section>`);
    if (m.taste_prompt) banners.push(`<section class="banner" aria-label="취향 변화"><p>“${esc(m.taste_prompt.text)}”와 다르게 고르고 계세요. 취향이 바뀌었나요?</p>
      <div class="actions">${button("adjust", "네, 이번엔 빼 주세요", 'data-adjust="taste_yes"', off)}${button("adjust", "아니요", 'data-adjust="taste_no" class="quiet"', off)}</div></section>`);
    if (g.ask) banners.push(askMarkup(g.ask, off));
    if (g.question && !g.reason_prompt) banners.push(`<section class="banner" aria-label="질문"><p>${esc(questionLabel(g.question))}</p>
      <div class="actions">${button("compose-toggle", "말로 답하기", "", off)}</div></section>`);
    return banners[0] ?? "";
  }
  function askMarkup(q, off) {
    // Question loop (graph/questions.py): one question per screen, the input stays open in every mode (1-modes.md).
    if (askPick.id !== q.question_id) askPick = { id: q.question_id, picks: [], strengths: {} };
    const allow = q.allow ?? [];
    const picked = id => askPick.picks.includes(id);
    const pair = q.layout === "pair";
    let body = "";
    if (q.mode === "reason_chips") {
      body = `<ul class="ask-chips">${q.options.map(o => `<li class="${picked(o.id) ? "picked" : ""}">
        ${button("ask-pick", esc(o.label), `data-option="${esc(o.id)}" aria-pressed="${picked(o.id)}" class="chip-main"`, off)}
        ${picked(o.id) ? `<span class="ask-strength" role="group" aria-label="${esc(o.label)} 정도">${[["only", "꼭 있어야 해요"], ["more", "있으면 좋아요"]].map(([s, label]) =>
          button("ask-strength", label, `data-option="${esc(o.id)}" data-strength="${s}" aria-pressed="${(askPick.strengths[o.id] ?? "more") === s}" class="quiet"`, off)).join("")}</span>` : ""}</li>`).join("")}</ul>`;
    } else if (q.options.some(o => o.image_url)) {
      body = `<ul class="ask-photos ${pair ? "pair" : ""}">${q.options.map(o => `<li>${q.multi
        ? button("ask-pick", `<img src="${esc(o.image_url)}" alt=""><span>${esc(o.label)}</span>`, `data-option="${esc(o.id)}" aria-pressed="${picked(o.id)}" class="ask-photo"`, off)
        : button("answer-q", `<img src="${esc(o.image_url)}" alt=""><span>${esc(o.label)}</span>`, `data-choice="options" data-option="${esc(o.id)}" class="ask-photo"`, off)}</li>`).join("")}</ul>`;
    } else {
      const base = q.base?.image_url ? `<img class="ask-base" src="${esc(q.base.image_url)}" alt="기준 상품">` : "";
      body = `${base}<div class="actions">${q.options.map(o => q.multi
        ? button("ask-pick", esc(o.label), `data-option="${esc(o.id)}" aria-pressed="${picked(o.id)}"`, off)
        : button("answer-q", esc(o.label), `data-choice="options" data-option="${esc(o.id)}"`, off)).join("")}</div>`;
    }
    const submit = q.multi ? button("ask-submit", "골랐어요", 'class="primary"', off || !askPick.picks.length) : "";
    const both = q.multi && pair ? button("ask-both", "둘 다 좋아요", 'class="secondary"', off) : "";
    const textAnswer = composerOpen || draft().text
      ? `<button type="submit" form="feedback-form" class="secondary" data-submit="grid" ${off ? "disabled" : ""}>글로 답하기</button>`
      : button("compose-toggle", "말로 답할게요", 'class="quiet"', off);
    return `<section class="banner ask" aria-label="질문" data-mode="${esc(q.mode)}" data-question="${esc(q.question_id)}"><p>${esc(q.prompt)}</p>${body}
      <div class="actions">${submit}${both}
      ${allow.includes("neither") ? button("answer-q", pair ? "둘 다 아니에요" : "다 별로예요", 'data-choice="neither" class="quiet"', off) : ""}
      ${allow.includes("unsure") ? button("answer-q", "잘 모르겠어요", 'data-choice="unsure" class="quiet"', off) : ""}
      ${(q.switch_to ?? []).map(m => button("answer-q", MODE_SWITCH_LABEL[m] ?? m, `data-choice="switch" data-mode="${esc(m)}" class="quiet"`, off)).join("")}
      ${q.mode === "propose_compare" ? "" : button("answer-q", "건너뛰기", 'data-choice="skip" class="quiet"', off)}${textAnswer}</div></section>`;
  }
  function memoryNoticeMarkup(g) {
    const n = g.memory_notice;
    if (!n || g.compare) return "";
    const from = n.situations.length ? `지난번 ${n.situations.map(esc).join(" · ")} 때 고른 취향` : "평소 취향";
    return `<p class="notice-line">${from}으로 골랐어요 <span class="hint">· ${n.lines.map(esc).join(" · ")}</span>
      ${button("memory-all-off", "기억 없이 보기", 'class="link"', !canFeedback())}</p>`;
  }
  function shortlistMarkup(g) {
    if (g.compare) return "";
    const items = g.shortlist ?? [];
    return `<section class="shortlist" aria-label="후보함"><div class="shortlist-head"><strong>후보함 <span class="count">${items.length}</span></strong>
      ${items.length ? "" : '<span class="hint">고른 옷이 여기에 모여요</span>'}</div>
      <ul class="thumbs">${items.slice(-6).map(item => `<li title="${esc(item.title)}">${item.image_url ? `<img src="${esc(item.image_url)}" alt="${esc(item.title)}">` : `<span>${esc(item.title)}</span>`}</li>`).join("")}</ul>
      ${button("adjust", "후보함에서 고르기", 'data-adjust="shortlist_compare" class="secondary"', !canFeedback() || !items.length)}</section>`;
  }
  function graphGridCard(card, d, refs) {
    const g = state.graph;
    const ghost = !state.cards.includes(card);
    if (g.compare) {
      return `<article class="card grid-card compare-card">${image(card)}<div class="compare-body"><h3 class="card-title">${esc(card.title)}</h3>
        <div class="actions">${button("preview-final", "이걸로 결정", `data-card="${esc(card.candidate_id)}" class="primary"`, ghost || !canFeedback() || !refs.set)}
        ${button("adjust", "빼기", `data-adjust="shortlist_remove" data-key="${esc(card.product_id)}" class="quiet"`, ghost || !canFeedback())}</div></div></article>`;
    }
    const selected = !ghost && d.selections.some(s => s.candidate_id === card.candidate_id);
    const off = ghost || !canFeedback() || !refs.set || !refs.round;
    const badge = g.slots?.[card.candidate_id] === "kept" ? '<span class="badge dark">고른 상품</span>'
      : g.slots?.[card.candidate_id] === "novel" ? '<span class="badge light" title="기억을 반영하지 않은 후보">새로움</span>' : "";
    return `<article class="card grid-card ${selected ? "selected" : ""} ${isKept(card.candidate_id) ? "kept" : ""}">
      <button type="button" class="image-pick" data-action="select" data-card="${esc(card.candidate_id)}" aria-pressed="${selected}" aria-label="${esc(card.title)} ${selected ? "선택 해제" : "선택"}" ${off ? "disabled" : ""}>${image(card)}
        ${badge}<span class="pick-mark" aria-hidden="true">✓</span></button></article>`;
  }
  function graphWorkspace() {
    const g = state.graph;
    const d = draft();
    const refs = comparison();
    if (!isOpen()) return graphDoneMarkup();
    const shown = state.cards.length ? state.cards : ghostCards ?? [];
    const loading = !state.cards.length && Boolean(ghostCards) && state.operation === "running";
    const cards = shown.map(card => graphGridCard(card, d, refs)).join("");
    const final = state.request.final_selection;
    const title = g.compare ? "후보함에서 골라 주세요" : "마음에 드는 걸 골라 주세요";
    const ready = g.progress?.ready && !g.compare && !final ? `<p class="ready-badge">취향이 꽤 좁혀졌어요 · ${button("adjust", "후보함에서 고르기", 'data-adjust="shortlist_compare" class="link"', !canFeedback())}</p>` : "";
    const empty = state.operation === "running" ? '<p class="hint loading-line">다음 8장을 고르고 있어요…</p>'
      : `<div class="empty-state"><h2>${g.compare ? "후보함이 비었어요" : g.outcome === "hidden_empty" ? "별로라고 한 상품을 빼니 남은 옷이 없어요" : state.operation === "no_results" ? "조건에 맞는 옷이 없어요" : "아직 보여 드릴 옷이 없어요"}</h2>
        <div class="actions">${g.outcome === "hidden_empty" ? button("adjust", "숨긴 옷 다시 보기", 'data-adjust="unhide"', !canFeedback()) : ""}${button("compose-toggle", "말로 조건 바꾸기", "", !canFeedback())}${g.compare ? button("explore", "계속 보기", "", !canFeedback()) : ""}</div></div>`;
    const counts = [g.shortage ? "조건에 맞는 옷이 8장보다 적어요" : "", g.hidden_count ? `숨긴 옷 ${g.hidden_count}` : ""].filter(Boolean);
    const composer = composerOpen || d.text ? `<form data-form="feedback" id="feedback-form" class="g-composer"><label for="free-text">말로 덧붙이기</label>
        <textarea id="free-text" maxlength="4000" placeholder="예: 색은 좋은데 조금 더 여유 있었으면 해요.">${esc(d.text)}</textarea></form>` : '<form data-form="feedback" id="feedback-form" hidden></form>';
    const picked = d.selections.length;
    const primary = g.compare ? button("explore", "계속 보기", 'class="secondary"', !canFeedback())
      : canSubmit(d) ? `<button type="submit" form="feedback-form" class="primary" data-submit="grid">${d.allBad ? "다른 방향으로 8장" : "다음 8장"}</button>`
      : button("explore", "다른 후보 보기", 'class="primary"', !canFeedback() || Boolean(d.text));
    const bar = `<div class="grid-bar" role="group" aria-label="이번 화면"><p class="grid-bar-summary" aria-live="polite">${d.allBad ? "이번 화면은 다 별로" : picked ? `${picked}장 골랐어요` : "마음에 드는 옷을 눌러 주세요"}</p>
      ${g.compare ? "" : button("all-bad", d.allBad ? "다 별로 취소" : "다 별로예요", `aria-pressed="${d.allBad}" class="secondary"`, !canFeedback())}
      ${g.compare ? "" : button("compose-toggle", composerOpen ? "덧붙이기 닫기" : "말로 덧붙이기", `aria-expanded="${composerOpen || Boolean(d.text)}" class="secondary"`, !canFeedback())}
      ${primary}</div>`;
    return `${reviewMarkup()}<div class="g-head"><div><h1>${title}</h1>${counts.length ? `<p class="hint">${counts.map(esc).join(" · ")}</p>` : ""}</div>${graphChipsMarkup(g)}</div>
      ${memoryNoticeMarkup(g)}${ready}${graphBannerMarkup(g)}
      <div class="workspace graph ${loading ? "is-loading" : ""}"><section aria-label="이미지 고르기"><h2 class="visually-hidden">이미지 고르기</h2>
        <div class="candidates grid" aria-busy="${loading}" ${imageAsk(g.ask) ? "hidden" : ""}>${cards}</div>${cards || imageAsk(g.ask) ? "" : empty}
        ${cards && !ghostCards && (!refs.round || !refs.set) ? `<p class="selection-note">화면 정보를 확인하지 못했어요.</p>${button("refresh", "최신 화면 불러오기")}` : ""}
        ${composer}${final ? graphFinalMarkup() : shortlistMarkup(g)}${final || imageAsk(g.ask) ? "" : bar}${graphSummaryMarkup()}${wrapMarkup()}</section></div>`;
  }
  function graphFinalMarkup() {
    const final = state.request.final_selection;
    const item = state.graph.shortlist?.find(s => s.product_id === final.product_id);
    return `<section class="wrap-up final-line" aria-label="결정한 상품"><h2>${esc(item?.title ?? "고른 상품")}으로 결정했어요</h2>
      <div class="actions">${button("explore", "계속 보기", 'class="secondary"')}${button("end", "마치기", 'class="primary"')}</div></section>`;
  }
  function graphDoneMarkup() {
    const sm = state.graph.summary;
    const saved = sm?.saved ?? [];
    const profile = sm?.profile ?? { status: "skipped", changes: [] };
    const changes = profile.status === "ready" ? `<h3>문장을 이렇게 다듬어 봤어요</h3><p class="hint">바꿀 문장만 골라 주세요. 원래 문장도 보관해요.</p>
      ${profile.changes.map(change => `<div class="proposal"><p><s>${esc(change.old)}</s><br>${esc(change.text)}</p><div class="actions seg">${[["accept", "바꾸기"], ["keep", "그대로"]].map(([value, label]) =>
        button("profile-choice", label, `data-memory="${esc(change.memory_id)}" data-choice="${value}" aria-pressed="${profileChoices.get(change.memory_id) === value}"`)).join("")}</div></div>`).join("")}
      <div class="actions">${button("profile-save", "반영하기", 'class="primary"')}</div>` : "";
    return `<section class="done graph-summary" aria-label="마친 요청"><h1>${saved.length ? "다음 요청에서 이 취향으로 시작할게요" : "저장 없이 마쳤어요"}</h1>
      ${saved.length ? `<ul class="saved">${saved.map(line => `<li>${esc(line)}</li>`).join("")}</ul><p class="hint">저장한 문장은 평소 취향에서 볼 수 있어요.</p>` : ""}
      ${profile.status === "running" ? '<p class="hint">문장을 짧게 다듬고 있어요…</p>' : ""}${changes}
      <div class="actions">${button("preferences", "평소 취향 보기", 'class="secondary"')}${button("new", "새 요청", 'class="primary"')}</div></section>`;
  }
  function garmentOptions() {
    return state?.garment_types?.length ? state.garment_types : [{ value: "Pants", label_ko: "바지" }];
  }
  function garmentLabel(value) {
    return garmentOptions().find(g => g.value === value)?.label_ko ?? value;
  }
  function contextMarkup() {
    if (!graphMode() || panel) return "";
    const g = state.graph;
    const items = [...g.situations.map(s => s.raw || s.value), { men: "남성", women: "여성" }[g.gender],
      garmentLabel(state.request.targets?.[0]?.garment_type ?? "")].filter(Boolean);
    return items.length ? `<div class="context" aria-label="이번 요청">${items.map(item => `<span>${esc(item)}</span>`).join("")}</div>` : "";
  }
  function longTermMemories() {
    return state.memories.filter(m => m.scope === "long_term" && !["withdrawn", "superseded"].includes(m.status));
  }
  function prefsMarkup() {
    const taste = state.graph?.taste;
    if (taste) {
      const groups = new Map();
      for (const item of taste) {
        const label = item.situation ? `${item.situation}할 때` : "평소에도";
        if (!groups.has(label)) groups.set(label, []);
        groups.get(label).push(item.text);
      }
      const ordered = [...groups.entries()].sort(([a], [b]) => (a === "평소에도" ? -1 : b === "평소에도" ? 1 : 0));
      return `<section class="prefs" aria-labelledby="prefs-title"><h1 id="prefs-title">평소 취향</h1>
        ${ordered.length ? ordered.map(([label, lines]) => `<section class="pref-group"><h2>${esc(label)}</h2><ul>${lines.map(line => `<li>${esc(line)}</li>`).join("")}</ul></section>`).join("")
          : '<div class="empty-state"><h2>아직 기억하는 취향이 없어요</h2><p>요청을 마칠 때 고른 문장이 여기에 쌓여요.</p></div>'}
        <div class="actions">${button("teach-preferences", "한마디로 더하기", 'class="secondary"')}${button("close-preferences", state.request ? "보던 화면으로" : "새 요청", 'class="primary"')}</div></section>`;
    }
    const items = longTermMemories();
    return `<section class="prefs" aria-labelledby="prefs-title"><div><h1 id="prefs-title">평소 취향</h1>
      <p class="section-intro">이후 활용에 동의한 문장만 여기에 있어요. 다음 요청을 시작할 때 이 문장으로 시작해요.</p></div>
      ${items.length ? `<ul>${items.map(m => `<li>${esc(m.content)}</li>`).join("")}</ul>` : '<div class="empty-state"><h2>아직 저장한 평소 취향이 없어요</h2><p>요청을 마칠 때 고른 문장이나 한마디로 알려 준 취향이 여기에 쌓여요.</p></div>'}
      <div class="actions">${button("teach-preferences", "한마디로 알려 주기", 'class="primary"')}${button("close-preferences", state.request ? "보던 화면으로" : "새 요청 시작")}</div>
      <p class="hint">적은 내용은 내용 확인과 이후 활용 동의를 따로 거친 뒤에 저장돼요.</p></section>`;
  }
  function startMarkup() {
    if (state.engine === "graph" && startMode === "shopping") return graphStartScreen();
    const onboarding = startMode === "onboarding";
    const requests = state.requests.filter(r => r.mode === "shopping" && r.status !== "expired");
    const remembered = onboarding ? [] : longTermMemories().slice(0, 3);
    return `<div class="start"><section class="start-main"><h1>${onboarding ? "평소 어떤 옷을 좋아하세요?" : "이번엔 어떤 옷을 찾을까요?"}</h1>
      <p>${onboarding ? "좋아하는 스타일·색·핏을 짧게 적어 주세요. 해석한 내용을 확인한 뒤 이후 활용 여부를 따로 선택할 수 있어요." : "아이템과 입을 상황을 짧게 알려주세요. 이전 요청의 조건은 자동으로 이어지지 않아요."}</p>
      <form class="start-form" data-form="start"><div><label for="target">찾을 아이템</label><select id="target" name="target">${garmentOptions().map(g => `<option value="${esc(g.value)}">${esc(g.label_ko)}${fixture ? " · 화면 연습 대상" : ""}</option>`).join("")}</select></div>
        ${state.engine === "graph" && !onboarding ? graphStartMarkup() : ""}
        <div><label for="initial-text">${onboarding ? "평소 취향 한마디 (선택)" : "입을 상황과 원하는 느낌 (선택)"}</label>
          <textarea id="initial-text" maxlength="4000" placeholder="${onboarding ? "예: 평소에는 여유 있는 바지를 자주 입어요." : state.engine === "graph" ? "예: 깔끔하게 입을 네이비 셔츠를 찾고 있어요." : "예: 이번 회사 발표에 입을 단정한 바지를 찾고 있어요."}">${esc(initialText[startMode])}</textarea></div>
        <div class="actions"><button class="primary" ${disabled() ? "disabled" : ""}>${onboarding ? "취향 살펴보기" : state.engine === "graph" ? "첫 8장 보기" : "새 요청 시작"}</button>
          ${onboarding ? button("skip-onboarding", "저장 없이 요청 시작", 'class="quiet"') : ""}
          ${state.request ? button("cancel-start", "기존 요청으로 돌아가기", 'class="quiet"') : ""}</div>
        <p class="hint">${fixture ? "합성 이미지와 문장으로 조작을 연습합니다. 실제 상품 검색이나 저장은 하지 않아요." : "처음부터 모든 조건을 정할 필요는 없어요."}</p>
      </form></section>
      ${remembered.length || requests.length ? `<aside class="start-aside">
      ${remembered.length ? `<section aria-label="기억하는 취향"><h2>기억하는 취향으로 시작해요</h2><ul>${remembered.map(m => `<li>${esc(m.content)}</li>`).join("")}</ul><p class="hint">동의한 문장만 써요. 탐색 중에 하나씩 끌 수 있어요.</p></section>` : ""}
      ${requests.length ? `<section class="request-list"><h2>이어서 보기</h2><p class="hint">열린 요청은 이어서 탐색하고, 종료한 요청은 요약을 볼 수 있어요.</p>${requests.map((r, index) => button("resume", `${esc(garmentLabel(r.targets?.[0]?.garment_type ?? "Pants"))} 요청 ${index + 1} · ${r.status === "open" ? "탐색 이어하기" : "종료 요약"}`, `data-request="${esc(r.id)}"`)).join("")}</section>` : ""}
      </aside>` : ""}</div>`;
  }
  function graphStartScreen() {
    const remembered = longTermMemories().slice(0, 3);
    const requests = state.requests.filter(r => r.mode === "shopping" && r.status === "open");
    const options = garmentOptions();
    const target = options.length === 1 ? `<input type="hidden" id="target" name="target" value="${esc(options[0].value)}">`
      : `<div><label for="target">찾을 옷</label><select id="target" name="target">${options.map(g => `<option value="${esc(g.value)}">${esc(g.label_ko)}</option>`).join("")}</select></div>`;
    return `<div class="start g-start"><section class="start-main"><h1>오늘은 어디에 입을 옷을 찾을까요?</h1>
      <form class="start-form" data-form="start">${target}${graphStartMarkup()}
        <div><label for="initial-text">원하는 느낌 <span class="sit-hint">(선택)</span></label>
          <textarea id="initial-text" maxlength="4000" placeholder="예: 깔끔한 네이비 셔츠">${esc(initialText.shopping)}</textarea></div>
        ${remembered.length ? `<section class="remembered" aria-label="기억하는 취향"><h2>이렇게 기억하고 있어요</h2><ul>${remembered.map(m => `<li>${esc(m.content)}</li>`).join("")}</ul><p class="hint">시작한 뒤에 하나씩 끌 수 있어요.</p></section>` : ""}
        <div class="actions"><button class="primary" ${disabled() ? "disabled" : ""}>첫 8장 보기</button>
          ${state.request ? button("cancel-start", "보던 화면으로", 'class="quiet"') : ""}</div>
      </form></section>
      ${requests.length ? `<aside class="start-aside"><section class="request-list"><h2>이어서 보기</h2>${requests.map((r, index) => button("resume", `요청 ${index + 1} 이어서 보기`, `data-request="${esc(r.id)}"`)).join("")}</section></aside>` : ""}</div>`;
  }
  function graphStartMarkup() {
    const situations = [["출근", "출근", "단정하게"], ["데이트", "데이트", "조금 신경 써서"], ["주말", "주말", "편하게"], ["free", "나의 상황", "직접 적기"]];
    return `<fieldset class="start-gender"><legend>누구 옷을 볼까요?</legend><div class="actions">${[["", "전체"], ["men", "남성"], ["women", "여성"]].map(([value, label]) =>
        button("gender", label, `data-gender="${value}" aria-pressed="${startGender === value}"`)).join("")}</div></fieldset>
      <fieldset class="start-situation"><legend>어떤 상황에 입나요? <span class="sit-hint">(선택)</span></legend><div class="actions">${situations.map(([value, label, hint]) =>
        button("situation", `${label} <span class="sit-hint">${hint}</span>`, `data-situation="${value}" aria-pressed="${startSituation === value}"`)).join("")}</div>
        ${startSituation === "free" ? `<label for="free-situation">어떤 상황인가요?</label><input id="free-situation" maxlength="200" placeholder="예: 팀 회식, 친구 결혼식 뒤풀이" value="${esc(freeSituation)}">` : ""}</fieldset>`;
  }
  function startSituationValue() {
    if (startSituation === null) return null;
    if (startSituation !== "free") return { kind: "chip", value: startSituation };
    return freeSituation.trim() ? { kind: "free", text: freeSituation.trim() } : null;
  }
  function graphSummaryMarkup() {
    const sm = state.graph?.summary;
    if (!sm || (sm.status === "draft" && (!isOpen() || summaryHidden))) return "";
    if (sm.status === "draft" || sm.status === "polishing") {
      const polishing = sm.status === "polishing";
      const situationButton = sm.situation_label ? `${esc(sm.situation_label)}할 때만` : null;
      const rows = sm.proposals.map(p => `<div class="proposal"><p>${esc(p.text)}</p><div class="actions seg" role="group" aria-label="기억할 범위">${[
        ["baseline", "평소에도"], ...(situationButton ? [["situation", situationButton]] : [])].map(([value, label]) =>
        button("summary-choice", label, `data-proposal="${esc(p.id)}" data-choice="${value}" aria-pressed="${summaryChoices.get(p.id) === value}"`, disabled() || polishing)).join("")}</div></div>`).join("");
      const count = sm.proposals.filter(p => ["baseline", "situation"].includes(summaryChoices.get(p.id))).length;
      return `<div class="sheet-backdrop"><section class="wrap-up graph-summary sheet" role="dialog" aria-modal="true" aria-labelledby="summary-title"><h2 id="summary-title">다음에도 기억할까요?</h2>
        ${polishing ? '<p class="hint">문장을 다듬고 있어요…</p>' : rows || '<p class="hint">이번에는 기억할 만한 문장이 없어요.</p>'}
        <p class="hint">고르지 않은 문장은 저장하지 않아요.</p>
        <div class="actions">${button("summary-cancel", "계속 보기", 'class="secondary"')}${button("summary-save", count ? `${count}개 저장하고 마치기` : "저장 없이 마치기", 'class="primary"', disabled() || polishing)}</div></section></div>`;
    }
    const profile = sm.profile ?? { status: "skipped", changes: [] };
    const view = sm.profile_view;
    const viewMarkup = view && (view.usual.length || view.situations.length) ? `<h3>지금 기억하는 취향</h3>
      ${view.usual.length ? `<p class="hint">평소</p><ul>${view.usual.map(line => `<li>${esc(line)}</li>`).join("")}</ul>` : ""}
      ${view.situations.map(group => `<p class="hint">${esc(group.situation)}</p><ul>${group.lines.map(line => `<li>${esc(line)}</li>`).join("")}</ul>`).join("")}` : "";
    const changes = profile.status === "ready" ? `<h3>취향 프로필을 이렇게 다듬었어요</h3><p class="hint">바뀐 문장만 보여요. 원래 문장과 근거는 그대로 보관해요.</p>
      ${profile.changes.map(change => `<div class="proposal"><p><s>${esc(change.old)}</s><br>${esc(change.text)}</p><div class="actions">${[["accept", "바꾸기"], ["keep", "그대로"]].map(([value, label]) =>
        button("profile-choice", label, `data-memory="${esc(change.memory_id)}" data-choice="${value}" aria-pressed="${profileChoices.get(change.memory_id) === value}"`)).join("")}</div></div>`).join("")}
      <div class="actions">${button("profile-save", "프로필 반영", 'class="primary"')}</div>` : "";
    return `<section class="wrap-up graph-summary" aria-label="저장한 취향"><h2>${sm.saved.length ? "다음 요청에 쓸 문장을 저장했어요" : "저장 없이 마쳤어요"}</h2>
      ${sm.saved.length ? `<ul>${sm.saved.map(line => `<li>${esc(line)}</li>`).join("")}</ul>` : ""}
      ${profile.status === "running" ? '<p class="hint">취향 프로필을 짧게 다듬고 있어요.</p>' : profile.status === "unavailable" ? '<p class="hint">프로필 다듬기를 지금은 할 수 없어요. 저장한 문장은 그대로 써요.</p>' : ""}
      ${changes}${viewMarkup}</section>`;
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
    const confirmed = state.memories.filter(m => m.scope === "short_term" && m.confirmed && m.status === "active" && m.reusable !== false);
    const show = request.status !== "open" || final || request.mode === "onboarding";
    if (!show && !finalPreview) return "";
    const previewCard = state.cards.find(c => c.candidate_id === finalPreview);
    if (state.graph && request.mode === "shopping" && !(previewCard && !final)) return "";
    if (previewCard && !final) {
      const facts = (previewCard.facts ?? []).filter(f => f.values?.length);
      return `<div class="sheet-backdrop"><section class="wrap-up sheet decide" role="dialog" aria-modal="true" aria-labelledby="decide-title">${image(previewCard)}
        <div class="decide-body"><h2 id="decide-title">이 상품으로 결정할까요?</h2><p class="product">${esc(previewCard.title)}</p>
        ${facts.length ? `<dl class="card-facts">${facts.filter(f => !LIKE_HIDDEN.has(f.feature)).map(f => `<div><dt>${esc(f.label_ko)}</dt><dd>${esc(f.values.map(v => valueLabel(f.feature, v)).join(", "))}</dd></div>`).join("")}</dl>` : ""}
        <div class="actions">${button("cancel-final", state.graph ? "다시 보기" : "계속 탐색", 'class="secondary"')}${button("confirm-final", state.graph ? "이걸로 결정" : "이 상품 확정", 'class="primary"', !canFeedback() || !comparison().set)}</div>
        <p class="hint">결정해도 취향은 저장되지 않아요.</p></div></section></div>`;
    }
    return `<section class="wrap-up" aria-label="선택과 마무리"><h2>${request.status === "closed" ? "탐색을 마쳤어요" : previewCard ? "이 상품으로 결정할까요?" : final ? "상품을 선택했어요" : "평소 취향을 확인해 주세요"}</h2>
      <p class="section-intro">${previewCard ? esc(previewCard.title) : final ? `${esc(selected?.title ?? "선택한 상품")} · ${request.status === "open" ? "탐색은 아직 열려 있어요." : "선택 내용은 요약에 남아요."}` : request.status === "closed" ? "상품 선택 없이 종료했어요." : "내용 확인과 이후 활용 선택을 각각 진행할 수 있어요."}</p>
      ${previewCard ? `<div class="actions">${button("confirm-final", "이 상품 확정", 'class="primary"', !canFeedback() || !comparison().set)}${button("cancel-final", "계속 탐색")}</div>` : ""}
      ${final && isOpen() ? button("explore", "계속 탐색") : ""}
      ${request.status === "closed" && state.graph?.summary ? "" : request.status === "closed" ? confirmed.length ? `<h3>이후에도 활용할 내용이 있나요?</h3><p class="hint">원하는 항목을 고른 뒤 활용 범위와 동의를 따로 확인해요.</p>${confirmed.map(m => `<div class="save-item"><label class="check-label"><input type="checkbox" data-save="${esc(m.ref.id)}" ${saveItems.has(m.ref.id) ? "checked" : ""}>${esc(m.content)}</label>${button("future", "이 항목의 이후 활용 검토", `data-memory="${esc(m.ref.id)}"`, disabled() || !saveItems.has(m.ref.id))}</div>`).join("")}` : '<p class="hint">다음에도 활용할 내용이 있다면 반영 내용에서 먼저 확인해 주세요. 저장하지 않고 새 요청을 시작해도 괜찮아요.</p>' : '<p class="hint">장기 활용 동의는 이 대화를 종료한 뒤 요약 화면에서 진행해요.</p>'}
      <div class="actions">${isOpen() ? button("end", request.mode === "onboarding" ? "온보딩 마치기" : "탐색 종료", 'class="primary"') : ""}
      ${request.mode === "onboarding" ? button("start-after-onboarding", "저장 없이 새 요청", 'class="quiet"') : ""}
      ${request.status === "closed" ? button("new", "새 요청 시작") : ""}</div>
      <p class="hint">최종 선택과 탐색 종료는 평소 취향을 저장하거나 이후 활용에 동의한 것으로 처리되지 않아요.</p>
    </section>`;
  }
  function workspaceMarkup() {
    if (state.graph && state.request.mode === "shopping") return graphWorkspace();
    const d = draft();
    const refs = comparison();
    const activeQuestion = state.questions.find(q => q.ref.id === d.question && q.status === "open");
    const cards = state.cards.map(card => listCard(card, d, refs)).join("");
    function listCard(card, d, refs) {
      const selection = d.selections.find(s => s.candidate_id === card.candidate_id);
      const interpretation = state.comparison?.options.find(o => o.candidate_id === card.candidate_id);
      const disliked = d.dislikes.includes(card.candidate_id);
      return `<article class="card ${selection ? "selected" : ""} ${disliked ? "disliked" : ""}">${image(card, selection?.part_ref?.box)}<div class="card-body"><h3 class="card-title">${esc(card.title)}</h3>
        ${card.facts?.length ? `<dl class="card-facts">${card.facts.map(f => `<div><dt>${esc(f.label_ko)}</dt><dd>${esc(f.values.join(", "))}${f.origin === "model" ? ' <span class="fact-origin" title="상품 사진·문구에서 모델이 보완한 값">추정</span>' : ""}</dd></div>`).join("")}</dl>` : ""}
        ${interpretation ? `<p>${esc(interpretation.label)}</p><p class="hint">${esc(interpretation.meaning)}</p>${button("comparison-choose", d.hypothesis?.candidate_id === card.candidate_id ? "이 조건 선택됨" : "이 조건 선택", `data-card="${esc(card.candidate_id)}" class="primary" aria-pressed="${d.hypothesis?.candidate_id === card.candidate_id}"`, !canFeedback())}` : ""}
        ${graphMode() && state.graph.slots?.[card.candidate_id] === "novel" ? '<p class="slot-badge">새로움 · 기억을 반영하지 않은 후보</p>' : ""}
        ${disliked ? '<p class="selected-label">별로 · 이 상품만 덜 보여요</p>' : ""}${d.similar === card.candidate_id ? '<p class="selected-label">이 상품과 비슷한 후보를 더 보여줘요</p>' : ""}
        ${selection ? `<p class="selected-label">${d.hypothesis?.candidate_id === card.candidate_id ? "조건 선택 중" : selection.part_ref ? "부분 선택 중" : "전체 선택 중"} · 반영 전</p>` : ""}
        ${button("select", selection ? "선택 해제" : "전체 선택", `data-card="${esc(card.candidate_id)}" aria-pressed="${Boolean(selection)}"`, !canFeedback() || !refs.set || !refs.round)}
        ${button("part", "부분 선택", `data-card="${esc(card.candidate_id)}"`, !canFeedback() || !safeImage(card) || !loadedImages.has(imageKey(card)) || !refs.set || !refs.round)}
        ${graphMode() && state.graph.set_id ? `${button("dislike", d.dislikes.includes(card.candidate_id) ? "별로 취소" : "별로", `data-card="${esc(card.candidate_id)}" aria-pressed="${d.dislikes.includes(card.candidate_id)}"`, !canFeedback() || d.allBad)}
          ${button("similar", d.similar === card.candidate_id ? "비슷한 거 취소" : "이거랑 비슷한 거", `data-card="${esc(card.candidate_id)}" aria-pressed="${d.similar === card.candidate_id}"`, !canFeedback() || d.allBad)}` : ""}
        ${state.request.mode === "shopping" ? button("preview-final", "최종 상품으로 살펴보기", `data-card="${esc(card.candidate_id)}" class="quiet"`, !canFeedback() || !refs.set) : ""}</div></article>`;
    }
    const noCards = !isOpen() ? "" : graphMode() && state.operation === "running" ? '<p class="hint">다음 후보를 고르고 있어요.</p>' : `<div class="empty-state"><h2>${state.graph?.outcome === "hidden_empty" ? "별로라고 한 상품을 빼니 남은 후보가 없어요" : state.operation === "no_results" ? "조건에 맞는 상품이 없어요" : "아직 비교할 후보가 없어요"}</h2><p>조건을 그대로 두거나 글로 조정할 수 있어요. 상품을 고르지 않고 탐색을 마쳐도 괜찮아요.</p>${state.graph?.outcome === "hidden_empty" ? button("adjust", "숨김 해제", 'data-adjust="unhide"', !canFeedback()) : ""}</div>`;
    const questionItems = (isOpen() ? state.questions : []).filter(q => q.status === "open").map(q => `<section class="question"><h3>${esc(questionLabel(q.text))}</h3>
      <p class="hint">답을 고르거나 자유롭게 적어주세요. 반영하기 전까지 바꿀 수 있어요.</p><div class="actions">${q.options.map((option, index) => button("answer", esc(option), `data-question="${esc(q.ref.id)}" data-option="${index}"`, !canFeedback())).join("")}
      ${button("skip-question", "질문 건너뛰기", `data-question="${esc(q.ref.id)}" class="quiet"`, !canFeedback())}</div></section>`);
    const questions = (questionItems[0] ?? "") + (questionItems.length > 1
      ? `<details><summary>다른 확인 질문 ${questionItems.length - 1}개</summary>${questionItems.slice(1).join("")}</details>` : "");
    const onboardingText = state.request.mode === "onboarding" && !cards;
    const grid = graphMode() && Boolean(state.graph.set_id);
    const likedCount = d.selections.reduce((n, s) => n + (d.liked[s.candidate_id]?.length ?? 0), 0);
    const gridBar = `<div class="grid-bar" role="group" aria-label="이번 화면 반영"><p class="grid-bar-summary" aria-live="polite"><strong>${d.allBad ? "이번 화면은 다 별로 · 고른 상품만 남겨요" : d.selections.length ? `${d.selections.length}장 선택${likedCount ? ` · 좋았던 점 ${likedCount}개` : ""}` : "마음에 드는 이미지를 눌러 주세요"}</strong><span class="hint">고른 상품은 다음 화면 맨 앞에 남아요.</span></p>
        ${button("end", "선택 없이 마치기", 'class="quiet"')}${button("explore", "다른 후보 보기", "", !canFeedback() || Boolean(d.text || gridSignal(d)))}
        ${button("all-bad", d.allBad ? "다 별로 취소" : "다 별로예요", `aria-pressed="${d.allBad}"`, !canFeedback())}
        <button type="submit" form="feedback-form" class="primary" data-submit="grid" ${canSubmit(d) ? "" : "disabled"}>${d.allBad ? "다른 방향으로 8장" : "반영하고 다음 8장"}</button></div>`;
    return `<div class="page-heading"><div><h1>${state.request.mode === "onboarding" ? "평소 취향을 찾아볼까요?" : state.request.status === "closed" ? "이번 요청의 탐색 요약" : "원하는 느낌에 가까운 쪽을 골라주세요"}</h1><p>${!isOpen() ? "이번 대화의 내용을 확인하고, 다음에도 활용할 항목을 선택할 수 있어요." : onboardingText ? "평소 취향은 글로 등록해요. 해석한 내용을 확인한 뒤 온보딩을 마치면 이후 활용 여부를 고를 수 있어요." : grid ? "여러 장 골라도 돼요. 고른 이미지에서 좋았던 점을 누르면 그 점을 더 반영해요." : "하나만 골라도, 여러 장을 골라도 좋아요. 이유는 글로 덧붙일 수 있어요."}</p></div></div>
      <div class="workspace ${isOpen() ? "open" : "closed"} ${state.comparison ? "hypothesis-comparison" : ""} ${grid ? "graph" : ""}"><section aria-label="이미지 비교"><h2 ${grid ? 'class="visually-hidden"' : ""}>${!isOpen() ? "대화 종료 요약" : onboardingText ? "평소 취향 적기" : "나란히 보고 선택하기"}</h2>${grid ? "" : `<p class="section-intro">${!isOpen() ? "저장 없이 마치거나, 확인한 내용을 이후 요청에 활용할 수 있어요." : onboardingText ? "이 단계에서는 상품 이미지를 보여 주지 않아요. 상품은 온보딩을 마친 뒤 새 요청에서 볼 수 있어요." : fixture ? "색 영역으로 만든 합성 자료예요. 실제 상품이나 추천 결과가 아니에요." : state.comparison ? "원하는 해석을 고르거나, 글로 수정할 수 있어요." : graphMode() ? "마음에 드는 이미지를 눌러 고르고 반영하면 다음 8장이 바뀌어요." : "선택만으로 후보가 바뀌지 않아요. 글과 함께 반영할 수 있어요."}</p>`}
        ${state.comparison ? `<section class="question" aria-label="요구에 맞는 조건 비교"><h3>${esc(state.comparison.prompt)}</h3><p>조건을 고른 뒤 아래에서 한 번에 반영해 주세요. 좋은 이유를 함께 적어도 되고, 선택만 보내도 돼요.</p><div class="actions">${button("comparison-neither", "둘 다 원하는 해석이 아니에요", "", !canFeedback())}${button("comparison-unsure", "아직 잘 모르겠어요", "", !canFeedback())}</div><p class="hint">이유나 바꾸고 싶은 점은 선택 사항이에요. 선택과 설명이 다르면 함께 확인해요.</p></section>` : ""}
        <div class="candidates ${grid ? "grid" : ""}">${cards}</div>${cards || onboardingText ? "" : noCards}
        ${cards && (!refs.round || !refs.set) ? `<p class="selection-note">비교 회차 정보를 확인할 수 없어 이미지 응답을 보류했어요. 글로 계속하거나 최신 화면을 확인해 주세요.</p>${button("refresh", "최신 화면 확인")}` : ""}
        ${grid ? gridBar : isOpen() ? `<div class="candidate-actions"><fieldset class="reactions"><legend>고르기 어려울 때</legend><div class="actions">
          ${graphMode() && state.graph.set_id ? button("all-bad", d.allBad ? "다 별로 취소" : "다 별로", `aria-pressed="${d.allBad}"`, !canFeedback()) : [["none", "마음에 드는 게 없어요"], ["unsure", "잘 모르겠어요"], ["text_only", "텍스트만 보낼게요"]].map(([reaction, label]) => button("reaction", label, `data-reaction="${reaction}" aria-pressed="${d.reaction === reaction && !d.selections.length}"`, !canFeedback() || (reaction !== "text_only" && (!refs.round || !refs.set)))).join("")}
        </div></fieldset><p class="selection-note">${d.selections.length ? `${d.selections.length}개를 선택했어요.` : "이미지 선택 없이도 이야기할 수 있어요."} ${graphMode() ? "이미지를 눌러 고르고, 좋았던 점을 누르면 그 점을 더 반영해요. 고른 상품은 다음 화면 맨 앞에 남아요." : "개별 속성이나 선택하지 않은 후보의 비선호를 확정하지 않아요."}</p>
        <div class="actions">${button("explore", "다른 후보 보기", "", !canFeedback() || Boolean(d.text || gridSignal(d)))}${button("end", "상품 선택 없이 종료", 'class="quiet"')}</div>
        ${d.text || d.selections.length ? '<p class="hint">작성 중인 선택과 글을 먼저 반영하거나, 그대로 둔 채 탐색을 마칠 수 있어요.</p>' : ""}</div>` : ""}
        ${partMarkup()}${graphSummaryMarkup()}${wrapMarkup()}</section>
        <aside class="conversation" aria-label="대화와 반영 내용">${reviewMarkup()}${questions}
          <section><details id="reflected-info" ${detailsOpen ? "open" : ""}><summary>반영 내용 보기</summary><p class="hint">이번 요청과 평소 취향은 구분해요. 평소 취향 수정은 별도 검토가 필요해요.</p>${memories()}</details></section>
          <section class="composer"><form data-form="feedback" id="feedback-form"><label for="free-text">${!isOpen() ? "종료 전에 작성하던 글" : grid && !activeQuestion ? "말로 덧붙이기" : state.comparison ? "좋은 이유나 바꾸고 싶은 점 (선택)" : activeQuestion ? "질문에 대한 답과 덧붙일 이야기" : "선택에 덧붙이거나, 글로 이야기해 주세요"}</label>
            <textarea id="free-text" maxlength="4000" placeholder="예: A의 색은 좋지만, 더 여유 있는 형태가 좋아요." ${isOpen() ? "" : "readonly"}>${esc(d.text)}</textarea>
            <div class="actions"><span class="hint">${graphMode() && state.graph.set_id ? (gridSignal(d) ? "이미지 반응 + 글 함께 반영" : "글만 반영") : d.reaction === "selected" ? "선택 + 글 함께 반영" : {none: "후보 없음으로 응답", unsure: "판단 보류로 응답", text_only: "글만 반영", question_skipped: "질문 건너뛰기"}[d.reaction]}</span>
              ${grid ? "" : `<button class="primary" ${canSubmit(d) ? "" : "disabled"}>선택과 글 반영</button>`}</div>
            <p class="hint">${grid ? "아래 반영 버튼을 누르면 고른 이미지와 함께 반영돼요. 기억 저장은 마칠 때 따로 물어봐요." : isOpen() ? "반영하기 전까지 자유롭게 고칠 수 있어요." : "종료한 요청이에요. 작성하던 초안은 이 화면에 남겨 두었어요."}</p>
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
    root.innerHTML = `<header class="topbar"><span class="wordmark" aria-label="LUMI">LUMI</span>${contextMarkup()}<nav aria-label="주요 메뉴">${graphMode() && !panel ? `<span class="turn">${esc(state.graph.turn)}번째 화면${state.graph.progress ? ` · 후보함 ${esc(state.graph.progress.shortlist_count)}` : ""}</span>${button("end", "마치기", 'class="link"')}` : ""}${button("preferences", "평소 취향", panel === "preferences" ? 'aria-current="page"' : "")}${button("new", "새 요청")}</nav></header>
      ${fixture ? `<div class="fixture-strip"><strong>화면 연습</strong><span>합성 자료 · 실제 저장·모델 호출 없음 · 새로고침하면 초기화</span><label>상태 연습<select id="fixture-scenario" ${busy ? "disabled" : ""}>${Object.entries(scenarios).map(([key, label]) => `<option value="${key}" ${adapter.scenario === key ? "selected" : ""}>${esc(label)}</option>`).join("")}</select></label></div>` : ""}
      <main class="shell" id="workspace" tabindex="-1" aria-busy="${busy || state?.operation === "running"}">${statusMarkup()}${state ? panel === "preferences" ? prefsMarkup() : panel === "start" || !state.request ? startMarkup() : workspaceMarkup() : '<p class="boot-message">화면을 불러오고 있어요.</p>'}</main>`;
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
    if (next.graph && next.operation === "running" && !next.cards.length) ghostCards = state?.cards?.length ? state.cards : ghostCards;
    else ghostCards = null;
    state = next;
    if (previousRequest !== requestId()) { generation += 1; part = null; editing = null; finalPreview = null; composerOpen = false; ghostCards = null; }
    if (state.graph) {
      const keys = new Set(state.graph.chips.map(chip => chip.key));
      if (seenChips.request === requestId() && state.operation !== "running") freshChips = new Set([...keys].filter(k => !seenChips.keys.has(k)));
      else if (seenChips.request !== requestId()) freshChips = new Set();
      if (state.operation !== "running") seenChips = { request: requestId(), keys };
    }
    const nextSet = uniqueRef("candidate_set");
    if (!sameRef(previousSet, nextSet)) {
      const d = draft();
      const kept = state.cards.filter(c => isKept(c.candidate_id)).map(c => ({ target_id: c.target_id, candidate_id: c.candidate_id, part_ref: null }));
      if (d.selections.length && !kept.length) notice = "후보가 바뀌어 이미지 선택을 해제했어요. 작성하던 글은 그대로예요.";
      else if (kept.length) notice = "";
      d.selections = kept; d.hypothesis = null; d.dislikes = []; d.similar = null; d.allBad = false; d.liked = {};
      d.reaction = kept.length ? "selected" : d.reaction === "selected" ? "text_only" : d.reaction;
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
    if (!disposed && (["running", "interpretation_pending"].includes(state?.operation) || state?.graph?.summary?.profile?.status === "running") && !state.error && !localError) {
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
        notice = state?.graph && state.request?.mode === "shopping" ? "" : fixture ? "화면 연습에 반영했어요. 실제 저장이나 처리는 하지 않았어요." : result.outcome === "accepted" ? "입력을 접수했어요. 해석 완료와 내용 확인은 별도예요." : "변경 내용을 반영했어요.";
        if (["grid_feedback", "submit_feedback"].includes(outgoing.action.op)) composerOpen = false;
        if (outgoing.action.op === "start_request") {
          panel = null;
          const mode = outgoing.action.mode;
          if (initialText[mode] === (outgoing.action.text ?? "")) initialText[mode] = "";
        }
        if (outgoing.action.op === "select_final") finalPreview = null;
        if (["submit_feedback", "respond_comparison", "grid_feedback"].includes(outgoing.action.op)) {
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
    if (graphMode() && state.graph.set_id && refs.round && refs.set?.id === state.graph.set_id) return {
      op: "grid_feedback", round_id: refs.round.id, candidate_set_id: refs.set.id, selections: clone(d.selections),
      dislikes: [...d.dislikes], similar: d.similar, all_bad: d.allBad, text: d.text.trim() ? d.text : null, question_id: null,
      liked: Object.fromEntries(Object.entries(d.liked).filter(([id, axes]) => axes.length && d.selections.some(s => s.candidate_id === id))) };
    if (d.hypothesis && state.comparison) return { op: "respond_comparison",
      candidate_set_ref: clone(state.comparison.candidate_set_ref), ...clone(d.hypothesis), text: d.text.trim() ? d.text : null };
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
      case "comparison-choose":
      case "comparison-neither":
      case "comparison-unsure":
        if (state.comparison) {
          d.hypothesis = { candidate_id: b.dataset.action === "comparison-choose" ? card.candidate_id : null,
            decision: b.dataset.action === "comparison-choose" ? "choose" : b.dataset.action === "comparison-neither" ? "neither" : "unsure" };
          d.selections = d.hypothesis.decision === "choose" ? [{ target_id: card.target_id, candidate_id: card.candidate_id, part_ref: null }] : [];
          d.reaction = d.hypothesis.decision === "choose" ? "selected" : d.hypothesis.decision === "neither" ? "none" : "unsure";
          d.version += 1; render(); root.querySelector("#free-text")?.focus();
        }
        break;
      case "new": panel = "start"; startMode = "shopping"; part = null; render(); focusMain(); break;
      case "preferences": panel = "preferences"; part = null; render(); focusMain(); break;
      case "close-preferences": panel = null; render(); focusMain(); break;
      case "teach-preferences": panel = "start"; startMode = "onboarding"; render(); root.querySelector("#initial-text")?.focus(); break;
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
        d.hypothesis = null;
        const selected = d.selections.findIndex(s => s.candidate_id === card.candidate_id);
        d.allBad = false;
        if (selected >= 0) { d.selections.splice(selected, 1); delete d.liked[card.candidate_id]; }
        else d.selections.push({ target_id: card.target_id, candidate_id: card.candidate_id, part_ref: null });
        d.reaction = d.selections.length ? "selected" : "text_only"; d.version += 1; render();
        root.querySelectorAll('[data-action="select"]').forEach(button => { if (button.dataset.card === card.candidate_id) button.focus({ preventScroll: true }); });
        break;
      }
      case "like": {
        if (!card || !d.selections.some(s => s.candidate_id === card.candidate_id)) return;
        const axes = d.liked[card.candidate_id] ?? [];
        d.liked[card.candidate_id] = axes.includes(b.dataset.feature) ? axes.filter(a => a !== b.dataset.feature) : [...axes, b.dataset.feature];
        d.version += 1; render(); break;
      }
      case "dislike":
        if (!card) return;
        d.dislikes = d.dislikes.includes(card.candidate_id) ? d.dislikes.filter(id => id !== card.candidate_id) : [...d.dislikes, card.candidate_id];
        d.version += 1; render(); break;
      case "similar": if (!card) return; d.similar = d.similar === card.candidate_id ? null : card.candidate_id; d.version += 1; render(); break;
      case "all-bad":
        d.allBad = !d.allBad;
        if (d.allBad) {
          d.selections = d.selections.filter(s => isKept(s.candidate_id)); d.dislikes = []; d.similar = null;
          d.liked = Object.fromEntries(Object.entries(d.liked).filter(([id]) => isKept(id))); d.reaction = d.selections.length ? "selected" : "text_only";
        }
        d.version += 1; render(); root.querySelector('[data-action="all-bad"]')?.focus(); break;
      case "adjust":
        await send({ op: "adjust_intent", action: b.dataset.adjust, key: b.dataset.key ?? null, feature: b.dataset.feature ?? null }); break;
      case "answer-q":
        if (!state.graph?.ask) return;
        await send({ op: "answer_question", question_id: state.graph.ask.question_id, choice: b.dataset.choice,
          option_ids: b.dataset.option ? [b.dataset.option] : [], switch_to: b.dataset.mode ?? null }); break;
      case "ask-pick": {
        const id = b.dataset.option;
        askPick.picks = askPick.picks.includes(id) ? askPick.picks.filter(p => p !== id) : [...askPick.picks, id];
        if (!askPick.picks.includes(id)) delete askPick.strengths[id];
        render(); root.querySelector(`[data-action="ask-pick"][data-option="${CSS.escape(id)}"]`)?.focus({ preventScroll: true }); break;
      }
      case "ask-strength": askPick.strengths[b.dataset.option] = b.dataset.strength; render(); break;
      case "ask-both":
      case "ask-submit": {
        const q = state.graph?.ask;
        if (!q) return;
        const ids = b.dataset.action === "ask-both" ? q.options.map(o => o.id) : askPick.picks;
        if (!ids.length) return;
        const strengths = q.strengths?.length ? Object.fromEntries(ids.map(id => [id, askPick.strengths[id] ?? "more"])) : null;
        await send({ op: "answer_question", question_id: q.question_id, choice: "options", option_ids: [...ids], switch_to: null,
          ...(strengths ? { strengths } : {}) }); break;
      }
      case "reaction": d.hypothesis = null; d.reaction = b.dataset.reaction; d.selections = []; d.question = null; d.version += 1; render(); root.querySelector("#free-text")?.focus(); break;
      case "part": d.hypothesis = null; part = { cardId: card.candidate_id, imageId: card.image_id, imageVersion: card.image_version, box: [0.15, 0.4, 0.85, 0.9] }; render(); root.querySelector('[data-coordinate="0"]')?.focus(); break;
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
        d.hypothesis = null;
        const q = state.questions.find(q => q.ref.id === b.dataset.question);
        const answer = q?.options[Number(b.dataset.option)];
        if (!answer) return;
        d.text = d.text ? `${d.text}\n${answer}` : answer; d.question = q.ref.id;
        d.reaction = answer === "잘 모르겠어요" ? "unsure" : d.selections.length ? "selected" : "text_only";
        if (d.reaction === "unsure") d.selections = [];
        d.version += 1; render(); root.querySelector("#free-text")?.focus(); break;
      }
      case "skip-question":
        d.hypothesis = null;
        d.question = b.dataset.question; d.reaction = "question_skipped"; d.selections = []; d.version += 1;
        announce("질문 건너뛰기를 골랐어요. 반영 버튼으로 보낼 수 있어요. 작성 중인 글은 별도 초안으로 남겨요."); break;
      case "preview-final": finalPreview = card.candidate_id; render(); root.querySelector('[data-action="confirm-final"]')?.focus(); break;
      case "cancel-final": finalPreview = null; render(); break;
      case "confirm-final": {
        const set = comparison().set;
        if (set && finalPreview) await send({ op: "select_final", candidate_set_ref: set, candidate_id: finalPreview }); break;
      }
      case "explore": await send({ op: "explore" }); break;
      case "end":
        if (state.graph && isOpen()) { summaryHidden = false; summaryChoices.clear(); await send({ op: "graph_summary", step: "prepare", choices: [] }); root.querySelector(".graph-summary button")?.focus(); }
        else await send({ op: "end_request" });
        break;
      case "gender": startGender = b.dataset.gender; storeGender(startGender); render(); break;
      case "situation":
        startSituation = startSituation === b.dataset.situation ? null : b.dataset.situation; render();
        if (startSituation === "free") root.querySelector("#free-situation")?.focus();
        break;
      case "summary-choice":
        if (summaryChoices.get(b.dataset.proposal) === b.dataset.choice) summaryChoices.delete(b.dataset.proposal);
        else summaryChoices.set(b.dataset.proposal, b.dataset.choice);
        render(); break;
      case "compose-toggle":
        composerOpen = !(composerOpen || draft().text); render();
        if (composerOpen) root.querySelector("#free-text")?.focus();
        break;
      case "memory-all-off": {
        for (const chip of (state.graph?.memory?.chips ?? []).filter(c => c.enabled)) {
          const result = await send({ op: "adjust_intent", action: "memory_off", key: chip.memory_id, feature: null });
          if (!result || result.outcome === "rejected") break;
        }
        break;
      }
      case "summary-cancel": summaryHidden = true; render(); break;
      case "summary-save": {
        const proposals = state.graph?.summary?.proposals ?? [];
        await send({ op: "graph_summary", step: "save", choices: proposals.map(p => ({ id: p.id, choice: summaryChoices.get(p.id) ?? "skip" })) });
        break;
      }
      case "profile-choice": profileChoices.set(b.dataset.memory, b.dataset.choice); render(); break;
      case "profile-save": {
        const changes = state.graph?.summary?.profile?.changes ?? [];
        await send({ op: "graph_summary", step: "profile", choices: changes.map(c => ({ id: c.memory_id, choice: profileChoices.get(c.memory_id) ?? "keep" })) });
        break;
      }
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
      root.querySelectorAll('[data-form="feedback"] button.primary, [data-submit="grid"]').forEach(submit => { submit.disabled = !canSubmit(d); });
      root.querySelectorAll('[data-action="explore"]').forEach(b => { b.disabled = !canFeedback() || Boolean(d.text || gridSignal(d)); });
      if (graphMode() && Boolean(root.querySelector('[data-submit="grid"]')) !== canSubmit(d)) render();
    }
    if (t.id === "initial-text") initialText[startMode] = t.value;
    if (t.id === "free-situation") freeSituation = t.value;
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
        targets: [{ target_id: "item-1", garment_type: form.querySelector("#target").value }], text: initialText[mode].trim() ? initialText[mode] : null,
        ...(state.engine === "graph" && mode === "shopping" ? { gender: startGender || null, situation: startSituationValue() } : {}) });
      if (result && result.outcome !== "rejected") focusMain();
    }
    if (form.dataset.form === "feedback" && canFeedback()) {
      const action = feedbackAction();
      if (!action || (action.op === "grid_feedback" && !canSubmit(draft())) || (action.op === "submit_feedback" && !action.text && !action.selections.length && action.reaction === "text_only")) return;
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
  function onKeydown(event) {
    if (event.key !== "Escape" || busy) return;
    if (finalPreview && !state?.request?.final_selection) { finalPreview = null; render(); }
    else if (state?.graph?.summary?.status === "draft" && isOpen() && !summaryHidden) { summaryHidden = true; render(); }
  }
  const listeners = { keydown: onKeydown, click: onClick, input: onInput, change: onChange, submit: onSubmit, pointerdown: onPointer, pointermove: onPointer, pointerup: onPointer, pointercancel: onPointer, lostpointercapture: onPointer };
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
