"""Draw 61 anonymous bars solely from physically truncated VOL2 OHLCV."""

import argparse
from collections import Counter
from io import BytesIO
from math import isfinite
from pathlib import Path
from time import perf_counter

from ops.pft_act080_core.archive import read_archive
from ops.pft_act080_core.core import Indicators
from ops.pft_act080_p2.contracts import digest, read_json, verify, write_csv, write_json

from .run import SELECT_FILE


VISIBLE = 61


def numeric_bars(bars):
    indicators = Indicators()
    result = []
    for bar in bars:
        signal = indicators.advance(bar)
        result.append((bar.open, bar.high, bar.low, bar.close, bar.volume, signal["W"], signal["Y"]))
    return result


def draw(candles):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.collections import LineCollection
    from matplotlib.figure import Figure
    from PIL import Image

    if len(candles) != VISIBLE or any(value is None or not isfinite(value) for bar in candles for value in bar):
        raise ValueError("anonymous chart requires exactly 61 complete finite OHLCV/W/Y rows")
    background = "#101520"
    figure = Figure(figsize=(10, 5.6), dpi=120, facecolor=background)
    FigureCanvasAgg(figure)
    gs = figure.add_gridspec(2, 1, height_ratios=(4, 1), hspace=0.018,
                            left=0.026, right=0.974, top=0.966, bottom=0.047)
    top, bottom = figure.add_subplot(gs[0]), figure.add_subplot(gs[1])
    x = list(range(VISIBLE))
    opens, highs, lows, closes, volumes, w, y = zip(*candles, strict=True)
    colors = ["#ef686e" if cc >= oo else "#4ec69a" for oo, cc in zip(opens, closes, strict=True)]
    top.add_collection(LineCollection(
        [[(i, ll), (i, hh)] for i, ll, hh in zip(x, lows, highs, strict=True)], colors=colors, linewidths=1.0,
    ))
    uv = max(max(highs), max(w), max(y))
    lv = min(min(lows), min(w), min(y))
    delta = max((uv - lv) * 0.004, abs(uv) * 1e-7)
    body = [max(abs(oo - cc), delta) for oo, cc in zip(opens, closes, strict=True)]
    baseline = [min(oo, cc) for oo, cc in zip(opens, closes, strict=True)]
    top.bar(x, body, bottom=baseline, color=colors, width=0.60, linewidth=0, zorder=2)
    top.plot(x, w, color="#f1f4f7", linewidth=1.4, zorder=3)
    top.plot(x, y, color="#ecc968", linewidth=1.4, zorder=3)
    top.set_ylim(lv - max((uv - lv) * 0.06, delta), uv + max((uv - lv) * 0.06, delta))
    bottom.bar(x, volumes, color=colors, width=0.60, linewidth=0, alpha=0.85)
    bottom.set_ylim(0, max(max(volumes) * 1.1, 1))
    for axis in (top, bottom):
        axis.set_facecolor(background)
        axis.set_xlim(-0.8, VISIBLE - 0.2)
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_visible(False)
    bottom.spines["top"].set_visible(True)
    bottom.spines["top"].set_color("#293241")
    if figure.texts or any(axis.texts for axis in (top, bottom)):
        raise ValueError("unexpected identity-bearing chart text")
    data = BytesIO()
    figure.savefig(data, format="png", facecolor=background, metadata={"Software": None})
    encoded = data.getvalue()
    with Image.open(BytesIO(encoded)) as image:
        if image.format != "PNG" or image.size != (1200, 672) or set(image.info) - {"dpi"}:
            raise ValueError("unexpected PNG metadata or raster geometry")
        image.verify()
    return encoded


def batch(analytics, vol2):
    started = perf_counter()
    metrics = read_json(analytics / "ACT081_P1_METRICS.json")
    selection_path = analytics / SELECT_FILE
    selection_sha = verify(selection_path, metrics["sample_selection_sha256"])
    rows = read_json(selection_path)["rows"]
    market = read_archive(vol2)
    if market.evidence["archive_sha256"] != metrics["VOL2"]["archive_sha256"]:
        raise ValueError("chart and analytics VOL2 bytes differ")
    chains = {chain.security_id: chain for chain in market.chains}
    destination = analytics / "visual"
    images = destination / "png"
    images.mkdir(parents=True)
    index, full_reference = [], {}
    for row in rows:
        stock, day, d, image = (row[k] for k in ("security_id", "D", "session_idx", "image_id"))
        original = chains[stock].bars
        prefix = original[:d + 1]
        if prefix[-1].trade_date != day or len(prefix) != d + 1:
            raise ValueError(f"{stock}/{day}: physical chart prefix cut mismatch")
        visible = numeric_bars(prefix)[-VISIBLE:]
        if len(visible) != VISIBLE:
            raise ValueError("61-bar window unavailable")
        if stock not in full_reference:
            # A separate audit branch only. draw() receives no date, identity or full-chain object.
            full_reference[stock] = numeric_bars(original)
        if visible != full_reference[stock][d + 1 - VISIBLE:d + 1]:
            raise ValueError(f"{stock}/{day}: W/Y or price/volume prefix drift")
        filename = f"{image}.png"
        path = images / filename
        with path.open("xb") as output:
            output.write(draw(visible))
        index.append({
            **row, "filename": f"png/{filename}", "first_visible_D": prefix[-VISIBLE].trade_date,
            "last_visible_D": prefix[-1].trade_date, "bars": VISIBLE, "volatile_future_input_rows": 0,
            "physical_prefix_bars": len(prefix), "full_chain_added_rows_for_audit": len(original) - len(prefix),
            "bytes": path.stat().st_size, "sha256": digest(path),
        })
    write_csv(destination / "ACT081_P1_PNG_IDENTITY_INDEX.csv", index)
    counts = Counter(row["universe"] for row in index)
    write_json(destination / "ACT081_P1_PNG_AUDIT.json", {
        "png_count": len(index), "count_by_universe": dict(counts), "bars_each": VISIBLE,
        "selection_sha256": selection_sha, "prefix_rows_full_chain_numeric_differences": 0,
        "future_bars_rendered": 0, "visible_identity_or_calendar_text_objects": 0,
        "identity_bearing_metadata_items": 0,
        "width": 1200, "height": 672, "seconds": perf_counter() - started,
    })
    print(f"ACT081 anonymous charts={len(index)}. Prefix drift=0. Future bars plotted=0.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analytics", type=Path, required=True)
    parser.add_argument("--vol2", type=Path, required=True)
    args = parser.parse_args()
    batch(args.analytics, args.vol2)


if __name__ == "__main__":
    main()
