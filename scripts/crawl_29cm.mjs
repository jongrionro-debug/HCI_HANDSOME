#!/usr/bin/env node
/**
 * 29CM catalog collector for LUMI tops/bottoms.
 * Discovers products from public category listing pages (not random sitemap picks), then reads
 * each product page one at a time (>= 2 s apart). No login, no profile reuse, no model calls.
 * Stops on HTTP 401/403/418/429 or a CAPTCHA/blocked page; never retries around blocking.
 * Output (outside the repository): products/<id>.json, images/<id>/<n>.<ext>, discovery.json, run.json, summary.json.
 */
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile, stat } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { prepareOutputRoot } from './crawl_naver.mjs';
import { classify, summarize } from './probe_sites.mjs';

export const COLLECTOR_VERSION = '29cm-category-v1';
const BASE = 'https://www.29cm.co.kr';
const BLOCK_STATUS = new Set([401, 403, 418, 429]);
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const pause = ms => new Promise(r => setTimeout(r, ms));
const failure = (code, message = code) => Object.assign(new Error(message), { code });

/** Medium categories per group. Codes observed on the public 29CM category menu (2026-11-17). */
export const SEEDS = [
  { group: 'top', gender: 'women', large: '268100100', medium: '268103100', name: '여성의류 > 상의' },
  { group: 'top', gender: 'women', large: '268100100', medium: '268105100', name: '여성의류 > 니트웨어' },
  { group: 'top', gender: 'men', large: '272100100', medium: '272103100', name: '남성의류 > 상의' },
  { group: 'top', gender: 'men', large: '272100100', medium: '272110100', name: '남성의류 > 니트웨어' },
  { group: 'bottom', gender: 'women', large: '268100100', medium: '268106100', name: '여성의류 > 바지' },
  { group: 'bottom', gender: 'women', large: '268100100', medium: '268107100', name: '여성의류 > 스커트' },
  { group: 'bottom', gender: 'men', large: '272100100', medium: '272104100', name: '남성의류 > 하의' },
];
/** Small categories that are outerwear-like or not a single top/bottom garment. */
const EXCLUDED_SMALL = /카디건|베스트|조끼|가디건|세트|셋업/;

export function listingUrl({ large, medium, small = null, page = 1 }) {
  const u = new URL('/store/category/list', BASE);
  u.searchParams.set('categoryLargeCode', large);
  u.searchParams.set('categoryMediumCode', medium);
  u.searchParams.set('sort', 'RECOMMENDED');
  u.searchParams.set('defaultSort', 'RECOMMENDED');
  u.searchParams.set('page', String(page));
  if (small) u.searchParams.set('categorySmallCode', small);
  return u.href;
}

/** Small categories under one medium code, from anchor (href, text) pairs on a listing page. */
export function parseSmallCategories(anchors, medium) {
  const out = new Map();
  for (const { href, text } of anchors) {
    let u; try { u = new URL(href); } catch { continue; }
    if (u.hostname !== 'www.29cm.co.kr' || u.pathname !== '/store/category/list') continue;
    const small = u.searchParams.get('categorySmallCode');
    if (u.searchParams.get('categoryMediumCode') !== medium || !small || !/^\d+$/.test(small)) continue;
    const name = (text || '').replace(/\s+/g, ' ').trim();
    if (name && !out.has(small)) out.set(small, name);
  }
  return [...out].map(([code, name]) => ({ code, name, excluded: EXCLUDED_SMALL.test(name) }));
}

/** Product IDs from listing anchors (product.29cm.co.kr/catalog/<id> or www.29cm.co.kr/products/<id>), in page order. */
export function parseProductIds(hrefs) {
  const ids = [];
  for (const href of hrefs) {
    let u; try { u = new URL(href); } catch { continue; }
    const m = (u.hostname === 'product.29cm.co.kr' && /^\/catalog\/(\d+)\/?$/.exec(u.pathname)) ||
      (u.hostname === 'www.29cm.co.kr' && /^\/products\/(\d+)\/?$/.exec(u.pathname));
    if (m && !ids.includes(m[1])) ids.push(m[1]);
  }
  return ids;
}

/** Interleave candidates across small categories so an early stop still covers many subcategories. */
export function roundRobin(lists) {
  const out = []; const seen = new Set();
  const max = Math.max(0, ...lists.map(l => l.items.length));
  for (let i = 0; i < max; i++) {
    for (const l of lists) {
      const id = l.items[i];
      if (id && !seen.has(id)) { seen.add(id); out.push({ id, ...l.meta }); }
    }
  }
  return out;
}

/**
 * Split the product page's visible text into the seller description and the 상품정보 (notice) table.
 * Seller identity rows (판매자정보: 사업자등록번호, 대표자, 주소) and reviews are excluded.
 */
export function extractSections(text) {
  const lines = String(text || '').replace(/\r/g, '').split('\n');
  const find = (re, from = 0) => { for (let i = from; i < lines.length; i++) if (re.test(lines[i].trim())) return i; return -1; };
  let description = '';
  const d0 = find(/^상품설명$/);
  if (d0 >= 0) {
    let d1 = find(/^(상품설명 (더보기|접기|닫기)|안전한 거래를 위해 확인해주세요|사이즈정보|상품정보)$/, d0 + 1);
    if (d1 < 0) d1 = Math.min(lines.length, d0 + 400);
    description = lines.slice(d0 + 1, d1).map(l => l.replace(/[​﻿]/g, '').trim()).filter(Boolean).join('\n');
  }
  let productInfo = '';
  const i0 = find(/^상품정보$/, Math.max(0, d0));
  if (i0 >= 0) {
    let i1 = find(/^(판매자정보|리뷰\s*\(\d+\)|배송정보|교환, 환불, A\/S 안내)$/, i0 + 1);
    if (i1 < 0) i1 = Math.min(lines.length, i0 + 40);
    productInfo = lines.slice(i0 + 1, i1).map(l => l.trim()).filter(Boolean)
      .filter(l => !/^A\/S 책임자|고객행복센터|^품질보증기준/.test(l)).join('\n');
  }
  return { description: description.slice(0, 6000), productInfo: productInfo.slice(0, 3000) };
}

/** 상품정보 rows as {name, value}; rows are tab-separated in innerText. */
export function parseInfoRows(productInfo) {
  return productInfo.split('\n').map(l => l.split('\t')).filter(p => p.length >= 2 && p[0].trim())
    .map(([name, ...rest]) => ({ name: name.trim(), value: rest.join(' ').trim() }));
}

export function priceOf(ld) {
  const offer = Array.isArray(ld?.offers) ? ld.offers[0] : ld?.offers;
  const num = v => (typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'string' && /^\d+(\.\d+)?$/.test(v) ? Number(v) : null);
  const list = offer?.priceSpecification;
  return {
    amount: num(offer?.price), currency: typeof offer?.priceCurrency === 'string' ? offer.priceCurrency : null,
    list_amount: num(Array.isArray(list) ? list[0]?.price : list?.price),
    availability: typeof offer?.availability === 'string' ? offer.availability.replace('https://schema.org/', '') : null,
  };
}

/** Main product image URLs from Product JSON-LD (ImageObject.contentUrl or string), img.29cm.co.kr only. */
export function mainImages(ld, max = 3) {
  const urls = [];
  for (const image of [ld?.image].flat()) {
    const raw = typeof image === 'string' ? image : image?.contentUrl || image?.url;
    if (typeof raw !== 'string') continue;
    try {
      const u = new URL(raw);
      if (u.protocol !== 'https:' || u.hostname !== 'img.29cm.co.kr' || u.username || u.password || u.port) continue;
      u.search = ''; u.hash = '';
      if (!urls.includes(u.href)) urls.push(u.href);
    } catch { /* skip malformed */ }
    if (urls.length >= max) break;
  }
  return urls;
}

export function imageExt(bytes) {
  if (bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) return 'png';
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return 'jpg';
  if (bytes.length >= 12 && bytes.toString('latin1', 0, 4) === 'RIFF' && bytes.toString('latin1', 8, 12) === 'WEBP') return 'webp';
  return null;
}

export async function fetchImage(url, { fetchImpl = fetch, maxBytes = MAX_IMAGE_BYTES } = {}) {
  const u = new URL(url);
  if (u.protocol !== 'https:' || u.hostname !== 'img.29cm.co.kr') throw failure('unsupported_image_host');
  const response = await fetchImpl(u.href, { redirect: 'error', headers: { Accept: 'image/png,image/jpeg,image/webp' } });
  if (!response.ok) { await response.body?.cancel?.(); throw failure(`image_http_${response.status}`); }
  if (!String(response.headers.get('content-type') || '').startsWith('image/')) { await response.body?.cancel?.(); throw failure('image_mime'); }
  if (Number(response.headers.get('content-length')) > maxBytes) { await response.body?.cancel?.(); throw failure('image_too_large'); }
  const buffer = Buffer.from(await response.arrayBuffer());
  if (buffer.length > maxBytes) throw failure('image_too_large');
  const ext = imageExt(buffer);
  if (!ext) throw failure('image_signature');
  return { buffer, ext, sha256: createHash('sha256').update(buffer).digest('hex') };
}

export function buildRecord(id, meta, snapshot, crawledAt) {
  const { description, productInfo } = extractSections(snapshot.text);
  const ld = snapshot.ld || {};
  const breadcrumb = snapshot.breadcrumb || [];
  const pi = classify({ ld: { category: ld.category || null, brand: ld.brand?.name || (typeof ld.brand === 'string' ? ld.brand : null),
    price: priceOf(ld).amount, currency: priceOf(ld).currency }, breadcrumb, text: `${description}\n${productInfo}` });
  return {
    collector_version: COLLECTOR_VERSION, url: `${BASE}/products/${id}`, product_id: id,
    group: meta.group, gender: meta.gender, discovered_from: { medium: meta.medium_name, small: meta.small_name, small_code: meta.small_code },
    breadcrumb, subcategory: breadcrumb.join(' > ') || null,
    title: typeof ld.name === 'string' ? ld.name : snapshot.title, brand: pi.Brand.value || null, price: priceOf(ld),
    pi, product_info: productInfo, product_info_rows: parseInfoRows(productInfo), description,
    images: mainImages(ld).map((source_url, index) => ({ index, source_url, download_status: 'pending' })),
    http_status: snapshot.status, crawled_at: crawledAt,
  };
}

async function readSnapshot(page) {
  return await page.evaluate(() => {
    let ld = null; let breadcrumb = null;
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      if (s.textContent.length > 512 * 1024) continue;
      try {
        for (const d of [JSON.parse(s.textContent)].flat()) {
          if (d['@type'] === 'Product') ld = d;
          if (d['@type'] === 'BreadcrumbList') breadcrumb = (d.itemListElement || []).map(i => String(i.name || '').trim()).filter(n => n && n !== '홈');
        }
      } catch { /* malformed structured data */ }
    }
    const body = document.body?.innerText || '';
    const blocked = /접속이.*제한|자동입력 방지|보안문자|captcha|Attention Required|비정상적인 접근/i.test(body.slice(0, 5000) + document.title) ? 'blocked_page' : null;
    return { title: document.title, ld, breadcrumb, text: body.slice(0, 60000), blocked };
  });
}

async function clickIfPresent(page, re) {
  const el = page.getByText(re).first();
  if (!await el.count()) return false;
  try { await el.click({ timeout: 3000 }); await pause(1200); return true; } catch { return false; }
}

async function exists(path) { try { await stat(path); return true; } catch { return false; } }
async function writeJson(path, value) { const tmp = `${path}.tmp`; await writeFile(tmp, JSON.stringify(value, null, 1)); await rename(tmp, path); }

async function gotoChecked(page, url, state) {
  const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 });
  const status = response?.status() ?? null;
  if (status && BLOCK_STATUS.has(status)) { state.stopped = `http_${status}`; state.log.push({ url, status, event: 'stopped' }); return null; }
  return status;
}

async function discover(page, root, intervalMs, state) {
  const path = join(root, 'discovery.json');
  if (await exists(path)) return JSON.parse(await readFile(path, 'utf8'));
  const lists = [];
  for (const seed of SEEDS) {
    if (state.stopped) break;
    await pause(intervalMs);
    if (await gotoChecked(page, listingUrl(seed), state) === null && state.stopped) break;
    await page.waitForSelector('a[href*="/catalog/"]', { timeout: 15000 }).catch(() => {});
    const anchors = await page.evaluate(() => [...document.querySelectorAll('a')].map(a => ({ href: a.href, text: a.innerText })));
    const smalls = parseSmallCategories(anchors, seed.medium);
    for (const small of smalls) {
      if (small.excluded) { lists.push({ ...seed, small: small.code, small_name: small.name, excluded: true, ids: [] }); continue; }
      if (state.stopped) break;
      await pause(intervalMs);
      const url = listingUrl({ ...seed, small: small.code });
      if (await gotoChecked(page, url, state) === null && state.stopped) break;
      await page.waitForSelector('a[href*="/catalog/"]', { timeout: 15000 }).catch(() => {});
      const snap = await page.evaluate(() => ({ hrefs: [...document.querySelectorAll('a')].map(a => a.href), blocked: /자동입력 방지|보안문자|captcha/i.test(document.body?.innerText?.slice(0, 3000) || '') }));
      if (snap.blocked) { state.stopped = 'blocked_page'; state.log.push({ url, event: 'stopped' }); break; }
      const ids = parseProductIds(snap.hrefs);
      lists.push({ ...seed, small: small.code, small_name: small.name, ids });
      console.error(`listing ${seed.name} > ${small.name}: ${ids.length}`);
    }
  }
  const discovery = { discovered_at: new Date().toISOString(), lists };
  if (!state.stopped) await writeJson(path, discovery);
  return discovery;
}

async function downloadImages(root, record, intervalMs, state, fetchImpl) {
  const dir = join(root, 'images', record.product_id);
  await mkdir(dir, { recursive: true });
  for (const image of record.images) {
    if (image.download_status === 'downloaded' && await exists(join(root, image.local_path))) continue;
    if (state.stopped) { image.download_status = 'not_attempted'; continue; }
    await pause(Math.min(intervalMs, 1000));
    try {
      const result = await fetchImage(image.source_url, { fetchImpl });
      const rel = `images/${record.product_id}/${image.index}.${result.ext}`;
      await writeFile(join(root, rel), result.buffer);
      Object.assign(image, { download_status: 'downloaded', local_path: rel, sha256: result.sha256, bytes: result.buffer.length });
      delete image.error;
    } catch (error) {
      Object.assign(image, { download_status: 'failed', error: error.code || 'image_download_failed' });
      if (/^image_http_(401|403|418|429)$/.test(error.code || '')) { state.stopped = error.code; state.log.push({ url: image.source_url, event: 'stopped', error: error.code }); }
    }
  }
}

export function summarizeRecords(records) {
  const by = key => Object.fromEntries(Object.entries(records.reduce((m, r) => { const k = key(r) || '?'; m[k] = (m[k] || 0) + 1; return m; }, {})).sort((a, b) => b[1] - a[1]));
  const groups = {};
  for (const g of ['top', 'bottom']) {
    const rs = records.filter(r => r.group === g);
    groups[g] = { count: rs.length, by_subcategory: by.call(null, r => r.subcategory), fill: summarize(rs) };
  }
  return { total: records.length, by_group: { top: groups.top.count, bottom: groups.bottom.count }, by_gender: by(r => `${r.gender}/${r.group}`),
    by_subcategory: by(r => r.subcategory), fill: summarize(records), groups,
    images_downloaded: records.reduce((s, r) => s + r.images.filter(i => i.download_status === 'downloaded').length, 0) };
}

export async function main(args = process.argv.slice(2)) {
  const get = (flag, fallback) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : fallback; };
  const outArg = get('--out');
  if (!outArg) {
    console.log('node scripts/crawl_29cm.mjs --out <저장소 밖 경로> [--per-group 110] [--limit <상품 방문 상한>] [--interval-ms 2000] [--no-images] [--headed] [--browser-path <chromium>]');
    return 2;
  }
  const perGroup = Number(get('--per-group', 110));
  const limit = Number(get('--limit', Infinity));
  const intervalMs = Math.max(2000, Number(get('--interval-ms', 2000)));
  const browserPath = get('--browser-path', process.env.LUMI_CHROMIUM_PATH || undefined);
  const root = await prepareOutputRoot(outArg);
  await mkdir(join(root, 'products'), { recursive: true });
  const state = { stopped: null, log: [] };
  const started = Date.now(); const startedAt = new Date().toISOString();
  const { chromium } = await import('playwright');
  const browser = await chromium.launch({ headless: !args.includes('--headed'), executablePath: browserPath });
  const records = []; let visits = 0;
  try {
    const page = await (await browser.newContext({ locale: 'ko-KR' })).newPage();
    const discovery = await discover(page, root, intervalMs, state);
    const queue = { top: [], bottom: [] };
    for (const g of ['top', 'bottom']) {
      queue[g] = roundRobin(discovery.lists.filter(l => l.group === g && !l.excluded).map(l => ({
        items: l.ids, meta: { group: g, gender: l.gender, medium_name: l.name, small_name: l.small_name, small_code: l.small },
      })));
    }
    const seen = new Set();
    for (const g of ['top', 'bottom']) {
      let have = 0;
      for (const item of queue[g]) {
        if (state.stopped || visits >= limit || have >= perGroup) break;
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        const path = join(root, 'products', `${item.id}.json`);
        if (await exists(path)) {
          const saved = JSON.parse(await readFile(path, 'utf8'));
          if (args.includes('--no-images') || saved.images.every(i => i.download_status === 'downloaded')) { records.push(saved); have += 1; continue; }
          await downloadImages(root, saved, intervalMs, state, fetch); await writeJson(path, saved); records.push(saved); have += 1; continue;
        }
        await pause(intervalMs); visits += 1;
        const url = `${BASE}/products/${item.id}`;
        let status; let snapshot;
        try {
          status = await gotoChecked(page, url, state);
          if (state.stopped) break;
          await page.waitForSelector('script[type="application/ld+json"]', { state: 'attached', timeout: 10000 }).catch(() => {});
          await pause(1500);
          snapshot = await readSnapshot(page);
          if (snapshot.blocked) { state.stopped = snapshot.blocked; state.log.push({ url, status, event: 'stopped' }); break; }
          const expanded = await clickIfPresent(page, /^상품설명 더보기$/);
          if (expanded) snapshot.text = (await readSnapshot(page)).text;
        } catch (error) { state.log.push({ url, status, error: String(error.message || error).slice(0, 160) }); continue; }
        if (!snapshot.ld) { state.log.push({ url, status, skipped: 'no_product_jsonld' }); continue; }
        const record = buildRecord(item.id, item, { ...snapshot, status }, new Date().toISOString());
        await writeJson(path, record);
        if (!args.includes('--no-images')) { await downloadImages(root, record, intervalMs, state, fetch); await writeJson(path, record); }
        records.push(record); have += 1;
        if (visits % 10 === 0) console.error(`visits=${visits} ${g}=${have} elapsed=${Math.round((Date.now() - started) / 1000)}s`);
      }
    }
  } finally { await browser.close(); }
  const summary = { collector_version: COLLECTOR_VERSION, started_at: startedAt, finished_at: new Date().toISOString(), wall_ms: Date.now() - started,
    visits, interval_ms: intervalMs, stopped: state.stopped, ...summarizeRecords(records), log: state.log };
  await writeJson(join(root, 'run.json'), summary);
  await writeJson(join(root, 'summary.json'), summarizeRecords(records));
  console.log(JSON.stringify({ total: summary.total, by_group: summary.by_group, visits, stopped: state.stopped, wall_s: Math.round(summary.wall_ms / 1000), images: summary.images_downloaded, failures: state.log.length }, null, 1));
  return state.stopped ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().then(code => { process.exitCode = code; }, error => { console.error(error.message); process.exitCode = 1; });
}
