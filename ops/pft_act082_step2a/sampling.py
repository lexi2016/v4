"""Preregistered stock-stratified probability and follow-up coverage draws."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
from random import Random
from uuid import uuid4

SEED = 20261128
FORMAL_QUOTAS = {"D": 120, "A": 40, "B": 40, "C": 40}
PILOT_QUOTAS = dict.fromkeys(FORMAL_QUOTAS, 5)
B2_INITIAL = "B2_INITIAL_PROPOSAL"
B3_SHRINK = "B3_SMALL_POSITIVE_SHRINK_PROPOSAL"
B3_EXPAND = "B3_SMALL_POSITIVE_EXPANSION_PROPOSAL"
B_COVERAGE = {
    "formal": {B2_INITIAL: 20, B3_SHRINK: 10, B3_EXPAND: 10},
    "pilot": {B2_INITIAL: 3, B3_SHRINK: 1, B3_EXPAND: 1},
}
STOCK_CAP = 8
BATCH_SIZE = 30
AUDITS_PER_BATCH = 3
RELABEL_COUNT = 40


@dataclass(frozen=True, slots=True)
class Candidate:
    security_id: str
    wave_group_id: str
    D: str
    mother_start_date: str
    root_dates: tuple[str, ...] = ()
    source_rule: str = ""


def group_frame(eligible):
    """Keep the first causal representative for each group and bucket."""
    frame = defaultdict(dict)
    for candidate, buckets in sorted(eligible, key=lambda pair: (
        pair[0].security_id, pair[0].D, pair[0].wave_group_id, pair[0].source_rule,
    )):
        group = frame[candidate.wave_group_id]
        prior = group.setdefault("D", candidate)
        if prior.security_id != candidate.security_id or prior.mother_start_date != candidate.mother_start_date:
            raise ValueError("a wave group changed identity")
        if set(buckets) - ({"A", "C"} | set(B_COVERAGE["formal"])):
            raise ValueError("unexpected sampling screen")
        for bucket in buckets:
            group.setdefault(bucket, candidate)
    return dict(frame)


def _allocate(frame, total, remaining):
    quotas = Counter()
    active = sorted(frame)
    while sum(quotas.values()) < total:
        feasible = [key for key in active if quotas[key] < min(len(frame[key]), remaining[key])]
        if not feasible:
            raise ValueError("frozen bucket quota infeasible without replacement")
        for key in feasible:
            quotas[key] += 1
            if sum(quotas.values()) == total:
                break
    return quotas


def _draw(frame, bucket, screen, count, used, used_by_stock, rng, phase):
    by_stock = defaultdict(list)
    for wave_id, reps in sorted(frame.items()):
        if wave_id not in used and screen in reps:
            by_stock[reps[screen].security_id].append(reps[screen])
    cap = {stock: STOCK_CAP - used_by_stock[stock] if phase == "formal" else count for stock in by_stock}
    quotas = _allocate(by_stock, count, cap)
    rows = []
    strata = []
    for stock, items in sorted(by_stock.items()):
        q, n = quotas[stock], len(items)
        probability = Fraction(q, n)
        pi_type = "MARGINAL_D_DESIGN" if bucket == "D" and phase == "formal" else "CONDITIONAL_COVERAGE_DESIGN"
        stratum = {
            "phase": phase, "bucket": bucket, "security_id": stock,
            "coverage_subtype": screen if bucket == "B" else "",
            "stratum_population": n, "stratum_quota": q, "stratum_probability": str(probability),
            "probability_type": pi_type,
        }
        strata.append(stratum)
        for pick in rng.sample(items, q):
            used.add(pick.wave_group_id)
            if phase == "formal":
                used_by_stock[stock] += 1
            rows.append((pick, stratum))
    return rows, strata


def sample_frame(frame, *, seed=SEED):
    rng = Random(seed)
    used = set()
    formal_by_stock = Counter()
    strata = []
    selected_by_phase = {}
    for phase, quotas in (("formal", FORMAL_QUOTAS), ("pilot", PILOT_QUOTAS)):
        selected = []
        for bucket, count in quotas.items():
            screens = B_COVERAGE[phase] if bucket == "B" else {bucket: count}
            if sum(screens.values()) != count:
                raise ValueError("coverage subquota totals disagree with frozen parent quota")
            for screen, subquota in screens.items():
                rows, stats = _draw(frame, bucket, screen, subquota, used, formal_by_stock, rng, phase)
                selected.extend(rows)
                strata.extend(stats)
        rng.shuffle(selected)
        selected_by_phase[phase] = selected

    formal = selected_by_phase["formal"]
    audits = set()
    for offset in range(0, len(formal), BATCH_SIZE):
        audits.update(rng.sample(range(offset, offset + BATCH_SIZE), AUDITS_PER_BATCH))
    relabel = rng.sample(range(len(formal)), RELABEL_COUNT)
    rng.shuffle(relabel)

    return {
        "selected": selected_by_phase, "strata": strata,
        "audit_indices": frozenset(audits), "relabel_indices": tuple(relabel),
        "probability_design": (
            "D stock-stratified SRSWOR with quotas fixed from stratum availability, exact q/N. "
            "A/B/C and pilot report conditional q/N given earlier selections and remaining caps. "
            "B screens have fixed chronological sampling order B2 initial, small positive B3 shrink, B3 expansion. "
            "Never pool D and coverage positive rates. Equity-level clustering is required for future CIs."
        ),
    }


def private_rows(draw):
    rows = []
    for phase in ("formal", "pilot"):
        for index, (candidate, stratum) in enumerate(draw["selected"][phase]):
            rows.append({
                **stratum,
                "wave_group_id": candidate.wave_group_id, "D": candidate.D,
                "mother_start_date": candidate.mother_start_date, "selection_rule": candidate.source_rule,
                "blind_id": str(uuid4()), "batch": index // BATCH_SIZE + 1,
                "review_order": index + 1,
                "agreement_audit_preregistered": phase == "formal" and index in draw["audit_indices"],
            })
    relabel = [{
        "first_blind_id": rows[index]["blind_id"], "relabel_blind_id": str(uuid4()), "review_order": rank + 1,
    } for rank, index in enumerate(draw["relabel_indices"])]
    return rows, relabel

