import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ops import pft_act030_features as f
from ops import pft_act030_eval as e
from ops import pft_act030_verify as v


def history(n=40):
    c = np.linspace(10., 14., n)
    return pd.DataFrame(dict(trade_date=pd.bdate_range('2020-01-01', periods=n).strftime('%Y%m%d'),
        open=c-.1, high=c+.4, low=c-.3, close=c, white=c-.2, yellow=c-.6,
        bbi=c-.4, volume=np.arange(n)+100., amount_cny=np.arange(n)+1000.))


def anchors(h):
    row = h.iloc[-3]
    return f.Anchors(h.trade_date.iloc[-8], row.trade_date, row.low, (row.open+row.close)/2, row.low)


def test_sixteen_continuous_groups_and_independent_numeric_windows():
    h = history()
    result = f.features(h, h.trade_date.iloc[-1], anchors(h))
    assert tuple(result) == f.FEATURES and len(result) == 16
    assert all(np.isfinite(x) for x in result.values())
    assert result['box_tightness_5d'] == pytest.approx((h.high.tail(5).max()-h.low.tail(5).min())/h.close.tail(5).mean())
    platform = h.volume.iloc[-25:-5].mean()
    peak = h.volume.iloc[-35:-5].nlargest(3).mean()
    assert result['vol_contraction_vs_platform'] == h.volume.tail(3).mean()/platform
    assert result['vol_contraction_vs_wave_peak'] == h.volume.tail(3).mean()/peak
    assert result['vol_d_vs_platform'] == h.volume.iloc[-1]/platform
    assert result['up_vol_purity_20d'] == 1
    assert result['max_dn_vol5_vs_plat'] == 0
    assert result['active_intact_margin_atr'] > 0


def test_candle_down_and_previous_close_up_are_distinct_rules():
    h = history()
    h.loc[h.index[-2], 'open'] = h.close.iloc[-2]+.1  # green body but rising close
    result = f.features(h, h.trade_date.iloc[-1], anchors(h))
    assert result['up_vol_purity_20d'] == 1
    assert result['max_dn_vol5_vs_plat'] == h.volume.iloc[-2]/h.volume.iloc[-25:-5].mean()


def test_inverse_newest_first_affine_volume_and_no_clipping():
    original = history()
    # Two noncommuting affines; independent volume != reciprocal price factor.
    events = [dict(ex_date=20210101, a=.7, b=-10., volume_a=1.3),
              dict(ex_date=20220101, a=.4, b=-2., volume_a=1.9)]
    baked = original.copy()
    for event in events:
        baked[list(f.PRICE_COLUMNS)] = baked[list(f.PRICE_COLUMNS)]*event['a']+event['b']
        baked['volume'] *= event['volume_a']
    assert baked.close.lt(0).all()
    restored, audit = f.to_d_basis(baked, events, original.trade_date.iloc[-1], 20221101)
    np.testing.assert_allclose(restored[list(f.PRICE_COLUMNS)], original[list(f.PRICE_COLUMNS)], atol=1e-14)
    np.testing.assert_allclose(restored.volume, original.volume)
    assert restored.amount_cny.equals(original.amount_cny)
    assert audit['event_dates'] == ['20220101', '20210101'] and not audit['price_clipping']


def test_event_on_d_is_retained_and_later_suffix_only():
    h = history()
    endpoint = h.trade_date.iloc[-1]
    events = [dict(ex_date=int(endpoint), a=.8, b=-1., volume_a=1.1),
              dict(ex_date=20210101, a=1., b=-2., volume_a=1.)]
    out, audit = f.to_d_basis(h, events, endpoint, 20211101)
    np.testing.assert_allclose(out.close, h.close+2)
    assert audit['events_undone'] == 1


@pytest.mark.parametrize('mutation', ['future', 'duplicate', 'unsorted', 'nonfinite'])
def test_history_fail_closed(mutation):
    h = history()
    endpoint = h.trade_date.iloc[-1]
    if mutation == 'future':
        endpoint = h.trade_date.iloc[-2]
    elif mutation == 'duplicate':
        h.loc[1, 'trade_date'] = h.trade_date.iloc[0]
    elif mutation == 'unsorted':
        h = h.iloc[::-1]
    else:
        h.loc[5, 'close'] = float('inf')
    with pytest.raises(ValueError):
        f.features(h, endpoint, anchors(history()))


def test_unknown_anchor_and_short_window_preserve_null():
    h = history(10)
    out = f.features(h, h.trade_date.iloc[-1], f.Anchors(active_date='20300101', active_low=1))
    assert all(out[n] is None for n in f.GROUPS['anchor'])
    assert out['vol_contraction_vs_platform'] is None and out['atr_contraction_5v20'] is None
    assert out['box_tightness_5d'] is not None


def test_reference_anchor_is_separate_and_midpoint_is_oc():
    h = history()
    row = h.iloc[-3]
    ref = dict(root_key_k_date=h.trade_date.iloc[-8], active_key_k_date=row.trade_date,
               active_anchor_low=row.low, invalidation_price=row.low-.1)
    result = f.diagnostic_reference_features(h, h.trade_date.iloc[-1], ref)
    assert result['active_close_vs_mid_pct'] == h.close.iloc[-1]/((row.open+row.close)/2)-1
    # The normal path receives only the user's own explicit Anchors type.
    with pytest.raises(AttributeError):
        f.features(h, h.trade_date.iloc[-1], ref)


def rows(n=62):
    labels, scores = [], []
    for i in range(n):
        eid = f'{i:024x}'
        label = e.POS if i < 22 else e.NEG if i < 54 else e.EVENT
        score = .8 if i < 20 else .5 if i < 25 else .2
        labels.append(dict(episode_id=eid, unanimous_gold_v1=label, adv20_cny=str(3e8),
                           unanimous_pos_subtype='S-Pullback' if i < 22 else '',
                           both_v_true='V01|V02' if label == e.NEG else '', chat_primary_veto='V01'))
        scores.append(dict(episode_id=eid, raw_score=score, gated_score=score, gate_reason='PASS'))
    return labels, scores


def test_same_exam_deterministic_ties_pk50_and_multilabel():
    labels, scores = rows()
    ids = {r['episode_id'] for r in labels}
    out = e.same_exam(labels, scores[::-1], ids)
    primary = out['consensus_primary']['raw_score']
    assert primary['n'] == 62 and primary['pos'] == 22
    assert primary['ranking']['50']['precision'] == 22/50
    assert primary['ranking']['20']['hits'] == 20
    assert primary['tp'] == 22 and primary['fp'] == 3  # >= .50 includes ties
    assert out['hard_neg_by_both_v']['V01']['raw_score']['n'] == 32
    assert out['hard_neg_by_both_v']['V02']['raw_score']['n'] == 32
    assert out['hard_neg_by_chat_primary_v']['V02']['raw_score']['n'] == 0
    assert out['hard_neg_adv_ge_3e8']['raw_score']['n'] == 32
    assert out['fit'] == out['model_load'] == out['predict'] == 0
    assert out == e.same_exam(labels[::-1], scores, ids)


def test_pk_less_than_k_null_and_auc_class_missing():
    labels, scores = rows(3)
    out = e.same_exam(labels, scores, {r['episode_id'] for r in labels})
    m = out['consensus_primary']['raw_score']
    assert m['ranking'] == {'20': None, '30': None, '50': None}
    assert m['auc'] is None


@pytest.mark.parametrize('bad', ['duplicate', 'missing', 'extra', 'nan', 'range', 'gate'])
def test_saved_scores_fail_closed(bad):
    labels, scores = rows(3)
    ids = {r['episode_id'] for r in labels}
    if bad == 'duplicate':
        scores.append(scores[0])
    elif bad == 'missing':
        scores.pop()
    elif bad == 'extra':
        scores.append({**scores[0], 'episode_id': 'f'*24})
    elif bad == 'nan':
        scores[0]['raw_score'] = float('nan')
    elif bad == 'range':
        scores[0]['gated_score'] = 1.1
    else:
        scores[0]['gate_reason'] = 'BLOCKED'
    with pytest.raises(ValueError):
        e.same_exam(labels, scores, ids)


def test_challenger_gate_contract_is_explicit_and_separate():
    labels, scores = rows(3)
    for score in scores:
        score['v2_gate'] = 'SOFT_PENALTY'
        score['gated_score'] = score['raw_score']/2
    out = e.same_exam(labels, scores, {r['episode_id'] for r in labels}, gate_field='v2_gate', gate_policy='provided_scores')
    assert out['gate_policy'] == 'provided_scores'
    with pytest.raises(ValueError, match='SAVED_GATE'):
        e.same_exam(labels, scores, {r['episode_id'] for r in labels}, gate_field='v2_gate')


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_no_fit_cli_scores_baseline_and_synthetic_challenger_identical_rows(tmp_path, monkeypatch):
    labels, scores = rows(100)
    # Synthetic test data are only a no-FIT ABI test, never challenger evidence.
    for label, score in zip(labels, scores):
        label.update(calib_100='true', gate_reason='BLOCKED', raw_S_lr=.3, gated_S_lr=0., raw_S_rf=.4, gated_S_rf=0.)
        score['v2_gate'] = 'SOFT_PENALTY'
        score['gated_score'] = score['raw_score']/2
    baseline, pred = tmp_path/'labels.csv', tmp_path/'synthetic.csv'
    write_csv(baseline, labels)
    write_csv(pred, scores)
    ids = tmp_path/'ids.json'
    ids.write_text(json.dumps([r['episode_id'] for r in labels]))
    monkeypatch.setattr(e, 'CALIB100_SHA', e.sha(baseline))
    output = tmp_path/'output.json'
    e.main(['--labels', str(baseline), '--predictions', str(pred), '--expected-ids', str(ids),
            '--gate-field', 'v2_gate', '--output', str(output)])
    result = json.loads(output.read_text())
    assert result['same_exam_id_set_verified']
    assert result['authorized_n'] == result['baseline']['authorized_n'] == 100
    assert set(result['baseline']['consensus_primary']) == set(e.SCORES)
    assert set(result['consensus_primary']) == {'raw_score', 'gated_score'}
    assert result['fit'] == result['model_load'] == result['predict'] == 0
    assert result['baseline']['consensus_primary']['gated_S_lr']['tp'] == 0
    assert result['consensus_primary']['gated_score']['mean_score'] > 0


def test_release_guard_precedes_reading_unreleased_labels(tmp_path):
    unknown = tmp_path/'unknown.csv'
    unknown.write_text('not authorized content')
    with pytest.raises(ValueError, match='ONLY_APPROVED_CALIB100'):
        e.main(['--labels', str(unknown), '--baseline-only', '--output', str(tmp_path/'out.json')])
    with pytest.raises(ValueError, match='WHOLE240_NOT_RELEASED'):
        e.validate_release({}, Path('/no-label-access'), Path('/no-score-access'), 240)


def test_public_zip_wrong_identity_does_not_open_members(tmp_path):
    bad = tmp_path/'bad.zip'
    bad.write_bytes(b'not the frozen archive')
    with pytest.raises(ValueError, match='SOURCE_TAMPER'):
        v.read_public(bad)


def test_whole240_receipt_cannot_admit_other_100_labels(tmp_path):
    labels, scores = rows(100)
    path, predictions = tmp_path/'labels.csv', tmp_path/'scores.csv'
    write_csv(path, labels)
    write_csv(predictions, scores)
    release = tmp_path/'release.json'
    release.write_text(json.dumps(dict(scope='ACT022_WHOLE240_SAME_EXAM', explicit_user_release=True,
        threshold=.5, fit_allowed=False, labels_sha256=e.sha(path), predictions_sha256=e.sha(predictions))))
    with pytest.raises(ValueError, match='ACTUAL240_LABELS'):
        e.main(['--labels',str(path),'--predictions',str(predictions),'--release-receipt',str(release),
                '--output',str(tmp_path/'out.json')])


def test_divergent_or_missing_raw_alias_ledger_withholds_d_basis():
    event = dict(ex_date=20210101, a=.7, b=-.1, volume_a=1.3)
    snapshot = dict(symbols={
        '920392.BJ':dict(event_coverage_complete=True, events=[event]),
        '872392.BJ':dict(event_coverage_complete=True, events=[]),
        '601666.SH':dict(event_coverage_complete=True, events=[event])})
    assert v.d_basis_eligibility('601666.SH', ['601666.SH'], snapshot)[0]
    assert not v.d_basis_eligibility('920392.BJ', ['872392.BJ'], snapshot)[0]
    assert not v.d_basis_eligibility('920392.BJ', ['872392.BJ', '920392.BJ'], snapshot)[0]
    assert not v.d_basis_eligibility('920392.BJ', ['830000.BJ'], snapshot)[0]
    snapshot['symbols']['872392.BJ']['events'] = [event]
    assert v.d_basis_eligibility('920392.BJ', ['872392.BJ', '920392.BJ'], snapshot)[0]
