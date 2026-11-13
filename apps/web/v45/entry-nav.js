const entries = [
  { id: "selection", label: "今日选股", href: "/v45/selection/" },
  { id: "research", label: "个股研究", href: "/v45/research/" },
  { id: "review", label: "复盘验证", href: "/v45/review/" },
];

export function attachEntries() {
  const nav = document.querySelector('nav.entry-nav[aria-label="功能入口"]');
  if (!nav) return;
  const vibe = [...nav.querySelectorAll("a")].find(link =>
    link.textContent?.trim().includes("原版 Vibe") && link.href.includes(":8910/")
  );
  if (!vibe) return;
  let cursor = vibe;
  for (const entry of entries) {
    let link = nav.querySelector(`[data-v45-entry="${entry.id}"]`);
    if (!link) {
      link = document.createElement("a");
      link.className = vibe.className || "entry-nav-link";
      link.href = entry.href;
      link.textContent = entry.label;
      link.dataset.v45Entry = entry.id;
    }
    if (cursor.nextElementSibling !== link) cursor.insertAdjacentElement("afterend", link);
    cursor = link;
  }
}

function start() {
  attachEntries();
  if (!document.body || window.__v45EntryNavObserver) return;
  const observer = new MutationObserver(attachEntries);
  observer.observe(document.body, { childList: true, subtree: true });
  window.__v45EntryNavObserver = observer;
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
else start();
