const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { Script, createContext } = require('node:vm');

const script = readFileSync(process.argv[2], 'utf-8');
const dateLookup = script.slice(script.indexOf('function zt(b)'), script.indexOf('function je(b)'));
const stageBatch = script.slice(script.indexOf('async function St(b,H,ne)'), script.indexOf('async function It()'));
assert(dateLookup.startsWith('function zt(b)') && stageBatch.startsWith('async function St(b,H,ne)'));

const selectedId = 'STAGE_0930_0935';
const siblingId = 'STAGE_0935_0940';
const secondSiblingId = 'STAGE_0940_0945';
const sameDay = '20261127';
const selected = { trade_date: sameDay, stage: { stage_id: selectedId }, unified_rows: [1] };
const card = (stage, date = sameDay) => ({ date, loading: false, payload: {
  summary: stage, stage: { stage_id: stage }, trade_date: date,
} });

function timeline(fetched) {
  const previousSibling = card(siblingId);
  const previousSecondSibling = card(secondSiblingId);
  const context = createContext({
    AbortController,
    U: { value: { [selectedId]: { date: sameDay, loading: false, payload: selected },
      [siblingId]: previousSibling, [secondSiblingId]: previousSecondSibling } },
    f: { value: sameDay },
    n: [selectedId, siblingId, secondSiblingId].map(id => ({ id })),
    L: null, re: 0, Sf: fetched,
  });
  new Script(dateLookup + stageBatch).runInContext(context);
  return { context, previousSibling };
}

async function main() {
  const transportError = timeline(async () => { throw new Error('HTTP 503'); });
  await transportError.context.St(sameDay, selectedId, selected);
  assert.equal(transportError.context.U.value[siblingId], transportError.previousSibling);
  assert.equal(transportError.context.U.value[selectedId].payload, selected);

  const fresh = { summary: 'updated second sibling' };
  const omittedEntry = timeline(async () => ({ [selectedId]: { summary: 'summary only' }, [secondSiblingId]: fresh }));
  await omittedEntry.context.St(sameDay, selectedId, selected);
  assert.equal(omittedEntry.context.U.value[siblingId], omittedEntry.previousSibling);
  assert.equal(omittedEntry.context.U.value[secondSiblingId].payload, fresh);
  assert.equal(omittedEntry.context.U.value[selectedId].payload, selected);

  const otherDate = timeline(async () => ({}));
  otherDate.context.f.value = '20261128';
  await otherDate.context.St('20261128', selectedId, null);
  assert.equal(otherDate.context.U.value[siblingId].date, '20261128');
  assert.equal(otherDate.context.U.value[siblingId].payload, undefined);
  assert(otherDate.context.U.value[siblingId].error);

  console.log('Three compiled timeline regression cases passed');
}
main().catch(error => { throw error; });
