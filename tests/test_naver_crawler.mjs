/** Offline synthetic browser regression checks. Never contacts Naver. */
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { mkdtemp, mkdir, readFile, readdir, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright';
import { collectProductPage, fetchImage, main, parseArgs, prepareOutputRoot, productIdentity, readProductDom } from '../scripts/crawl_naver.mjs';

const url = 'https://smartstore.naver.com/synthetic/products/12345';
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ1kAAAAASUVORK5CYII=', 'base64');
let browser; let root;
before(async () => { root = await mkdtemp(join(tmpdir(), 'lumi-crawler-test-')); browser = await chromium.launch({ headless: true }); });
after(async () => { await browser?.close(); if (root) await rm(root, { recursive: true, force: true }); });

const html = `<!doctype html><meta charset="utf-8"><meta property="og:title" content="합성 상품">
<script type="application/ld+json">{"@type":"Product","productID":"12345","name":"합성 1+1 바지 2장","category":"패션의류>남성의류>바지","offers":{"price":49600,"priceCurrency":"KRW"},"image":"https://shop-phinf.pstatic.net/synthetic/0.png?type=o1000"}</script>
<button id="expand">상품정보 펼쳐보기</button><ul id="attributes">
<li><div>상품번호</div><div>12345</div></li><li><div>브랜드</div><div>새로운브랜드</div></li>
<li class="extra" hidden><div>하의핏</div><div>세미와이드</div></li>
<li class="extra" hidden><div>주요소재</div><div>면 97%, 폴리우레탄 3%</div></li>
<li class="extra" hidden><div>디테일</div><div>노턱, 히든밴딩</div></li></ul>
<aside><h2>추천·리뷰</h2><ul><li><div>브랜드</div><div>추천상품브랜드</div></li><li><div>색상</div><div>리뷰색상</div></li></ul></aside>
<button id="notice">상품정보제공고시 보기</button><div id="option-root"></div>
<button aria-label="대표이미지 이미지 상세보기" id="zoom">사진 보기</button>
<button id="buy">바로구매</button><button id="cart">장바구니</button><div id="modal-root"></div>
<script>
 window.purchaseActions=0;window.finalSelections=0;
 document.querySelector('#buy').onclick=document.querySelector('#cart').onclick=()=>window.purchaseActions++;
 document.querySelector('#expand').onclick=e=>{document.querySelectorAll('.extra').forEach(x=>x.hidden=false);e.target.textContent='상품정보 접기'};
 const groups=['사이즈','정장바지1','정장바지2'];let selected=[];
 function values(index){if(index===0)return ['30','38'];if(index===1)return selected[0]==='30'?['자개민트','체크블랙']:['투톤레몬'];return ['첫번째와 같은 색','다른 디자인 (+4,000원)'];}
 function render(){
  const root=document.querySelector('#option-root');root.innerHTML='';
  groups.forEach((group,index)=>{
   const wrapper=document.createElement('div');const button=document.createElement('a');
   button.href='#';button.role='button';button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');
   button.setAttribute('aria-disabled',index>0&&!selected[index-1]?'true':'false');
   button.dataset.shpInventory='pcs';button.dataset.shpContentsType=group;
   button.textContent=group+(selected[index]?' / '+selected[index]:'');
   const list=document.createElement('ul');list.role='listbox';list.hidden=true;
   if(index===0||selected[index-1])values(index).forEach(value=>{
    const li=document.createElement('li');const option=document.createElement('a');option.href='#';option.role='option';
    option.dataset.shpContentsType=group;option.dataset.shpContentsId=value;option.textContent=value;
    option.onclick=e=>{e.preventDefault();if(index===groups.length-1)window.finalSelections++;selected=selected.slice(0,index);selected[index]=value;render()};li.append(option);list.append(li);
   });
   button.onclick=e=>{e.preventDefault();if(button.getAttribute('aria-disabled')==='true')return;list.hidden=!list.hidden;button.setAttribute('aria-expanded',String(!list.hidden))};
   wrapper.append(button,list);root.append(wrapper);
  });
 }render();
 const modal=document.querySelector('#modal-root');
 document.querySelector('#notice').onclick=()=>{modal.innerHTML='<div role="dialog"><h2>商品정보 제공고시</h2><ul><li><div>제품소재</div><div>상세페이지참고</div></li><li><div>색상</div><div>상세페이지참고</div></li></ul><button aria-label="닫기">닫기</button></div>'.replace('商品','상품');modal.querySelector('button').onclick=()=>modal.innerHTML=''};
 function image(index,type){return 'https://shop-phinf.pstatic.net/synthetic/'+index+'.png?type='+type}
 document.querySelector('#zoom').onclick=()=>{
  modal.innerHTML='<div role="dialog"><h2>이미지 확대</h2><div id="full-images"></div><div id="thumbs"></div><button aria-label="닫기">닫기</button></div>';
  function display(index){document.querySelector('#full-images').innerHTML=[(index+2)%3,index,(index+1)%3].map(i=>'<img src="'+image(i,'m10000_10000_no_rotate')+'">').join('')}
  for(let index=0;index<3;index++){const button=document.createElement('button');button.setAttribute('aria-label','추가이미지'+index);button.innerHTML='<img src="'+image(index,'f90')+'">';button.onclick=()=>display(index);document.querySelector('#thumbs').append(button)}
  display(0);modal.querySelector('button[aria-label="닫기"]').onclick=()=>modal.innerHTML='';
 };
</script>`;

async function fixture(content = html) {
  const page = await browser.newPage();
  await page.route('**/*', route => {
    const request = route.request().url();
    if (request === url) return route.fulfill({ contentType: 'text/html; charset=utf-8', body: content });
    if (request.startsWith('https://shop-phinf.pstatic.net/synthetic/')) return route.fulfill({ contentType: 'image/png', body: png });
    throw new Error(`Unexpected network request: ${request}`);
  });
  await page.goto(url); return page;
}
const fakeImage = async () => new Response(png, { headers: { 'content-type': 'image/png' } });
const settings = outDir => ({ url, outDir, intervalMs: 0, timeoutMs: 1000, fetchImpl: fakeImage });

test('canonical product identity strips tracking and rejects unrelated or credential URLs', () => {
  assert.deepEqual(productIdentity(url + '?tracking=unused#zoom'), { store: 'synthetic', id: '12345', url });
  for (const input of ['http://smartstore.naver.com/a/products/1', 'https://evil.example/a/products/1', 'https://smartstore.naver.com/a/products/../secret', 'https://user:password@smartstore.naver.com/a/products/1']) assert.throws(() => productIdentity(input));
  assert.throws(() => parseArgs(['--url', url, '--out', root, '--manual-start', '--headless']));
  assert.throws(() => parseArgs(['--url', url, '--out', root, '--interval-ms', '0']));
  assert.equal(parseArgs(['--url', url, '--out', root]).maxOptionStates, 100);
});

test('output resolves symlinks and prevents writes into the repository', async () => {
  await assert.rejects(prepareOutputRoot(resolve('output/crawl-test')), { code: 'output_in_repository' });
  const link = join(root, 'repo-link'); await symlink(resolve('.'), link);
  await assert.rejects(prepareOutputRoot(join(link, 'new-data')), { code: 'output_in_repository' });
});

test('synthetic product preserves unfamiliar values, contextual options and bundle price without purchase actions', async () => {
  const page = await fixture(); const outDir = join(root, 'complete');
  try {
    const result = await collectProductPage(page, settings(outDir));
    assert.equal(result.status, 'collected');
    const record = JSON.parse(await readFile(result.path, 'utf8'));
    assert.deepEqual(Object.keys(record.pi).sort(), ['Type', 'Brand', 'Price', 'Color', 'Fit', 'Fabric', 'Detail'].sort());
    assert.deepEqual(record.pi.Brand.raw_values, ['새로운브랜드']);
    assert.deepEqual(record.pi.Fit.raw_values, ['세미와이드']);
    assert.deepEqual(record.pi.Fabric.raw_values, ['면 97%, 폴리우레탄 3%']);
    assert.deepEqual(record.pi.Price.raw_values, [49600]);
    assert.equal(record.price_context.bundle_quantity, 2);
    assert.equal(record.pi.Color.capture_status, 'inferred');
    assert.ok(record.pi.Color.raw_values.includes('투톤레몬'));
    assert.ok(!record.pi.Color.raw_values.includes('리뷰색상'));
    assert.equal(record.variants.visible_branches_complete, true);
    assert.equal(record.variants.states.length, 6);
    assert.ok(record.variants.states.some(state => state.selected.some(choice => choice.value === '38') && state.options.some(option => option.raw_label.includes('4,000원'))));
    assert.equal(record.images.length, 3);
    assert.equal(record.images[0].source_url, 'https://shop-phinf.pstatic.net/synthetic/0.png?type=m10000_10000_no_rotate');
    assert.equal((await readdir(join(outDir, 'synthetic-12345', 'images'))).length, 1, 'identical image bytes use one content-addressed file');
    assert.equal(await page.evaluate(() => window.purchaseActions + window.finalSelections), 0);
    const noPage = { url() { throw new Error('resume must not access browser'); } };
    assert.equal((await collectProductPage(noPage, settings(outDir))).status, 'skipped');
  } finally { await page.close(); }
});

test('traversal cap is recorded instead of claiming complete options; image cap excludes preloaded neighbors', async () => {
  const page = await fixture();
  try {
    const result = await collectProductPage(page, { ...settings(join(root, 'limited')), maxOptionStates: 2, maxImages: 1 });
    const record = JSON.parse(await readFile(result.path, 'utf8'));
    assert.equal(record.variants.truncated, true);
    assert.equal(record.variants.visible_branches_complete, false);
    assert.equal(record.images.length, 1);
    assert.match(record.images[0].source_url, /\/0\.png\?/);
  } finally { await page.close(); }
});

test('failed image download can resume without re-reading a browser; corrupted files are rejected', async () => {
  const page = await fixture(); const outDir = join(root, 'retry');
  try {
    const first = await collectProductPage(page, { ...settings(outDir), maxImages: 1, fetchImpl: async () => new Response('', { status: 503 }) });
    assert.equal(first.status, 'partial');
    const noPage = { url() { throw new Error('image retry must not access browser'); } };
    const second = await collectProductPage(noPage, settings(outDir));
    assert.equal(second.status, 'collected');
    const record = JSON.parse(await readFile(second.path, 'utf8'));
    await writeFile(join(outDir, 'synthetic-12345', record.images[0].local_path), 'corrupt');
    await assert.rejects(collectProductPage(noPage, settings(outDir)), { code: 'corrupt_output' });
  } finally { await page.close(); }
});

test('access limit and wrong product identity never create successful product files', async () => {
  const page = await fixture();
  try {
    await assert.rejects(collectProductPage(page, { ...settings(join(root, 'blocked')), httpStatus: 429 }), { code: 'access_http_429' });
    await page.setContent('<h1>쇼핑 서비스 접속이 일시적으로 제한되었습니다.</h1>');
    await assert.rejects(collectProductPage(page, settings(join(root, 'blocked-dom'))), { code: 'access_limited' });
    assert.deepEqual(await readdir(join(root, 'blocked-dom')), []);
    await page.setContent(html.replaceAll('12345', '99999'));
    assert.equal((await readProductDom(page, '12345')).identity_found, false);
  } finally { await page.close(); }
});

test('missing PI values and an extraction failure remain distinguishable', async () => {
  const page = await fixture(html.replace('주요소재', '기타소재').replace('디테일', '기타디테일').replace('id="notice"', 'id="notice" disabled'));
  try {
    const result = await collectProductPage(page, settings(join(root, 'partial-extraction')));
    const record = JSON.parse(await readFile(result.path, 'utf8'));
    assert.equal(result.status, 'partial');
    assert.equal(record.validation.extraction_status, 'partial');
    assert.ok(record.validation.warnings.includes('notice_unavailable'));
    assert.equal(record.pi.Fabric.capture_status, 'missing');
    assert.equal(record.pi.Detail.capture_status, 'missing');
    assert.deepEqual(record.pi.Fabric.raw_values, []);
    assert.equal(record.pi.Fabric.missing_reason, 'not_provided');
    assert.ok(record.variants.states.length > 0);
  } finally { await page.close(); }
});

test('URL batch stops at 429, records unattempted products, and closes its browser', async () => {
  let closed = false; let requests = 0;
  const browserType = { async launch() {
    const isolatedBrowser = await chromium.launch({ headless: true });
    const originalClose = isolatedBrowser.close.bind(isolatedBrowser);
    isolatedBrowser.close = async () => { closed = true; await originalClose(); };
    const originalContext = isolatedBrowser.newContext.bind(isolatedBrowser);
    isolatedBrowser.newContext = async () => {
      const context = await originalContext();
      await context.route('**/*', route => { requests++; return route.fulfill({ status: 429, contentType: 'text/html', body: '접속 제한' }); });
      return context;
    };
    return isolatedBrowser;
  } };
  const outDir = join(root, 'batch');
  assert.equal(await main(['--url', url, '--url', url.replace('12345', '67890'), '--out', outDir], { browserType }), 1);
  const manifest = JSON.parse(await readFile(join(outDir, 'run.json'), 'utf8'));
  assert.equal(manifest.results[0].error, 'access_http_429');
  assert.equal(manifest.results[1].status, 'not_attempted');
  assert.equal(requests, 1);
  assert.equal(closed, true);
  assert.deepEqual(await readdir(outDir), ['run.json']);
});

test('existing unrelated output is preserved', async () => {
  const page = await fixture(); const outDir = join(root, 'conflict');
  await mkdir(join(outDir, 'synthetic-12345'), { recursive: true });
  const file = join(outDir, 'synthetic-12345', 'product.json'); await writeFile(file, '{"user":"original"}');
  try {
    await assert.rejects(collectProductPage(page, settings(outDir)), { code: 'output_conflict' });
    assert.equal(await readFile(file, 'utf8'), '{"user":"original"}');
  } finally { await page.close(); }
});

test('image host access limit stops remaining downloads and is resumable', async () => {
  const page = await fixture(); let calls = 0;
  const outDir = join(root, 'image-limit');
  try {
    const first = await collectProductPage(page, { ...settings(outDir), fetchImpl: async () => { calls++; return new Response('', { status: 429 }); } });
    assert.equal(calls, 1);
    assert.equal(first.status, 'partial');
    const record = JSON.parse(await readFile(first.path, 'utf8'));
    assert.deepEqual(record.images.map(image => image.download_status), ['failed', 'not_attempted', 'not_attempted']);
    const next = await collectProductPage(null, settings(outDir));
    assert.equal(next.status, 'collected');
    assert.equal(next.images, 3);
  } finally { await page.close(); }
});

test('image downloads validate redirect hosts, size, MIME and file bytes', async () => {
  let calls = 0;
  const fetchImpl = async () => { calls++; return new Response('', { status: 302, headers: { location: 'http://127.0.0.1/private' } }); };
  await assert.rejects(fetchImage('https://shop-phinf.pstatic.net/image.png', { fetchImpl }), { code: 'unsupported_image_host' });
  assert.equal(calls, 1);
  await assert.rejects(fetchImage('https://evil.example/image.png', { fetchImpl }), { code: 'unsupported_image_host' });
  assert.equal(calls, 1);
  await assert.rejects(fetchImage('https://shop-phinf.pstatic.net/image.png', { fetchImpl: async () => new Response(png, { headers: { 'content-type': 'image/png' } }), maxBytes: 2 }), { code: 'image_too_large' });
  await assert.rejects(fetchImage('https://shop-phinf.pstatic.net/image.png', { fetchImpl: async () => new Response('<html>blocked</html>', { headers: { 'content-type': 'image/jpeg' } }) }), { code: 'image_signature' });
});
