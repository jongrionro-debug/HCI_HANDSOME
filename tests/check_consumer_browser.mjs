/** E1 only: an ephemeral allowlisted static server, synthetic adapter, Chromium.
 * Run: node tests/check_consumer_browser.mjs [--capture-dir /private/tmp/...]
 * Uses an already-installed Playwright; does not install dependencies.
 */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const project = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const assetRoot = join(project, "src/stylemate_memory");
const assets = new Map([
  ["/consumer.html", "text/html; charset=utf-8"], ["/consumer.js", "text/javascript; charset=utf-8"],
  ["/consumer-fixture.js", "text/javascript; charset=utf-8"], ["/consumer.css", "text/css; charset=utf-8"],
]);
const captureIndex = process.argv.indexOf("--capture-dir");
const keepCaptures = captureIndex >= 0;
const captures = keepCaptures ? resolve(process.argv[captureIndex + 1]) : await mkdtemp(join(tmpdir(), "lumi-e1-ui-"));
await mkdir(captures, { recursive: true });
const server = createServer(async (request, response) => {
  const path = new URL(request.url, "http://127.0.0.1").pathname;
  if (!assets.has(path)) { response.writeHead(404); response.end(); return; }
  try { response.writeHead(200, { "Content-Type": assets.get(path), "Cache-Control": "no-store" }); response.end(await readFile(join(assetRoot, path.slice(1)))); }
  catch { response.writeHead(500); response.end(); }
});
let browser;
const checks = [];
try {
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1360, height: 940 }, reducedMotion: "reduce" });
  const errors = [];
  const external = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (!/^(http:\/\/127\.0\.0\.1:|data:)/.test(request.url())) external.push(request.url()); });
  const url = `http://127.0.0.1:${server.address().port}/consumer.html`;
  const action = name => page.locator(`[data-action="${name}"]`);
  const input = () => page.locator("#free-text");
  const check = name => checks.push(name);
  const state = () => page.evaluate(() => window.fixture.state());
  const commands = () => page.evaluate(() => window.fixture.commands);
  const idle = () => page.waitForFunction(() => {
    const main = document.querySelector("main");
    const status = document.querySelector("#operation-status")?.textContent ?? "";
    return main?.getAttribute("aria-busy") === "false" && !/해석을 기다리고|처리 중이에요/.test(status);
  });
  async function fixture() {
    await page.route("**/consumer.html", async route => {
      const html = (await readFile(join(assetRoot, "consumer.html"), "utf8")).replace('data-adapter="fixture"', 'data-adapter="test"');
      await route.fulfill({ contentType: "text/html; charset=utf-8", body: html });
    });
    await page.goto(url);
    await page.evaluate(async () => {
      const { mountConsumer } = await import("./consumer.js");
      const { createFixtureAdapter, FIXTURE_SCENARIOS } = await import("./consumer-fixture.js");
      window.fixture = createFixtureAdapter({ delay: 100 });
      window.dropNextResponse = false;
      const adapter = {
        state: id => window.fixture.state(id),
        async command(command) {
          const result = await window.fixture.command(command);
          if (window.dropNextResponse) { window.dropNextResponse = false; throw new Error("simulated response loss after receipt"); }
          return result;
        },
        setScenario: name => window.fixture.setScenario(name),
        get scenario() { return window.fixture.scenario; },
      };
      window.ui = mountConsumer(document.querySelector("#consumer-app"), adapter, { fixture: true, scenarios: FIXTURE_SCENARIOS });
      await window.ui.ready;
    });
  }
  async function startShopping(text = "") {
    await action("new").first().click();
    await page.locator("#initial-text").fill(text);
    await page.locator('[data-form="start"] button.primary').click();
    await input().waitFor(); await idle();
  }
  async function scenario(name) {
    await page.locator("#fixture-scenario").selectOption(name);
    await page.waitForFunction(name => document.querySelector("#fixture-scenario")?.value === name &&
      (name === "running" || document.querySelector("main")?.getAttribute("aria-busy") === "false"), name);
  }

  // The shipped entry works without a test adapter injection.
  await page.goto(url);
  await page.locator("#initial-text").waitFor();
  assert.match(await page.locator(".fixture-strip").innerText(), /실제 저장·모델 호출 없음/);
  await page.screenshot({ path: join(captures, "onboarding.png"), fullPage: true });
  check("shipped fixture entry and explicit simulation label");

  await fixture();
  await page.locator("#initial-text").fill("평소에는 여유 있는 바지를 자주 입어요.");
  await page.locator('[data-form="start"] button.primary').click();
  await input().waitFor(); await idle();
  await page.locator("#reflected-info summary").click();
  await action("confirm").first().click();
  assert.equal(await page.locator(".review input[type=checkbox]").count(), 0);
  await page.locator('.review [data-decision="accept"]').click();
  await idle();
  assert.equal((await state()).memories.filter(m => m.scope === "long_term").length, 0);
  assert.equal(await page.locator("[data-save]:checked").count(), 0);
  assert.equal(await action("future").first().isDisabled(), true);
  await page.locator("[data-save]").first().check();
  await action("future").first().click();
  assert.equal(await page.locator("[data-consent]").isChecked(), false);
  assert.equal(await page.locator('.review [data-decision="accept"]').isDisabled(), true);
  await page.locator('.review [data-decision="skip"]').click();
  assert.equal((await state()).memories.filter(m => m.scope === "long_term").length, 0);
  await action("future").first().click();
  await page.locator("[data-consent]").check();
  await page.screenshot({ path: join(captures, "future-review.png"), fullPage: true });
  await page.locator('.review [data-decision="accept"]').click();
  assert.equal((await state()).memories.filter(m => m.scope === "long_term").length, 1);
  await action("start-after-onboarding").click();
  await page.locator("#initial-text").waitFor();
  check("content confirmation, unchecked item/consent, skip, independent future reuse");

  await startShopping("이번 발표에는 단정한 바지를 입고 싶어요.");
  const shoppingId = (await state()).request.id;
  assert.equal((await state()).memories.filter(m => m.scope === "short_term").length, 1);
  await input().fill("A의 색과 B의 모양을 함께 보고 싶어요.");
  const before = (await commands()).length;
  const idsBefore = (await state()).cards.map(c => c.candidate_id);
  await action("select").nth(0).click();
  await action("select").nth(1).click();
  assert.equal(await input().inputValue(), "A의 색과 B의 모양을 함께 보고 싶어요.");
  assert.equal((await commands()).length, before);
  assert.deepEqual((await state()).cards.map(c => c.candidate_id), idsBefore);
  await action("part").first().click();
  const stage = page.locator("[data-crop-stage]");
  await stage.scrollIntoViewIfNeeded();
  const bounds = await stage.boundingBox();
  await page.mouse.move(bounds.x + bounds.width * .1, bounds.y + bounds.height * .2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * .7, bounds.y + bounds.height * .8, { steps: 8 });
  await page.mouse.up();
  const coordinates = await page.locator("[data-coordinate]").evaluateAll(inputs => inputs.map(i => Number(i.value)));
  assert.ok(coordinates.every((v, i) => Math.abs(v - [.1, .2, .7, .8][i]) < .015));
  await page.locator('[data-form="part"] button.primary').click();
  assert.equal(await input().inputValue(), "A의 색과 B의 모양을 함께 보고 싶어요.");
  await page.screenshot({ path: join(captures, "desktop.png"), fullPage: true });
  const textSent = await input().inputValue();
  await page.locator('[data-form="feedback"]').evaluate(form => { form.requestSubmit(); form.requestSubmit(); });
  await input().fill("응답을 기다리는 동안 쓴 다음 초안");
  await page.waitForFunction(() => document.querySelector("main")?.getAttribute("aria-busy") === "false");
  assert.match(await page.locator("#operation-status").innerText(), /접수됐어요|해석을 기다리고/);
  assert.equal(await input().inputValue(), "응답을 기다리는 동안 쓴 다음 초안");
  await idle();
  const sent = (await commands()).slice(before).filter(c => c.action.op === "submit_feedback");
  assert.equal(sent.length, 1);
  assert.equal(sent[0].action.text, textSent);
  assert.equal(sent[0].action.selections.length, 2);
  const selectedPart = sent[0].action.selections.find(s => s.part_ref).part_ref;
  assert.equal(selectedPart.image_version, 1);
  assert.equal(selectedPart.region_id, null);
  assert.deepEqual(selectedPart.box, coordinates);
  check("selection is local until apply; multi/partial+text; duplicate submit; editing during loading");

  await action("skip-question").first().click();
  await page.locator('[data-form="feedback"] button.primary').click();
  await idle();
  assert.equal(await input().inputValue(), "응답을 기다리는 동안 쓴 다음 초안");
  const skipped = (await commands()).at(-1).action;
  assert.equal(skipped.reaction, "question_skipped"); assert.equal(skipped.text, null); assert.ok(skipped.question_id);
  await page.locator("#reflected-info").evaluate(details => { details.open = true; details.dispatchEvent(new Event("toggle")); });
  await action("edit").first().click();
  await page.locator("#memory-edit").fill("이번 발표에서만 단정한 바지를 입고 싶어요.");
  await page.locator('[data-form="edit"] button.primary').click();
  assert.equal(await input().inputValue(), "응답을 기다리는 동안 쓴 다음 초안");
  await page.locator('.review [data-decision="decline"]').click();
  check("question skip keeps independent text; review/edit does not consume draft; decline is separate");
  const savedPreference = (await state()).memories.find(m => m.scope === "long_term");
  await action("edit").first().click();
  await page.locator("#memory-edit").fill("새로 제안하는 평소 취향 문장");
  await page.locator('[data-form="edit"] button.primary').click();
  assert.match(await page.locator(".review").innerText(), /이번 요청만/);
  await page.locator('.review [data-decision="accept"]').click();
  assert.deepEqual((await state()).memories.find(m => m.scope === "long_term"), savedPreference);
  assert.equal((await state()).memories.filter(m => m.scope === "long_term").length, 1);
  assert.equal(await input().inputValue(), "응답을 기다리는 동안 쓴 다음 초안");
  check("editing a saved preference preserves its original and needs a separate reuse decision");

  await startShopping();
  await input().fill("다른 요청 초안");
  await action("new").click();
  await page.locator(`[data-action="resume"][data-request="${shoppingId}"]`).click();
  await input().waitFor();
  assert.equal(await input().inputValue(), "응답을 기다리는 동안 쓴 다음 초안");
  await startShopping();
  assert.equal(await input().inputValue(), "");
  assert.equal((await state()).memories.filter(m => m.scope === "short_term").length, 0);
  assert.equal((await state()).memories.filter(m => m.scope === "long_term").length, 1);
  check("request-specific drafts on resume; new request isolation; usual preference retained");

  for (const [reaction, label] of [["none", "없어요"], ["unsure", "모르겠어요"], ["text_only", "텍스트만"]]) {
    await action("reaction").filter({ hasText: label }).click();
    if (reaction === "text_only") await input().fill("새 요청에만 쓰는 문장");
    await page.locator('[data-form="feedback"] button.primary').click(); await idle();
    assert.equal((await commands()).at(-1).action.reaction, reaction);
  }
  check("none/unsure/text_only are distinct reactions");

  await scenario("pending");
  await input().fill("접수 후 해석 대기 중인 문장");
  await page.locator('[data-form="feedback"] button.primary').click();
  await page.waitForFunction(() => document.querySelector("main")?.getAttribute("aria-busy") === "false");
  await scenario("model_error");
  assert.match(await page.locator("#operation-status").innerText(), /입력은 접수됐지만/);
  const acceptedRef = (await state()).expected.object_versions.find(r => r.type === "feedback");
  await action("retry-extraction").click();
  assert.equal((await commands()).at(-1).action.feedback_ref.id, acceptedRef.id);
  await scenario("normal"); await idle();
  check("accepted/pending/model error and extraction retry retain the original evidence reference");

  await input().fill("접수 응답이 끊겨도 보존할 문장");
  await page.evaluate(() => { window.dropNextResponse = true; });
  await page.locator('[data-form="feedback"] button.primary').click();
  await action("retry-command").waitFor();
  assert.equal(await input().inputValue(), "접수 응답이 끊겨도 보존할 문장");
  const lost = (await commands()).at(-1);
  await action("retry-command").click();
  const retried = (await commands()).at(-1);
  assert.deepEqual(retried, lost);
  await idle();
  check("lost response retries identical command ID/action/expected instead of resubmitting evidence");

  await input().fill("오래된 화면에서도 남길 초안");
  await page.evaluate(() => window.fixture.setScenario("stale"));
  await page.locator('[data-form="feedback"] button.primary').click();
  await action("refresh").waitFor();
  assert.equal(await input().inputValue(), "오래된 화면에서도 남길 초안");
  await page.evaluate(() => window.fixture.setScenario("normal"));
  await action("refresh").click();
  assert.equal(await input().inputValue(), "오래된 화면에서도 남길 초안");
  await scenario("no_results");
  assert.match(await page.locator(".empty-state").innerText(), /상품이 없어요/);
  assert.equal(await input().isEditable(), true);
  await scenario("no_images");
  assert.equal(await page.locator(".image-placeholder").count(), 3);
  assert.equal(await action("part").first().isDisabled(), true);
  assert.equal(await action("select").first().isEnabled(), true);
  await scenario("broken_images");
  await page.waitForFunction(() => [...document.querySelectorAll(".image-placeholder")].some(node => node.textContent.includes("불러오지 못했어요")));
  assert.equal(await action("part").first().isDisabled(), true);
  await page.screenshot({ path: join(captures, "image-fallback.png"), fullPage: true });
  await scenario("blocked");
  assert.equal(await input().isEditable(), true);
  assert.equal(await page.locator('[data-form="feedback"] button.primary').isEnabled(), true);
  await input().fill("");
  assert.equal(await action("explore").first().isEnabled(), true);
  await scenario("running");
  assert.match(await page.locator("#operation-status").innerText(), /처리 중/);
  await scenario("normal");
  check("stale rejection preserves draft; no products; image absence/failure; blocked/running");

  await page.setViewportSize({ width: 390, height: 844 });
  await input().focus();
  await page.keyboard.press("ControlOrMeta+ArrowRight"); await page.keyboard.insertText(" 키보드 보완");
  assert.ok((await input().inputValue()).endsWith(" 키보드 보완"));
  await page.keyboard.press("Tab");
  assert.equal(await page.evaluate(() => document.activeElement.textContent), "선택과 글 반영");
  assert.notEqual(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), "none");
  const inputRect = await input().boundingBox();
  assert.ok(inputRect.y >= 0 && inputRect.y + inputRect.height <= 844);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: join(captures, "mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 320, height: 740 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: join(captures, "narrow.png"), fullPage: true });
  check("390px/320px layout; persistent mobile composer; keyboard focus and text editing");

  await page.setViewportSize({ width: 1360, height: 940 });
  await input().fill("");
  await action("preview-final").first().click();
  await action("confirm-final").click();
  assert.equal((await state()).request.status, "open");
  assert.ok((await state()).request.final_selection);
  assert.equal((await state()).memories.filter(m => m.scope === "long_term").length, 1);
  await action("end").filter({ hasText: /^탐색 종료$/ }).click();
  assert.equal((await state()).request.status, "closed");
  assert.ok((await state()).request.final_selection);
  assert.equal(await input().isEditable(), false);
  await startShopping();
  await action("end").filter({ hasText: "상품 선택 없이 종료" }).click();
  assert.equal((await state()).request.final_selection, null);
  await page.screenshot({ path: join(captures, "closed-without-selection.png"), fullPage: true });
  check("final selection leaves request open; end preserves final; end without selection is allowed");

  await startShopping('<img src=x onerror="window.badMarkup=true">');
  assert.equal(await page.evaluate(() => window.badMarkup), undefined);
  assert.equal(await page.locator('img[src="x"]').count(), 0);
  await page.evaluate(async () => {
    window.ui.destroy();
    const { mountConsumer } = await import("./consumer.js");
    window.ui = mountConsumer(document.querySelector("#consumer-app"), {
      async state(id) {
        const state = await window.fixture.state(id);
        state.expected.object_versions.push({ type: "candidate_set", id: "historical-set", version: 1 });
        state.cards[0].image_url = "javascript:window.badImage=true";
        return state;
      },
      command: command => window.fixture.command(command),
    });
    await window.ui.ready;
  });
  assert.equal(await action("select").first().isDisabled(), true);
  assert.equal(await action("preview-final").first().isDisabled(), true);
  assert.equal(await input().isEditable(), true);
  assert.equal(await page.locator('img[src^="javascript:"]').count(), 0);
  assert.equal(await page.evaluate(() => window.badImage), undefined);
  check("ambiguous comparison refs block image/final submission; unsafe image URL falls back");
  await page.evaluate(async () => {
    window.ui.destroy();
    const { mountConsumer } = await import("./consumer.js");
    let first = true;
    window.ui = mountConsumer(document.querySelector("#consumer-app"), {
      async state() { if (first) { first = false; throw new Error("initial state unavailable"); } return window.fixture.state(); },
      command: command => window.fixture.command(command),
    });
    await window.ui.ready;
  });
  await action("refresh").click();
  await input().waitFor();
  check("initial state load failure has a working recovery action");
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
  check("untrusted text is escaped; no page errors or external network");
  console.log(JSON.stringify({ passed: checks.length, checks, ...(keepCaptures ? { captures } : {}) }, null, 2));
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
  if (!keepCaptures) await rm(captures, { recursive: true, force: true });
}
