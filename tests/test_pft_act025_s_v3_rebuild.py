"""Synthetic ACT025 regressions; no model fits, real panels or external writes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ops import pft_act025_s_v3_rebuild as study


def evidence(**changes):
    return {"status": "READY", "white": 110., "yellow": 100., "yellow_extension": .4, **changes}


class RouterTests(unittest.TestCase):
    def test_low_s_precedence_threshold_and_missing(self):
        children = [.01, .02, .03, .94]
        low = study.route(np.nextafter(.10, 0), children, evidence(status="MISSING_CONTEXT"))
        self.assertEqual((low["final_state"], low["route_reasons"]), ("REJECTED_FAKE", "PROJECTED_S_LT_010"))
        for root,p in [(.10, children), (.01, [.01,.02,.10,.87]), (None,None), (.01,[.1,.1,.1,.1])]:
            self.assertEqual(study.route(root,p,evidence()), study.prior.route(root,p,evidence()))
        strict = study.route(.01, children, evidence(white=99.))
        self.assertEqual(strict["route_reasons"], "STRICT_OBSERVED_W_BELOW_Y")
        self.assertEqual(study.route(None,None,evidence())["final_state"], "UNKNOWN_BORDERLINE")

    def test_only_valid_projected_low_s_changes_exact_prior_router(self):
        rng = np.random.default_rng(25)
        for _ in range(300):
            root, p = rng.random(), rng.dirichlet(np.ones(4))
            e = evidence(white=float(rng.choice([99,100,110])), yellow_extension=float(rng.random()))
            before, after = study.prior.route(root,p,e), study.route(root,p,e)
            if not before["strict_g1_failure"] and before["projected_p_s"] < .10:
                self.assertEqual(after["route_reasons"], "PROJECTED_S_LT_010")
            else:
                self.assertEqual(after, before)

    def test_external_replays_old_routes_and_preserves_positive_rejection_tradeoff(self):
        rows = []
        for i, cohort in enumerate(["GOLD40"]*40+["ANCHOR20"]*20+["COMMON61"]*33):
            e = evidence()
            result = study.prior.route(.04, [.01,.02,.03,.94], e)
            rows.append({"cohort":cohort,"case_id":str(i),"ts_code":f"{i:06d}.SZ","trade_date":"20261120",
                         "truth_state":"CONFIRMED_S" if i == 0 else "REJECTED_FAKE", "prediction_status":"READY",
                         **{k:e[k] for k in ("white","yellow","yellow_extension")},
                         "baseline_final_state":"UNKNOWN_BORDERLINE", "structure_ch_final_state":"REJECTED_FAKE",
                         **{f"act024_{k}":v for k,v in result.items()}})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"external.csv"
            pd.DataFrame(rows).to_csv(path,index=False)
            with patch.object(study.prior,"checked",side_effect=lambda p,h:p):
                frame, receipt = study.external_review(path)
                self.assertEqual(len(frame),93)
                self.assertEqual(receipt["cleaned_n"],92)
                metric = receipt["ACT025"]["ALL"]["arms"]["act025"]
                self.assertEqual(metric["false_reject_n"],1)
                self.assertEqual(metric["false_accept_n"],0)
                self.assertEqual(metric["confirmed_s_recall"],0)
                rows[0]["act024_route_reasons"] = "CORRUPTED"
                pd.DataFrame(rows).to_csv(path,index=False)
                with self.assertRaisesRegex(study.ContractError,"ACT024_ROUTER_REPLAY"):
                    study.external_review(path)


class CandidateTests(unittest.TestCase):
    def test_security_exclusions_and_deterministic_fallback_index(self):
        rows = [dict(ts_code=c,trade_date=d,tactic="rebuild",split=s,security_group=s,feature_ready="True")
                for c,d,s in [("000001.SZ","20260901","validation"),("000002.SZ","20260902","validation"),
                              ("000003.SZ","20260903","validation"),("000004.SZ","20250202","train"),
                              ("000004.SZ","20250101","train")]]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pd.DataFrame(rows).to_csv(root/"labels.csv",index=False)
            pd.DataFrame({"ts_code":["000001.SZ"]}).to_csv(root/"excluded.csv",index=False)
            pd.DataFrame({"ts_code":["000002.SZ"]}).to_csv(root/"train.csv",index=False)
            with patch.object(study,"LABEL_COUNT",len(rows)):
                targets, receipt = study.candidate_index(root/"labels.csv",root/"train.csv",root/"excluded.csv")
            self.assertEqual(list(targets.ts_code),["000003.SZ","000004.SZ"])
            self.assertEqual(list(targets.trade_date),["20260903","20250101"])
            self.assertEqual(receipt["training_overlap_n"],0)

    def test_sampling_preserves_quotas_unique_codes_and_rejects_strong_fake(self):
        rows = []
        for i in range(30):
            rows.append({"ts_code":f"{i:06d}.SZ", "trade_date":"20261120", "prediction_status":"READY",
                         "pool":"primary", "projected_p_s":.8,"raw_p_rebuild":.7-i*.001,
                         "raw_p_pullback":.1,"raw_p_readvance":.1,
                         "final_state":"CONFIRMED_S" if i<15 else "UNKNOWN_BORDERLINE",
                         "main_tactic":"rebuild" if i<15 else "", "route_reasons":"EXTENSION"})
        rows.append({**rows[0],"ts_code":"999999.SZ","raw_p_rebuild":.99,"route_reasons":"STRONG_BINARY_FAKE_HEAD_CONTRADICTION"})
        rows.append({**rows[1],"trade_date":"20261119"})
        chosen, receipt = study.select_candidates(pd.DataFrame(rows))
        shuffled, _ = study.select_candidates(pd.DataFrame(rows).sample(frac=1,random_state=2))
        self.assertEqual(chosen.to_dict("records"),shuffled.to_dict("records"))
        self.assertEqual(receipt["actual_strata"],{"high":10,"boundary":10})
        self.assertEqual(chosen.ts_code.nunique(),20)
        self.assertNotIn("999999.SZ",set(chosen.ts_code))
        _, short = study.select_candidates(pd.DataFrame(rows[:2]))
        self.assertEqual(short["status"],"FAIL_INSUFFICIENT_ELIGIBLE_REBUILD")

    def test_each_feature_prefix_is_bounded_before_extract(self):
        raw = pd.DataFrame({"ts_code":["000001.SZ"]*4,"trade_date":["20240101","20250101","20251120","20261120"]})
        targets = pd.DataFrame({"ts_code":["000001.SZ"]*2,"trade_date":["20251120","20261120"]})
        seen = []
        def extract(frame, day, codes):
            seen.append((day,list(frame.trade_date)))
            return np.zeros((1,43)),[evidence()]
        with patch.object(study.prior,"extract_structure",side_effect=extract), \
             patch.object(study.prior,"batch_predict",return_value={0:(.8,[.1,.1,.7,.1])}):
            study.score_targets(raw, targets, {})
        self.assertEqual(seen,[("20251120",["20250101","20251120"]),("20261120",["20251120","20261120"])])

    def test_public_csv_payload_has_no_scores_labels_outcomes(self):
        frame = pd.DataFrame({"trade_date":pd.date_range(end="2026-11-20",periods=60).strftime("%Y%m%d"),
                              **{k:[v]*60 for k,v in dict(open=100.,high=110.,low=90.,close=100.,vol=1.,zge_white_line=95.,zge_yellow_line=90.).items()}})
        frame["vol"] = list(range(1,61))
        e = evidence(white=95.,yellow=90.,volume_compression=.5,range_compression=.6,
                     anchors={"events":[],"old_close_failure_survives_new_anchor":False})
        result = study.public_sequence({"frame":frame,"evidence":e})
        self.assertEqual(set(result),{"bars","anchors","guards"})
        self.assertEqual(len(result["bars"]),60)
        self.assertEqual(result["bars"][0]["close"],1.)
        self.assertEqual(result["bars"][0]["volume_rel_first5"],1/3)
        self.assertEqual(result["bars"][-1]["volume_rel_first5"],20.)
        self.assertEqual(result["guards"]["volume_compression"],.5)
        self.assertEqual(result["guards"]["range_compression"],.6)
        missing = study.public_sequence({"frame":frame,"evidence":evidence(white=95.,yellow=90.)})
        self.assertNotIn("volume_compression", missing["guards"])
        self.assertNotIn("range_compression", missing["guards"])
        self.assertNotRegex(json.dumps(result),r"probability|truth|tactic|future|return|outcome|label")
        with self.assertRaisesRegex(study.ContractError,"60_VALID"):
            study.public_sequence({"frame":frame.tail(59),"evidence":e})


class RankTests(unittest.TestCase):
    def test_optional_rank_never_substitutes_d20_and_requires_full_identity(self):
        rank, receipt = study.load_rank(None)
        self.assertIsNone(rank)
        self.assertEqual(receipt["status"],"NOT_LANDED")
        rows = [{"source_rank":i+1,"ts_code":f"{i:06d}.SZ"} for i in range(200)]
        data = {"rank_date":"20261123","source_ref":"official-source","ranking_sha256":"a"*64,"rows":rows}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"rank.json"
            path.write_text(json.dumps(data))
            self.assertEqual(len(study.load_rank(path)[0]),200)
            for change in ({"rank_date":"20261120"},{"rows":rows[:199]},{"rows":[rows[0]]*200}):
                path.write_text(json.dumps({**data,**change}))
                with self.assertRaises(study.ContractError):
                    study.load_rank(path)


if __name__ == "__main__":
    unittest.main()
