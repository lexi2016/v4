"""Regression checks for the bounded catch-up and its read-only preview seam."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ops import bootstrap_stock_event_history as boot
from ops import read_candidate_stock_history as overlay


def test_reader_relocation_preserves_frozen_identity_and_rejects_other_changes(tmp_path):
    before = tmp_path / 'before'
    after = tmp_path / 'after'
    before.mkdir()
    after.mkdir()
    for key in boot.TRANSPORT_WITNESSES:
        for directory in (before, after):
            (directory / key).write_text(key)
    def identity(directory):
        return dict(generation='frozen', reader_provenance=dict(
            actual_reader={'path': '/fixed'}, transport_equivalence={
                key: boot.ref(directory / key) for key in boot.TRANSPORT_WITNESSES}))
    expected = identity(before)
    live = identity(after)
    context = SimpleNamespace(identity=live)
    assert len(boot.bind_product_identity(context, expected)) == 6
    assert context.identity == expected
    assert context.identity is not expected
    changed = deepcopy(live)
    changed["reader_provenance"]["actual_reader"]["path"] = "/unexpected"
    with pytest.raises(ValueError, match="FROZEN_GENERATION_CONFLICT"):
        boot.bind_product_identity(SimpleNamespace(identity=changed), expected)
    (before / "oracle").write_text("damaged")
    with pytest.raises(ValueError, match="FROZEN_TRANSPORT_WITNESS_DRIFT"):
        boot.bind_product_identity(SimpleNamespace(identity=live), expected)


def test_preview_overlay_isolated_by_symbol_date_and_frozen_identity(tmp_path):
    symbol = overlay.SYMBOL
    views = {}
    old_rows = {}
    def write(name, value):
        return boot.save(tmp_path / name, {**value, **overlay.RAW_FLAGS})
    for date in sorted(overlay.DATES):
        generation, inp = date + "-generation", date + "-input"
        asof = overlay._iso(date)
        src = dict(generation=generation, input_sha256=inp)
        stat_case = dict(event_date=asof, target_date="2026-11-16", return_pct=None,
                         status="not_matured", detail_status="TARGET_AFTER_ASOF")
        horizon = dict(total=1, cases=[stat_case], valid=0)
        stats = dict(asof=asof, groups=[
            dict(group_id=g, source_identity=src, rule_sha256="rule", identity_status="BOUND", eligible_event_count=1,
                 horizons={h: horizon for h in overlay.HORIZONS}) for g in sorted(overlay.GROUPS)])
        old_stats = deepcopy(stats)
        old_stats["asof"] = "old"
        old_rows[date] = old = dict(symbol=symbol, data_date=date, statistics=old_stats,
                                    historical_coverage={}, qualification={"sentinel": True})
        original = write(f"original-{date}.json", old)
        product = write(f"product-{date}.json", dict(data_date=date, source_generation=generation,
                        source_identity=src, row_refs={symbol: original}))
        numeric = write(f"manifest-{date}.json", dict(data_date=date, source_generation=generation,
                        input_sha256=inp, artifact=product))
        row = write(f"detail-{date}.json", {**old, "statistics": stats,
                    "historical_coverage": dict(known_full_history=True, historical_PIT=False,
                        requested_end=int(date), evaluated_dates=[int(date)],
                        evaluated_count=1, available_prefix_dates=1)})
        projection = {"bytes": 42, "sha256": date}
        event_cases = write(f"cases-{date}.json", dict(schema_version="v4.a_share.event_cases.v1",
                            symbol=symbol, data_date=date, numeric_manifest=numeric, source_generation=generation,
                            input_sha256=inp, statistics_sha256=overlay._digest(stats), projection=projection,
                            groups={g: {h: horizon for h in overlay.HORIZONS} for g in overlay.GROUPS}))
        chart = write(f"chart-{date}.json", dict(samples={symbol: dict(data_date=date,
                      source_generation=generation, source_input_sha256=inp, product_row_ref=original, projection=projection)}))
        views[date] = dict(numeric_manifest=numeric, generation=generation, input_sha256=inp,
                           detail_row=row, event_cases=event_cases, chart_manifest=chart)
    manifest = write("overlay.json", dict(schema="V4_STOCK_HISTORY_CANDIDATE_OVERLAY_V1", symbol=symbol, dates=views))
    class Source:
        moved = False
        def read_a_daily_event_cases(self, date, ticker, *, group, horizon):
            return {"underlying": (date, ticker, group, horizon)}
        def read_a_daily_product(self, date=None, ticker=None, *, include_display_names=True):
            if ticker != symbol or date not in views:
                return {"underlying": (date, ticker, include_display_names)}
            view = views[date]
            return dict(status="READY", data_date=date, manifest=view["numeric_manifest"],
                        source_generation="moved" if self.moved else view["generation"],
                        source_identity={"input_sha256": view["input_sha256"]},
                        row={**old_rows[date], "display_name": "The original name"})
    overlay.install(Source, manifest["path"], manifest["sha256"])
    source = Source()
    for day in sorted(views):
        response = source.read_a_daily_product(day, symbol)
        assert response["row"]["display_name"] == "The original name"
        assert response["row"]["statistics"]["asof"] == overlay._iso(day)
        assert response["row"]["historical_coverage"]["evaluated_count"] == 1
        cases = source.read_a_daily_event_cases(day, symbol, group="nav_smallk", horizon="d5")
        assert cases["cases"][0]["event_date"] == overlay._iso(day)
        assert cases["status"] == "READY"
    assert source.read_a_daily_product("20261111", symbol) == {"underlying": ("20261111", symbol, True)}
    assert source.read_a_daily_product("20261113", "000001.SZ") == {"underlying": ("20261113", "000001.SZ", True)}
    assert source.read_a_daily_event_cases("20261113", symbol, group="bad") == {
        "underlying": ("20261113", symbol, "bad", "d2")}
    source.moved = True
    with pytest.raises(ValueError, match="DETAIL_MOVED"):
        source.read_a_daily_event_cases("20261113", symbol)
    original = views["20261112"]["detail_row"]
    with open(original["path"], "a") as stream:
        stream.write(" ")
    class OtherSource:
        pass
    with pytest.raises(ValueError, match="CANDIDATE_SHA"):
        overlay.install(OtherSource, manifest["path"], manifest["sha256"])


def test_statistics_only_routes_the_two_existing_date_commits(tmp_path):
    refs = {}
    for day in sorted(map(overlay._iso, overlay.DATES)):
        root = tmp_path / day
        refs[day] = boot.save(root / "statistics.json", dict(schema="V4_WORKBENCH_STATISTICS_V1",
            source_date=day, rows={overlay.SYMBOL: {g: {} for g in overlay.GROUPS}}, **overlay.RAW_FLAGS))
        receipt = boot.save(root / "receipt.json", dict(status="COMMITTED",
            artifact=refs[day], **overlay.RAW_FLAGS))
        boot.save(root / "latest.json", dict(schema="V4_WORKBENCH_MODULE_COMMIT_V1",
            module="statistics", date=day, artifact=refs[day], receipt=receipt, **overlay.RAW_FLAGS))

    class Host:
        def _module_reference(self, module, day):
            return module, day

    overlay.install_statistics(Host, tmp_path)
    host = Host()
    for day, ref in refs.items():
        assert host._module_reference("statistics", day) == ref
        assert host._module_reference("overseas", day) == ("overseas", day)
    assert host._module_reference("statistics", "2026-11-11") == ("statistics", "2026-11-11")
    with open(refs["2026-11-12"]["path"], "a") as stream:
        stream.write(" ")

    class AnotherHost:
        pass

    with pytest.raises(ValueError, match="CANDIDATE_SHA"):
        overlay.install_statistics(AnotherHost, tmp_path)
