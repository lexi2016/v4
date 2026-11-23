"""Focused synthetic ACT028 tests; no real evaluation, model or panel reads."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ops import pft_act028_rebuild_maturity as study


def evidence(**kwargs):
    return {"status":"READY", "white":110., "yellow":100., "yellow_extension":.10, **kwargs}


def baseline(root=.9, children=None, **kwargs):
    return study.act025.route(root, children if children is not None else [.01,.02,.96,.01], evidence(**kwargs))


class MaturityTests(unittest.TestCase):
    def test_anchor_zero_three_four_and_missing(self):
        sessions = study.ExchangeSessions()
        before = baseline()
        for anchor, age, changed in (("20261120",0,True),("20261117",3,True),("20261116",4,False),(None,None,True)):
            actual = study.maturity(before,anchor,"20261120",sessions)
            self.assertEqual(actual["repair_age_sessions"],age)
            self.assertEqual(actual["maturity_guard_applied"],changed)
            self.assertEqual(actual["final_state"],"UNKNOWN_BORDERLINE" if changed else "CONFIRMED_S")
            self.assertEqual(actual["main_tactic"],"" if changed else "rebuild")
            self.assertEqual(study.REASON in actual["route_reasons"],changed)
            for key in before:
                if key not in {"final_state","main_tactic","route_reasons","final_decision_contradiction"}:
                    self.assertEqual(actual[key],before[key])
        self.assertEqual(study.maturity(before,None,"20261120",sessions)["repair_age_status"],"MISSING_REPAIR_ANCHOR")

    def test_exchange_holidays_weekends_and_unsupported_year_no_business_day_fallback(self):
        sessions = study.ExchangeSessions()
        # National Day closure is removed by the authoritative schedule.
        self.assertEqual(sessions.age("20260930","20261012"),(3,"CANONICAL_2026_EXCHANGE_SESSIONS"))
        self.assertEqual(sessions.age("20261113","20261119")[0],4)
        self.assertEqual(sessions.age("20250630","20250707"),(None,"MISSING_EXCHANGE_CALENDAR"))
        self.assertIsNone(sessions.age("20261121","20261123")[0])
        self.assertIsNone(sessions.age("20261123","20261120")[0])

    def test_historical_exact_calendar_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"sessions.csv"
            records = [{"session_date":d,"source_ref":"V4:reader","source_sha256":"a"*64,
                        "coverage_start":"20250630","coverage_end":"20250707"}
                       for d in ("20250630","20250701","20250702","20250703","20250704","20250707")]
            pd.DataFrame(records).to_csv(path,index=False)
            sessions = study.ExchangeSessions(path)
            self.assertEqual(sessions.age("20250630","20250707")[0],5)
            self.assertEqual(sessions.age("20250701","20250707")[0],4)
            self.assertEqual(sessions.age("20250627","20250707")[1],"MISSING_EXCHANGE_CALENDAR")
            records[0]["source_sha256"] = "bad"
            pd.DataFrame(records).to_csv(path,index=False)
            with self.assertRaises(study.ContractError):
                study.ExchangeSessions(path)

    def test_prior_guards_and_nonrebuild_are_exactly_unchanged(self):
        class NeverRead:
            def age(self,*args):
                raise AssertionError("nonapplicable calendar lookup")
        cases = [baseline(white=99), baseline(.01,[.01,.02,.03,.94]),
                 baseline(yellow_extension=.36), baseline(None,[.01,.02,.96,.01]),
                 baseline(.9,[.96,.01,.02,.01]), baseline(.9,[.01,.96,.02,.01])]
        for before in cases:
            after = study.maturity(before,None,"20261120",NeverRead())
            self.assertEqual({k:after[k] for k in before},before)
            self.assertFalse(after["maturity_guard_applied"])

    def test_replay_checks_public_tactic_raw_projection_and_state(self):
        before = baseline()
        row = {"ts_code":"000001.SZ","case_id":"case","prediction_status":"READY",
               **{k:v for k,v in evidence().items() if k != "status"},
               **before,"act025_state":"CONFIRMED_S","act025_primary_tactic":"S_REBUILD"}
        self.assertEqual(study.replay(row,"","act025_state","act025_primary_tactic","route_reasons"),before)
        for key,value in (("act025_state","UNKNOWN_BORDERLINE"),("projected_p_s",.5)):
            with self.assertRaises(study.ContractError):
                study.replay({**row,key:value},"","act025_state","act025_primary_tactic","route_reasons")


class TopAndMetricTests(unittest.TestCase):
    def fixture(self):
        groups, records = [], []
        for day in study.prior.DAYS:
            ranks = [{"source_rank":i,"ts_code":f"{i:06d}.SZ"} for i in range(1,201)]
            g = {"decision_date":day,"source_date":day,"observation_date":day,"source_generation":"gen"+day,
                 "panel_generation":"panel"+day,"panel_sha256":"a"*64,"ranking_sha256":"b"*64,
                 "price_basis":"qfq","rows":ranks}
            groups.append(g)
            for rank in ranks:
                good = day == "20261120" and rank["source_rank"] == 1
                e = evidence()
                route = study.prior.route(.9 if good else .01,[.01,.02,.96,.01] if good else [.01,.02,.03,.94],e)
                records.append({**{k:v for k,v in g.items() if k not in {"rows","decision_date"}},
                    **rank,"trade_date":day,"prediction_status":"READY", "white":110.,"yellow":100.,"yellow_extension":.1,
                    **{"act024_"+k:v for k,v in route.items()}})
        return groups,pd.DataFrame(records)

    def test_1000_identity_rejects_changed_rank_or_generation(self):
        groups, frame = self.fixture()
        study.validate_top200(frame.astype(str),groups)
        for key,value in (("source_rank","2"),("source_generation","wrong")):
            changed = frame.astype(str)
            changed.loc[0,key] = value
            with self.assertRaises(study.ContractError):
                study.validate_top200(changed,groups)

    def test_only_confirmed_rebuild_subset_reader_latest_repair_and_missing_evidence(self):
        groups,frame = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"top.csv"
            frame.to_csv(path,index=False)
            e = {**evidence(), "anchors":{"events":[{"role":"repair","date":"20261110"},
                  {"role":"management","date":"20261116"},{"role":"repair","date":"20261117"}]}}
            with patch.object(study.review,"load_groups",return_value=(groups,{})), \
                 patch.object(study.review,"bind_panel",return_value=(Path("synthetic"),{"status":"BOUND"})), \
                 patch.object(study.review,"read_group",return_value=pd.DataFrame()) as reader, \
                 patch.object(study.prior,"extract_structure",return_value=(np.empty((1,43)),[e])) as extract:
                out,summary = study.top200(path,Path("groups"),study.ExchangeSessions())
                self.assertEqual(reader.call_count,1)
                self.assertEqual(reader.call_args.args[1]["rows"],[{"ts_code":"000001.SZ","source_rank":1}])
                self.assertEqual(extract.call_args.args[2],["000001.SZ"])
                affected = out.loc[out.act028_maturity_guard_applied].iloc[0]
                self.assertEqual(affected.act028_repair_anchor_date,"20261117")
                self.assertEqual(affected.act028_repair_age_sessions,3)
                self.assertEqual(len(out),1000)
                self.assertEqual(out.act025_final_state.eq("REJECTED_FAKE").sum(),999)
            with patch.object(study.review,"load_groups",return_value=(groups,{})), \
                 patch.object(study.review,"bind_panel",return_value=(None,{"status":"CANNOT_CONFIRM"})):
                out,_ = study.top200(path,Path("groups"),study.ExchangeSessions())
                self.assertEqual(out.act028_final_state.eq("UNKNOWN_BORDERLINE").sum(),1)
                self.assertEqual(len(out),1000)

    def test_strict_precision_counts_truth_boundary_and_retention_denominator(self):
        rows = [{"cohort":"REBUILD20","truth_state":"CONFIRMED_S","act025_final_state":"CONFIRMED_S",
                 "act028_final_state":"CONFIRMED_S"} for _ in range(4)]
        rows += [{"cohort":"REBUILD20","truth_state":"UNKNOWN_BORDERLINE","act025_final_state":"CONFIRMED_S",
                  "act028_final_state":"UNKNOWN_BORDERLINE"},
                 {"cohort":"REBUILD20","truth_state":"REJECTED_FAKE","act025_final_state":"CONFIRMED_S",
                  "act028_final_state":"CONFIRMED_S"}]
        report = study.metrics(pd.DataFrame(rows))
        self.assertEqual(report["ALL"]["act025"]["strict_confirmation_precision"],4/6)
        self.assertEqual(report["ALL"]["act028"]["strict_confirmation_precision"],4/5)
        self.assertEqual(report["ALL"]["act028"]["truth_boundary_retained_n"],1)
        self.assertEqual(report["ALL"]["act028"]["known_negative_false_positive_n"],1)
        self.assertEqual(report["rebuild20_prior_true_positive_retention"]["denominator"],4)


if __name__ == "__main__":
    unittest.main()
