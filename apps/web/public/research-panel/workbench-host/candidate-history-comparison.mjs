const groups = [
  ["original", "原公式"], ["nav_smallk", "小 K"],
  ["nav_pullback", "回踩"], ["nav_breakout", "突破"],
];

function summary(value) {
  return `${value.positive}/${value.valid}（未成熟 ${value.not_matured}）`;
}

export function renderCandidateHistoryComparison(container, detail) {
  const comparison = detail?.candidate_history_comparison;
  if (!comparison) return;
  const doc = container.ownerDocument;
  const make = (tag, text) => {
    const element = doc.createElement(tag);
    if (text) element.textContent = text;
    return element;
  };
  const table = make("table");
  table.dataset.candidateHistoryComparison = "";
  Object.assign(table.style, {width: "100%", marginTop: "0.75rem", borderCollapse: "collapse", fontSize: "0.75rem"});
  const caption = make("caption", "四组历史补前 → 补后（正收益 / 有效样本）");
  Object.assign(caption.style, {textAlign: "left", paddingBottom: "0.4rem", fontWeight: "600"});
  table.append(caption);
  const header = make("tr");
  const styleCell = (cell) => Object.assign(cell.style, {
    borderBottom: "1px solid var(--line, #c5ccd5)", textAlign: "left", padding: "0.32rem 0.25rem",
  });
  for (const label of ["组别", "D+2", "D+5"]) {
    const cell = make("th", label);
    cell.scope = "col";
    styleCell(cell);
    header.append(cell);
  }
  const head = make("thead");
  head.append(header);
  table.append(head);
  const body = make("tbody");
  for (const [group, label] of groups) {
    const row = make("tr");
    const hit = comparison.current_hit_groups.includes(group);
    row.dataset.group = group;
    row.dataset.currentHit = String(hit);
    const title = make("th", label);
    title.scope = "row";
    const state = make("small", hit ? "当天命中" : "当天未命中");
    if (!hit) state.style.color = "var(--muted, #626b77)";
    title.append(make("br"), state);
    styleCell(title);
    row.append(title);
    for (const horizon of ["d2", "d5"]) {
      const cell = make("td");
      cell.dataset.horizon = horizon;
      styleCell(cell);
      cell.append(make("span", `${summary(comparison.before[group][horizon])} → `),
        make("wbr"), make("span", summary(comparison.after[group][horizon])));
      row.append(cell);
    }
    body.append(row);
  }
  table.append(body);
  container.append(table);
}
