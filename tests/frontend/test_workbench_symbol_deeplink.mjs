import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const sourcePath = new URL('../../apps/web/public/research-panel/workbench-host/dot/shell/workbench.local.mjs', import.meta.url);
const source = await readFile(sourcePath, 'utf8');
const helpers = source.split('\n').filter(line =>
  line.startsWith('export function requestedSelectionFromSearch(') ||
  line.startsWith('export function resolveRequestedSelection(')
);
assert.equal(helpers.length, 2, 'selection helpers must be defined in the canonical workbench module');
const {requestedSelectionFromSearch, resolveRequestedSelection} = await import(
  `data:text/javascript,${encodeURIComponent(helpers.join('\n'))}`
);

test('a valid URL symbol wins over the first row in the same-day filtered list', () => {
  const intent = requestedSelectionFromSearch('?symbol=600018.SH&source_date=2026-11-11');
  const result = resolveRequestedSelection([
    {symbol: '000159.SZ'},
    {symbol: '600018.SH'},
  ], intent);

  assert.equal(result.status, 'MATCHED');
  assert.equal(result.index, 1);
  assert.equal(result.row.symbol, '600018.SH');
});

test('an absent URL symbol keeps the existing first-row default', () => {
  const intent = requestedSelectionFromSearch('?source_date=2026-11-11');
  const result = resolveRequestedSelection([{symbol: '000159.SZ'}, {symbol: '600018.SH'}], intent);

  assert.equal(result.status, 'ABSENT');
  assert.equal(result.row.symbol, '000159.SZ');
});

test('invalid, duplicated, and out-of-candidate URL symbols fall back explicitly', () => {
  const rows = [{symbol: '000159.SZ'}];
  const malformed = resolveRequestedSelection(rows, requestedSelectionFromSearch('?symbol=not-a-symbol'));
  const duplicate = resolveRequestedSelection(rows, requestedSelectionFromSearch('?symbol=600018.SH&symbol=600018.SH'));
  const missing = resolveRequestedSelection(rows, requestedSelectionFromSearch('?symbol=600018.SH'));

  assert.equal(malformed.status, 'INVALID');
  assert.equal(malformed.row.symbol, '000159.SZ');
  assert.equal(duplicate.status, 'INVALID');
  assert.equal(missing.status, 'NOT_FOUND');
  assert.equal(missing.row.symbol, '000159.SZ');
});

test('loadDay captures the route before asynchronous reads and passes it into first render', () => {
  assert.match(source, /async function loadDay\(\)\{const routeSelection=requestedSelectionFromSearch\(location\.search\);/);
  assert.match(source, /const initial=renderList\(true,routeSelection\);/);
  assert.match(source, /initial\.status==='INVALID'\?`链接指定股票代码无效 · CANNOT_CONFIRM/);
  assert.match(source, /链接指定股票 \$\{initial\.symbol\} 不在 \$\{day\.source_date\} 当前候选中 · CANNOT_CONFIRM/);
});
