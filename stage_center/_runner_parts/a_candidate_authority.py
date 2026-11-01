"""stage_center.runner: a_candidate_authority (review candidate, not deployment)."""
from __future__ import annotations
from dataclasses import replace
import csv
import re
from stage_center.runner import _FORMAL_AUTHORITY_OVERLAY_PROOF, _normal_code, _validate_formal_input


def __attach_a_authority_body(source, *, formal_root, trade_date):
    """Overlay exact formal-pool metadata onto a selection-only copy.

    The acquisition artifact remains untouched.  ``pool_score`` and
    ``formal_rank`` are V3 upstream fields, so they must be read from the
    verified formal CSV instead of inferred from the 125-code acquisition
    universe or defaulted to zero.
    """
    csv_path, _manifest_path, _csv_sha = _validate_formal_input(formal_root, trade_date)
    authority: dict[str, Mapping[str, Any]] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if str(row.get("eligible_for_formal_pool") or "").lower() not in {"true", "1", "yes"}:
                continue
            match = re.search(r"(\d{6})", str(row.get("ts_code") or row.get("stock_code") or ""))
            if not match:
                continue
            authority[f"A.{match.group(1)}"] = row
    enriched: list[dict[str, Any]] = []
    for raw in source.rows:
        code = _normal_code("A_SHARE", raw.get("code"))
        merged = dict(raw)
        # This private marker is created only by this verified exact-date
        # overlay.  Remove any inherited value before assigning the result so
        # a collector row cannot self-authorize formal membership.
        merged.pop("_formal_authority_overlay_verified", None)
        merged.pop("_formal_authority_overlay_proof", None)
        # PyTDX adapters may expose SH./SZ./BJ. prefixes; the cross-version
        # selection artifact is canonical A.###### regardless of provider.
        merged["code"] = code
        metadata = authority.get(code)
        if metadata is not None:
            merged["formal_eligible"] = True
            merged["formal_rank"] = metadata.get("rank") or metadata.get("pool_rank") or ""
            merged["pool_score"] = metadata.get("score") or metadata.get("pool_score") or 0.0
            merged["candidate"] = {"score": merged["pool_score"]}
            merged["_formal_authority_overlay_verified"] = True
            merged["_formal_authority_overlay_proof"] = _FORMAL_AUTHORITY_OVERLAY_PROOF
            merged["lane_evidence"] = list(dict.fromkeys([*(merged.get("lane_evidence") or ()), "A_SHARE_FORMAL_POOL"]))
        else:
            # Formal membership is an authority overlay, never a default for
            # every exact-date acquisition row. Keep the raw row eligible for
            # the Windows V3 live formula while explicitly proving that it is
            # non-formal and came from the stage acquisition universe.
            merged["formal_eligible"] = False
            merged["formal_rank"] = ""
            merged["_formal_authority_overlay_verified"] = False
            merged.pop("candidate", None)
            merged.pop("pool_score", None)
            lane_evidence = [
                item for item in (merged.get("lane_evidence") or ())
                if item != "A_SHARE_FORMAL_POOL"
            ]
            merged["lane_evidence"] = list(
                dict.fromkeys([*lane_evidence, "STAGE_ACQUISITION_UNIVERSE"])
            )
        enriched.append(merged)
    return replace(
        source,
        rows=tuple(enriched),
        source_evidence=tuple(
            dict.fromkeys(
                (
                    *source.source_evidence,
                    "formal_metadata_overlay=exact_date_authority_only",
                    f"v3_formal_pool_csv_sha256={_csv_sha}",
                    f"v3_formal_pool_trade_date={trade_date}",
                )
            )
        ),
    )
