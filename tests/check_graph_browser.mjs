/** ADR 0013 graph grid over real HTTP + SQLite, offline scripted model.
 * Needs the optional graph dependency: LUMI_GRAPH_PYTHON=~/.venvs/lumi-graph/bin/python node tests/check_graph_browser.mjs
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright";

const captures = process.argv[2] || await mkdtemp(join(tmpdir(), "lumi-graph-"));
await mkdir(captures, { recursive: true });
const backend = spawn(process.env.LUMI_GRAPH_PYTHON || "python3", ["-u", "-B", "-W", "ignore", "-m", "tests.graph_browser_fixture"],
  { env: { ...process.env, PYTHONPATH: "src" }, stdio: ["pipe", "pipe", "pipe"] });
const lines = createInterface({ input: backend.stdout })[Symbol.asyncIterator]();
let stderr = "", browser;
backend.stderr.on("data", data => { stderr += data; });
backend.stdin.on("error", () => {});
async function next() {
  let timer;
  try { const line = await Promise.race([lines.next(), new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(stderr || "fixture timeout")), 20000);
  })]); assert.equal(line.done, false, stderr); return JSON.parse(line.value); }
  finally { clearTimeout(timer); }
}
async function rpc(op) { backend.stdin.write(`${JSON.stringify({ op })}\n`); return next(); }
try {
  const { url } = await next();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1360, height: 940 }, reducedMotion: "reduce" });
  const errors = [], commands = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("request", req => { if (req.url() === `${url}/api/command`) commands.push(req.postDataJSON()); });
  await page.goto(url);
  const cards = page.locator("article.card");
  await cards.first().waitFor();
  assert.equal(await cards.count(), 8);
  assert.equal(await page.locator('[data-action="dislike"]').count(), 8);
  assert.equal(await page.locator('[data-action="all-bad"]').count(), 1);
  assert.match(await page.locator(".graph-panel").innerText(), /출근/);
  await page.screenshot({ path: join(captures, "desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: join(captures, "mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1360, height: 940 });

  // Multi-select every Wide card, mark one other card "별로", submit once.
  let view = await rpc("inspect");
  const grid = view.intent.last_grid.cards;
  const wide = grid.filter(c => c.facts.Fit?.[0] === "Wide").map(c => c.candidate_id);
  const other = grid.find(c => c.facts.Fit && c.facts.Fit[0] !== "Wide").candidate_id;
  const memories = view.state.memories.length;
  for (const id of wide) await page.locator(`[data-action="select"][data-card="${id}"]`).click();
  await page.locator(`[data-action="dislike"][data-card="${other}"]`).click();
  assert.match(await page.locator(`[data-action="dislike"][data-card="${other}"]`).innerText(), /별로 취소/);
  await page.locator('[data-form="feedback"] button.primary').click();
  await page.waitForFunction(turn => document.querySelector("article.card") && !document.querySelector('[aria-pressed="true"][data-action="select"]'), null);
  view = await rpc("inspect");
  const sent = commands.findLast(c => c.action.op === "grid_feedback");
  assert.deepEqual(sent.action.selections.map(s => s.candidate_id).sort(), [...wide].sort());
  assert.deepEqual(sent.action.dislikes, [other]);
  assert.equal(view.intent.turn, 2);
  assert.equal(view.state.memories.length, memories, "image reactions alone never create memory");

  // "다 별로" clears the draft selections and sends all_bad.
  await page.locator('[data-action="select"]').first().click();
  await page.locator('[data-action="all-bad"]').click();
  assert.equal(await page.locator('[aria-pressed="true"][data-action="select"]').count(), 0);
  await page.locator('[data-form="feedback"] button.primary').click();
  await page.waitForFunction(() => document.querySelector('[data-action="all-bad"]')?.getAttribute("aria-pressed") === "false");
  view = await rpc("inspect");
  assert.equal(commands.findLast(c => c.action.op === "grid_feedback").action.all_bad, true);
  assert.equal(view.intent.turn, 3);

  // Two contrasts on Wide raise a chip; pin it and every card follows.
  view = await rpc("inspect");
  const grid3 = view.intent.last_grid.cards;
  for (const c of grid3.filter(c => c.facts.Fit?.[0] === "Wide")) await page.locator(`[data-action="select"][data-card="${c.candidate_id}"]`).click();
  await page.locator('[data-form="feedback"] button.primary').click();
  const pin = page.locator('.chip [data-adjust="pin"]').first();
  await pin.waitFor();
  await pin.click();
  await page.locator('.chip.pinned').waitFor();
  await cards.first().waitFor();
  view = await rpc("inspect");
  assert.ok(view.intent.last_grid.cards.every(c => c.facts.Fit?.[0] === "Wide"));
  assert.equal(commands.findLast(c => c.action.op === "adjust_intent").action.action, "pin");
  await page.screenshot({ path: join(captures, "pinned.png"), fullPage: true });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: "PASS", checks: ["8-card grid desktop/mobile", "multi-select + 별로 in one grid_feedback",
    "no memory from image reactions", "다 별로 clears draft", "chip appears after repeated contrast", "pin narrows grid", "no runtime errors"], captures }));
} finally {
  if (browser) await browser.close();
  if (backend.exitCode === null) {
    const stopped = new Promise(resolve => backend.once("close", resolve));
    backend.stdin.end(`${JSON.stringify({ op: "close" })}\n`);
    await stopped;
  }
  if (!process.argv[2]) await rm(captures, { recursive: true, force: true });
}
