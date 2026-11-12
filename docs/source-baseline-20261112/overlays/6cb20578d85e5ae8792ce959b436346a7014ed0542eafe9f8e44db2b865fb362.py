"""Bounded idempotency for the existing two close-review builders."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from infrastructure.data_store import _date, _sha256
from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.owned_io import SafeRoot
from infrastructure.owned_path import resolve_owned_path


def builder_sha(paths):
    return _sha256({str(Path(p).name): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths})


def materialize_once(*, root: Path, market: str, date: str, builder: str,
                     inputs: Callable, read_current: Callable, build: Callable):
    if market not in {"A", "HK"}: raise ValueError("REVIEW_MARKET_INVALID")
    _date(date)
    io = SafeRoot(root)
    lock = resolve_owned_path(root, f"review_generations/{market}/{date}/.claim")
    with owned_interprocess_lock(lock, timeout_seconds=10, timeout_message="REVIEW_GENERATION_BUSY"):
        source = inputs()
        generation = _sha256({"date": date, "market": market, "input_generation": source, "builder_sha256": builder})
        relative = f"review_generations/{market}/{date}/{generation}.json"
        try:
            previous = json.loads(io.read_bytes(relative))
        except FileNotFoundError:
            previous = None
        current = read_current()
        if previous is not None and current is not None and previous["product_sha256"] == _sha256(current):
            return {"review": current, "publication": previous["publication"], "generation": generation,
                    "builder_sha256": builder, "status": "NOOP", "reused": True}
        result = build(current)
        if inputs() != source:
            raise ValueError("REVIEW_INPUT_GENERATION_CHANGED_DURING_BUILD")
        payload = {"schema_version": "v4.close_review_generation.v1", "date": date, "market": market,
            "input_generation": source, "builder_sha256": builder, "generation": generation,
            "product_sha256": _sha256(result["review"]), "publication": result["publication"],
            "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
        io.write_bytes(relative, (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode())
        return {**result, "generation": generation, "builder_sha256": builder, "status": "MATERIALIZED", "reused": False}
