import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, sourceRoot, versions } from './ssr_harness.mjs';

const fixture=resolve(process.argv[2]);
const payload=JSON.parse(readFileSync(fixture,'utf8'));
const html=await render(payload.execution_evidence);
const source=readFileSync(resolve(sourceRoot,'components/review/StageExecutionEvidencePanel.vue'),'utf8');
const css=source.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] ?? '';
const output=resolve(process.argv[3]);
writeFileSync(output,`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>合成回归：Stage 研究结果读回</title><style>body{max-width:1100px;margin:2rem auto;padding:0 1rem;font-family:system-ui,sans-serif;color:#0f172a;line-height:1.55}${css}</style><h1>合成回归：原 consumer 输出的 Vue 渲染</h1><p>由真实 SelectionStore、owner receipt writer、reader 与 consumer 生成，使用合成测试数据；不代表实时行情、部署或自然时段验收。</p>${html}</html>\n`);
console.log(JSON.stringify({output,node:process.version,packages:versions}));
