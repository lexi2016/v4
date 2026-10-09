// Compatibility for the unchanged R3 research-presentation assertions. Their
// App boundary now uses the full verified live App via live_app_harness.
import { renderApp as renderLiveApp, text } from './live_app_harness.mjs';
export { evidenceHtml } from './live_app_harness.mjs';
export async function renderApp(payload) { return (await renderLiveApp(payload)).html; }
export function hkColumnCount(html) {
  return text(html.match(/<div class="market-title"><h3>港股通[^<]*<\/h3><span>([\s\S]*?)<\/span>/)?.[1] ?? '');
}
