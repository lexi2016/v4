import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {mergePoolPages,fetchAllPreselection,loadResearchBundle,maturityGroups} from './shared/data.js';
const root=process.env.V45_REPLAY_DIR;
const read=name=>JSON.parse(readFileSync(join(root,name+'.json'),'utf8'));
test('complete SHA-verified two-day membership projections retain all original sources',{skip:!root},async()=>{
  for(const [date,a,relations] of [['20261112',421,554],['20261113',272,386]]){
    const pages=read(date),value=mergePoolPages(pages);
    assert.deepEqual(value.counts,{A:a,HK:100});assert.equal(value.membershipCount,relations);assert.equal(value.complete,true);
    assert.equal(value.rows.some(r=>r.identity==='A:000159'),false,'000159 is an independent research sample, not a pool member');
    assert.ok(value.pools.every(p=>p.sourceDate===null||p.sourceDate===(date==='20261112'?'20261111':'20261112')));
    const actual=await fetchAllPreselection(date,async url=>{
      const q=new URL(url,'http://test').searchParams;
      assert.equal(q.get('limit'),'300');return new Response(JSON.stringify(pages.find(p=>p.pagination.offset===Number(q.get('offset')))));
    });
    assert.equal(actual.complete,true);assert.equal(actual.membershipCount,relations);
    const missing=structuredClone(pages);
    const overlap=missing[0].pools.find(p=>p.pool_id==='a_d1_fupan_watchlist_pool');overlap.rows.pop();
    assert.equal(mergePoolPages(missing).complete,false);
  }
  assert.equal(mergePoolPages(read('20261112')).pools.find(p=>p.poolId==='a_d1_stage7_fenshi_review_pool').status,'CANNOT_CONFIRM');
});
test('000159 exact real daily product preserves source-asof pullback maturity and missing company materials',{skip:!root},async()=>{
  const names={'daily-product':'individual_product_000159_D11','original-chart':'original_chart_descriptor_000159_D11','company-materials':'company_materials_000159_D11'};
  const bundle=await loadResearchBundle({market:'A',symbol:'000159',date:'20261111'},async url=>{
    const u=new URL(url,'http://test');assert.equal(u.searchParams.get('symbol'),'000159.SZ');
    if(!u.pathname.endsWith('daily-product'))assert.equal(u.searchParams.get('generation'),'270ba879ab1086df0c89a8e130ea6352b332cfb244ab9c125e10a29a15481e45');
    return new Response(JSON.stringify(read(names[u.pathname.split('/').at(-1)])));
  });
  assert.equal(bundle.product.status,'READY');assert.equal(bundle.chart.status,'READY');assert.equal(bundle.company.status,'NOT_MATERIALIZED');
  assert.ok(bundle.chart.assets.html.url.includes('input_sha256='));
  const pullback=maturityGroups(bundle.product).find(g=>g.groupId==='nav_pullback');
  assert.equal(pullback.d2.total,2);assert.equal(pullback.d2.valid,1);assert.equal(pullback.d2.not_matured,1);
  assert.equal(pullback.d2.latest.event_date,'2026-11-11');assert.equal(pullback.d2.latest.status,'not_matured');
  assert.equal(pullback.d5.total,2);assert.equal(pullback.d5.valid,0);assert.equal(pullback.d5.not_matured,2);
});
