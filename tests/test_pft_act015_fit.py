import numpy as np
import pandas as pd
import pytest
from ops.pft_act015_common import FOLDS, NUMERIC, bucket
from ops.pft_act015_fit import training_mask, capped, merge_cap, s_oof, infer_frame, FitArchive, read_fit_ledger


class Constant:
    classes_ = np.array([0, 1])
    def predict_proba(self, x):
        return np.tile([.2, .8], (len(x), 1))
    def predict(self, x):
        return np.ones(len(x))


class ArchiveSpy(Constant):
    fit_calls = 0
    def fit(self, x, y):
        type(self).fit_calls += 1
        self.feature_names_in_ = np.asarray(x.columns)
        return self
    def set_params(self, **kwargs):
        self.parameters = kwargs
        return self


def rows():
    f = pd.DataFrame({'canonical_security_id': [f'{i:06d}.SZ' for i in range(12)],
        'D': ['20221220']*12, 'eligible': True, 'lane': 'B1', 'label': [0., 1.]*6,
        'rank_status': 'VALID', 'target_end': '20221227', 'rank_target': 1., 'gate': 1.,
        'raw_trigger': True, 'near_trigger': False, 'stratum': 'UNKNOWN', 'reason': 'UNKNOWN',
        'formula_mismatch': False, 'prior_anchor_date': '', 'prior_anchor_low': np.nan})
    f['outer'] = f.canonical_security_id.map(bucket)
    f['inner'] = f.canonical_security_id.map(lambda c: bucket(c, 'INNER'))
    f['episode_id'] = f.index.astype(str)
    return pd.concat([f, pd.DataFrame(0., index=f.index, columns=NUMERIC)], axis=1)


def test_rank_maturity_purges_cross_fold_target_and_never_2026_fit():
    f = rows(); held = 1 - int(f.iloc[0].outer)
    f.loc[0, 'target_end'] = '20230103'
    assert not training_mask(f, 2023, held, maturity=True).iloc[0]
    f.loc[0, 'target_end'] = '20221231'
    assert training_mask(f, 2023, held, maturity=True).iloc[0]
    f.loc[0, ['D', 'target_end']] = ['20260105', '20260112']
    assert not any(training_mask(f, year, held, maturity=True).iloc[0] for year in FOLDS)


def test_streaming_sampling_is_order_independent_and_balanced():
    f = rows()
    one = capped(f, 2, 'B_B1', 'label')
    a = merge_cap(None, f.iloc[:6], 2, 'B_B1', 'label')
    a = merge_cap(a, f.iloc[6:], 2, 'B_B1', 'label')
    assert one.episode_id.tolist() == a.episode_id.tolist()
    assert one.groupby('label').size().tolist() == [2, 2]


def test_oof_score_uses_exact_held_inner_and_gate():
    class Held(Constant):
        def __init__(self, expected): self.expected = expected
        def predict_proba(self, x):
            assert set(x.index) <= set(f.index[f.inner.eq(self.expected)])
            return super().predict_proba(x)
    f = rows(); f.loc[0, 'gate'] = 0.
    scores = s_oof(f, {i: Held(i) for i in range(3)})
    assert scores[0] == 0 and (scores[1:] == .8).all()


def test_oos_joins_exact_model_year_and_outer_and_keeps_unknown_truth():
    f = rows(); f.D = '20230103'; f.label = np.nan
    f.loc[0, 'D'] = '20240103'; f.loc[1, 'eligible'] = False
    models = {(lane, role): Constant() for lane in ['B1', 'B2', 'B3'] for role in ['B', 'R']}
    both = pd.concat([infer_frame(f, 2023, held, Constant(), models) for held in [0, 1]])
    assert set(both.episode_id) == set(f.episode_id) - {'0'}
    assert both.label.isna().all()
    assert both.model_year.eq(2023).all()
    assert both.outer.eq(both.held_outer).all()
    assert not both.loc[both.episode_id.eq('1'), 'hard_eligible'].iloc[0]
    assert not any(c.startswith('rank_target') or c == 'target_end' for c in both)


def test_ranker_role_is_regression_and_exact_resume_never_refits(tmp_path):
    # File-only spy; no actual sklearn model fitting.
    f = rows(); held = 1-int(f.iloc[0].outer)
    f = f.loc[f.outer.ne(held)].reset_index(drop=True)
    f['rank_target'] = np.arange(len(f))+.123
    ledger, outputs = [], {}
    ArchiveSpy.fit_calls = 0
    a = FitArchive(tmp_path, 2023, held, ledger, outputs)
    a.fit(ArchiveSpy(), f, f[['ret1_pct']], 'rank_target', 'B1_RANK_H5')
    assert ArchiveSpy.fit_calls == 1 and len(ledger) == 1
    on_disk = read_fit_ledger(tmp_path/'fit_ledger.json')
    assert on_disk == ledger
    assert ledger[0]['fit_n_jobs'] == -1 and ledger[0]['inference_n_jobs'] == 1
    resumed = FitArchive(tmp_path, 2023, held, ledger, {})
    resumed.fit(ArchiveSpy(), f, f[['ret1_pct']], 'rank_target', 'B1_RANK_H5')
    assert ArchiveSpy.fit_calls == 1 and len(ledger) == 1
    changed = f.copy(); changed.loc[0, 'ret1_pct'] = .1
    with pytest.raises(ValueError, match='RESUME_EXACT_TRAINING_IDENTITY_MISMATCH'):
        resumed.fit(ArchiveSpy(), changed, changed[['ret1_pct']], 'rank_target', 'B1_RANK_H5')
    changed = f.copy(); changed.loc[0, 'rank_target'] = .1
    with pytest.raises(ValueError, match='RESUME_EXACT_TRAINING_IDENTITY_MISMATCH'):
        resumed.fit(ArchiveSpy(), changed, changed[['ret1_pct']], 'rank_target', 'B1_RANK_H5')


def test_resume_loader_rejects_object_shape_and_symlink(tmp_path):
    path = tmp_path/'ledger.json'; path.write_text('{}')
    with pytest.raises(ValueError, match='LIST_OF_OBJECTS'):
        read_fit_ledger(path)
    path.write_text('[{"fit_call":1,"status":"ARCHIVED_RELOAD_PASS"}]')
    assert read_fit_ledger(path)[0]['fit_call'] == 1
    link = tmp_path/'link.json'; link.symlink_to(path)
    with pytest.raises(ValueError, match='UNSAFE_FIT_LEDGER_PATH'):
        read_fit_ledger(link)
