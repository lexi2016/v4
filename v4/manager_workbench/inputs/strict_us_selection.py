"""Read-only strict-selection inputs from the already bound HK owners."""
from __future__ import annotations

import io
from pathlib import Path

from infrastructure.owned_io import SafeRoot
from contracts.trading_calendar import previous_session
from .validation import raw_sha, before, owner_digest, symbol


def validate_mapping_quote(quote, us_symbol, session):
    """Validate one bound quote without aliasing another instrument."""
    from decimal import Decimal, DecimalException
    if not isinstance(quote, dict) or quote.get("symbol") != us_symbol:
        return None, "QUOTE_SYMBOL_MISMATCH"
    if quote.get("session_date") != session:
        return None, "QUOTE_SESSION_MISMATCH"
    try:
        numbers = []
        for key in ("last", "previous_close", "change_pct"):
            value = quote.get(key)
            if isinstance(value, bool) or value is None:
                raise ValueError
            number = Decimal(str(value))
            if not number.is_finite():
                raise ValueError
            numbers.append(number)
        last, previous, saved = numbers
        if last <= 0 or previous <= 0:
            raise ValueError
        calculated = (last / previous - 1) * 100
        if abs(calculated - saved) > Decimal("0.001"):
            return None, "QUOTE_RETURN_MISMATCH"
        return format(calculated.normalize(), "f"), None
    except (DecimalException, ValueError, TypeError, OverflowError):
        return None, "QUOTE_PRICE_OR_RETURN_INVALID"


def _window(calendar, end, count):
    days = [end]
    while len(days) < count:
        days.append(previous_session(calendar, days[-1], market="hk_securities"))
    return list(reversed(days))


def _unavailable(reason):
    return dict(status="CANNOT_CONFIRM", gap=reason,
        amount_unit_status="SOURCE_SCALE_CHECKED",
        basic_unit_check_sha256="6118718612b3be075d7757e37874564ca7fa09b35dddfca2f6c943aacbfc0d03")


def load_strict_selection_input(adapter, context, monthly_research):
    """Project the exact bound panel into 21-close/20-amount windows.

    This function only reads the same shared panel and membership used by the
    existing US_MAPPING/Connect path. It does not fall back to a collector or
    another price producer.
    """
    if (not isinstance(monthly_research, dict)
            or monthly_research.get("status") != "VERIFIED"
            or not isinstance(monthly_research.get("codes"), list)
            or not monthly_research.get("codes")):
        return dict(monthly_membership=None, hk_history=_unavailable("MONTHLY_RESEARCH_UNIVERSE_UNAVAILABLE"))

    price_date = context.source_sessions.get("hk_price")
    if not isinstance(price_date, str):
        return dict(monthly_membership=dict(monthly_research),
            hk_history=_unavailable("HK_PRICE_SESSION_UNAVAILABLE"))

    membership = dict(
        status="VERIFIED", target_eligibility="CANNOT_CONFIRM",
        owner=monthly_research.get("owner"), source_date=monthly_research.get("source_date"),
        source_sha256=monthly_research.get("artifact_sha256"),
        codes_sha256=monthly_research.get("codes_sha256"),
        codes=monthly_research.get("codes"),
    )
    base = dict(monthly_membership=membership)
    try:
        pin = adapter._binding("hk_panel", price_date, context)
        root = Path(pin.get("source_local_path") or adapter.config.shared_root)
        manifest, manifest_sha = adapter._json(root, pin["manifest_relative"], pin["manifest_sha256"])
        available_at = manifest.get("manifest_prepared_at", manifest.get("prepared_at", pin.get("available_at")))
        projected = (context.phase.value == "RETROSPECTIVE"
            and isinstance(manifest.get("panel_max_date"), str)
            and price_date <= manifest["panel_max_date"] <= context.target_date)
        if ((manifest.get("panel_max_date") != price_date and not projected)
                or manifest.get("research_only") is not True
                or manifest.get("production_allowed") is not False
                or manifest.get("orders_sent", False) is not False
                or not before(available_at, context.cutoff)
                or pin.get("available_at") != available_at):
            raise ValueError("HK_PANEL_DATE_SAFETY_OR_CUTOFF_INVALID")

        relative = pin.get("panel_relative", "assets/hk_0_2/" + manifest["panel_relative"])
        raw = SafeRoot(root).read_bytes(relative, max_bytes=512 * 1024 * 1024)
        panel_sha = raw_sha(raw)
        if panel_sha != manifest.get("panel_sha256"):
            raise ValueError("HK_PANEL_BYTES_SHA_MISMATCH")

        import pandas as pd

        frame = pd.read_parquet(io.BytesIO(raw))
        date_col = "trade_date_compact" if "trade_date_compact" in frame else "trade_date"
        code_col = "code_norm" if "code_norm" in frame else "symbol"
        if date_col not in frame or code_col not in frame or "close" not in frame or "amount" not in frame:
            raise ValueError("HK_PANEL_CLOSE_OR_AMOUNT_FIELD_MISSING")
        frame[date_col] = frame[date_col].astype(str).str.replace("-", "", regex=False).str[:8]
        frame[code_col] = frame[code_col].map(symbol)
        frame = frame[frame[code_col].notna()].copy()
        frame = frame[frame[date_col] <= price_date].copy()

        from upstreams.v3_shared_data.shared_data.hk_history_resolution import policy_for_shared

        resolution = policy_for_shared(root)
        resolution.check_panel(manifest["panel_sha256"])
        close_sessions = _window(adapter.calendar, price_date, 21)
        amount_sessions = close_sessions[-20:]
        effective_frame = resolution.project_frame(frame, code_column=code_col,
            date_column=date_col, source="C")
        close_frame = resolution.guard_frame(effective_frame, required_fields=("close",),
            code_column=code_col, date_column=date_col, end=price_date, lookback=21,
            consumer="STRICT_US_SELECTION_CLOSE21_V1")
        close_holds = dict(close_frame.attrs.get("history_resolution_holds", {}))
        close_proof = resolution.encode_proof(close_frame.attrs["history_resolution_proof"])
        amount_frame = resolution.guard_frame(effective_frame, required_fields=("amount",),
            code_column=code_col, date_column=date_col, end=price_date, lookback=20,
            consumer="STRICT_US_SELECTION_AMOUNT20_V1")
        amount_holds = dict(amount_frame.attrs.get("history_resolution_holds", {}))
        amount_proof = resolution.encode_proof(amount_frame.attrs["history_resolution_proof"])

        relevant = effective_frame[effective_frame[date_col].isin(close_sessions)]
        # Optional explicit immutable material only; no discovery, acquisition or
        # inference of units/current membership from a capture date.
        material_proofs = []
        material_refs = []
        for material_pin in pin.get("strict_materials", []):
            material, material_sha = adapter._json(root, material_pin["relative"], material_pin["sha256"])
            reference = str((root / material_pin["relative"]).resolve())
            material_refs.append(dict(reference=reference, sha256=material_sha))
            material_proofs.extend(dict(record, evidence_refs=[dict(reference=reference, sha256=material_sha)])
                for record in material.get("records", []) if isinstance(record, dict))
        from upstreams.v3_shared_data.shared_data.hk_panel_audit import strict_window_readiness
        histories = {}
        def scalar(value):
            if value is None or pd.isna(value):
                return None
            return value.item() if hasattr(value, "item") else value

        for code in monthly_research["codes"]:
            rows = []
            for _, record in relevant[relevant[code_col] == code].iterrows():
                day = record[date_col]
                if day not in close_sessions:
                    continue
                bar = {"date": day}
                for field in ("open", "high", "low"):
                    bar[field] = scalar(record.get(field))
                if day in amount_sessions:
                    bar["amount"] = scalar(record.get("amount"))
                bar["close"] = scalar(record.get("close"))
                suspended = record.get("suspended")
                if isinstance(suspended, bool) or type(suspended).__name__ == "bool_":
                    bar["suspended"] = bool(suspended)
                rows.append(bar)
            holds = {}
            if code in close_holds:
                holds["close"] = close_holds[code]
            if code in amount_holds:
                holds["amount"] = amount_holds[code]
            readiness = strict_window_readiness(
                [dict(bar, code_norm=code, trade_date_compact=bar["date"]) for bar in rows],
                code=code, sessions=close_sessions, cutoff=context.cutoff,
                panel_sha256=panel_sha, proof=material_proofs, target_date=context.target_date)
            histories[code] = dict(bars=rows, history_holds=holds, readiness=readiness)

        history_rows = [dict(symbol=code, **histories[code]) for code in monthly_research["codes"]]
        base["hk_history"] = dict(status="READY", rows=history_rows,
            close_sessions=close_sessions, amount_sessions=amount_sessions,
            panel_sha256=panel_sha, panel_manifest_sha256=manifest_sha,
            panel_available_at=available_at, panel_owner=pin.get("owner", "v3_shared_data"),
            panel_relative=relative,
            strict_material_refs=material_refs,
            history_resolution_manifest_sha256=resolution.manifest_sha256,
            history_resolution_proof_sha256=owner_digest({"close21": close_proof, "amount20": amount_proof}),
            history_resolution_proofs={"close21": close_proof, "amount20": amount_proof},
            amount_unit_status="SOURCE_SCALE_CHECKED",
            basic_unit_check_sha256="6118718612b3be075d7757e37874564ca7fa09b35dddfca2f6c943aacbfc0d03")
    except Exception as error:
        reason = str(error) if isinstance(error, ValueError) and str(error).isupper() else "HK_HISTORY_OWNER_UNAVAILABLE_OR_INVALID"
        base["hk_history"] = _unavailable(reason)
    return base
