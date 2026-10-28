"""Explicit dependencies for the existing V4 generation entry, not a producer.

Market/news input is read from the one shared authority's immutable snapshot.
The explicit assembly materializes data before this graph consumer runs; no
service, reflection writer, CLI provider fallback or HOME discovery is used.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Mapping

from ._owned_io import BoundaryError, directory, read_json, records
from ._snapshot import ReviewSnapshot, SOURCE_ROLE, sha
from ._evidence import verify_evidence
from .vibe_core import preflight, reflection_context, serializer
from .vibe_core.prompts import RESEARCH_PACK


@dataclass(frozen=True)
class LlmIdentity:
    provider_id: str
    model_id: str
    config_sha256: str

    def public(self) -> dict[str, str]:
        if not self.provider_id or not self.model_id:
            raise BoundaryError("explicit non-secret LLM identity required")
        return {"provider_id": self.provider_id, "model_id": self.model_id,
                "config_sha256": sha(self.config_sha256)}


class _CountedLlm:
    def __init__(self, client: Any, name: str, counts: Counter):
        if not callable(getattr(client, "invoke", None)):
            raise BoundaryError("LLM client must expose invoke(prompt)")
        self.client, self.name, self.counts = client, name, counts

    def invoke(self, prompt: str):
        self.counts[self.name] += 1
        return self.client.invoke(prompt)


def verify_owned_sources(expected_sha256: str) -> dict:
    """Check exact owned source bytes against a caller-pinned manifest."""
    root = Path(__file__).parent
    with directory(root) as fd:
        manifest, actual, _ = read_json(fd, "OWNED_SOURCE_MANIFEST.json", limit=256 * 1024)
    if actual != sha(expected_sha256) or not isinstance(manifest, dict):
        raise BoundaryError("owned source manifest SHA drift")
    entries = manifest.get("files")
    if not isinstance(entries, dict) or not entries:
        raise BoundaryError("owned source manifest is empty")
    observed = set()
    for name, info in entries.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".py":
            raise BoundaryError("invalid owned source manifest path")
        with directory(root / relative.parent) as fd:
            from ._owned_io import read_bytes
            data = read_bytes(fd, relative.name, limit=2 * 1024 * 1024)
        digest = hashlib.sha256(data).hexdigest()
        if not isinstance(info, dict) or info.get("sha256") != digest or info.get("bytes") != len(data):
            raise BoundaryError(f"owned source byte drift: {name}")
        observed.add(name)
    actual_files = {str(path.relative_to(root)) for path in root.rglob("*.py")}
    if actual_files != observed:
        raise BoundaryError("unlisted or missing owned Python module")
    project = root.parents[1]
    from infrastructure.owned_io import SafeRoot
    external = manifest.get("external_files")
    required = {"infrastructure/owned_io.py", "infrastructure/interprocess_lock.py",
                "infrastructure/trading_safety.py", "ops/run_research_review_generation.py",
                "contracts/vibe_runtime_profile.json"}
    if not isinstance(external, dict) or set(external) != required:
        raise BoundaryError("owned source external closure incomplete")
    io = SafeRoot(project)
    for name, info in external.items():
        raw = io.read_bytes(name, max_bytes=2 * 1024 * 1024)
        if info.get("sha256") != hashlib.sha256(raw).hexdigest() or info.get("bytes") != len(raw):
            raise BoundaryError("external source byte drift: " + name)
    return {"status": "HASH_BOUND", "root": str(root), "manifest_sha256": actual,
            "files": entries, "external_files": external}


@dataclass
class PreparedInputs:
    snapshot: ReviewSnapshot
    reflections: list[dict]
    provenance: dict


@dataclass(frozen=True)
class VibeRuntime:
    """All paths are children of one explicit V4-owned state directory.

    inputs/<date>.json: written by the EXISTING shared authority, read-only here.
    reflections/<prediction-date>.json: validated historical copies, read-only.
    reviews/<date>.json: written only by generation.write_exact_review.
    """
    state_root: Path
    snapshot_sha256: str
    implementation_manifest_sha256: str
    quick: Any
    deep: Any
    quick_identity: LlmIdentity
    deep_identity: LlmIdentity
    pack: Any  # Explicit built-in RESEARCH_PACK selected in local evidence.
    reflection_root: Path | None = None
    authority: Any | None = None

    def _reflections_root(self) -> Path:
        return self.reflection_root or Path(self.state_root) / "reflections"

    def prepare(self, trade_date: str, review_root: Path) -> PreparedInputs:
        root = Path(self.state_root)
        if not root.is_absolute() or ".." in root.parts or review_root != root / "reviews":
            raise BoundaryError("review root must match the explicit V4-owned state binding")
        source = verify_owned_sources(self.implementation_manifest_sha256)
        if root == Path(source["root"]) or Path(source["root"]) in root.parents or root in Path(source["root"]).parents:
            raise BoundaryError("state and code roots must be separate")
        if self.pack is not RESEARCH_PACK:
            raise BoundaryError("custom prompt pack is not in this frozen candidate; do not silently substitute")
        from .model_provider import BoundLlm
        clients = {}
        for name, client, identity in (("quick", self.quick, self.quick_identity), ("deep", self.deep, self.deep_identity)):
            if not isinstance(client, BoundLlm) or client.identity != identity:
                raise BoundaryError("LLM identity is not bound to the constructed client")
            clients[name] = client.public()
        with directory(root / "inputs") as fd:
            raw, digest, size = read_json(fd, trade_date + ".json")
        if digest != sha(self.snapshot_sha256):
            raise BoundaryError("input snapshot SHA mismatch")
        # Preserve legitimate research order arrays while refusing capability flags
        # recursively before constructing prompts or invoking any model.
        from .generation import _assert_research_flags, GenerationRefused
        try:
            _assert_research_flags(raw)
        except GenerationRefused as exc:
            raise BoundaryError("unsafe input research capability flag") from exc
        snapshot = ReviewSnapshot(raw, trade_date)
        with directory(self._reflections_root()) as fd:
            history, before, warnings = records(fd)
        try:
            _assert_research_flags(history)
        except GenerationRefused as exc:
            raise BoundaryError("unsafe reflection research capability flag") from exc
        if self.authority is not None:
            self.authority.assert_clean()
        evidence = verify_evidence(state_root=root, payload=raw,
            implementation_sha256=self.implementation_manifest_sha256, reflection_manifest=before)
        if not history:
            warnings.append("reflection history empty: prior-context continuity CANNOT_CONFIRM")
        return PreparedInputs(snapshot, history, {
            "source": source,
            "source_role": SOURCE_ROLE,
            "input_snapshot": {"path": str(root / "inputs" / (trade_date + ".json")), "sha256": digest, "bytes": size},
            "shared_authority_id": snapshot.authority_id,
            "authority_receipt_sha256": snapshot.authority_receipt_sha256,
            "authority_receipt_independently_verified": True,
            "evidence_validation": evidence,
            "section_and_function_sources": deepcopy(snapshot.sources),
            "reflection": {"root": str(self._reflections_root()), "before_manifest": before, "warnings": warnings,
                           "records_read": len(history), "auto_evaluate_prior_written": False},
            "llm_clients": clients,
            "prompt_pack": {"name": RESEARCH_PACK.name, "selection": "explicit_builtin", "custom_pack_continuity": "EXPLICIT_BUILTIN_RESEARCH_PER_FROZEN_SELECTION"},
            "snapshot": {"disk_reads": 1, "high_level_values_loaded": 8, "live_market_calls_in_generator": 0,
                         "live_news_calls_in_generator": 0,
                         "upstream_provider_counts_reported": snapshot.reported_provider_counts,
                         "lower_level_provider_deduplication": "RAW_OWNER_SUCCESS_AND_FAILURE_KEYED_REUSE",
                         "provider_count_scope": "verified receipt; live SDK-internal HTTP not measured"},
            "natural_generation": "CANNOT_CONFIRM",
        })

    def run(self, trade_date: str, review_root: Path) -> tuple[Mapping[str, Any], dict]:
        prepared = self.prepare(trade_date, review_root)
        snapshot, history, metadata = prepared.snapshot, prepared.reflections, prepared.provenance
        pre = preflight.check(trade_date, data=snapshot)
        if not pre["ok"]:
            raise BoundaryError(preflight.refuse_reason(pre, trade_date) or "preflight refused")
        # Import the real library and graph. Never substitute a fake StateGraph.
        try:
            from .vibe_core.review_graph import build_review_graph
        except ImportError as exc:
            raise BoundaryError("real LangGraph dependency missing; graph execution CANNOT_CONFIRM") from exc
        counts: Counter = Counter()
        graph = build_review_graph(data=snapshot,
            quick=_CountedLlm(self.quick, "quick_invoke", counts),
            deep=_CountedLlm(self.deep, "deep_invoke", counts), search=snapshot.search, pack=self.pack)
        initial = initial_state(trade_date, history)
        final = graph.invoke(initial, {"recursion_limit": 50})
        if not isinstance(final, Mapping) or final.get("trade_date") != trade_date:
            raise BoundaryError("graph result identity mismatch")
        warnings = [*pre["warnings"], *snapshot.warnings(), *metadata["reflection"]["warnings"]]
        payload = serializer.serialize(dict(final), trade_date, warnings,
            pack=self.pack, reflection_record=reflection_context.latest_reflection(history, as_of=trade_date),
            data_as_of=snapshot.data_as_of, generated_at=datetime.now(timezone.utc).isoformat())
        if not serializer.usable(payload):
            raise BoundaryError("graph focus unusable; dated artifact not published")
        payload["source_role"] = SOURCE_ROLE
        payload["source_lineage"] = deepcopy(snapshot.sources)
        with directory(Path(self.state_root) / "inputs") as fd:
            after_input, after_sha, _ = read_json(fd, trade_date + ".json")
        with directory(self._reflections_root()) as fd:
            _, after_history, _ = records(fd)
        if after_sha != self.snapshot_sha256 or after_history != metadata["reflection"]["before_manifest"]:
            raise BoundaryError("input or reflection state changed during graph execution")
        verify_evidence(state_root=self.state_root, payload=after_input,
            implementation_sha256=self.implementation_manifest_sha256, reflection_manifest=after_history)
        if self.authority is not None:
            self.authority.assert_clean()
        # Also refuse a code deployment that changed bytes while the graph ran.
        verify_owned_sources(self.implementation_manifest_sha256)
        metadata["snapshot"]["disk_reads"] = 2  # materialize once + end-of-run drift verification
        metadata["snapshot"]["materializations"] = 1
        metadata["snapshot"]["verification_reads"] = 1
        metadata["snapshot"]["lookup_counts"] = dict(snapshot.lookup_counts)
        metadata["llm_invoke_counts"] = dict(counts)
        metadata["llm_transport_attempts"] = "CANNOT_CONFIRM_CLIENT_INTERNAL_RETRIES"
        metadata["reflection"]["after_manifest"] = after_history
        metadata["reflection"]["unchanged"] = True
        metadata["reflection"]["directory_scans"] = 2  # context load + drift verification
        metadata["graph"] = {"implementation": type(graph).__module__ + "." + type(graph).__qualname__,
                             "recursion_limit": 50, "role_order": ["情绪面", "资金面", "题材热点", "龙虎榜游资", "龙头跟踪", "复盘裁判"]}
        return payload, metadata


def initial_state(trade_date: str, reflections: list[dict]) -> dict:
    """main.initial_state fields preserved, with explicit one-read history."""
    return {"trade_date": trade_date, "sentiment_report": "", "capital_report": "", "theme_report": "",
            "dragon_tiger_report": "", "leader_report": "", "macro_sector_report": "",
            "emotion_metrics": {}, "market_facts": {}, "tomorrow_focus": "", "focus_struct": None,
            "past_context": reflection_context.get_past_context(reflections, as_of=trade_date)}
