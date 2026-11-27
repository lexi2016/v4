"""Render Junda case charts using only the already-issued OOT checkpoint."""

import argparse
import csv
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.dates import YearLocator, DateFormatter

from .contracts import verify_payload


CASE_FNAME = "ACT080_P2_JUNDA_CASES.csv"
SERIES_FNAME = "ACT080_P2_JUNDA_REVIEW_SERIES.csv"
TRIGGERS_FNAME = "ACT080_P2_JUNDA_FIRST_COMPARATOR.csv"


def _rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _pct(value):
    return f"{100 * float(value):+.2f}%" if value else "Unknown"


def _chart(pdf, closes, triggers, cases):
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.subplots_adjust(bottom=0.13, left=0.11, right=0.97, top=0.88)
    days = [date.fromisoformat(r["D"]) for r in closes]
    price = {d: float(r["close_qfq"]) for d, r in zip(days, closes, strict=True)}
    ax.plot(days, list(price.values()), color="#425269", linewidth=1, label="VOL2 close")
    for policy, color, marker, label in (
        ("P1B", "#08735F", "^", "ACT-080 P1B FIRST passing fixed threshold"),
        ("V21", "#AD4F01", "o", "Frozen V2.1 Grade A FIRST"),
    ):
        marks = [date.fromisoformat(r["D"]) for r in triggers if r["policy"] == policy and r["selected"] == "True"]
        ax.scatter(marks, [price[d] for d in marks], c=color, marker=marker, s=28, alpha=0.8, label=label)
    for i, case in enumerate(sorted(cases, key=lambda r: r["D"])):
        day = date.fromisoformat(case["D"])
        ax.axvline(day, color="#64748B", linewidth=0.45, alpha=0.6)
        ax.annotate(case["case_id"], (day, 0.99 - (i % 2) * 0.07), xycoords=("data", "axes fraction"),
                    fontsize=8, ha="center", va="top")
    ax.xaxis.set_major_locator(YearLocator())
    ax.xaxis.set_major_formatter(DateFormatter("%Y"))
    ax.legend(loc="upper left", fontsize=8)
    ax.set_ylabel("Archival QFQ close")
    ax.grid(axis="y", color="#CBD5E1", linewidth=0.45)
    fig.suptitle("Junda 002865.SZ | Frozen policy comparison", fontsize=17)
    fig.text(0.11, 0.055, "Stock held out from TRAIN / VAL. Historical adjustment-factor PIT: CANNOT_CONFIRM. Research only.", fontsize=9)
    pdf.savefig(fig)
    plt.close(fig)


def _cases(pdf, cases):
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.set_axis_off()
    columns = ("Case", "Exact date", "Desired", "P1B FIRST", "V2.1 A FIRST", "T+2", "T+5", "T+10", "MAE5")
    rows = [[
        r["case_id"], r["D"], r["expected"], r["P1B_selected_policy"],
        r["V21_FIRST_POLICY_A"], *[_pct(r[key]) for key in ("T2", "T5", "T10", "MAE5")],
    ] for r in cases]
    table = ax.table(cellText=rows, colLabels=columns, bbox=(0, 0.4, 1, 0.5), cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    for (i, j), cell in table.get_celld().items():
        cell.set_edgecolor("#CBD5E1")
        if i == 0:
            cell.set_facecolor("#19324D")
            cell.get_text().set_color("white")
        elif i % 2:
            cell.set_facecolor("#EAF1F6")
    ax.text(0, 0.97, "Seven exact-date witnesses | Junda held-out history", fontsize=15, va="top")
    ax.text(0, 0.32, "T+N uses original observed-stock bars. Entry at D+1 open, 30 bp round trip.", fontsize=10)
    ax.text(0, 0.25, "See the issued CSV for candidate/release roles, exact rule status and frozen legacy tiers.", fontsize=10)
    ax.text(0, 0.18, "Trading and production disabled. This rendered view does not access sealed input or score models.", fontsize=10)
    pdf.savefig(fig)
    plt.close(fig)


def render(root, output, expected_release):
    if output.exists():
        raise FileExistsError(output)
    issued = root / "oot_issued"
    if output.resolve().is_relative_to(issued.resolve()):
        raise ValueError("write chart outside immutable issued directory")
    locked = verify_payload(root / "ACT080_P2_OOT_RELEASE_SEAL.json", issued, expected_release)
    if locked["stage"] != "OPENED_ONCE_ISSUED" or locked["OOT_OPEN_COUNT"] != 1:
        raise ValueError("sealed issued checkpoint required")
    closes, triggers, cases = (_rows(issued / name) for name in (SERIES_FNAME, TRIGGERS_FNAME, CASE_FNAME))
    with PdfPages(output, metadata={"Title": "ACT-080 Phase 2 Junda held-out cases"}) as pdf:
        _chart(pdf, closes, triggers, cases)
        _cases(pdf, cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--expected-release-sha256", required=True)
    args = parser.parse_args()
    render(args.run_root, args.pdf, args.expected_release_sha256)


if __name__ == "__main__":
    main()
