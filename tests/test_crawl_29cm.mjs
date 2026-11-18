import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildRecord, extractSections, fetchImage, imageExt, listingUrl, mainImages, parseInfoRows, parseProductIds,
  parseSmallCategories, priceOf, roundRobin,
} from '../scripts/crawl_29cm.mjs';

const PAGE = `29CM\n여성의류\n바지\n상품설명\nCore Point : 배색 하프팬츠\n﻿\n겉감 (Fabric) : 폴리에스터 45%\n- 투턱 디테일 적용\n상품설명 닫기
안전한 거래를 위해 확인해주세요\n상품정보\n제품 소재\t폴리에스터 45%, 면 55%\n색상\t상세 페이지 참고\n치수\tS/ M/ L
A/S 책임자와 전화번호\t29CM 고객행복센터 1644-0561\n판매자정보\n상호명\t주식회사 예시\n대표자\t홍길동\n리뷰(0)`;

test('listing URL and small-category parsing keep only the requested medium code', () => {
  const url = new URL(listingUrl({ large: '268100100', medium: '268106100', small: '268106107', page: 2 }));
  assert.equal(url.searchParams.get('categorySmallCode'), '268106107');
  assert.equal(url.searchParams.get('page'), '2');
  const smalls = parseSmallCategories([
    { href: 'https://www.29cm.co.kr/store/category/list?categoryLargeCode=268100100&categoryMediumCode=268105100&categorySmallCode=268105101', text: ' 크루넥 ' },
    { href: 'https://www.29cm.co.kr/store/category/list?categoryLargeCode=268100100&categoryMediumCode=268105100&categorySmallCode=268105109', text: '카디건' },
    { href: 'https://www.29cm.co.kr/store/category/list?categoryLargeCode=268100100&categoryMediumCode=268106100&categorySmallCode=268106101', text: '쇼트' },
    { href: 'https://evil.example/store/category/list?categoryMediumCode=268105100&categorySmallCode=1', text: 'x' },
  ], '268105100');
  assert.deepEqual(smalls, [
    { code: '268105101', name: '크루넥', excluded: false },
    { code: '268105109', name: '카디건', excluded: true },
  ]);
});

test('product IDs come only from 29CM product links, deduplicated in order', () => {
  assert.deepEqual(parseProductIds([
    'https://product.29cm.co.kr/catalog/4229975?categoryLargeCode=1', 'https://product.29cm.co.kr/catalog/4229975',
    'https://www.29cm.co.kr/products/2545554', 'https://example.com/products/1', 'not a url',
  ]), ['4229975', '2545554']);
});

test('roundRobin interleaves subcategories and drops duplicates', () => {
  const out = roundRobin([{ items: ['1', '2', '3'], meta: { small: 'a' } }, { items: ['2', '4'], meta: { small: 'b' } }]);
  assert.deepEqual(out.map(o => [o.id, o.small]), [['1', 'a'], ['2', 'b'], ['4', 'b'], ['3', 'a']]);
});

test('extractSections keeps description and notice table, drops seller identity and A/S phone', () => {
  const { description, productInfo } = extractSections(PAGE);
  assert.match(description, /투턱 디테일/);
  assert.doesNotMatch(description, /닫기|﻿/);
  assert.match(productInfo, /제품 소재\t폴리에스터 45%, 면 55%/);
  assert.doesNotMatch(productInfo, /대표자|홍길동|1644-0561/);
  assert.deepEqual(parseInfoRows(productInfo).map(r => r.name), ['제품 소재', '색상', '치수']);
});

test('buildRecord marks referred notice values and keeps structured price/brand', () => {
  const ld = { name: 'Half Pants', brand: { name: '홀리선' }, category: '쇼트',
    offers: { price: 92000, priceCurrency: 'KRW', priceSpecification: { price: 115000 } },
    image: [{ contentUrl: 'https://img.29cm.co.kr/item/a.jpg?width=700' }, 'https://evil.example/b.jpg', { contentUrl: 'https://img.29cm.co.kr/item/c.jpg' }] };
  const r = buildRecord('2545554', { group: 'bottom', gender: 'men', medium_name: '남성의류 > 하의', small_name: '쇼트', small_code: '1' },
    { ld, breadcrumb: ['남성의류', '하의', '쇼트'], text: PAGE, status: 200 }, '2026-11-17T00:00:00.000Z');
  assert.equal(r.pi.Price.source, 'structured');
  assert.equal(r.pi.Color.source, 'referred');
  assert.equal(r.pi.Fabric.source, 'text');
  assert.equal(r.subcategory, '남성의류 > 하의 > 쇼트');
  assert.deepEqual(r.price, { amount: 92000, currency: 'KRW', list_amount: 115000, availability: null });
  assert.deepEqual(r.images.map(i => i.source_url), ['https://img.29cm.co.kr/item/a.jpg', 'https://img.29cm.co.kr/item/c.jpg']);
});

test('priceOf and mainImages tolerate missing data', () => {
  assert.deepEqual(priceOf(null), { amount: null, currency: null, list_amount: null, availability: null });
  assert.deepEqual(mainImages({ image: 'https://img.29cm.co.kr/x.png' }), ['https://img.29cm.co.kr/x.png']);
  assert.deepEqual(mainImages({}), []);
});

test('image signature and host checks', async () => {
  assert.equal(imageExt(Buffer.from([0xff, 0xd8, 0xff, 0xe0])), 'jpg');
  assert.equal(imageExt(Buffer.from('RIFF0000WEBPVP8 ', 'latin1')), 'webp');
  assert.equal(imageExt(Buffer.from('<html>')), null);
  await assert.rejects(fetchImage('https://evil.example/a.jpg'), { code: 'unsupported_image_host' });
  const fake = (status, type, body) => async () => new Response(body, { status, headers: { 'content-type': type } });
  await assert.rejects(fetchImage('https://img.29cm.co.kr/a.jpg', { fetchImpl: fake(429, 'text/html', 'no') }), { code: 'image_http_429' });
  await assert.rejects(fetchImage('https://img.29cm.co.kr/a.jpg', { fetchImpl: fake(200, 'image/jpeg', 'notanimage') }), { code: 'image_signature' });
  const ok = await fetchImage('https://img.29cm.co.kr/a.jpg', { fetchImpl: fake(200, 'image/jpeg', Buffer.from([0xff, 0xd8, 0xff, 0x00])) });
  assert.equal(ok.ext, 'jpg');
  assert.equal(ok.sha256.length, 64);
});
