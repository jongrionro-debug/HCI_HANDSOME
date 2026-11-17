#!/usr/bin/env node
/** Public SmartStore DOM collector. No credentials, persistent profiles or model calls. */
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, realpath, rename, rm, writeFile } from 'node:fs/promises';
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';

const PROJECT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const COLLECTOR_VERSION = 'naver-dom-v1';
const FEATURES = ['Type', 'Brand', 'Price', 'Color', 'Fit', 'Fabric', 'Detail'];
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const controls = '[role="button"][aria-haspopup="listbox"][data-shp-inventory="pcs"]';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const unique = items => [...new Set(items)];
const escapeRegex = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const inside = (root, path) => path === root || (!relative(root, path).startsWith(`..${sep}`) && relative(root, path) !== '..' && !isAbsolute(relative(root, path)));
const failure = (code, message = code) => Object.assign(new Error(message), { code });

export function productIdentity(input) {
  let url;
  try { url = new URL(input); } catch { throw failure('invalid_url'); }
  const match = /^\/([a-zA-Z0-9_-]+)\/products\/([0-9]+)\/?$/.exec(url.pathname);
  if (url.protocol !== 'https:' || url.hostname !== 'smartstore.naver.com' || url.port || url.username || url.password || !match) {
    throw failure('unsupported_url', 'https://smartstore.naver.com/<store>/products/<id> 주소가 필요합니다.');
  }
  return { store: match[1], id: match[2], url: `https://smartstore.naver.com/${match[1]}/products/${match[2]}` };
}

async function physicalPath(path) {
  try { return await realpath(path); }
  catch (error) {
    if (error.code !== 'ENOENT') throw error;
    return join(await physicalPath(dirname(path)), basename(path));
  }
}

export async function prepareOutputRoot(path) {
  const target = await physicalPath(resolve(path));
  if (inside(await realpath(PROJECT), target)) throw failure('output_in_repository', '수집 데이터는 저장소 밖 --out 경로에 저장하세요.');
  await mkdir(target, { recursive: true });
  return await realpath(target);
}

/** Read only Product JSON-LD and the identified product attribute list, not reviews or application state. */
export async function readProductDom(page, expectedId) {
  return await page.evaluate(expectedId => {
    const text = value => typeof value === 'string' ? value.trim().slice(0, 4000) : '';
    const products = [];
    function visit(value, depth = 0) {
      if (!value || typeof value !== 'object' || depth > 12) return;
      if (Array.isArray(value)) { value.forEach(item => visit(item, depth + 1)); return; }
      if ([value['@type']].flat().includes('Product')) products.push(value);
      if (value['@graph']) visit(value['@graph'], depth + 1);
    }
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      if (script.textContent.length > 1024 * 1024) continue;
      try { visit(JSON.parse(script.textContent)); } catch { /* Other structured data can be malformed. */ }
    }
    const product = products.find(p => [p.productID, p.mpn].some(id => String(id) === expectedId));
    const groups = new Map();
    for (const li of document.querySelectorAll('li')) {
      if (li.children.length !== 2) continue;
      const name = text(li.children[0].textContent);
      if (!['상품번호', '브랜드', '제조사', '사용대상', '하의핏', '상의핏', '핏', '주요소재', '소재', '제품소재', '디테일', '색상', '패턴', '하의기장', '종류'].includes(name)) continue;
      const rows = groups.get(li.parentElement) || [];
      rows.push({ name, value: text(li.children[1].textContent.replace(/복사$/, '')) });
      groups.set(li.parentElement, rows);
    }
    const attributes = [...groups.values()].find(rows => rows.some(row => row.name === '상품번호' && row.value === expectedId)) || [];
    const identityFound = Boolean(product || attributes.some(row => row.name === '상품번호' && row.value === expectedId));
    const offers = (Array.isArray(product?.offers) ? product.offers : [product?.offers]).filter(Boolean).map(offer => ({
      price: typeof offer.price === 'number' && Number.isFinite(offer.price) ? offer.price :
        typeof offer.price === 'string' && /^\d+(?:\.\d+)?$/.test(offer.price) ? Number(offer.price) : null,
      currency: text(offer.priceCurrency) || null,
      availability: text(offer.availability) || null,
    }));
    const metadata = product ? {
      product_id: expectedId, name: text(product.name), description: text(product.description),
      category: text(product.category), sku: ['string', 'number'].includes(typeof product.sku) ? String(product.sku) : null,
      images: [product.image].flat().map(image => typeof image === 'string' ? image : image?.url).filter(value => typeof value === 'string'), offers,
    } : null;
    const body = document.body?.innerText || '';
    return {
      identity_found: identityFound, product: metadata, attributes,
      title: text(product?.name) || text(document.querySelector('meta[property="og:title"]')?.content),
      access_issue: !identityFound && (/접속이.*제한|접속.*제한되었습니다|에러페이지|시스템오류/.test(body) ? 'access_limited' :
        /captcha/i.test(body) || /자동입력 방지|보안문자/.test(body) ? 'captcha' :
        document.querySelector('input[type="password"]') ? 'login_required' : null),
    };
  }, expectedId);
}

async function readNotice(page, timeoutMs) {
  const button = page.getByRole('button', { name: /^상품정보\s*제공고시\s*보기$/ }).first();
  if (!await button.count()) return { fields: [], status: 'not_available' };
  await button.click();
  const dialog = page.getByRole('dialog').filter({ hasText: '상품정보 제공고시' }).first();
  try {
    await dialog.waitFor({ state: 'visible', timeout: timeoutMs });
    const fields = await dialog.evaluate(root => [...root.querySelectorAll('li')].filter(li => li.children.length === 2 &&
      ['제품소재', '색상', '치수'].includes(li.children[0].textContent.trim())).map(li => ({
      name: li.children[0].textContent.trim(), value: li.children[1].textContent.trim().slice(0, 4000),
    })));
    return { fields, status: fields.length ? 'observed' : 'unsupported_layout' };
  } finally {
    if (await dialog.isVisible()) await dialog.getByRole('button', { name: '닫기', exact: true }).click();
  }
}

/** Enumerate displayed option branches; never select the final group or click purchase controls. */
export async function readOptions(page, { maxOptionStates = 100, intervalMs = 2000, log = () => {} } = {}) {
  const groups = await page.locator(controls).evaluateAll(elements => [...new Set(elements.map(e => e.getAttribute('data-shp-contents-type')).filter(Boolean))]);
  const states = [];
  let truncated = false; let error = null;
  const buttonFor = group => page.locator(controls).filter({ hasText: new RegExp(`^${escapeRegex(group)}(?:\\s*/|$)`) }).first();
  async function open(group) {
    const button = buttonFor(group);
    if (!await button.count() || await button.getAttribute('aria-disabled') === 'true') return null;
    if (await button.getAttribute('aria-expanded') !== 'true') await button.click();
    return { button, options: button.locator('..').getByRole('option') };
  }
  const describe = locator => locator.evaluateAll(elements => elements.map(e => ({
    raw_value: e.getAttribute('data-shp-contents-id') || e.textContent.trim(),
    raw_label: e.textContent.trim().replace(/\s+/g, ' '), disabled: e.getAttribute('aria-disabled') === 'true',
  })));
  async function walk(depth, selected) {
    if (states.length >= maxOptionStates) { truncated = true; return; }
    const group = groups[depth];
    const current = await open(group);
    const values = current ? await describe(current.options) : [];
    states.push({ selected, group, options: values, status: current ? 'observed' : 'disabled' });
    log({ event: 'options', states: states.length, group });
    if (depth === groups.length - 1 || !current) return;
    for (const value of values.filter(value => !value.disabled)) {
      if (states.length >= maxOptionStates) { truncated = true; break; }
      const fresh = await open(group);
      if (!fresh) throw failure('options_changed');
      const list = await describe(fresh.options);
      const index = list.findIndex(item => item.raw_value === value.raw_value && !item.disabled);
      if (index < 0) throw failure('options_changed');
      await fresh.options.nth(index).click();
      await pause(intervalMs);
      await walk(depth + 1, [...selected, { group, value: value.raw_value }]);
    }
  }
  try { if (groups.length) await walk(0, []); }
  catch { error = 'options_incomplete'; }
  finally {
    for (const group of groups) {
      const button = buttonFor(group);
      try { if (await button.count() && await button.getAttribute('aria-expanded') === 'true') await button.click(); }
      catch { error = 'options_incomplete'; }
    }
  }
  return { groups, states, truncated, error, visible_branches_complete: groups.length > 0 && !truncated && !error, full_inventory_coverage: false };
}

export async function readImages(page, { maxImages = 32, intervalMs = 2000, timeoutMs = 10000 } = {}) {
  const open = page.getByRole('button', { name: '대표이미지 이미지 상세보기', exact: true }).first();
  if (!await open.count()) return { images: [], status: 'not_available', truncated: false };
  await open.click();
  const dialog = page.getByRole('dialog').filter({ hasText: '이미지 확대' }).first();
  const images = new Map();
  let count = 0; let error = null;
  try {
    await dialog.waitFor({ state: 'visible', timeout: timeoutMs });
    const buttons = dialog.getByRole('button', { name: /^추가이미지[0-9]+$/ });
    count = await buttons.count();
    for (let index = 0; index < Math.min(count, maxImages); index++) {
      const target = await buttons.nth(index).locator('img').evaluate(e => new URL(e.currentSrc || e.src).pathname);
      await buttons.nth(index).click();
      await page.waitForFunction(path => [...document.querySelectorAll('[role="dialog"] img')].some(e => {
        try { const url = new URL(e.currentSrc || e.src); return url.pathname === path && url.searchParams.get('type') === 'm10000_10000_no_rotate'; }
        catch { return false; }
      }), target, { timeout: timeoutMs });
      const candidates = await dialog.locator('img').evaluateAll(elements => elements.map(e => ({ url: e.currentSrc || e.src })).filter(e => {
        try { return new URL(e.url).searchParams.get('type') === 'm10000_10000_no_rotate'; } catch { return false; }
      }));
      for (const candidate of candidates) if (new URL(candidate.url).pathname === target) images.set(target, candidate);
      await pause(intervalMs);
    }
  } catch { error = 'gallery_incomplete'; }
  finally {
    try { if (await dialog.isVisible()) await dialog.getByRole('button', { name: '닫기', exact: true }).click(); }
    catch { error = 'gallery_incomplete'; }
  }
  return { images: [...images.values()].slice(0, maxImages), status: error ? 'partial' : 'observed', error, truncated: count > maxImages };
}

const usable = value => value && !/상세\s*(?:페이지|정보)?\s*참[고조]|상품\s*상세|별도\s*표기/.test(value);
export function buildRecord(identity, snapshot, options, gallery, notice, warnings = [], httpStatus = null) {
  if (!snapshot.identity_found || !snapshot.title) throw failure('product_not_found');
  const raw = { product: snapshot.product, attributes: snapshot.attributes, option_states: options.states, notice: notice.fields };
  function attribute(names) { return unique(snapshot.attributes.filter(row => names.includes(row.name)).map(row => row.value).filter(usable)); }
  function observation(values, fields, quote, status = 'observed') {
    return { raw_values: values, capture_status: values.length ? status : 'missing', source_fields: values.length ? fields : [],
      quote: values.length ? quote : null, ...(values.length ? {} : { missing_reason: 'not_provided' }) };
  }
  function field(names) {
    const values = attribute(names);
    return observation(values, ['raw_metadata.attributes'], values.join(' / '), values.length > 1 ? 'conflict' : 'observed');
  }
  const colors = unique([...attribute(['색상']), ...notice.fields.filter(row => row.name === '색상').map(row => row.value).filter(usable)]);
  const colorOptions = unique(options.states.filter(state => /색상|컬러|color/i.test(state.group)).flatMap(state => state.options.map(option => option.raw_value)));
  const designOptions = unique(options.states.filter(state => !/사이즈|size/i.test(state.group)).flatMap(state => state.options.map(option => option.raw_value)));
  const color = observation(colors.length ? colors : colorOptions.length ? colorOptions : designOptions,
    colors.length ? ['raw_metadata.attributes', 'raw_metadata.notice'] : ['raw_metadata.option_states'],
    (colors.length ? colors : colorOptions.length ? colorOptions : designOptions).join(' / '), colors.length || colorOptions.length ? 'observed' : 'inferred');
  if (!colors.length && !colorOptions.length && designOptions.length) color.interpretation = '디자인 옵션명 후보. 색상 부분의 분리·정규화가 필요하며 확정 색상이 아님.';
  const prices = unique((snapshot.product?.offers || []).map(offer => offer.price).filter(value => value !== null));
  const currencies = unique((snapshot.product?.offers || []).map(offer => offer.currency).filter(Boolean));
  const bundle = /(\d+)\s*\+\s*(\d+)/.exec(snapshot.title);
  const record = {
    schema_version: 'lumi-crawl-draft-v1', collector_version: COLLECTOR_VERSION,
    product_key: `naver-smartstore:${identity.store}:${identity.id}`,
    source: { mode: httpStatus === null ? 'playwright_existing_page' : 'playwright_navigation', url: identity.url, collected_at: new Date().toISOString(), http_status: httpStatus },
    ids: { channel_product_no: identity.id, origin_product_no: null, catalog_model_id: null, structured_data_sku: snapshot.product?.sku || null },
    title: snapshot.title, description: snapshot.product?.description || null,
    garment: { category_raw: snapshot.product?.category || null }, raw_metadata: raw,
    pi: {
      Type: observation(snapshot.product?.category ? [snapshot.product.category.split('>').at(-1).trim()] : attribute(['종류']), snapshot.product?.category ? ['raw_metadata.product.category'] : ['raw_metadata.attributes'], snapshot.product?.category || attribute(['종류']).join(' / ')),
      Brand: field(['브랜드']),
      Price: observation(prices, ['raw_metadata.product.offers'], JSON.stringify(snapshot.product?.offers || []), prices.length > 1 || currencies.length > 1 ? 'conflict' : 'observed'),
      Color: color, Fit: field(['하의핏', '상의핏', '핏']),
      Fabric: observation(unique([...attribute(['주요소재', '소재', '제품소재']), ...notice.fields.filter(row => row.name === '제품소재').map(row => row.value).filter(usable)]), ['raw_metadata.attributes', 'raw_metadata.notice'], [...attribute(['주요소재', '소재', '제품소재']), ...notice.fields.filter(row => row.name === '제품소재').map(row => row.value).filter(usable)].join(' / ')),
      Detail: field(['디테일']),
    },
    price_context: { currency: currencies.length === 1 ? currencies[0] : null, bundle_quantity: bundle ? Number(bundle[1]) + Number(bundle[2]) : null, quantity_source: bundle ? 'title' : null, basis: '상품에 표시된 가격. 묶음 수량·선택 옵션의 추가금을 보존하며 개당 가격으로 환산하지 않음.' },
    variants: { groups: options.groups, states: options.states, visible_branches_complete: options.visible_branches_complete, truncated: options.truncated, full_inventory_coverage: false },
    images: gallery.images.map((image, index) => ({ image_id: `${identity.id}-${index}`, source_url: image.url, option_ref: null, option_mapping_status: 'unknown', download_status: 'pending' })),
    validation: { extraction_status: warnings.length ? 'partial' : 'collected', material_ratios_verified: false, image_to_option_mapping_verified: false, gallery_status: gallery.status, gallery_truncated: gallery.truncated, warnings },
  };
  return record;
}

function imageUrl(input) {
  const url = new URL(input);
  if (url.protocol !== 'https:' || url.username || url.password || url.port || !url.hostname.endsWith('.pstatic.net')) throw failure('unsupported_image_host');
  return url;
}

export async function fetchImage(input, { fetchImpl = fetch, maxBytes = MAX_IMAGE_BYTES } = {}) {
  let url = imageUrl(input);
  for (let redirect = 0; redirect <= 5; redirect++) {
    const response = await fetchImpl(url.href, { redirect: 'manual', signal: AbortSignal.timeout(20000) });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const next = response.headers.get('location'); await response.body?.cancel();
      if (!next || redirect === 5) throw failure('image_redirect');
      url = imageUrl(new URL(next, url).href); continue;
    }
    if (!response.ok) { await response.body?.cancel(); throw failure(`image_http_${response.status}`); }
    if (!response.headers.get('content-type')?.startsWith('image/')) { await response.body?.cancel(); throw failure('image_mime'); }
    if (Number(response.headers.get('content-length')) > maxBytes) { await response.body?.cancel(); throw failure('image_too_large'); }
    const reader = response.body.getReader(); const chunks = []; let bytes = 0;
    while (true) {
      const part = await reader.read(); if (part.done) break;
      bytes += part.value.length;
      if (bytes > maxBytes) { await reader.cancel(); throw failure('image_too_large'); }
      chunks.push(Buffer.from(part.value));
    }
    const buffer = Buffer.concat(chunks);
    const ext = buffer.subarray(0, 3).equals(Buffer.from([255, 216, 255])) ? 'jpg' :
      buffer.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) ? 'png' :
      buffer.subarray(0, 4).toString() === 'RIFF' && buffer.subarray(8, 12).toString() === 'WEBP' ? 'webp' :
      /^GIF8[79]a$/.test(buffer.subarray(0, 6).toString()) ? 'gif' : null;
    if (!ext) throw failure('image_signature');
    return { buffer, ext, sha256: createHash('sha256').update(buffer).digest('hex') };
  }
}

async function atomicJson(path, data) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  try { await writeFile(temporary, JSON.stringify(data, null, 2) + '\n', { flag: 'wx' }); await rename(temporary, path); }
  finally { await rm(temporary, { force: true }); }
}

async function verifyImage(directory, image) {
  if (!image.local_path || !image.sha256) throw failure('corrupt_output');
  const path = await realpath(resolve(directory, image.local_path));
  if (!inside(directory, path)) throw failure('corrupt_output');
  const bytes = await readFile(path);
  if (bytes.length !== image.bytes || createHash('sha256').update(bytes).digest('hex') !== image.sha256) throw failure('corrupt_output');
}

export async function savedProduct(root, identity) {
  const directory = join(root, `${identity.store}-${identity.id}`);
  let record;
  try { record = JSON.parse(await readFile(join(directory, 'product.json'), 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw failure('output_conflict'); }
  if (await realpath(directory) !== directory || record.collector_version !== COLLECTOR_VERSION || record.source?.url !== identity.url ||
      record.product_key !== `naver-smartstore:${identity.store}:${identity.id}` || !FEATURES.every(key => record.pi?.[key])) throw failure('output_conflict');
  for (const image of record.images) if (image.download_status === 'downloaded') await verifyImage(directory, image);
  return { record, directory };
}

export async function saveProduct(root, identity, record, { download = true, fetchImpl = fetch, intervalMs = 2000 } = {}) {
  const directory = join(root, `${identity.store}-${identity.id}`);
  const existing = await savedProduct(root, identity);
  if (existing && (existing.record.source.collected_at !== record.source.collected_at ||
      JSON.stringify(existing.record.raw_metadata) !== JSON.stringify(record.raw_metadata))) throw failure('output_conflict');
  if (!existing) await mkdir(directory); // Existing incomplete/unknown directories are never overwritten.
  await mkdir(join(directory, 'images'), { recursive: true });
  if (await realpath(join(directory, 'images')) !== join(directory, 'images')) throw failure('output_conflict');
  record.validation.download_status = 'partial';
  await atomicJson(join(directory, 'product.json'), record); // Durable metadata before fetching; interruption can resume.
  let attempted = false;
  for (const [index, image] of record.images.entries()) {
    if (image.download_status === 'downloaded') continue;
    if (!download) { image.download_status = 'not_requested'; continue; }
    try {
      if (attempted) await pause(intervalMs);
      attempted = true;
      const result = await fetchImage(image.source_url, { fetchImpl });
      const path = `images/${result.sha256}.${result.ext}`;
      try { await writeFile(join(directory, path), result.buffer, { flag: 'wx' }); }
      catch (error) { if (error.code !== 'EEXIST') throw error; await verifyImage(directory, { local_path: path, sha256: result.sha256, bytes: result.buffer.length }); }
      Object.assign(image, { local_path: path, sha256: result.sha256, source_revision: `sha256:${result.sha256}`, bytes: result.buffer.length, download_status: 'downloaded' });
      delete image.error;
    } catch (error) {
      Object.assign(image, { download_status: 'failed', error: error.code || 'image_download_failed' });
      if (/^image_http_(401|403|418|429)$/.test(error.code || '')) {
        for (const remaining of record.images.slice(index + 1)) if (remaining.download_status !== 'downloaded') remaining.download_status = 'not_attempted';
        break;
      }
    }
  }
  record.validation.download_status = record.images.some(image => ['failed', 'not_attempted'].includes(image.download_status)) ? 'partial' : download ? 'complete' : 'not_requested';
  await atomicJson(join(directory, 'product.json'), record);
  return { status: record.validation.download_status === 'partial' || record.validation.extraction_status === 'partial' ? 'partial' : 'collected', path: join(directory, 'product.json'), images: record.images.filter(image => image.download_status === 'downloaded').length };
}

export async function collectProductPage(page, { url, outDir, httpStatus = null, intervalMs = 2000, maxOptionStates = 100, maxImages = 32, timeoutMs = 10000, download = true, fetchImpl = fetch, log = () => {} }) {
  const identity = productIdentity(url); const root = await prepareOutputRoot(outDir);
  const saved = await savedProduct(root, identity);
  if (saved && saved.record.validation.download_status !== 'partial' && !(download && saved.record.validation.download_status === 'not_requested')) return { status: saved.record.validation.extraction_status === 'partial' ? 'partial' : 'skipped', path: join(saved.directory, 'product.json') };
  if (saved) return await saveProduct(root, identity, saved.record, { download, fetchImpl, intervalMs });
  if ([401, 403, 418, 429].includes(httpStatus)) throw failure(`access_http_${httpStatus}`);
  if (httpStatus !== null && (httpStatus < 200 || httpStatus >= 300)) throw failure(`http_${httpStatus}`);
  if (new URL(page.url()).hostname === 'nid.naver.com') throw failure('login_required');
  if (productIdentity(page.url()).id !== identity.id || productIdentity(page.url()).store !== identity.store) throw failure('wrong_product_url');
  let snapshot = await readProductDom(page, identity.id);
  const deadline = Date.now() + timeoutMs;
  while (!snapshot.identity_found && !snapshot.access_issue && Date.now() < deadline) {
    await pause(100);
    snapshot = await readProductDom(page, identity.id);
  }
  if (snapshot.access_issue) throw failure(snapshot.access_issue);
  if (!snapshot.identity_found) throw failure('product_not_found');
  page.setDefaultTimeout(timeoutMs);
  const warnings = [];
  while (!snapshot.attributes.length && Date.now() < deadline) {
    await pause(100);
    snapshot = await readProductDom(page, identity.id);
  }
  if (!snapshot.attributes.length) warnings.push('attribute_list_unavailable');
  const expand = page.getByRole('button', { name: '상품정보 펼쳐보기', exact: true }).first();
  if (await expand.count()) {
    await expand.click();
    await page.getByRole('button', { name: '상품정보 접기', exact: true }).first().waitFor({ state: 'visible', timeout: timeoutMs });
  }
  snapshot = await readProductDom(page, identity.id);
  let notice = { fields: [], status: 'not_available' };
  try { notice = await readNotice(page, timeoutMs); } catch { warnings.push('notice_unavailable'); }
  if (notice.status === 'unsupported_layout') warnings.push('notice_unsupported_layout');
  let options = { groups: [], states: [], truncated: false, visible_branches_complete: false, full_inventory_coverage: false };
  try { options = await readOptions(page, { maxOptionStates, intervalMs, log }); } catch { warnings.push('options_incomplete'); }
  if (options.error) warnings.push(options.error);
  let gallery = { images: [], status: 'not_available', truncated: false };
  try { gallery = await readImages(page, { maxImages, intervalMs, timeoutMs }); } catch { warnings.push('gallery_incomplete'); }
  if (gallery.error) warnings.push(gallery.error);
  if (!gallery.images.length) gallery.images = (snapshot.product?.images || []).slice(0, maxImages).map(url => ({ url }));
  if (productIdentity(page.url()).url !== identity.url || !(await readProductDom(page, identity.id)).identity_found) throw failure('product_changed');
  const record = buildRecord(identity, snapshot, options, gallery, notice, warnings, httpStatus);
  return await saveProduct(root, identity, record, { download, fetchImpl, intervalMs });
}

export function parseArgs(args) {
  const options = { urls: [], outDir: null, urlsFile: null, manualStart: false, headless: false, download: true, maxProducts: 20, intervalMs: 2000, maxOptionStates: 100, maxImages: 32, timeoutMs: 10000 };
  const names = { '--out': 'outDir', '--urls-file': 'urlsFile', '--limit': 'maxProducts', '--interval-ms': 'intervalMs', '--max-option-states': 'maxOptionStates', '--max-images': 'maxImages', '--timeout-ms': 'timeoutMs' };
  for (let index = 0; index < args.length; index++) {
    const arg = args[index];
    if (arg === '--help') { options.help = true; continue; }
    if (arg === '--manual-start') { options.manualStart = true; continue; }
    if (arg === '--headless') { options.headless = true; continue; }
    if (arg === '--no-images') { options.download = false; continue; }
    if (arg === '--url' || names[arg]) {
      const value = args[++index]; if (!value || value.startsWith('--')) throw failure('missing_argument', arg);
      if (arg === '--url') options.urls.push(productIdentity(value).url);
      else if (['outDir', 'urlsFile'].includes(names[arg])) options[names[arg]] = value;
      else { if (!/^\d+$/.test(value)) throw failure('invalid_argument', arg); options[names[arg]] = Number(value); }
      continue;
    }
    throw failure('unknown_argument', arg);
  }
  if (options.help) return options;
  if (!options.outDir || (!options.urls.length && !options.urlsFile && !options.manualStart)) throw failure('missing_arguments', '--out과 --url/--urls-file 또는 --manual-start가 필요합니다.');
  if (options.manualStart && options.headless) throw failure('incompatible_arguments');
  if (options.intervalMs < 2000 || options.intervalMs > 60000 || options.maxProducts < 1 || options.maxProducts > 10000 ||
      options.maxOptionStates < 1 || options.maxOptionStates > 1000 || options.maxImages < 1 || options.maxImages > 32 || options.timeoutMs < 1000 || options.timeoutMs > 120000) throw failure('invalid_argument_range');
  return options;
}

export async function main(args = process.argv.slice(2), { browserType } = {}) {
  const options = parseArgs(args);
  if (options.help) {
    console.log('node scripts/crawl_naver.mjs --out <저장소 밖 경로> [--url <SmartStore 상품 URL>] [--urls-file <줄마다 URL>] [--manual-start] [--headless] [--no-images] [--limit 20] [--interval-ms 2000] [--max-option-states 100] [--max-images 32] [--timeout-ms 10000]');
    return 0;
  }
  const root = await prepareOutputRoot(options.outDir);
  if (options.urlsFile) for (const line of (await readFile(options.urlsFile, 'utf8')).split(/\r?\n/).map(line => line.trim()).filter(line => line && !line.startsWith('#'))) options.urls.push(productIdentity(line).url);
  options.urls = unique(options.urls);
  const manifestPath = join(root, 'run.json');
  try { const old = JSON.parse(await readFile(manifestPath, 'utf8')); if (old.collector_version !== COLLECTOR_VERSION) throw failure('output_conflict'); }
  catch (error) { if (error.code !== 'ENOENT') throw failure('output_conflict'); }
  if (options.manualStart && !process.stdin.isTTY) throw failure('terminal_required', '--manual-start는 입력 가능한 터미널에서 실행하세요.');
  const chromium = browserType || (await import('playwright')).chromium;
  const browser = await chromium.launch({ headless: options.headless });
  const results = []; let exitCode = 0;
  const runId = randomUUID();
  const manifest = () => ({ run_id: runId, collector_version: COLLECTOR_VERSION, updated_at: new Date().toISOString(),
    settings: { manual_start: options.manualStart, limit: options.maxProducts, interval_ms: options.intervalMs, max_option_states: options.maxOptionStates, max_images: options.maxImages, download_images: options.download }, results });
  try {
    const context = await browser.newContext(); let page = await context.newPage();
    if (options.manualStart) {
      await page.goto('https://www.naver.com/', { waitUntil: 'domcontentloaded', timeout: options.timeoutMs });
      const input = createInterface({ input: process.stdin, output: process.stdout });
      try { await input.question('이 Chromium에서 수집할 상품을 연 뒤 여기서 Enter를 누르세요. 로그인은 필요할 때 창에서 직접 진행하세요.\n'); }
      finally { input.close(); }
      if (!options.urls.length) options.urls = unique(context.pages().flatMap(tab => { try { return [productIdentity(tab.url()).url]; } catch { return []; } }));
    }
    if (!options.urls.length) throw failure('no_product_tabs');
    for (const [index, url] of options.urls.slice(0, options.maxProducts).entries()) {
      const identity = productIdentity(url);
      try {
        const saved = await savedProduct(root, identity);
        const existingTab = context.pages().find(tab => { try { return productIdentity(tab.url()).url === url; } catch { return false; } });
        let httpStatus = null;
        if (existingTab) page = existingTab;
        else if (!saved) { const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: options.timeoutMs }); httpStatus = response?.status() ?? null; }
        const result = await collectProductPage(page, { ...options, url, outDir: root, httpStatus, log: event => console.log(JSON.stringify({ product: identity.id, ...event })) });
        results.push({ url, ...result });
        if (result.status === 'partial') exitCode = 1;
      } catch (error) {
        const code = error.code || 'extraction_failed';
        results.push({ url, status: 'failed', error: code }); exitCode = 1;
        if (/^access_http_|access_limited|captcha|login_required/.test(code)) {
          for (const pending of options.urls.slice(index + 1, options.maxProducts)) results.push({ url: pending, status: 'not_attempted', reason: 'access_stopped' });
          break;
        }
      }
      await atomicJson(manifestPath, manifest());
      await pause(options.intervalMs);
    }
    await atomicJson(manifestPath, manifest());
    console.log(JSON.stringify({ output: root, results }, null, 2));
  } finally { await browser.close(); }
  return exitCode;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().then(code => { process.exitCode = code; }).catch(error => { console.error(JSON.stringify({ status: 'failed', error: error.code || 'execution_failed', message: error.code ? error.message : 'Playwright 설치·브라우저 실행 환경을 확인하세요.' })); process.exitCode = 1; });
}
