/** E2: real local HTTP + SQLite + synthetic catalog + fake model transport.
 * Run: node tests/check_consumer_http_browser.mjs [--capture-dir /private/tmp/...]
 * --sparse-maps selects a smaller synthetic Map variant. The default verifies
 * the full 37-assertion D2 output without dropping unknown attributes.
 * Uses installed Playwright; no credentials or dependencies are installed.
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const project = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const captureIndex = process.argv.indexOf("--capture-dir");
const keepCaptures = captureIndex >= 0;
const captures = keepCaptures ? resolve(process.argv[captureIndex + 1]) : await mkdtemp(join(tmpdir(), "lumi-e2-captures-"));
await mkdir(captures, { recursive: true });
const sparseMaps = process.argv.includes("--sparse-maps");
const backend = spawn("python3", ["-u", "-B", "-m", "tests.consumer_browser_fixture", ...(sparseMaps ? ["--sparse-maps"] : [])], {
  cwd: project, env: { ...process.env, PYTHONPATH: "src" }, stdio: ["pipe", "pipe", "pipe"],
});
const lines = createInterface({ input: backend.stdout })[Symbol.asyncIterator]();
let stderr = "";
backend.stderr.on("data", data => { stderr += data; });
backend.stdin.on("error", () => {}); // Startup failures are reported by next().
async function next() {
  let timer;
  try {
    const line = await Promise.race([lines.next(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`browser harness timed out: ${stderr}`)), 15000);
    })]);
    assert.equal(line.done, false, stderr);
    return JSON.parse(line.value);
  } finally { clearTimeout(timer); }
}
async function rpc(command) { backend.stdin.write(`${JSON.stringify(command)}\n`); return next(); }
const checks = [];
const integrationNotes = new Set();
if (sparseMaps) integrationNotes.add("Explicit sparse synthetic Maps; the default full-map path must be checked separately.");
const check = name => checks.push(name);
let browser;
let page;
try {
  const { url } = await next();
  browser = await chromium.launch({ headless: true });
  page = await browser.newPage({ viewport: { width: 1360, height: 940 }, reducedMotion: "reduce" });
  page.setDefaultTimeout(12000);
  const errors = [], external = [], sent = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (!request.url().startsWith(url) && !request.url().startsWith("data:")) external.push(request.url());
    if (request.url() === `${url}/api/command`) sent.push(request.postDataJSON());
  });
  page.on("response", async response => {
    if (response.url() === `${url}/api/command`) {
      const result = await response.json().catch(() => null);
      if (result?.outcome === "accepted" && result.state.operation === "stale") {
        integrationNotes.add("Backend can report accepted+stale while a replacement search is running; explicit refresh is needed (A handoff).");
      }
    }
  });
  const action = name => page.locator(`[data-action="${name}"]`);
  const input = () => page.locator("#free-text");
  const inspect = request_id => rpc({ op: "inspect", ...(request_id ? { request_id } : {}) });
  const settled = () => page.waitForFunction(() => document.querySelector("main")?.getAttribute("aria-busy") === "false");
  async function apply() { await page.locator('[data-form="feedback"] button.primary').click(); await settled(); }
  async function explore(expectedOperation = "idle") {
    await action("explore").first().click(); await settled();
    assert.equal((await inspect()).state.operation, expectedOperation, "Replacement search must finish through normal HTTP polling.");
  }
  async function start(text = null) {
    await action("new").first().click();
    await page.locator("#initial-text").fill(text ?? "");
    await page.locator('[data-form="start"] button.primary').click();
    await input().waitFor(); await settled();
  }
  async function confirm(memoryId, bindings = false) {
    await page.locator("#reflected-info").evaluate(node => { node.open = true; node.dispatchEvent(new Event("toggle")); });
    await page.locator(`[data-action="${bindings ? "bindings" : "confirm"}"][data-memory="${memoryId}"]`).click();
    await page.locator('.review [data-decision="accept"]').click();
    await settled();
  }
  async function future(memoryId) {
    await page.locator(`[data-save="${memoryId}"]`).check();
    await page.locator(`[data-action="future"][data-memory="${memoryId}"]`).click();
    await page.locator("[data-consent]").waitFor();
  }
  async function untilEntered() {
    for (let i = 0; i < 100; i++) {
      if ((await rpc({ op: "entered" })).entered) return;
      const current = await inspect();
      assert.notEqual(current.state.operation, "interpretation_pending",
        `Image intake succeeded but model input failed before fake transport: ${current.state.error?.code}`);
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    assert.fail("fake model did not receive the request");
  }

  await page.goto(url);
  assert.equal(await page.locator('[data-adapter="http"]').count(), 1);
  assert.equal(await page.locator(".fixture-strip").count(), 0);
  await page.locator("#initial-text").fill("평소에는 네이비 바지를 좋아해요");
  await page.locator('[data-form="start"] button.primary').click();
  await input().waitFor(); await settled();
  let view = await inspect();
  const onboarding = view.state.request.id;
  const onboardMemory = view.state.memories[0].ref.id;
  assert.equal(view.snapshot.feedback.length, 1);
  assert.equal(view.snapshot.consents.length, 0);
  assert.equal(view.state.memories[0].confirmed, false);
  await confirm(onboardMemory);
  view = await inspect();
  assert.equal(view.snapshot.memories[0].confirmed, true);
  assert.equal(view.snapshot.bindings[0].confirmed, false);
  await confirm(onboardMemory, true);
  assert.equal((await inspect()).snapshot.bindings[0].confirmed, true);
  assert.equal(await action("future").count(), 0);
  await action("end").filter({hasText:"온보딩 마치기"}).click(); await settled();
  assert.equal(await page.locator("[data-save]:checked").count(), 0);
  assert.equal(await action("future").first().isDisabled(), true);
  await future(onboardMemory);
  assert.equal(await page.locator("[data-consent]").isChecked(), false);
  assert.equal(await page.locator('.review [data-decision="accept"]').isDisabled(), true);
  await page.locator('.review [data-decision="decline"]').click(); await settled();
  assert.equal((await inspect()).snapshot.consents.length, 0);
  await action("start-after-onboarding").click();
  await page.locator("#initial-text").waitFor();
  assert.equal((await inspect(onboarding)).state.request.status, "closed");
  check("real HTTP onboarding; separate content/binding confirmation; unchecked reuse and explicit refusal");

  await page.locator("#initial-text").fill("이번 발표에는 네이비 바지가 좋아요");
  await page.locator('[data-form="start"] button.primary').click();
  await input().waitFor(); await settled();
  view = await inspect();
  const shopping = view.state.request.id;
  const initialMemory = view.state.memories[0].ref.id;
  assert.equal(view.state.operation, "blocked");
  assert.equal(await action("explore").first().isEnabled(), true);
  await input().fill("수정할 수 있는 글");
  assert.equal(await page.locator('[data-form="feedback"] button.primary').isEnabled(), true);
  await input().fill("");
  await confirm(initialMemory);
  await confirm(initialMemory, true);
  await explore();
  assert.equal((await inspect()).state.cards.length, 2);
  check("unconfirmed request stays blocked; text adjustment and separate confirmation unblock exploration");

  await input().fill("A의 색에 B의 핏이면 좋겠어요");
  const before = (await inspect()).snapshot.feedback.length;
  const initialCards = (await inspect()).state.cards;
  await action("select").nth(0).click(); await action("select").nth(1).click();
  assert.equal((await inspect()).snapshot.feedback.length, before);
  assert.deepEqual((await inspect()).state.cards, initialCards);
  await action("part").first().click();
  const stage = page.locator("[data-crop-stage]");
  await stage.scrollIntoViewIfNeeded();
  const bounds = await stage.boundingBox();
  await page.mouse.move(bounds.x + bounds.width * .1, bounds.y + bounds.height * .2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * .7, bounds.y + bounds.height * .8, { steps: 6 });
  await page.mouse.up();
  const coords = await page.locator("[data-coordinate]").evaluateAll(nodes => nodes.map(node => Number(node.value)));
  assert.ok(coords.every((v, i) => Math.abs(v - [.1, .2, .7, .8][i]) < .015));
  // Keyboard coordinates and submission refer to the original image's ratios.
  await page.locator('[data-coordinate="0"]').fill("0.12");
  coords[0] = .12;
  await page.locator('[data-coordinate="3"]').focus(); await page.keyboard.press("Tab"); await page.keyboard.press("Enter");
  assert.equal(await input().inputValue(), "A의 색에 B의 핏이면 좋겠어요");
  await page.screenshot({ path: join(captures, "desktop.png"), fullPage: true });
  await rpc({ op: "provider", pause: "extract" });
  await page.locator('[data-form="feedback"]').evaluate(form => { form.requestSubmit(); form.requestSubmit(); });
  await untilEntered();
  await input().fill("처리 중 작성한 다음 초안");
  assert.equal(await page.locator('[data-form="feedback"] button.primary').isDisabled(), true);
  await rpc({ op: "release" }); await settled();
  assert.equal(await input().inputValue(), "처리 중 작성한 다음 초안");
  await rpc({ op: "provider" });
  view = await inspect();
  assert.equal(view.snapshot.feedback.length, before + 1);
  const combined = view.snapshot.feedback.at(-1);
  const selectedEvidence = view.snapshot.evidence.filter(e => combined.evidence_refs.some(r => r.id === e.id));
  assert.equal(selectedEvidence.filter(e => e.kind === "image_selection").length, 2);
  assert.equal(selectedEvidence.filter(e => e.kind === "user_text").length, 1);
  assert.equal(selectedEvidence.find(e => e.kind === "user_text").quote, "A의 색에 B의 핏이면 좋겠어요");
  assert.deepEqual(selectedEvidence.find(e => e.selection?.part_ref).selection.part_ref.box, coords);
  assert.equal(selectedEvidence.find(e => e.selection?.part_ref).selection.part_ref.image_version, initialCards[0].image_version);
  assert.equal(view.snapshot.consents.length, 0);
  check("multi/partial selection + A-color/B-fit text stored together once; original coordinates; draft survives processing");

  await action("skip-question").first().click(); await apply();
  view = await inspect();
  const skipped = view.snapshot.feedback.at(-1);
  assert.equal(skipped.reaction, "question_skipped");
  const skipEvidence = view.snapshot.evidence.filter(e => skipped.evidence_refs.some(r => r.id === e.id));
  assert.deepEqual(skipEvidence.map(e => e.kind), ["ui_response"]);
  assert.equal(skipEvidence[0].quote, null);
  assert.equal(skipEvidence[0].selection, null);
  assert.equal(view.snapshot.questions.find(q => q.id === skipped.question_ref.id).status, "skipped");
  assert.equal(await input().inputValue(), "처리 중 작성한 다음 초안");
  await input().fill("");
  await confirm(view.snapshot.memories.find(m => m.content === "A의 색에 B의 핏이면 좋겠어요").id);
  await explore();
  const memoriesBefore = view.snapshot.memories.length;
  for (const reaction of ["none", "unsure"]) {
    await page.locator(`[data-reaction="${reaction}"]`).click(); await apply();
    assert.equal((await inspect()).snapshot.feedback.at(-1).reaction, reaction);
  }
  view = await inspect();
  assert.equal(view.snapshot.memories.length, memoriesBefore);
  assert.equal(view.snapshot.consents.length, 0);
  await page.locator('[data-reaction="text_only"]').click();
  await input().fill("미정으로 둘게요"); await apply();
  view = await inspect();
  const unresolved = view.snapshot.memories.find(m => m.content === "미정으로 둘게요");
  assert.equal(unresolved.confirmed, false);
  assert.equal(view.snapshot.bindings.filter(b => b.memory_id === unresolved.id).length, 0);
  await confirm(unresolved.id);
  await explore();
  assert.notEqual((await inspect()).state.cards[0].candidate_id, initialCards[0].candidate_id);
  check("none/unsure/skipped stay distinct without invented preferences; unbound wording retained; new comparison issued");

  await action("preview-final").first().click(); await action("confirm-final").click(); await settled();
  view = await inspect();
  assert.equal(view.state.request.status, "open");
  assert.ok(view.state.request.final_selection);
  assert.equal(view.snapshot.consents.length, 0);
  await action("end").filter({ hasText: /^탐색 종료$/ }).click(); await settled();
  assert.equal((await inspect()).state.request.status, "closed");
  await future(initialMemory);
  await page.locator('.review [data-decision="decline"]').click(); await settled();
  assert.equal((await inspect()).snapshot.consents.length, 0);
  await future(initialMemory);
  await page.locator("[data-consent]").check();
  await page.reload(); await page.locator("[data-consent]").waitFor();
  assert.equal(await page.locator("[data-consent]").isChecked(), false);
  await rpc({ op: "restart" });
  await page.reload(); await page.locator("[data-consent]").waitFor();
  view = await inspect();
  assert.equal(view.state.request.id, shopping);
  assert.equal(view.state.request.status, "closed");
  assert.ok(view.state.request.final_selection);
  assert.equal(view.snapshot.consents.length, 0);
  assert.equal(await page.locator("[data-consent]").isChecked(), false);
  await page.locator("[data-consent]").check();
  await page.locator('.review [data-decision="accept"]').click(); await settled();
  view = await inspect();
  assert.equal(view.snapshot.consents.length, 1);
  assert.equal(view.snapshot.memories.filter(m => m.scope === "long_term").length, 1);
  assert.equal(view.snapshot.consents[0].purpose, "future_reuse");
  assert.equal(view.snapshot.consents[0].status, "active");
  assert.equal(view.snapshot.consents[0].event_ref.type, "event");
  check("final selection/end/decline do not consent; review, evidence and final restore across reload/restart; only explicit reuse writes consent");

  await start();
  view = await inspect();
  const secondRequest = view.state.request.id;
  assert.notEqual(secondRequest, shopping);
  assert.equal(view.snapshot.memories.filter(m => m.scope === "short_term").length, 0);
  assert.equal(view.snapshot.memories.filter(m => m.scope === "long_term").length, 1);
  await input().fill("두 번째 요청의 초안");
  await action("new").first().click();
  await page.locator(`[data-action="resume"][data-request="${shopping}"]`).click(); await settled();
  assert.equal((await inspect()).state.request.id, shopping);
  assert.equal((await inspect()).state.request.status, "closed");
  await action("new").first().click();
  await page.locator(`[data-action="resume"][data-request="${secondRequest}"]`).click(); await settled();
  assert.equal(await input().inputValue(), "두 번째 요청의 초안");
  await input().fill("");
  check("new request isolates short-term evidence; consented usual preference survives; exact existing request resumes with its draft");

  await rpc({ op: "provider", fail_extract: true });
  await input().fill("접수 뒤 해석 오류를 확인할 문장"); await apply();
  await action("retry-extraction").waitFor();
  assert.match(await page.locator("#operation-status").innerText(), /입력은 접수됐지만/);
  view = await inspect();
  const feedbackCount = view.snapshot.feedback.length, evidenceCount = view.snapshot.evidence.length;
  assert.equal(view.state.operation, "interpretation_pending");
  await rpc({ op: "restart" }); await page.reload();
  await action("retry-extraction").waitFor();
  assert.equal((await inspect()).snapshot.feedback.length, feedbackCount);
  assert.equal((await inspect()).snapshot.evidence.length, evidenceCount);
  // Delay an old state response beyond the newer successful command response.
  let releaseOld, oldRead;
  const held = new Promise(resolve => { oldRead = resolve; });
  const gate = new Promise(resolve => { releaseOld = resolve; });
  const oldRoute = async route => { const response = await route.fetch(); oldRead(); await gate; await route.fulfill({ response }); };
  await page.route("**/api/state*", oldRoute, { times: 1 });
  await action("refresh").click(); await held;
  await rpc({ op: "provider" });
  await action("retry-extraction").click(); await settled();
  releaseOld(); await page.waitForTimeout(100);
  assert.equal(await action("retry-extraction").count(), 0);
  view = await inspect();
  assert.equal(view.snapshot.feedback.length, feedbackCount);
  assert.equal(view.snapshot.evidence.length, evidenceCount);
  assert.notEqual(view.state.operation, "interpretation_pending");
  await rpc({ op: "provider", fail_propose: true }); await explore("error");
  assert.equal((await inspect()).state.operation, "error");
  assert.equal(await action("retry-extraction").count(), 0);
  assert.doesNotMatch(await page.locator("#operation-status").innerText(), /입력은 접수됐지만/);
  await rpc({ op: "provider" }); await explore();
  assert.equal((await inspect()).state.operation, "idle");
  check("provider failure and server restart keep accepted evidence; same-feedback retry; delayed older read cannot roll back success; proposal error retries search");

  await input().fill("응답 손실 때에도 한 번만 접수해요");
  const beforeLoss = (await inspect()).snapshot.feedback.length;
  await page.route("**/api/command", async route => { await route.fetch(); await route.abort("failed"); }, { times: 1 });
  await page.locator('[data-form="feedback"] button.primary').click();
  await action("retry-command").waitFor();
  const lost = sent.at(-1);
  assert.equal(await input().inputValue(), "응답 손실 때에도 한 번만 접수해요");
  await action("retry-command").click(); await settled();
  assert.deepEqual(sent.at(-1), lost);
  assert.equal((await inspect()).snapshot.feedback.length, beforeLoss + 1);
  check("lost HTTP response retries the identical command without duplicating SQLite evidence");

  await input().fill("후보가 바뀌어도 남길 글"); await action("select").first().click();
  await rpc({ op: "catalog", change: true });
  await apply();
  assert.match(await page.locator("#operation-status").innerText(), /후보나 반영 내용이 바뀌었어요/);
  assert.equal(await input().inputValue(), "후보가 바뀌어도 남길 글");
  assert.equal((await inspect()).state.operation, "stale");
  assert.equal(await action("select").count(), 0);
  await input().fill(""); await rpc({ op: "catalog" }); await explore();
  assert.equal((await inspect()).state.cards.length, 2);
  await page.route("**/api/images/*", route => route.abort("failed"));
  await page.reload(); await page.locator(".image-placeholder").first().waitFor();
  assert.equal(await action("part").first().isDisabled(), true);
  assert.equal(await action("select").first().isEnabled(), true);
  await page.screenshot({ path: join(captures, "image-failure.png"), fullPage: true });
  await page.unroute("**/api/images/*"); await page.reload();
  await page.waitForFunction(() => [...document.querySelectorAll('[data-action="part"]')].some(b => !b.disabled));
  check("changed catalog rejects stale selection and preserves text; fresh search recovers; broken images keep whole/text actions usable");

  for (const [width, height] of [[390, 844], [320, 740]]) {
    await page.setViewportSize({ width, height });
    await input().fill("좁은 화면 키보드 입력"); await input().focus(); await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.textContent), "선택과 글 반영");
    assert.notEqual(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), "none");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    const rect = await input().boundingBox();
    assert.ok(rect.y >= 0 && rect.y + rect.height <= height);
    await page.screenshot({ path: join(captures, `mobile-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 1360, height: 940 }); await input().fill("");
  await action("part").first().click();
  const crop = page.locator("[data-crop-stage]");
  await crop.scrollIntoViewIfNeeded();
  await crop.evaluate(stage => stage.addEventListener("pointerdown", event => { window.cropPointer = event.pointerId; }, { once: true }));
  const cropBounds = await crop.boundingBox();
  await page.mouse.move(cropBounds.x + cropBounds.width * .1, cropBounds.y + cropBounds.height * .2);
  await page.mouse.down();
  await page.mouse.move(cropBounds.x + cropBounds.width * .5, cropBounds.y + cropBounds.height * .6);
  const beforeOtherPointer = await page.locator("[data-coordinate]").evaluateAll(nodes => nodes.map(node => Number(node.value)));
  // Native mouse drag, followed by synthesized secondary-pointer/cancel events.
  await crop.evaluate(stage => {
    const rect = stage.getBoundingClientRect();
    for (const type of ["pointerdown", "pointermove", "pointerup"]) stage.dispatchEvent(new PointerEvent(type, {
      bubbles: true, pointerId: 99, button: 0, clientX: rect.right, clientY: rect.bottom,
    }));
  });
  assert.deepEqual(await page.locator("[data-coordinate]").evaluateAll(nodes => nodes.map(node => Number(node.value))), beforeOtherPointer);
  await crop.evaluate(stage => stage.dispatchEvent(new PointerEvent("pointercancel", { bubbles: true, pointerId: window.cropPointer })));
  assert.equal(await crop.evaluate(stage => stage.hasPointerCapture(window.cropPointer)), false);
  await page.mouse.up();
  await page.mouse.move(cropBounds.x + cropBounds.width * .2, cropBounds.y + cropBounds.height * .3);
  await page.mouse.down();
  await page.mouse.move(cropBounds.x + cropBounds.width * .6, cropBounds.y + cropBounds.height * .7);
  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  assert.equal(await crop.evaluate(stage => stage.hasPointerCapture(window.cropPointer)), false);
  await page.mouse.up();
  await page.locator('[data-coordinate="0"]').fill("0.2");
  await page.locator('[data-form="part"] button.primary').click();
  assert.equal(await page.locator(".selected-label").count(), 1);
  await action("select").first().click();
  assert.doesNotMatch(await page.locator("main").innerText(), /dummy-e2|synthetic-e2-user|request_revision|profile_revision|object_versions|unconfirmed_hypothesis|"garment_type"|SQLite|prompt/);
  check("390/320px composer and keyboard focus; keyboard partial selection still works after cancellation; internal model/DB/version details stay hidden");

  await rpc({ op: "catalog", empty: true }); await explore("no_results");
  assert.equal((await inspect()).state.operation, "no_results");
  assert.match(await page.locator(".empty-state").innerText(), /조건에 맞는 상품이 없어요/);
  await action("end").filter({ hasText: "상품 선택 없이 종료" }).click(); await settled();
  view = await inspect();
  assert.equal(view.state.request.status, "closed");
  assert.equal(view.state.request.final_selection, null);
  assert.equal(view.snapshot.consents.length, 1);
  check("real empty search remains empty and permits ending without a product or additional consent");
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
  check("no page errors or external network; browser and DB evidence checked together");
  console.log(JSON.stringify({ passed: checks.length, productMaps: sparseMaps ? "explicit sparse synthetic fixture" : "default D2 output",
    checks, integrationNotes: [...integrationNotes], ...(keepCaptures ? { captures } : {}) }, null, 2));
} catch (error) {
  if (page) await page.screenshot({ path: join(captures, "failure.png"), fullPage: true }).catch(() => {});
  if (backend.exitCode === null && !backend.stdin.destroyed) {
    const failure = await rpc({ op: "inspect" }).catch(() => null);
    if (failure) console.error(JSON.stringify({ passed: checks, operation: failure.state.operation, error: failure.state.error,
      lastReaction: failure.snapshot?.feedback.at(-1)?.reaction,
      interpretations: failure.snapshot?.interpretations.map(i => ({ status: i.status, error: i.error })) }));
  }
  throw error;
} finally {
  await browser?.close();
  if (backend.exitCode === null && !backend.stdin.destroyed) {
    await rpc({ op: "close" }).catch(() => {});
    backend.stdin.end();
    await new Promise(resolve => {
      const timer = setTimeout(() => { backend.kill("SIGTERM"); resolve(); }, 5000);
      backend.once("exit", () => { clearTimeout(timer); resolve(); });
    });
  }
  if (!keepCaptures) await rm(captures, { recursive: true, force: true });
}
