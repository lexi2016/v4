"""Bind the coordinator to pinned V4 bytes and the original, resumable R2 rule."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
import csv
import io
import json
import math
from pathlib import Path
from statistics import mean

from .drive_store import sha256_bytes
from .r2_resume import ORIGINAL_SOURCE_SHA256, R2AnchorGrant, R2Session
from .source_seams import verify_reader_projection, verify_top200

_PRICE = ("open", "high", "low", "close")
_BAR = (*_PRICE, "volume")
_MATURE = frozenset(("SUCCESS_RESTART", "FAILED_SUPPORT", "FAILED_RISK", "EXPIRED_PULLBACK"))


class MatrixBindingError(ValueError):
    """Input feature bytes differ from the frozen mapping of the pinned rows."""


@dataclass(frozen=True)
class AnchorEvidence:
    """Externally pinned grant and optional already committed R2 checkpoint."""

    receipt: bytes
    grant: R2AnchorGrant
    checkpoint: bytes | None = None
    checkpoint_sha256: str | None = None
    proven_reset: bool = False


def _valid(bar):
    if not bar or any(bar.get(key) is None for key in _BAR):
        return False
    o, h, low, c, v = (bar[key] for key in _BAR)
    return min(o, h, low, c, v) > 0 and low <= min(o, c) <= max(o, c) <= h


def _r2_features(observation, history, sessions, pullbacks):
    """The frozen 20-column D16 mapping, applied only to a verified D-only window."""
    ix = {day: i for i, day in enumerate(sessions)}
    D = observation["candidate_date"]
    current = ix[D]
    wave = observation["wave_start"]
    k1 = observation["wave_end_confirmed_at"]
    origin = observation["origin_key_k_date"]
    win = sessions[ix[wave]:ix[k1]]
    expanded = sessions[ix[wave]:current]
    warm = sessions[max(0, current - 23):current + 1]
    ks = sessions[ix[k1]:current + 1]
    required = set(win + expanded + warm + ks) | {origin, observation["wave_end"]}
    if len(ks) != 3 or len(warm) != 24 or not win or any(not _valid(history.get(d)) for d in required):
        return None
    ordinal = observation["pullback_index"]
    hi, low = observation["frozen_wave_high"], observation["origin_low"]
    mature = [r for r in pullbacks if r["family_id"] == observation["family_id"]
              and r["pullback_index"] < ordinal and r["outcome"] in _MATURE
              and r["end_date"] is not None and r["end_date"] < D]
    last = max((r["end_date"] for r in mature if r["outcome"] == "SUCCESS_RESTART"), default="")
    if (len(mature) != observation["trajectory_prior_pullback_count"] or len(mature) != ordinal - 1
            or wave != (last or origin) or hi != max(history[d]["high"] for d in win)
            or low != history[origin]["low"]):
        return None
    fixed = mean(history[d]["volume"] for d in win)
    extended = mean(history[d]["volume"] for d in expanded)
    close = [history[d]["close"] for d in warm]
    bbi = mean(mean(close[-n:]) for n in (3, 6, 12, 24))
    features = [int(ordinal > 1), ordinal, current - ix[origin] + 1]
    for column in ("close", "low"):
        features.extend((history[d][column] - hi) / hi for d in ks)
    features.extend(history[d]["volume"] / fixed for d in ks)
    features.extend((history[D]["volume"] / extended, len(win), (close[-1] - low) / low,
                     int(close[-1] >= bbi), int(close[-1] >= mean(close[-5:])),
                     len(mature), current - ix[last] if last else 0, int(not last)))
    return tuple(features)


class BoundV4Inputs:
    """One D only. The operator must obtain the expected metadata from verified assets.

    The same exact projection feeds the R2 state and guards the matrix. This
    object does not fetch market data, verify a self-asserted clock, or widen
    authorized scope. Incompatible generation/factor histories fail closed.
    """

    def __init__(self, *, metadata, projection_sessions, r2_calendar, anchors,
                 source_observed_at, instruments, anchor_catalog_bytes=None,
                 calendar_bytes=None, feature_map_bytes=None):
        self.metadata = dict(metadata)
        self.projection_sessions = tuple(projection_sessions)
        self.r2_calendar = tuple(r2_calendar)
        self.anchors = dict(anchors)
        self.instruments = dict(instruments)
        self.anchor_catalog_bytes = anchor_catalog_bytes
        self.calendar_bytes = calendar_bytes
        self.feature_map_bytes = feature_map_bytes
        if not isinstance(source_observed_at, datetime) or source_observed_at.tzinfo is None:
            raise ValueError("V4_SOURCE_OBSERVATION_TIME_REQUIRED")
        self.source_observed_at = source_observed_at
        if (list(self.r2_calendar) != sorted(set(self.r2_calendar))
                or not self.projection_sessions
                or self.projection_sessions[0] not in self.r2_calendar):
            raise ValueError("R2_CALENDAR_ORDER_OR_SCOPE")
        start = self.r2_calendar.index(self.projection_sessions[0])
        if self.r2_calendar[start:start + len(self.projection_sessions)] != self.projection_sessions:
            raise ValueError("R2_CALENDAR_PROJECTION_DISCONTINUITY")

    def _read(self, daily):
        D = date.fromisoformat(daily.D).strftime("%Y%m%d")
        roster = verify_top200(daily.top200_body, D, self.metadata)
        proof = verify_reader_projection(daily.reader_evidence, D, self.metadata, roster,
                                         self.projection_sessions)
        bodies = {r["symbol"]: r for r in json.loads(daily.top200_body)["top200"]}
        bars = {code: {} for _, code in roster}
        for row in json.loads(daily.reader_evidence)["rows"]:
            bars[row["ts_code"]][row["trade_date"]] = row
        return roster, proof, bodies, bars

    def source_proof(self, daily, matrix_sha, keys_sha, row_projection_sha):
        from .coordinator import SourceProof, _canonical_json, _source_proof_payload

        roster, proof, published, bars = self._read(daily)
        D = date.fromisoformat(daily.D).strftime("%Y%m%d")
        basis_conflicts = []
        for row in daily.rows:
            code = row.ts_code
            source_bar = bars[code].get(D)
            values = tuple(source_bar[key] for key in _BAR) if source_bar else None
            if row.bar_values != values:
                raise ValueError("COORDINATOR_D_BAR_DIFFERS_FROM_READER")
            bar_date = date.fromisoformat(D).isoformat() if source_bar is not None else None
            if row.bar_trade_date != bar_date:
                raise ValueError("COORDINATOR_D_BAR_DATE_DIFFERS_FROM_READER")
            if (row.market, row.instrument_type) != self.instruments.get(code):
                raise ValueError("COORDINATOR_INSTRUMENT_IDENTITY_UNBOUND")
            if _valid(source_bar) and (any(type(published[code].get(key)) not in (int, float)
                                             or not math.isfinite(published[code][key])
                                             for key in _PRICE)
                                       or any(abs(source_bar[key] - published[code][key]) > 0.011
                                              for key in _PRICE)):
                basis_conflicts.append(code)
        result = SourceProof(
            D=D, top200_body_sha256=self.metadata["top200_raw_sha256"],
            source_generation=self.metadata["generation"],
            generation_manifest_sha256=self.metadata["panel_manifest_sha256"],
            source_input_sha256=self.metadata["input_sha256"],
            top200_roster=tuple((rank, code, date.fromisoformat(D).isoformat()) for rank, code in roster),
            reader_query_start=date.fromisoformat(self.projection_sessions[0]).isoformat(),
            reader_query_end=date.fromisoformat(D).isoformat(),
            reader_max_trade_date=(date.fromisoformat(proof["max_trade_date"]).isoformat()
                                   if proof["max_trade_date"] else None),
            reader_manifest_sha256=self.metadata["panel_manifest_sha256"],
            reader_evidence_sha256=self.metadata["reader_projection_sha256"],
            reader_projection_sha256=row_projection_sha,
            canonical_matrix_sha256=matrix_sha, canonical_keys_sha256=keys_sha,
            reader_code_sha256=self.metadata["reader_sha256"],
            top200_code_sha256=self.metadata["top200_code_sha256"],
            source_observed_at=self.source_observed_at, price_basis="QFQ_ASOF",
            volume_basis="QFQ_EVENT_VOLUME", proof_sha256="",
            qfq_basis_conflicts=tuple(sorted(basis_conflicts)),
            source_evidence_verifier_sha256=sha256_bytes(Path(__file__).with_name("source_seams.py").read_bytes()),
        )
        return replace(result, proof_sha256=sha256_bytes(_canonical_json(_source_proof_payload(result))))

    def state_proofs(self, daily, rows, pins=None):
        return self.state_proofs_and_evidence(daily, rows, pins)[0]

    def _verify_context(self, pins):
        from .coordinator import FEATURE_NAMES, LATEST_PB15, _parse_json_object, fixed_d_dates

        expected = pins.identity_sha256
        if (expected.get("r2_rules_sha256") != ORIGINAL_SOURCE_SHA256
                or expected.get("feature_builder_sha256") != sha256_bytes(Path(__file__).read_bytes())):
            raise ValueError("R2_RULE_OR_FEATURE_BUILDER_NOT_PINNED")
        assets = (
            (self.calendar_bytes, expected.get("calendar_sha256")),
            (self.feature_map_bytes, expected.get("feature_map_sha256")),
        )
        if any(not isinstance(raw, bytes) or sha256_bytes(raw) != digest for raw, digest in assets):
            raise ValueError("EXCHANGE_CALENDAR_OR_FEATURE_MAP_NOT_PINNED")
        cal = _parse_json_object(self.calendar_bytes, "exchange sessions")
        full = cal.get("common_trading_sessions")
        if (cal.get("schema") != "P515_COMMON_EXCHANGE_SESSIONS_V1" or not isinstance(full, list)
                or not all(isinstance(d, str) and date.fromisoformat(d).strftime("%Y%m%d") == d for d in full)
                or sorted(set(full)) != full):
            raise ValueError("EXCHANGE_CALENDAR_FORMAT")
        begin, end = (fixed_d_dates()[i].strftime("%Y%m%d") for i in (0, -1))
        accepted = [d.strftime("%Y%m%d") for d in fixed_d_dates()]
        first = full.index(self.r2_calendar[0])
        last = full.index(end)
        if ([d for d in full if begin <= d <= end] != accepted
                or full[first:first + len(self.r2_calendar)] != list(self.r2_calendar)
                or full[last + 12:last + 13] != [LATEST_PB15.strftime("%Y%m%d")]):
            raise ValueError("EXCHANGE_CALENDAR_DOES_NOT_BIND_STUDY_OR_STATE")
        columns = list(csv.DictReader(io.StringIO(self.feature_map_bytes.decode("utf-8-sig"))))
        if (tuple(col.get("feature") for col in columns) != tuple(FEATURE_NAMES)
                or [col.get("index_0based") for col in columns] != list(map(str, range(20)))):
            raise ValueError("FROZEN_FEATURE_ORDER_MISMATCH")

    def state_proofs_and_evidence(self, daily, rows, pins=None):
        from .coordinator import StateEvidence, StateProof, _parse_json_object, compute_state_proof_sha256

        _, _, _, histories = self._read(daily)
        D = date.fromisoformat(daily.D).strftime("%Y%m%d")
        confirmed_anchors = {}
        if not daily.synthetic_fixture:
            if (pins is None or not isinstance(self.anchor_catalog_bytes, bytes)
                    or sha256_bytes(self.anchor_catalog_bytes) != pins.identity_sha256["r2_anchor_catalog_sha256"]):
                raise ValueError("R2_ANCHOR_CATALOG_NOT_BOUND_TO_PRE_STUDY")
            catalog = _parse_json_object(self.anchor_catalog_bytes, "R2 anchor catalog")
            if catalog.get("schema") != "P515_VERIFIED_R2_ANCHOR_CATALOG_V1" or not isinstance(
                    catalog.get("securities"), dict):
                raise ValueError("R2_ANCHOR_CATALOG_FORMAT")
            confirmed_anchors = catalog["securities"]
        identity = {
            "generation": self.metadata["generation"], "market": "A",
            "price_basis": "QFQ_ASOF", "volume_basis": "QFQ_EVENT_VOLUME",
            "adjustment_snapshot_sha256": self.metadata["adjustment_snapshot_sha256"],
            "panel_manifest_sha256": self.metadata["panel_manifest_sha256"],
            "input_sha256": self.metadata["input_sha256"],
            "reader_sha256": self.metadata["reader_sha256"],
        }
        adapter_sha = sha256_bytes(Path(__file__).with_name("r2_resume.py").read_bytes())
        proofs = {}
        raw_evidence = {}
        for row in rows:
            unknown = StateProof(row.ts_code, D, "UNKNOWN", None, None, None, None, None, None,
                                 None, adapter_sha, "", "", "")
            proofs[row.ts_code] = replace(unknown, proof_sha256=compute_state_proof_sha256(unknown))
            anchor = self.anchors.get(row.ts_code)
            if anchor is None:
                continue
            history = histories[row.ts_code]
            try:
                evidence = json.loads(anchor.receipt)
                verified_at = datetime.fromisoformat(evidence["verified_at"])
                if verified_at.tzinfo is None or verified_at > daily.captured_at:
                    continue
                if not daily.synthetic_fixture:
                    listed = confirmed_anchors.get(row.ts_code)
                    approved = {
                        "receipt_sha256": anchor.grant.pinned_receipt_sha256,
                        "incoming_checkpoint_sha256": anchor.checkpoint_sha256,
                        "boundary_date": evidence["boundary_date"],
                        "verification_method": anchor.grant.verification_method,
                        "verification_id": evidence["verification_id"],
                        "verifier_id": anchor.grant.verifier_id,
                        "authorization_receipt_sha256": anchor.grant.authorization_receipt_sha256,
                    }
                    if (anchor.grant.verification_method == "SYNTHETIC_FIXTURE_ONLY"
                            or not isinstance(listed, list) or approved not in listed):
                        continue
                    self._verify_context(pins)
                args = dict(symbol=row.ts_code, calendar=self.r2_calendar, source_identity=identity,
                            receipt_bytes=anchor.receipt, grant=anchor.grant)
                if anchor.checkpoint is None:
                    if anchor.checkpoint_sha256 is not None or anchor.proven_reset:
                        continue
                    session = R2Session.from_listing_inception(**args)
                    dates = [d for d in sorted(history) if d >= evidence["boundary_date"]]
                else:
                    restore = R2Session.from_proven_reset if anchor.proven_reset else R2Session.resume
                    session = restore(snapshot_bytes=anchor.checkpoint,
                                      pinned_snapshot_sha256=anchor.checkpoint_sha256, **args)
                    previous = session.last_trade_date
                    if previous is None:
                        continue
                    dates = [d for d in sorted(history) if d > previous]
                expected = [d for d in self.projection_sessions if d >= dates[0]] if dates else []
                if dates != expected or dates[-1:] != [D]:
                    continue
                if anchor.checkpoint is None and dates[0] != evidence["boundary_date"]:
                    continue
                if anchor.checkpoint is not None and (
                        self.r2_calendar.index(dates[0]) != self.r2_calendar.index(previous) + 1):
                    continue
                delta = session.feed([history[d] for d in dates], source_identity=identity)
                observation = next((v for v in reversed(delta.observations)
                                    if v["candidate_date"] == D), {})
                _, _, _, pullbacks = session.readout()
                origin, mother, pb = (observation.get(key) for key in
                                      ("origin_key_k_date", "family_id", "pullback_id"))
                terminal = observation.get("terminal_observed_today") or next(
                    (v["outcome"] for v in delta.pullbacks if v["pullback_id"] == pb), None)
                if (observation.get("stage") == "SAME_EVENT_PULLBACK"
                        and observation.get("pullback_sessions") == 3 and not terminal):
                    features = _r2_features(observation, history, self.r2_calendar, pullbacks)
                    if row.features != features:
                        raise MatrixBindingError("COORDINATOR_FEATURES_DIFFER_FROM_FROZEN_R2_D_ONLY_MAPPING")
                prior_end = observation.get("trajectory_latest_pullback_end_date")
                snapshot = session.snapshot()
                checkpoint_sha = sha256_bytes(snapshot)
                result = StateProof(
                    ts_code=row.ts_code, D=D, status="PROVEN",
                    mother_key=mother, pb_id=pb,
                    origin_date=date.fromisoformat(origin).isoformat() if origin else None,
                    stage=observation.get("stage"),
                    pullback_sessions=observation.get("pullback_sessions"), terminal_on_D=bool(terminal),
                    prior_pb_terminal_date=date.fromisoformat(prior_end).isoformat() if prior_end else None,
                    adapter_sha256=adapter_sha,
                    anchor_receipt_sha256=anchor.grant.pinned_receipt_sha256,
                    checkpoint_sha256=checkpoint_sha, proof_sha256="",
                )
                proofs[row.ts_code] = replace(result, proof_sha256=compute_state_proof_sha256(result))
                raw_evidence[row.ts_code] = StateEvidence(anchor.receipt, snapshot)
            except MatrixBindingError:
                raise
            except (ValueError, TypeError, KeyError, IndexError):
                # Unproven state remains absent and the coordinator logs STATE_ANCHOR_UNKNOWN.
                continue
        return proofs, raw_evidence


@dataclass(frozen=True)
class BoundSourceVerifier:
    source: BoundV4Inputs

    def verify(self, daily, canonical_matrix_sha256, canonical_keys_sha256, row_projection_sha256):
        return self.source.source_proof(daily, canonical_matrix_sha256, canonical_keys_sha256,
                                        row_projection_sha256)


@dataclass(frozen=True)
class BoundStateVerifier:
    source: BoundV4Inputs

    def verify(self, daily, rows, pins):
        return self.source.state_proofs_and_evidence(daily, rows, pins)
