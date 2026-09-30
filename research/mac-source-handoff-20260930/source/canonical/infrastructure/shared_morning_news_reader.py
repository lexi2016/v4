"""Fail-closed reader for the shared morning-news JSON contract."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Mapping

from infrastructure.data_store import _date, _sha256
from infrastructure.isolated_package_loader import load_isolated_package_module

_RESOLVED_REGISTRY_MARKER = "STOCK_MENTIONS_RESOLVED_BY_EACH_CONSUMER_CANDIDATE_REGISTRY"
_SHARED_IMPORT_LOCK = threading.RLock()


class SharedMorningNewsReader:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def _resolve(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("shared morning-news path escapes root")
        return candidate

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("shared morning-news JSON is not an object")
        return dict(value)

    def _shared_contract(
        self,
    ) -> tuple[
        Callable[[Path | str, str], list[dict[str, Any]]],
        Callable[[Any, Any], list[dict[str, Any]]],
    ] | None:
        """Load the shared producer functions without reimplementing them."""

        roots: list[Path] = []
        configured = str(os.environ.get("V3_SHARED_DATA_SOURCE_ROOT") or "").strip()
        if configured:
            roots.append(Path(configured).resolve())
        anchors = [self.root, *self.root.parents, Path.cwd(), *Path.cwd().parents]
        for anchor in anchors:
            roots.extend((anchor, anchor.parent / "v3_shared_data"))
        seen: set[Path] = set()
        for source_root in roots:
            source_root = source_root.resolve()
            if source_root in seen or not (
                (source_root / "shared_data" / "morning_news.py").is_file()
                and (source_root / "shared_data" / "public_morning_news.py").is_file()
            ):
                continue
            seen.add(source_root)
            with _SHARED_IMPORT_LOCK:
                try:
                    public = load_isolated_package_module(
                        source_root,
                        package_directory="shared_data",
                        module_leaf="public_morning_news",
                        namespace_prefix="v35_shared_public_morning_news",
                    )
                    morning = load_isolated_package_module(
                        source_root,
                        package_directory="shared_data",
                        module_leaf="morning_news",
                        namespace_prefix="v35_shared_morning_news",
                    )
                    loader = getattr(public, "load_shared_candidate_registry", None)
                    materializer = getattr(morning, "materialize_stock_mentions", None)
                    if callable(loader) and callable(materializer):
                        return loader, materializer
                except (ImportError, OSError, ValueError):
                    continue
        return None

    def _cannot_confirm_projection(
        self, payload: Mapping[str, Any], reason: str
    ) -> dict[str, Any]:
        projected = dict(payload)
        raw_items = payload.get("cannot_confirm") or []
        if isinstance(raw_items, str):
            raw_items = [raw_items]
        cannot_confirm = [
            str(item).strip() for item in raw_items if str(item).strip()
        ]
        if reason not in cannot_confirm:
            cannot_confirm.append(reason)
        projected["cannot_confirm"] = sorted(set(cannot_confirm))
        projected["stock_mentions"] = []
        projected["mention_count"] = 0
        projected["stock_mentions_materialization"] = reason
        return projected

    def _resolved_projection(
        self, payload: Mapping[str, Any], derived: list[dict[str, Any]]
    ) -> dict[str, Any]:
        projected = dict(payload)
        raw_items = payload.get("cannot_confirm") or []
        if isinstance(raw_items, str):
            raw_items = [raw_items]
        remaining = sorted(
            {
                str(item).strip()
                for item in raw_items
                if str(item).strip() and str(item).strip() != _RESOLVED_REGISTRY_MARKER
            }
        )
        if remaining:
            projected["cannot_confirm"] = remaining
        else:
            projected.pop("cannot_confirm", None)
        projected["stock_mentions"] = derived
        projected["mention_count"] = len(derived)
        projected["stock_mentions_materialization"] = "SHARED_CANDIDATE_CONTRACT_BODY_MATCH"
        return projected

    def read(self, trade_date: str) -> dict[str, Any] | None:
        trade_date = _date(trade_date)
        latest_path = self._resolve("morning_news/latest.json")
        if not latest_path.is_file():
            return None
        latest = self._read(latest_path)
        if (
            latest.get("schema_version") != "v3_shared_data.morning_news_latest.v1"
            or not isinstance(latest.get("entries"), Mapping)
        ):
            raise ValueError("shared morning-news latest pointer invalid")
        entry = latest["entries"].get(trade_date)
        if entry is None:
            return None
        if not isinstance(entry, Mapping):
            raise ValueError("shared morning-news latest entry invalid")
        payload = self._read(self._resolve(str(entry.get("payload_relative") or "")))
        manifest = self._read(self._resolve(str(entry.get("manifest_relative") or "")))
        receipt = self._read(self._resolve(str(entry.get("receipt_relative") or "")))
        articles = payload.get("articles")
        mentions = payload.get("stock_mentions")
        payload_sha = _sha256(payload)
        if (
            payload.get("schema_version") != "v3_shared_data.morning_news.v1"
            or payload.get("trade_date") != trade_date
            or payload.get("source_role") != "JIUYANGONGSHE_MORNING_NEWS"
            or not isinstance(articles, list)
            or payload.get("article_count") != len(articles)
            or not isinstance(mentions, list)
            or payload.get("mention_count") != len(mentions)
            or entry.get("payload_sha256") != payload_sha
            or manifest.get("payload_sha256") != payload_sha
            or receipt.get("manifest_sha256") != _sha256(manifest)
            or any(
                payload.get(key) is not False or receipt.get(key) is not False
                for key in ("production_allowed", "buy_gate_updated", "orders_sent")
            )
        ):
            raise ValueError("shared morning-news evidence failed verification")
        if mentions:
            return payload

        contract = self._shared_contract()
        if contract is None:
            return self._cannot_confirm_projection(
                payload, "CANNOT_CONFIRM_SHARED_MORNING_NEWS_PARSER_UNAVAILABLE"
            )
        load_registry, materialize = contract
        try:
            registry = load_registry(self.root, trade_date)
        except (OSError, TypeError, ValueError):
            return self._cannot_confirm_projection(
                payload, "CANNOT_CONFIRM_SHARED_CANDIDATE_REGISTRY_INVALID"
            )
        if not registry:
            return self._cannot_confirm_projection(
                payload, "STOCK_MENTIONS_CANDIDATE_REGISTRY_MISSING"
            )
        try:
            derived = materialize(articles, registry)
        except (TypeError, ValueError):
            return self._cannot_confirm_projection(
                payload, "CANNOT_CONFIRM_SHARED_MENTION_MATERIALIZATION"
            )
        if not derived:
            return payload
        return self._resolved_projection(payload, derived)


__all__ = ["SharedMorningNewsReader"]
