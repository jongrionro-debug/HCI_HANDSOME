#!/usr/bin/env node
/**
 * Issue #8 site probe: 29CM / Ably PI fill-rate and speed comparison.
 * Small sample, 2s+ interval, one request at a time, stops on 401/403/418/429/CAPTCHA.
 * No login, no profile reuse, no model calls. Raw output goes outside the repository.
 */
import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { prepareOutputRoot } from './crawl_naver.mjs';

export const PROBE_VERSION = 'probe-v1';
const PI = ['Type', 'Brand', 'Price', 'Color', 'Fit', 'Fabric', 'Detail'];
const BLOCK_STATUS = new Set([401, 403, 418, 429]);
const pause = ms => new Promise(r => setTimeout(r, ms));
const TOP = /상의|티셔츠|셔츠|니트|스웨터|맨투맨|스웻|후디|후드|블라우스|카디건|탑/;
const BOTTOM = /하의|팬츠|바지|슬랙스|데님|청바지|스커트|치마|쇼츠|레깅스/;

/** Label-anchored patterns. Reviews are cut off first; "상품상세 참조" values count as referred, not filled. */
const REFERRED = /상품\s*상세\s*참[조고]|상세\s*페이지\s*참[조고]|상세\s*참[조고]/;
export const TEXT_PATTERNS = {
  Color: /(?:색상|컬러|\bcolor)\s*[:：]?\s*(?!\/?\s*(?:size|사이즈|성인))([^\s:：][^\n]{0,39})/i,
  Fit: /([^\n]{0,20}(?:핏감|\bFIT\b|(?:루즈|오버|슬림|와이드|레귤러|세미|스트레이트|부츠컷)\s*핏)[^\n]{0,30})/i,
  Fabric: /(?:제품\s*소재|주요\s*소재)\s*[:：]?\s*([^\n]{1,60})|((?:겉감|안감|shell|outshell|lining)[^\n:]{0,12}[:：]?[^\n]{0,30}?\d+\s*%[^\n]{0,30})|((?:면|코튼|cotton|폴리|polyester|nylon|나일론|울|wool|레이온|rayon|린넨|linen|스판|span|spandex|아크릴|acrylic|캐시미어|실크|silk|비스코스|텐셀|모달|합성섬유|천연)[^\n]{0,20}\d+\s*%[^\n]{0,30})/i,
  Detail: /([^\n]{0,20}(?:디테일|detail)[^\n]{0,40})/i,
};

/** Keep product-description text; drop reviews/Q&A, where fit/size comments produce false hits. */
export function descriptionText(text) {
  const cut = text.search(/\n\s*리뷰\s*\(?\d*|\n\s*전체 상품 리뷰/);
  return cut > 0 ? text.slice(0, cut) + '\n' + (text.match(/상품정보[\s\S]{0,1500}?제조국[^\n]{0,30}/)?.[0] || '') : text;
}

export function groupOf(text) {
  const bottom = BOTTOM.test(text); const top = TOP.test(text);
  if (bottom && !top) return 'bottom';
  if (top && !bottom) return 'top';
  if (/하의/.test(text)) return 'bottom';
  if (/상의/.test(text)) return 'top';
  return null;
}

/** Decide each feature's source. structured = JSON-LD/meta, text = labelled visible text, referred = "see detail page" (image/description), none = absent. */
export function classify(snapshot) {
  const out = {};
  const ld = snapshot.ld;
  const text = descriptionText(snapshot.text || '');
  out.Type = ld?.category || snapshot.breadcrumb?.length ? { source: 'structured', value: ld?.category || snapshot.breadcrumb.join(' > ') }
    : snapshot.metaCategory ? { source: 'structured', value: snapshot.metaCategory } : { source: 'none' };
  out.Brand = ld?.brand ? { source: 'structured', value: ld.brand } : snapshot.textBrand ? { source: 'text', value: snapshot.textBrand } : { source: 'none' };
  out.Price = ld?.price != null ? { source: 'structured', value: `${ld.price} ${ld.currency || ''}`.trim() }
    : /\d[\d,]*\s*원/.test(text) ? { source: 'text', value: /(\d[\d,]*)\s*원/.exec(text)[0] } : { source: 'none' };
  for (const [feature, re] of Object.entries(TEXT_PATTERNS)) {
    const hits = [...text.matchAll(new RegExp(re.source, re.flags.includes('g') ? re.flags : re.flags + 'g'))].map(m => (m.slice(1).find(Boolean) || m[0]).replace(/\s+/g, ' ').trim());
    const real = hits.find(h => h && !REFERRED.test(h) && !/^(사이즈|size|장바구니|SIZE)/i.test(h));
    if (real) out[feature] = { source: 'text', value: real.slice(0, 80) };
    else if (hits.some(h => REFERRED.test(h))) out[feature] = { source: 'referred', value: '상품상세 참조' };
    else out[feature] = { source: 'none' };
  }
  return out;
}

export function summarize(records) {
  const rows = {};
  for (const feature of PI) {
    const counts = { structured: 0, text: 0, referred: 0, none: 0 };
    for (const r of records) counts[r.pi[feature].source] += 1;
    const total = records.length;
    rows[feature] = { ...counts, fill_rate: total ? Number(((counts.structured + counts.text) / total).toFixed(2)) : null };
  }
  return rows;
}

async function readSnapshot(page) {
  return await page.evaluate(() => {
    const t = v => (typeof v === 'string' ? v.trim().slice(0, 1000) : '');
    let ld = null; let breadcrumb = null;
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const data = JSON.parse(s.textContent); const items = Array.isArray(data) ? data : [data];
        for (const d of items) {
          if (d['@type'] === 'Product') {
            const offer = Array.isArray(d.offers) ? d.offers[0] : d.offers;
            ld = { name: t(d.name), category: t(d.category) || null, brand: t(d.brand?.name || d.brand) || null,
              price: offer?.price ?? null, currency: offer?.priceCurrency ?? null, image_count: [d.image].flat().filter(Boolean).length };
          }
          if (d['@type'] === 'BreadcrumbList') breadcrumb = (d.itemListElement || []).map(i => t(i.name)).filter(n => n && n !== '홈');
        }
      } catch { /* malformed structured data */ }
    }
    const metaDesc = [...document.querySelectorAll('meta[property="og:description"]')].map(m => m.content).pop() || '';
    const body = document.body?.innerText || '';
    const blocked = /접속이.*제한|자동입력 방지|보안문자|captcha|Attention Required/i.test(body + document.title) ? 'blocked_page' : null;
    return { title: document.title, ld, breadcrumb, metaCategory: t(metaDesc), text: body.slice(0, 20000), blocked,
      imageCount: document.images.length };
  });
}

/** Expand the product-info tab if one exists. Never touches purchase/cart/review controls. */
async function expandInfo(page, intervalMs) {
  const tab = page.getByText(/^상품\s*정보$/).first();
  if (!await tab.count()) return false;
  try { await tab.click({ timeout: 3000 }); await pause(Math.min(intervalMs, 1500)); return true; } catch { return false; }
}

async function discover(site, page, perGroup, intervalMs) {
  const candidates = { top: [], bottom: [] };
  if (site === '29cm') {
    await page.goto('https://www.29cm.co.kr/sitemap/sitemap-root.xml', { waitUntil: 'domcontentloaded' });
    const index = await page.evaluate(() => document.body.innerText);
    const files = [...index.matchAll(/https:\/\/www\.29cm\.co\.kr\/sitemap\/sitemap-item-\d+\.xml/g)].map(m => m[0]);
    const picks = files.sort(() => Math.random() - 0.5).slice(0, 4);
    const urls = [];
    for (const pick of picks) {
      await pause(intervalMs);
      await page.goto(pick, { waitUntil: 'domcontentloaded' });
      const xml = await page.evaluate(() => document.body.innerText);
      urls.push(...[...xml.matchAll(/https:\/\/www\.29cm\.co\.kr\/products\/\d+/g)].map(m => m[0]).sort(() => Math.random() - 0.5).slice(0, perGroup * 30));
    }
    const shuffled = urls.sort(() => Math.random() - 0.5);
    const pick = picks.join(',');
    return { pool: shuffled, source: pick };
  }
  await page.goto('https://mobile.a-bly.com/', { waitUntil: 'domcontentloaded' });
  await pause(3000);
  for (const [label, group] of [['상의', 'top'], ['팬츠', 'bottom']]) {
    const tab = page.getByText(label, { exact: true }).first();
    if (await tab.count()) { await tab.click(); await pause(3000); }
    const links = await page.evaluate(() => [...new Set([...document.querySelectorAll('a[href*="/goods/"]')].map(a => a.href))]);
    candidates[group].push(...links.map(u => u.replace('//m.a-bly.com', '//mobile.a-bly.com')));
    await pause(intervalMs);
  }
  return { grouped: candidates, source: 'home tabs' };
}

export async function main(args = process.argv.slice(2)) {
  const get = (flag, fallback) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : fallback; };
  const site = get('--site'); const outArg = get('--out');
  if (!['29cm', 'ably'].includes(site) || !outArg) { console.log('node scripts/probe_sites.mjs --site 29cm|ably --out <저장소 밖 경로> [--per-group 5] [--max-visits 40] [--interval-ms 2000] [--headless]'); return 2; }
  const perGroup = Number(get('--per-group', 5)); const maxVisits = Number(get('--max-visits', 40));
  const intervalMs = Math.max(2000, Number(get('--interval-ms', 2000)));
  const root = await prepareOutputRoot(outArg);
  const dir = join(root, site); await mkdir(dir, { recursive: true });
  const { chromium } = await import('playwright');
  const browser = await chromium.launch({ headless: args.includes('--headless') });
  const records = []; const log = []; let stopped = null; const started = Date.now();
  const visitedPath = join(dir, 'visited.json');
  const visited = new Set(await readFile(visitedPath, 'utf8').then(JSON.parse, () => []));
  for (const f of (await readdir(dir)).filter(f => /^\d+\.json$/.test(f))) records.push(JSON.parse(await readFile(join(dir, f), 'utf8')));
  try {
    const page = await (await browser.newContext()).newPage();
    const found = await discover(site, page, perGroup, intervalMs);
    const queue = site === '29cm' ? found.pool.map(url => ({ url, group: null })) :
      [...found.grouped.top.map(url => ({ url, group: 'top' })), ...found.grouped.bottom.map(url => ({ url, group: 'bottom' }))];
    const filled = { top: records.filter(r => r.group === 'top').length, bottom: records.filter(r => r.group === 'bottom').length }; let visits = 0;
    for (const item of queue) {
      if (stopped || visits >= maxVisits || (filled.top >= perGroup && filled.bottom >= perGroup)) break;
      if (item.group && filled[item.group] >= perGroup) continue;
      if (visited.has(item.url)) continue;
      await pause(intervalMs); visits += 1; visited.add(item.url);
      if (visits % 20 === 0) { await writeFile(visitedPath, JSON.stringify([...visited])); console.error(`visits=${visits} top=${filled.top} bottom=${filled.bottom} elapsed=${Math.round((Date.now() - started) / 1000)}s`); }
      const t0 = Date.now();
      let status = null; let snapshot = null; let error = null; let expanded = false;
      try {
        const response = await page.goto(item.url, { waitUntil: 'domcontentloaded', timeout: 15000 });
        status = response?.status() ?? null;
        await pause(2500);
        if (status && BLOCK_STATUS.has(status)) { stopped = `http_${status}`; log.push({ url: item.url, status }); break; }
        snapshot = await readSnapshot(page);
        if (snapshot.blocked) { stopped = snapshot.blocked; log.push({ url: item.url, status, blocked: snapshot.blocked }); break; }
        expanded = await expandInfo(page, intervalMs);
        if (expanded) { const after = await readSnapshot(page); snapshot.text = after.text; snapshot.imageCount = after.imageCount; }
      } catch (e) { error = String(e.message || e).slice(0, 200); }
      const elapsedMs = Date.now() - t0;
      if (!snapshot) { log.push({ url: item.url, status, error, elapsed_ms: elapsedMs }); continue; }
      const group = item.group || groupOf(`${snapshot.breadcrumb?.join(' ') || ''} ${snapshot.metaCategory} ${snapshot.title}`);
      if (!group || filled[group] >= perGroup) { log.push({ url: item.url, status, skipped: group ? 'group_full' : 'not_top_or_bottom', elapsed_ms: elapsedMs }); continue; }
      filled[group] += 1;
      const record = { url: item.url, group, http_status: status, elapsed_ms: elapsedMs, info_tab_expanded: expanded,
        image_count: snapshot.imageCount, pi: classify(snapshot), title: snapshot.title };
      records.push(record);
      const id = /(\d+)\/?$/.exec(new URL(item.url).pathname)?.[1] || String(records.length);
      await writeFile(join(dir, `${id}.json`), JSON.stringify({ ...record, text_head: snapshot.text.slice(0, 20000) }, null, 1));
    }
  } finally { await writeFile(visitedPath, JSON.stringify([...visited])); await browser.close(); }
  const elapsedTotal = Date.now() - started;
  const summary = {
    probe_version: PROBE_VERSION, site, discovered_from: undefined, sample: records.length,
    by_group: { top: records.filter(r => r.group === 'top').length, bottom: records.filter(r => r.group === 'bottom').length },
    brands: Object.fromEntries(Object.entries(records.reduce((m, r) => { const b = r.pi.Brand.value || '?'; m[b] = (m[b] || 0) + 1; return m; }, {})).sort((x, y) => y[1] - x[1]).slice(0, 15)),
    fill: summarize(records), stopped, mean_ms_per_product: records.length ? Math.round(records.reduce((s, r) => s + r.elapsed_ms, 0) / records.length) : null,
    wall_ms: elapsedTotal, interval_ms: intervalMs, skipped_or_failed: log.length, log,
  };
  await writeFile(join(dir, 'summary.json'), JSON.stringify(summary, null, 1));
  console.log(JSON.stringify({ site, sample: summary.sample, by_group: summary.by_group, fill: summary.fill, stopped, mean_ms_per_product: summary.mean_ms_per_product }, null, 1));
  return stopped ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().then(code => { process.exitCode = code; }, error => { console.error(error.message); process.exitCode = 1; });
}
