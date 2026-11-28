"""Same-day HK close review observations and exact D-1 Stage7 references."""
from math import isfinite
import re

from .closure_reads import ARCHIVE_STATE, _compact
from .formal_admission_reads import exact_date
from .seven_p0_reads import SAFETY, STAGES

STAGE7 = "STAGE_1445_1500"
STAGE7_POOL = "a_d1_stage7_fenshi_review_pool"
HK_CLOSE_DATE = "20261127"
HK_CODE = re.compile(r"HK\.[0-9]{5}")
FUTU_MINUTE_GAP = re.compile(
    r"futu 只返回 (?P<available>[0-9]+)/(?P<requested>[0-9]+) 只标的分钟线，缺少："
    r"(?P<codes>HK\.[0-9]{5}(?:,HK\.[0-9]{5})*)"
)


def safe(document):
    return isinstance(document, dict) and all(document.get(key) is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))


def close_identity(review, day):
    rows = review.get("close_top20", [])
    if len(rows) != 20 or any(
        _compact(row.get("trade_date")) != day or not HK_CODE.fullmatch(str(row.get("code")))
        or any(type(row.get(key)) not in (int, float) or not isfinite(row[key])
               for key in ("close", "pre_close", "pct_chg_close"))
        for row in rows
    ):
        return None
    # The isolated recovery serializes percent changes to eight decimal places.
    return [(row["rank"], row["code"], row["close"], row["pre_close"], round(row["pct_chg_close"], 8))
            for row in rows]


def display_stage_gaps(evidence):
    displayed = {}
    details = {}
    for stage, item in evidence.items():
        displayed[stage] = item
        gaps = item.get("cannot_confirm", [])
        compact = []
        for gap in gaps:
            match = FUTU_MINUTE_GAP.fullmatch(gap) if isinstance(gap, str) else None
            if match:
                available, requested = int(match["available"]), int(match["requested"])
                codes = match["codes"].split(",")
                if requested - available == len(codes) == len(set(codes)):
                    compact.append(f"分钟线 {available}/{requested}，缺 {len(codes)} 只")
                    details.setdefault(gap.replace(",", ", "), []).append(stage)
                    continue
            if gap == "HK_STAGE_ORDERBOOK_INCOMPLETE":
                compact.append("盘口缺证")
                details.setdefault(gap, []).append(stage)
                continue
            compact.append(gap)
        if compact != gaps:
            displayed[stage] = {**item, "cannot_confirm": compact, "cannot_confirm_raw": gaps}
    return displayed, [f"{', '.join(stages)}：{gap}" for gap, stages in details.items()]


class StageObservationReads:
    def __init__(self, closure, preselection_proof):
        self.closure = closure
        self.sources = {target: proof["source_signal_date"] for target, proof in preselection_proof.items()}
        self.hk_review = self._load_hk_review()
        self.stage7_sources = {
            source: closure.legacy(source, "stage", STAGE7) for source in set(self.sources.values())
        }

    def _binding(self, day, kind, stage=None):
        entry = self.closure.legacy_manifest.get(day.isoformat(), {}).get(kind, {})
        return entry[stage]["sha256"] if stage else entry["sha256"]

    def _load_hk_review(self):
        envelope = self.closure.legacy(HK_CLOSE_DATE, "review")
        if not envelope:
            return None
        owner = envelope.get("market_reviews", {}).get("HK", {})
        report = owner.get("model_selection_review", {})
        observed = report.get("observed_stage_union") or {}
        if (owner.get("market") != "HK" or _compact(owner.get("trade_date")) != HK_CLOSE_DATE
                or _compact(report.get("trade_date")) != HK_CLOSE_DATE or not safe(owner) or not safe(report)
                or not safe(observed) or observed.get("evidence_status") != "PARTIAL_RESEARCH_ONLY"
                or observed.get("pit_status") != "UNVERIFIED" or observed.get("stage_ids") != list(STAGES)
                or observed.get("expected_stage_count") != len(STAGES)):
            return None
        top = close_identity(report, HK_CLOSE_DATE)
        if top is None or [item[0] for item in top] != list(range(1, 21)):
            return None
        top_codes = {item[1] for item in top}
        stage_rows = report.get("stage_rows", [])
        if report.get("row_counts", {}).get("stage_rows") != len(stage_rows):
            return None
        groups = {}
        for stage in STAGES:
            detail = self.closure.legacy(HK_CLOSE_DATE, "stage", stage)
            if detail is None:
                return None
            source_rows = [row for row in detail.get("unified_rows", []) if row.get("market") == "HK"]
            review_rows = [row for row in stage_rows if row.get("stage_id") == stage]
            source_codes = [row.get("code") for row in source_rows]
            review_codes = [row.get("code") for row in review_rows]
            if (not review_codes or detail.get("selected_hk_rows") != len(source_codes)
                    or source_codes != review_codes or len(set(review_codes)) != len(review_codes)
                    or report.get("stage_input_evidence", {}).get(stage, {}).get("row_count") != len(review_codes)
                    or any((row.get("trade_date") is not None and _compact(row["trade_date"]) != HK_CLOSE_DATE)
                           or not HK_CODE.fullmatch(str(row.get("code"))) for row in source_rows)
                    or any(_compact(row.get("trade_date")) != HK_CLOSE_DATE
                           or row.get("stage_rank") != rank
                           or row.get("hit_top20") is not (row.get("code") in top_codes)
                           for rank, row in enumerate(review_rows, 1))):
                return None
            groups[stage] = review_rows
        selected = {row["code"] for rows in groups.values() for row in rows}
        hits = selected & top_codes
        if (sum(map(len, groups.values())) != len(stage_rows)
                or observed.get("selected_count") != len(selected)
                or set(observed.get("selected_codes", [])) != selected
                or observed.get("hit_count") != len(hits)
                or set(observed.get("hit_codes", [])) != hits):
            return None
        return report

    def review(self, payload, date):
        report = self.hk_review
        native_hk = payload.get("market_reviews", {}).get("HK", {})
        native = native_hk.get("model_selection_review", {})
        if (not report or _compact(date) != HK_CLOSE_DATE or _compact(payload.get("trade_date")) != HK_CLOSE_DATE
                or _compact(native_hk.get("trade_date")) != HK_CLOSE_DATE
                or _compact(native.get("trade_date")) != HK_CLOSE_DATE or not safe(native)
                or native.get("observed_stage_union") is not None
                or close_identity(native, HK_CLOSE_DATE) != close_identity(report, HK_CLOSE_DATE)):
            return payload
        native_top20 = {row["code"] for row in native["close_top20"]}
        model = "0.2_prob_active"
        facts = ("evidence_status", "selected_count", "selected_codes", "hit_count", "hit_codes")
        bound_model = native.get("models", {}).get(model, {})
        owner_model = report.get("models", {}).get(model, {})
        if any(bound_model.get(key) != owner_model.get(key) for key in facts):
            return payload
        attribution = native.get("top20_attribution", [])
        if len(attribution) != 20 or {row.get("code") for row in attribution} != native_top20:
            return payload
        day = exact_date(HK_CLOSE_DATE)
        observed = report["observed_stage_union"]
        hits = set(observed["hit_codes"])
        stage_evidence, gap_details = display_stage_gaps(report["stage_input_evidence"])
        projected = {
            **native,
            "observed_stage_union": {
                **observed, "row_count": len(report["stage_rows"]), "source_date": day.isoformat(),
                "source_scope": ARCHIVE_STATE, "source_sha256": self._binding(day, "review"),
                "formal_eligible": False, "natural_verified": False,
            },
            "observed_stage_rows": report["stage_rows"],
            "stage_input_evidence": stage_evidence,
            "cannot_confirm": [*native.get("cannot_confirm", []), *gap_details],
            "top20_attribution": [
                {**row, "observed_stage_union_hit": row["code"] in hits} for row in attribution
            ],
        }
        return {**payload, "market_reviews": {**payload["market_reviews"], "HK": {
            **native_hk, "model_selection_review": projected,
        }}}

    def preselection(self, payload):
        target = _compact(payload.get("trade_date"))
        expected = self.sources.get(target)
        pool = next((pool for pool in payload.get("pools", []) if pool.get("pool_id") == STAGE7_POOL), {})
        if (not expected or _compact(payload.get("source_signal_date")) != expected
                or pool.get("status") != "CANNOT_CONFIRM" or pool.get("pool_size") != 0):
            return payload
        source = self._prior_observation(target, expected, "A", 0)
        return {**payload, "prior_stage7_observation": source} if source else payload

    def prior_stage7(self, payload, target_date, source_date, stage, market, limit):
        target = _compact(target_date)
        expected = self.sources.get(target)
        if (stage != STAGE7 or payload.get("stage_id") != STAGE7
                or _compact(payload.get("trade_date")) != target
                or not expected or expected >= target
                or (source_date is not None and _compact(source_date) != expected)):
            return payload
        source = self._prior_observation(target, expected, market, limit)
        return {**payload, "prior_stage7_observation": source} if source else payload

    def _prior_observation(self, target, expected, market, limit):
        owner = self.stage7_sources.get(expected)
        if owner is None or owner.get("status") not in {"PARTIAL_WITH_ROWS", "PARTIAL", "READY"}:
            return None
        rows = []
        markets = {}
        for kind, source_count in (("A", "selected_a_rows"), ("HK", "selected_hk_rows")):
            if market is not None and kind != market:
                continue
            selected = [row for row in owner.get("unified_rows", []) if row.get("market") == kind]
            if (len(selected) != owner.get(source_count)
                    or any((row.get("trade_date") is not None and _compact(row["trade_date"]) != expected)
                           or row.get("stage_id") not in (None, STAGE7)
                           or not row.get("code") for row in selected)
                    or len({row["code"] for row in selected}) != len(selected)):
                return None
            markets[kind] = len(selected)
            for rank, row in enumerate(selected, 1):
                change = row.get("current_change_pct")
                rows.append({
                    "market": kind, "rank": rank, "code": row["code"],
                    "name": row.get("display_name") or row.get("name"), "source_date": expected,
                    "current_change_pct": change if type(change) in (float, int) and isfinite(change) else None,
                })
        if not rows:
            return None
        return {
            "schema_version": "v4.r21.prior_stage7_observation.v1",
            "status": "PARTIAL_RESEARCH_ONLY", "source_date": expected, "target_date": target,
            "stage_id": STAGE7, "source_scope": ARCHIVE_STATE,
            "source_sha256": self._binding(exact_date(expected), "stage", STAGE7),
            "source_artifact_id": owner.get("artifact_id"),
            "market_counts": markets, "row_count": len(rows), "rows": rows[:limit] if limit else rows,
            "formal_eligible": False, "natural_verified": False, "execution_verified": False,
            **SAFETY,
        }
