/** Real HTTP comparison controls + SQLite outcomes, offline synthetic inputs. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright";

const captures = process.argv[2] || await mkdtemp(join(tmpdir(), "lumi-hypothesis-"));
await mkdir(captures, {recursive:true});
const backend = spawn("python3", ["-u", "-B", "-m", "tests.hypothesis_browser_fixture"],
  { env: { ...process.env, PYTHONPATH: "src" }, stdio: ["pipe", "pipe", "pipe"] });
const lines = createInterface({ input: backend.stdout })[Symbol.asyncIterator]();
let stderr = "", browser;
backend.stderr.on("data", data => { stderr += data; });
backend.stdin.on("error", () => {});
async function next() {
  let timer;
  try { const line = await Promise.race([lines.next(), new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(stderr || "fixture timeout")), 15000);
  })]); assert.equal(line.done, false, stderr); return JSON.parse(line.value); }
  finally { clearTimeout(timer); }
}
async function rpc(op) { backend.stdin.write(`${JSON.stringify({op})}\n`); return next(); }
try {
  const { url } = await next();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1360, height: 940 }, reducedMotion: "reduce" });
  const errors = [], commands = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("request", req => { if (req.url() === `${url}/api/command`) commands.push(req.postDataJSON()); });
  await page.goto(url);
  const choices = () => page.locator('[data-action="comparison-choose"]');
  const apply = () => page.locator('[data-form="feedback"] button.primary').click();
  await choices().first().waitFor();
  assert.equal(await choices().count(), 2);
  assert.match(await page.locator('[aria-label="요구에 맞는 조건 비교"]').innerText(), /편안함/);
  await page.screenshot({ path: join(captures, "desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: join(captures, "mobile.png"), fullPage: true });
  await page.locator('[data-action="comparison-unsure"]').click();
  assert.equal(commands.filter(c => c.action.op === "respond_comparison").length, 0);
  await apply();
  await page.waitForFunction(() => !document.querySelector('[data-action="comparison-choose"]'));
  let view = await rpc("inspect");
  assert.equal(view.snapshot.bindings.filter(b => b.domain === "PI").length, 0);
  assert.equal(view.state.comparison, null);

  await rpc("reset"); await page.reload(); await choices().first().waitFor();
  await choices().last().click();
  assert.equal(await page.locator("#free-text").getAttribute("required"), null);
  await apply();
  await page.waitForFunction(() => !document.querySelector('[data-action="comparison-choose"]'));
  view = await rpc("inspect");
  let pi = view.snapshot.bindings.filter(b => b.domain === "PI");
  assert.equal(pi.length, 1); assert.equal(pi[0].confirmed, true); assert.equal(pi[0].origin, "inferred");
  assert.equal(pi[0].strength, "soft"); assert.equal(view.snapshot.consents.length, 0);
  const replay = commands.findLast(c => c.action.op === "respond_comparison");
  const response = await page.request.post(`${url}/api/command`, { data: replay });
  assert.notEqual((await response.json()).outcome, "rejected");
  assert.equal((await rpc("inspect")).snapshot.bindings.filter(b => b.domain === "PI").length, 1);

  await rpc("reset"); await page.reload(); await choices().first().waitFor();
  await choices().first().click();
  const reason = "오래 앉아 있어요. 허벅지가 조이는 건 싫어요.";
  await page.locator("#free-text").fill(reason);
  await page.screenshot({path:join(captures,"choice-and-reason.png"),fullPage:true});
  await apply();
  await page.waitForFunction(() => !document.querySelector('[data-action="comparison-choose"]'));
  view = await rpc("inspect");
  const feedback = view.snapshot.feedback.find(f => f.reaction === "selected");
  assert.equal(feedback.evidence_refs.length, 2);
  assert.equal(commands.findLast(c => c.action.op === "respond_comparison").action.text, reason);
  assert.equal(view.snapshot.bindings.filter(b => b.domain === "PI" && b.confirmed).length, 0);
  let remembered = view.state.memories.find(m => m.content.includes("허벅지"));
  assert.equal(remembered.confirmed, false);
  assert.equal(view.snapshot.consents.length, 0);
  await page.reload();
  assert.equal(await page.locator('[data-action="future"]').count(), 0);
  await page.locator('[data-action="end"]').filter({hasText:"상품 선택 없이 종료"}).click();
  await page.getByRole("heading", {name:"탐색을 마쳤어요",exact:true}).waitFor();
  assert.equal((await rpc("inspect")).snapshot.consents.length, 0);
  await page.locator("#reflected-info summary").click();
  await page.locator(`[data-action="confirm"][data-memory="${remembered.ref.id}"]`).click();
  await page.locator('.review [data-decision="accept"]').click();
  await page.locator(`[data-save="${remembered.ref.id}"]`).waitFor();
  await page.locator(`[data-save="${remembered.ref.id}"]`).check();
  await page.locator(`[data-action="future"][data-memory="${remembered.ref.id}"]`).click();
  assert.equal(await page.locator("[data-consent]").isChecked(), false);
  await page.screenshot({path:join(captures,"end-consent.png"),fullPage:true});
  await page.locator("[data-consent]").check();
  await page.locator('.review [data-decision="accept"]').click();
  view = await rpc("inspect");
  assert.equal(view.snapshot.consents.length, 1);
  assert.equal(view.snapshot.memories.filter(m => m.scope === "long_term" && m.content.includes("허벅지")).length, 1);

  await rpc("reset"); await page.reload(); await choices().first().waitFor();
  view = await rpc("inspect");
  const stale = { contract_version: view.state.contract_version, command_id: "stale-hypothesis",
    request_id: view.state.request.id, expected: view.state.expected,
    action: { op: "respond_comparison", candidate_set_ref: view.state.comparison.candidate_set_ref,
      candidate_id: view.state.comparison.options[0].candidate_id, decision: "choose" } };
  await rpc("change_catalog");
  const rejected = await page.request.post(`${url}/api/command`, { data: stale });
  assert.equal((await rejected.json()).outcome, "rejected");
  assert.equal((await rpc("inspect")).snapshot.bindings.filter(b => b.domain === "PI").length, 0);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: "PASS", checks: ["desktop/mobile", "staged choice without required text", "unsure keeps PI unconfirmed", "explicit choice-only PI confirmation", "joint image/reason intake", "end-only unchecked consent", "closed-session reason review", "replay", "stale catalog rejected", "no runtime errors"], captures }));
} finally {
  if (browser) await browser.close();
  if (backend.exitCode === null) {
    const stopped = new Promise(resolve => backend.once("close", resolve));
    backend.stdin.end(`${JSON.stringify({op:"close"})}\n`);
    await stopped;
  }
  if (!process.argv[2]) await rm(captures, {recursive:true, force:true});
}
