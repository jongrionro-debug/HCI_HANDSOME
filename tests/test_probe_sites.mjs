import test from 'node:test';
import assert from 'node:assert/strict';
import { classify, groupOf, summarize } from '../scripts/probe_sites.mjs';

test('groupOf separates tops and bottoms', () => {
  assert.equal(groupOf('남성의류 상의 긴소매 셔츠'), 'top');
  assert.equal(groupOf('여성의류 하의 데님 팬츠'), 'bottom');
  assert.equal(groupOf('뷰티 립 글레이즈'), null);
});

test('classify records the source of each feature', () => {
  const pi = classify({
    ld: { category: null, brand: '라코스테', price: 167300, currency: 'KRW' },
    breadcrumb: ['남성의류', '상의'], text: '상품정보 제품 소재 면 100% 색상 BLACK\nFIT: 오버핏\n리뷰 (3)\n디테일 좋아요', metaCategory: '',
  });
  assert.equal(pi.Brand.source, 'structured');
  assert.equal(pi.Price.source, 'structured');
  assert.equal(pi.Type.source, 'structured');
  assert.equal(pi.Fabric.source, 'text');
  assert.equal(pi.Fit.source, 'text');
  assert.equal(pi.Color.source, 'text');
  assert.equal(pi.Detail.source, 'none');
  const ref = classify({ ld: null, breadcrumb: ['상의'], text: '제품 소재 상품상세 참조 색상 상품상세 참조' });
  assert.equal(ref.Fabric.source, 'referred');
  assert.equal(ref.Color.source, 'referred');
});

test('summarize computes fill rates', () => {
  const rec = fit => ({ pi: Object.fromEntries(['Type','Brand','Price','Color','Fit','Fabric','Detail'].map(k => [k, { source: k === 'Fit' ? fit : 'text' }])) });
  const s = summarize([rec('text'), rec('none')]);
  assert.equal(s.Fit.fill_rate, 0.5);
  assert.equal(s.Brand.fill_rate, 1);
});
