"""Read-only adapter over the V3 research-module generated lane snapshot.

V4 renders the research decision desk from the V3 research module's
``runtime_outputs/latest/<trade_date>/research_lane_snapshot.json`` plus a few
peripheral artifacts (zsxq/ocr/finance/ai_news). Those are raw generated files
owned by the legacy research module, NOT legacy final API answers, so reading
them keeps V4 production independent while aligning the decision desk.

Every path is resolved under an explicit V3 research-module root and rejects
any traversal outside it. Nothing is written.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class V3ResearchLaneSource:
    def __init__(
        self,
        *,
        research_module_root: Path,
        assistant_run_logs_root: Path | None = None,
        external_finance_root: Path | None = None,
    ) -> None:
        self.research_module_root = research_module_root
        self.assistant_run_logs_root = assistant_run_logs_root
        self.external_finance_root = external_finance_root

    def _snapshot_path(self, trade_date: str) -> Path:
        relative = Path("runtime_outputs") / "latest" / trade_date / "research_lane_snapshot.json"
        return self._resolve_read(relative)

    def _resolve_read(self, relative: Path) -> Path:
        candidate = (self.research_module_root / relative).resolve(strict=False)
        root = self.research_module_root.resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError("v3 research-lane source escapes research module root") from error
        return candidate

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return None
        return payload if isinstance(payload, Mapping) else None

    def read_lane_snapshot(self, trade_date: str) -> dict[str, Any] | None:
        path = self._snapshot_path(trade_date)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return None
        if not isinstance(payload, Mapping):
            return None
        if payload.get("schema_version") != "v3_research_lane.v2":
            return None
        if payload.get("write_policy") != "read_only" or payload.get("default_status") != "RESEARCH_ONLY":
            return None
        result = dict(payload)
        result["served_from"] = str(path)
        result["v35_read_policy"] = "V3_RAW_GENERATED_READ_ONLY"
        return result

    def read_zsxq_0830(self, trade_date: str) -> dict[str, Any] | None:
        relative = Path("runtime_outputs") / "zsxq_hourly" / trade_date / "0830" / f"v3_zsxq_0830_status_{trade_date}_0830.json"
        return self._read_json(self._resolve_read(relative))

    def read_external_finance(self) -> dict[str, Any] | None:
        if self.external_finance_root is None:
            return None
        candidate = (self.external_finance_root / "latest_external_finance.json").resolve(strict=False)
        root = self.external_finance_root.resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return self._read_json(candidate)

    def _run_logs(self, trade_date: str) -> list[Path]:
        if self.assistant_run_logs_root is None:
            return []
        root = self.assistant_run_logs_root
        return sorted(
            (path for path in root.iterdir() if path.is_dir() and path.name.startswith(trade_date)),
            reverse=True,
        )

    def _latest_run_log(self, trade_date: str) -> Path | None:
        logs = self._run_logs(trade_date)
        return logs[0] if logs else None

    def _unified_intelligence(self, run_log: Path) -> dict[str, Any]:
        """Read the run's unified intelligence (V3 fallback for finance/ai)."""
        if self.assistant_run_logs_root is None:
            return {}
        run_name = run_log.name
        # run_logs sits under 助手/current_push_v24_refetch_fixed/run_logs;
        # unified previews live under 助手/调试/unified_hourly_preview_<run>.
        preview_root = self.assistant_run_logs_root.parent.parent / "调试"
        candidates = (
            preview_root / f"unified_hourly_preview_{run_name}" / "unified_intelligence.json",
            run_log / "unified_intelligence.json",
        )
        for path in candidates:
            payload = self._read_json(path.resolve(strict=False))
            if payload is not None:
                return payload
        return {}

    def read_finance(self, trade_date: str) -> dict[str, Any] | None:
        # V3 discovery: pick the latest run that has a finance artifact, then
        # fall back to the run's unified intelligence source_updates.
        for run_log in self._run_logs(trade_date):
            finance_dir = run_log / "finance"
            has_finance_artifact = finance_dir.is_dir() and any(
                (finance_dir / name).is_file()
                for name in ("finance_summary.json", "finance_raw_news.json", "finance_final_push_content.txt")
            )
            summary = self._read_json((finance_dir / "finance_summary.json").resolve(strict=False))
            unified = self._unified_intelligence(run_log)
            finance_items = [
                item
                for item in (unified.get("source_updates") or [])
                if isinstance(item, Mapping) and str(item.get("source_type") or "").strip().lower() == "finance"
            ]
            if not has_finance_artifact and not summary and not finance_items:
                continue
            return {
                "ok": bool(summary.get("ok", True)) if summary else bool(finance_items),
                "quality_pass": bool(summary.get("quality_pass", True)) if summary else None,
                "provider": str((summary or {}).get("provider") or "unified_hourly_intelligence"),
                "latest_run_id": run_log.name,
                "fetched_at": (summary or {}).get("fetched_at") or "",
                "fetched_at_display": (summary or {}).get("fetched_at_display") or "",
                "raw_item_count": len(finance_items) or int((summary or {}).get("raw_item_count", 0) or 0),
                "high_signal_item_count": len(finance_items),
                "overview": finance_items[:12],
                "details": finance_items[:40],
                "source_path": str(finance_dir if finance_dir.is_dir() else run_log),
                "cannot_confirm": [] if finance_items else ["HOURLY_FINANCE_RAW_NEWS_NOT_FOUND"],
                "write_policy": "read_only",
                "buy_gate_effect": "none",
                "live_order_effect": "none",
            }
        return None

    def read_ai_news(self, trade_date: str) -> dict[str, Any] | None:
        for run_log in self._run_logs(trade_date):
            probe = self._read_json((run_log / "aihot_subprocess_result.json").resolve(strict=False))
            if probe is None or not isinstance(probe.get("json_path"), str):
                continue
            json_path = probe["json_path"].replace("\\", "/")
            if json_path.startswith("C:/"):
                external = Path(json_path)
                if external.is_file():
                    return self._read_json(external)
        return None

    def read_latest_event(self) -> dict[str, Any] | None:
        relative = Path("runtime_outputs") / "events" / "latest_research_event.json"
        return self._read_json(self._resolve_read(relative))

    def list_available_dates(self) -> list[str]:
        base = self.research_module_root / "runtime_outputs" / "latest"
        if not base.is_dir():
            return []
        return sorted(
            path.name
            for path in base.iterdir()
            if path.is_dir()
            and len(path.name) == 8
            and path.name.isdigit()
            and (path / "research_lane_snapshot.json").is_file()
        )


__all__ = ["V3ResearchLaneSource"]
