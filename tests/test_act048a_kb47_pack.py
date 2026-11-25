import io
import zipfile
from collections import Counter

import pytest

from ops import act048a_kb47_pack as pack
from ops import act048a_kb47_precompute as pre


def episode_row(symbol, day, session, family, anchors=()):
    return dict(ts_code=symbol, trade_date=day, session=session, methods=[family], old_methods=[],
                window_bars=60, wave=list(anchors))


def test_qc08_transitive_stock_family_and_shared_preexisting_anchor():
    old = [episode_row("A", 2000, 30, 5, [18])]
    rows = [episode_row("A", 2001, 34, 5), episode_row("A", 2002, 38, 5),
            episode_row("A", 2003, 80, 25, [18]), episode_row("A", 2004, 100, 25),
            episode_row("B", 2000, 30, 5, [18])]
    pool, stats = pack.episode_pool(rows, old)
    assert [pack.security_day(r) for r in pool] == [("A", 2004), ("B", 2000)]
    assert stats["known_same_episode"] == 3


def test_qc08_no_exact_or_offset_review_exposure_under_unknown_anchors():
    old = [episode_row("A", 2000, 30, 5)]
    pool, stats = pack.episode_pool(
        [episode_row("A", 1999, 25, 25), episode_row("A", 2001, 35, 25),
         episode_row("A", 2011, 41, 25), episode_row("B", 2001, 35, 25)], old)
    assert len(pool) == 2
    assert stats["stock_session_within_5_of_exposure"] == 2


def target_options():
    options = []
    for family_no, family in enumerate(pack.GROUPS):
        count = 0
        for tier, quota in zip(pack.TIERS, pack.quotas(family)):
            for _ in range(quota):
                fold = "holdout" if count % 4 == 3 else "dev"
                risk = pack.RISKS[(family_no*5+count-19) % 3] if tier == "hard" else ""
                n = len(options)
                day = 400 + n if fold == "holdout" else 100 + (n % 60)
                row = episode_row(str(count%6), 20000101+n, day, family)
                row.update(episode=n, first_session=day-59, board="A", board_epoch="X")
                options.append(dict(row=row, group=family, fold=fold, tier=tier, risk=risk, rank=n.to_bytes(3,"big")))
                count += 1
    # Capacity of each stratum is exact, so seed a separate known-feasible risk schedule.
    for no, item in enumerate(x for x in options if x["tier"] == "hard"):
        item["risk"] = pack.RISKS[no % 3]
    return options


def test_allocator_and_wave_certify_exact_quota():
    selected, proof = pack.choose(target_options())
    wave1, rest = pack.choose_wave1(selected)
    summary = pack.audit_picks(selected, wave1, [], 200)
    assert (summary["total"], summary["dev"], summary["holdout"], summary["wave1"]) == (240, 180, 60, 60)
    assert summary["hard_risk_actual"] == {risk:16 for risk in pack.RISKS}
    assert len(summary["wave1_risks"]) == 3
    assert len(rest) == 180 and proof["max_count_proven"]
    assert Counter(x["tier"] for x in selected) == {"strong":120, "gray":72, "hard":48}


def test_allocator_does_not_multiply_duplicate_episodes_to_fill_quota():
    options = target_options()[:2]
    options[1]["row"]["episode"] = options[0]["row"]["episode"]
    selected, proof = pack.choose(options)
    assert len(selected) == 1 and proof["max_count_proven"]


def test_holdout_rejects_overlapping_display_bars():
    picks, _ = pack.choose(target_options())
    wave, _ = pack.choose_wave1(picks)
    holdout = next(p for p in picks if p["fold"] == "holdout")
    holdout["row"]["first_session"] = 205
    with pytest.raises(Exception, match="HOLDOUT_WINDOW_EMBARGO"):
        pack.audit_picks(picks, wave, [], 200)


def fixture():
    anon = "ZABCDEF0123456789ABCDEF01"
    records = dict(anon_id=anon, window_bar_count=60, warmup_bar_count=200)
    bars = [dict({key: 1.0 for key in pack.BARS}, anon_id=anon, relative_bar=i, relative_market_session=i)
            for i in range(-59, 1)]
    cards = dict.fromkeys(pack.CARD)
    cards.update(anon_id=anon, fixed_anchor_offset=-11, d_offset=-9, t_offset=-6, c_offset=0)
    return records, bars, cards


def test_archive_contract_all_members_and_sha():
    one = [fixture()]
    blob = pack.archive(one)
    assert pack.validate_archive(blob, 1) == {one[0][0]["anon_id"]}
    assert pack.archive(one) == blob
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        assert tuple(z.namelist()) == tuple(pack.SCHEMAS)
    import hashlib
    assert hashlib.sha256(blob).hexdigest() != hashlib.sha256(blob + b" ").hexdigest()


@pytest.mark.parametrize(("selector", "column", "value", "reason"), [
    (0, "ts_code", "000001.SZ", None),
    (0, "source_bucket", "hard", None),
    (0, "future_return", "0.2", None),
    (0, "actual_date", "20261125", None),
    (0, "holdout", True, None),
    (1, "relative_market_session", 1, "BAD_BAR_CLOCK"),
    (2, "fixed_anchor_offset", 0, "NON_PRIOR_FIXED_ANCHOR"),
    (2, "t_offset", -9, "NONCAUSAL_CARD_CLOCK"),
])
def test_archive_rejects_payload_leak_and_noncausal_clocks(selector, column, value, reason):
    one = fixture()
    target = one[selector][0] if selector == 1 else one[selector]
    target[column] = value
    if reason is None:
        with pytest.raises(ValueError, match="fields not in fieldnames"):
            pack.archive([one])
    else:
        with pytest.raises(Exception, match=reason):
            pack.validate_archive(pack.archive([one]), 1)


def test_single_fixed_basis_window_excludes_later_corporate_action():
    def bar(day, price):
        row = dict.fromkeys(pre.PRICE.values(), price)
        row.update(trade_date=day, D_raw_volume=100.0, D_J=0.0, D_K=0.0, D_KDJ_D=0.0, D_ratio_hfq_segment=1)
        return row

    prefix = [bar(20200101,10), bar(20200102,10)]
    last = bar(20200103,5)
    authority = dict(events=[dict(ex_date=20200103,a=.5,b=0,volume_a=2)],
                     event_coverage_complete=True,history_start_date=20191231)
    pos = {20200101:0,20200102:1,20200103:2}
    early = pre.crop(prefix, pre.build_links(prefix,authority), 1, pos)
    all_rows = prefix+[last]
    links = pre.build_links(all_rows,authority)
    assert early == pre.crop(all_rows, links, 1, pos)
    assert [r["close"] for r in pre.crop(all_rows,links,2,pos)] == [5,5,5]


def test_f05_count_keeps_current_and_uses_prior_twenty_actual_bars():
    bars = [dict(close=1.0, high=1.0, volume=1.0) for _ in range(60)]
    bars[-2].update(close=1.05, high=1.05)
    bars[-1].update(close=1.10, high=1.10)
    ret, count = pack.f05_observation(bars)
    assert ret == pytest.approx((1.10/1.05-1)*100)
    assert count == 2
