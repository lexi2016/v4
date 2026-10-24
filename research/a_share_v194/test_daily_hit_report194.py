"""Synthetic membership and Top100 hit units; no dataset reads or fits."""
import long_run194 as runner


def test_daily_report_common_new_lost_count_top100_hits():
    day = '2003-09-24'
    codes = [f'{number:06d}.SZ' for number in range(1, 195)]
    positives = set(codes[:100])
    common = {codes[0], codes[100], codes[101]}
    added = {codes[1], codes[2]} | set(codes[102:147])
    lost = set(codes[147:194])
    baseline, candidate = common | lost, common | added
    calendar = dict(target_date=day, truth_positive_denominator='100',
        truth_rankable_research_rows='194',
        truth_rankable_code_keys_sha256=runner.canonical_json_sha256(sorted(codes)),
        cohort_role='eligible', training_eligible='true')
    truth = [dict(target_date=day, code=code, label=int(code in positives)) for code in codes]
    picks = lambda selected: [dict(target_date=day, code=code) for code in sorted(selected)]
    daily, _, _ = runner._selection_comparison(
        oof_dates=[day], truth_rows=truth, raw_natural_rows=[],
        technical_rows=picks(baseline), v194_rows=picks(candidate),
        calendar_rows=[calendar], universe_codes=set(codes),
        fold_for_date={day: 'fold_01'}, fold_source_audit={})
    for name, selections, hits in [('common', 3, 1), ('new', 47, 2), ('lost', 47, 0)]:
        assert daily[0]['technical11_l2_vs_v194_' + name] == selections
        assert daily[0]['technical11_l2_vs_v194_' + name + '_hits'] == hits
    coverage = dict(calendar)
    for scope in ('raw', 'model'):
        coverage[scope + '_source_state_denominator'] = '194'
        for lane in ('fupan', 'stage7', 'research'):
            for state in ('hit', 'confirmed_absent', 'unknown'):
                coverage[f'{scope}_source_{lane}_{state}_rows'] = '194' if state == 'unknown' else '0'
    report = runner._daily_model_report_rows(
        oof_daily=daily, coverage_rows=[coverage], calendar_rows=[calendar])
    assert len(report) == 1
    assert report[0]['baseline_v194_common'] == len(common & positives) == 1
    assert report[0]['baseline_v194_new'] == len(added & positives) == 2
    assert report[0]['baseline_v194_lost'] == len(lost & positives) == 0
    assert report[0]['baseline_selected'] == report[0]['v194_selected'] == 50
    assert report[0]['baseline_hits'] == 1
    assert report[0]['v194_hits'] == 3
    assert report[0]['top100_truth_count'] == 100
