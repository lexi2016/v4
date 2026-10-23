"""V2 incremental tests only: dates, source states, OOF, oracle and inference gates."""
import copy
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
import model194 as m
import report194 as r


def fixture(n=24):
    dates=[];at=date(2026,1,1)
    while len(dates)<n:
        if at.weekday()<5:dates.append(at.isoformat())
        at+=timedelta(days=1)
    calendar=[];rows=[];truth=[]
    previous="2025-12-31"
    for d in dates:
        calendar.append(dict(target_date=d,signal_date=previous,truth_positive_denominator=2))
        for i in range(60):
            row=dict(target_date=d,signal_date=previous,code=f"SYNTH{i:03}",decision_at=m.decision(d).isoformat(),
                     available_at=m.decision(d).replace(hour=9,minute=0).isoformat(),
                     source_fupan="hit" if i%3==0 else "unknown",source_stage7="confirmed_absent",source_research="unknown")
            row.update({name:int(i%(j+2)==0) for j,name in enumerate(m.TECHNICAL)})
            row["tech_192"]=1
            rows.append(row)
            truth.append(dict(target_date=d,code=row["code"],label=int(i>=58),label_end_at=m.decision(d).replace(hour=15,minute=0).isoformat(),label_available_at=m.decision(d).replace(hour=15,minute=1).isoformat()))
        previous=d
    manifest=dict(schema="V194_DATASET_MANIFEST_V2",mode=m.MODE,historical_availability_bound=False,
                  semantic_ready=True,complete_ten_buy_points=True,synthetic_fixture=True,
                  technical_features=m.TECHNICAL,source_state_columns=m.SOURCES,**m.FLAGS)
    config=dict(technical_features=m.TECHNICAL,top_n=50,seed=194)
    return config,manifest,rows,truth,calendar


class V2Tests(unittest.TestCase):
    def test_mixed_role_truth_join_preserves_unlabelled_candidates(self):
        from run194 import eligible_training_view
        _,_,rows,truth,calendar=fixture()
        for c in calendar:c["cohort_role"]="eligible"
        future=dict(rows[0],target_date="2026-10-23")
        candidates=rows+[future]
        mixed=calendar+[dict(target_date="2026-10-23",cohort_role="unlabelled_prediction",truth_positive_denominator=None)]
        result=eligible_training_view(candidates,truth,mixed)
        self.assertEqual(len(result),len(rows))
        self.assertEqual(candidates[-1],future)
        with self.assertRaisesRegex(ValueError,"MISSING_CANDIDATE_TRUTH"):
            eligible_training_view(candidates,truth,[*calendar,dict(mixed[-1],cohort_role="eligible")])

    def test_unused_unlabelled_denominator_ignored_evaluated_missing_rejected(self):
        _,_,_,truth,calendar=fixture()
        dates=[x["target_date"] for x in calendar[:10]]
        mixed=calendar+[dict(target_date="2026-10-23",truth_positive_denominator=None)]
        self.assertEqual(r.evaluate(dates,[],[],truth,mixed)["fixed_selection_slots"],500)
        mixed[0]=dict(mixed[0],truth_positive_denominator=None)
        with self.assertRaisesRegex(ValueError,"EVALUATED_DENOMINATOR_MISSING"):
            r.evaluate(dates,[],[],truth,mixed)

    def test_v2_mode_does_not_relax_old_certified_gate(self):
        _,manifest,_,_,_=fixture()
        m.validate_manifest(manifest,synthetic=True)
        with self.assertRaisesRegex(ValueError,"V1_CERTIFIED_PIT_REQUIRED"):
            m.validate_manifest(dict(manifest,schema="V1"),synthetic=True)
        with self.assertRaisesRegex(ValueError,"NO_FALSE_PIT_CERTIFICATION"):
            m.validate_manifest(dict(manifest,historical_availability_bound=True),synthetic=True)

    def test_unknown_explicit_mask_and_same_baseline_cohort(self):
        config,_,rows,_,_=fixture()
        row=rows[1];unknown=m.feature_values(row,config,"candidate")
        absent=m.feature_values(dict(row,source_fupan="confirmed_absent"),config,"candidate")
        self.assertNotEqual(unknown,absent)
        self.assertEqual(unknown[11:14],[0.0,0.0,1.0])
        self.assertEqual(m.feature_values(row,config,"baseline"),unknown[:11])
        with self.assertRaisesRegex(ValueError,"SOURCE_STATE_UNKNOWN_FORMAT"):
            m.feature_values(dict(row,source_fupan=None),config,"baseline")

    def test_target_key_decision_and_label_end(self):
        config,manifest,rows,truth,calendar=fixture()
        joined=m.join_truth(rows,truth);m.validate_rows(joined,config,manifest,calendar,synthetic=True)
        changed=copy.deepcopy(joined);changed[0]["decision_at"]=m.decision(changed[0]["signal_date"]).isoformat()
        with self.assertRaisesRegex(ValueError,"DECISION_NOT_TARGET_0925"):
            m.validate_rows(changed,config,manifest,calendar,synthetic=True)
        changed=copy.deepcopy(joined);changed[0]["label_end_at"]=m.decision(changed[0]["target_date"]).isoformat()
        with self.assertRaisesRegex(ValueError,"LABEL_NOT_TARGET_CLOSE"):
            m.validate_rows(changed,config,manifest,calendar,synthetic=True)

    def test_truth_cannot_enter_candidate_view(self):
        _,_,rows,truth,_=fixture();rows[0]["label"]=1
        with self.assertRaisesRegex(ValueError,"TRUTH_IN_FEATURE_VIEW"):m.join_truth(rows,truth)

    def test_expanding_floor_half_and_short_tail(self):
        _,_,_,_,calendar=fixture(23)
        splits=m.make_splits([r["target_date"] for r in calendar])
        self.assertEqual(len(splits[0]["train_target_dates"]),11)
        self.assertEqual([len(s["evaluation_target_dates"]) for s in splits],[5,5,2])
        with self.assertRaisesRegex(ValueError,"MINIMUM_20"):m.make_splits([r["target_date"] for r in calendar[:19]])

    def test_label_available_not_end_controls_purge(self):
        config,_,rows,truth,calendar=fixture();joined=m.join_truth(rows,truth)
        split=m.make_splits([r["target_date"] for r in calendar])[0]
        changed=copy.deepcopy(joined);late=changed[0];late["label_available_at"]=m.decision(split["evaluation_target_dates"][0]).isoformat()
        train,_=m.split_rows(changed,split)
        self.assertNotIn((late["target_date"],late["code"]),[(r["target_date"],r["code"]) for r in train])

    def test_exposed_target_dates_excluded_every_fit_role(self):
        _,_,rows,truth,calendar=fixture();joined=m.join_truth(rows,truth)
        dates=[r["target_date"] for r in calendar]+list(m.EXPOSED)
        self.assertFalse(set(d for s in m.make_splits(dates) for d in s["train_target_dates"]+s["evaluation_target_dates"])&m.EXPOSED)
        split=m.make_splits([r["target_date"] for r in calendar])[0]
        split["train_target_dates"].append("2026-10-16")
        with self.assertRaises(ValueError):m.split_rows(joined,split)

    def test_fixed_slots_empty_day_and_oracle_minimum(self):
        _,_,rows,truth,calendar=fixture()
        dates=[r["target_date"] for r in calendar[:10]]
        result=r.evaluate(dates,[],[],truth,calendar)
        self.assertEqual(result["fixed_selection_slots"],500)
        self.assertEqual(result["candidate"]["actual_selection_slots"],0)
        self.assertEqual(result["truth_positive_denominator"],20)
        self.assertEqual(result["status"],"CANNOT_CONFIRM_INSUFFICIENT_OOF_DATES")

    def test_non_circular_frozen_bootstrap_and_effect_gate(self):
        self.assertEqual(r.moving_block_ci([2.0]*20),[2.0,2.0])
        self.assertEqual(r.moving_block_ci(list(range(20))),r.moving_block_ci(list(range(20))))
        _,_,rows,truth,calendar=fixture()
        dates=[x["target_date"] for x in calendar[:20]]
        b=[dict(target_date=d,code=f"SYNTH{i:03}",score=.5) for d in dates for i in range(50)]
        c=[dict(target_date=d,code=f"SYNTH{i:03}",score=.5) for d in dates for i in range(10,60)]
        result=r.evaluate(dates,b,c,truth,calendar)
        self.assertEqual(result["primary_mean_delta_hits"],2)
        self.assertEqual(result["status"],"EFFECT_GATE_CANDIDATE_DIRECTION_ONLY")

    def test_fold_json_scaler_and_actual_training_prediction_gate(self):
        config,manifest,rows,truth,calendar=fixture();joined=m.join_truth(rows,truth)
        split=m.make_splits([r["target_date"] for r in calendar])[0]
        for row in joined:
            if row["target_date"] in split["evaluation_target_dates"]:row["B1"]=1
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/"fold";before=dict(m.FIT_COUNTS)
            m.run_fold(joined,config,split,folder,synthetic=True)
            model=m.load(folder/"baseline_model.json")
            train,ev=m.split_rows(joined,split)
            self.assertEqual(model["mean"][1],sum(float(x["B1"]) for x in train)/len(train))
            self.assertEqual(m.predict(model,ev,historical_oof=True),m.load(folder/"baseline_predictions.json"))
            with self.assertRaisesRegex(ValueError,"PREDICTION_BEFORE_TRAINING_CUTOFF"):m.predict(model,ev)
            future=dict(ev[0],target_date="2099-01-05",decision_at="2099-01-05T09:25:00+08:00")
            self.assertEqual(len(m.predict(model,[future])),1)
            self.assertEqual(m.FIT_COUNTS["synthetic_fit_returned"]-before["synthetic_fit_returned"],2)
            self.assertEqual(m.FIT_COUNTS["real_fit_entered"],0)


if __name__=="__main__":unittest.main(verbosity=2)
