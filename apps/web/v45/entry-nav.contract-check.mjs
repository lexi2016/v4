import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

test("V4.5 nav is appended after Vibe 8910, preserves legacy links and is idempotent", async () => {
  const dom = new JSDOM('<nav class="entry-nav" aria-label="功能入口"><a href="/legacy">旧入口</a><a href="http://127.0.0.1:8910/a-share/review">原版 Vibe · 8910</a></nav>', { url: "http://127.0.0.1:8873/" });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.MutationObserver = dom.window.MutationObserver;
  try {
    const { attachEntries } = await import("./entry-nav.js?nav-test=1");
    attachEntries();
    const nav = document.querySelector("nav.entry-nav");
    const labels = [...nav.querySelectorAll("a")].map(x => x.textContent.trim());
    assert.deepEqual(labels, ["旧入口","原版 Vibe · 8910","今日选股","个股研究","复盘验证"]);
    attachEntries();
    assert.equal(nav.querySelectorAll("[data-v45-entry]").length, 3);
    assert.equal(nav.querySelector('a[href="/legacy"]')?.textContent, "旧入口");
  } finally {
    dom.window.__v45EntryNavObserver?.disconnect();
    dom.window.close();
    delete globalThis.window;
    delete globalThis.document;
    delete globalThis.MutationObserver;
  }
});
