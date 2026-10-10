"""Read-only V3.5-owned research lane source over verified research archives.

The research decision-desk lane is served exclusively from the explicitly
bound ``data_root`` through exact archives and hourly artifacts plus an
optional V3.5-owned validated event artifact. Nothing reads the V3 research
module, assistant run logs, or legacy finance/ai sources; no event is ever
synthesized and no sibling root is searched. The bound root is disclosed only
as read-only provenance so a deployment can be audited.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from infrastructure.data_store import _sha256
from infrastructure.market_time import shanghai_now
from infrastructure.owned_path import resolve_owned_path
from infrastructure.research_store import HourlyResearchStore, ResearchArchiveStore
from infrastructure.scheduling.execution_ledger import ExecutionLedger


_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,255}")
_STATUS_TIMELINE_SLOTS = tuple(f"{hour:02d}00" for hour in range(7, 24))
_STATUS_RECEIPT_GLOB = "*.dispatch-receipt.json"


class ResearchLaneSource:
    """Projections over a verified ``ResearchArchiveStore``.

    The class is deliberately thin: the archive is already validated by
    ``validate_research_archive`` (manifest, payload SHA, receipt, schema,
    safety flags), so the lane reads the archive through
    ``ResearchArchiveStore.read_exact`` / ``read_latest`` and only projects.
    """

    def __init__(self, data_root: Path, *, ledger_root: Path | None = None) -> None:
        self.data_root = Path(data_root)
        self.ledger_root = Path(ledger_root) if ledger_root is not None else self.data_root.parent / "dispatcher"
        self.store = ResearchArchiveStore(self.data_root)
        self.hourly_store = HourlyResearchStore(self.data_root)

    def _resolve(self, relative: str) -> Path:
        return resolve_owned_path(self.data_root, relative)

    def binding(self) -> dict[str, Any]:
        """Describe the explicitly bound research producer/consumer roots.

        The API uses this read-only identity to make a cross-root deployment
        auditable.  A missing explicit override still binds the lane to the
        server data root; there is no sibling-root search here.
        """
        return {
            "source_id": "V35_RESEARCH_DATA_ROOT",
            "source_root": str(self.data_root),
            "ledger_root": str(self.ledger_root),
            "binding_policy": "EXPLICIT_RESEARCH_DATA_ROOT_OR_SERVER_DATA_ROOT",
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def artifact_binding(
        self,
        archive_date: str,
        *,
        slot: str = "",
        mode: str = "LIVE",
    ) -> dict[str, Any]:
        """Return exact artifact/receipt identity after the store verified it.

        Callers invoke this only after ``read_exact_lane`` or
        ``read_latest_lane`` has validated the manifest and receipt.  The
        method therefore reports the already-consumed physical trio without
        creating a second producer or accepting an unverified file.
        """
        normalized_mode = str(mode).upper()
        if normalized_mode not in {"LIVE", "REPLAY", "BACKFILL"}:
            raise ValueError("research artifact mode is invalid")
        if slot:
            payload_relative = HourlyResearchStore._relative(
                archive_date, slot, normalized_mode
            )
            receipt_relative = HourlyResearchStore._receipt_relative(
                archive_date, slot, normalized_mode
            )
        else:
            payload_relative = ResearchArchiveStore._relative(archive_date)
            receipt_relative = ResearchArchiveStore._receipt_relative(archive_date)
        manifest_path = self._resolve("manifest.json")
        manifest = self.hourly_store._manifest()
        payload_sha = str(manifest.get(payload_relative) or "")
        receipt_sha = ""
        receipt_path = self._resolve(receipt_relative)
        if receipt_path.is_file():
            receipt_sha = _sha256(self.hourly_store._read(receipt_relative))
        verified = bool(payload_sha and receipt_sha and receipt_path.is_file())
        return {
            **self.binding(),
            "status": "VERIFIED" if verified else "CANNOT_CONFIRM",
            "source_date": archive_date,
            "slot": slot,
            "mode": normalized_mode,
            "payload_path": payload_relative,
            "payload_sha256": payload_sha,
            "receipt_path": receipt_relative,
            "receipt_sha256": receipt_sha,
            "manifest_path": "manifest.json",
            "manifest_sha256": _sha256(manifest) if manifest_path.is_file() else "",
        }

    def read_latest_archive(self) -> dict[str, Any] | None:
        return self.store.read_latest()

    def read_exact_archive(self, archive_date: str) -> dict[str, Any] | None:
        return self.store.read_exact(archive_date)

    def list_dates(self) -> list[str]:
        dates = set(self.store.list_dates())
        manifest = self.hourly_store._manifest()
        for relative in manifest:
            parts = relative.replace("\\", "/").split("/")
            if (
                len(parts) == 5
                and parts[:3] == ["research", "hourly", "live"]
                and len(parts[3]) == 8
                and parts[3].isdigit()
            ):
                dates.add(parts[3])
        return sorted(dates, reverse=True)

    @staticmethod
    def today_date() -> str:
        return shanghai_now().strftime("%Y%m%d")

    @staticmethod
    def current_slot() -> str:
        return shanghai_now().strftime("%H%M")

    def _status_receipt_root(self, research_date: str) -> Path:
        # Same explicit binding as the runtime-status API. Never silently read
        # a sibling ledger when the server supplied a different root.
        return self.ledger_root / "receipts" / "live" / research_date

    def _read_status_receipt(
        self, research_date: str, slot: str
    ) -> tuple[dict[str, Any], str] | None:
        # Use the existing ledger's date/mode ordering and integrity check.
        # Random run filenames are not execution chronology. Unverified JSON
        # cannot be projected as a successful hourly run.
        ledger = ExecutionLedger(self.ledger_root)
        try:
            rows = ledger.list_receipts(research_date, mode="LIVE")
            valid, _ = ledger.verify_receipt_chain(research_date, mode="LIVE")
        except (OSError, UnicodeError, ValueError, TypeError, KeyError):
            return None
        if not valid:
            return None
        for payload in reversed(rows):
            if (payload.get("scheduled_date") != research_date
                    or payload.get("target_date") != research_date
                    or str(payload.get("slot") or "") != slot):
                continue
            return dict(payload), f"receipts/live/{research_date}/{slot}"
        return None

    @staticmethod
    def _workload_result(
        receipt: Mapping[str, Any], workload_id: str
    ) -> Mapping[str, Any] | None:
        results = receipt.get("workload_results")
        if not isinstance(results, list):
            return None
        for result in results:
            if not isinstance(result, Mapping):
                continue
            if str(result.get("workload_id") or "") == workload_id:
                return result
        return None

    @staticmethod
    def _status_slot(
        receipt: Mapping[str, Any] | None,
        *,
        slot: str,
        receipt_path: str = "",
    ) -> dict[str, Any]:
        base = {
            "slot": slot,
            "hour": slot[:2],
            "window": f"{slot[:2]}:00-{str((int(slot[:2]) + 1) % 24).zfill(2)}:00",
            "run_id": "",
            "status": "NOT_RUN",
            "receipt_status": "NOT_FOUND",
            "receipt_path": receipt_path,
            "workload_id": "hourly_research",
            "cannot_confirm": ["DISPATCH_RECEIPT_NOT_FOUND"],
        }
        if receipt is None:
            return base
        status = str(receipt.get("status") or "").upper()
        result = ResearchLaneSource._workload_result(receipt, "hourly_research")
        selected = receipt.get("selected_workload_ids")
        selected_hourly = isinstance(selected, list) and "hourly_research" in selected
        if not selected_hourly and result is None:
            base["receipt_status"] = status or "NO_DUE_WORKLOADS"
            base["cannot_confirm"] = ["HOURLY_RESEARCH_NOT_SELECTED"]
            base["receipt_run_id"] = str(receipt.get("run_id") or "")
            return base
        result_status = str((result or {}).get("status") or status or "NOT_RUN").upper()
        base.update(
            {
                "run_id": str(receipt.get("run_id") or ""),
                "status": result_status,
                "receipt_status": status or result_status,
                "cannot_confirm": [],
            }
        )
        stderr = str((result or {}).get("stderr") or "").strip()
        if stderr:
            base["error"] = "执行器记录了错误；请由本机维护者核对原始回执。"
        base["source_verification"] = "LEDGER_CHAIN_VERIFIED_EXECUTOR_DECLARATION"
        return base

    @staticmethod
    def _stdout_payload(result: Mapping[str, Any] | None) -> dict[str, Any]:
        if not isinstance(result, Mapping):
            return {}
        candidates: list[Any] = [result.get("stdout")]
        adapter = result.get("adapter_result")
        if isinstance(adapter, Mapping):
            candidates.append(adapter.get("stdout_tail"))
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            parsed_any = False
            for line in reversed(candidate.splitlines()):
                try:
                    payload = json.loads(line)
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(payload, Mapping):
                    parsed_any = True
                    def find_leaf(value: Mapping[str, Any]) -> dict[str, Any]:
                        if "topic_count" in value or "effective_topic_count" in value:
                            return dict(value)
                        for nested_key in ("adapter_result", "result", "payload", "stdout_tail"):
                            nested = value.get(nested_key)
                            if isinstance(nested, Mapping):
                                found = find_leaf(nested)
                                if found:
                                    return found
                            if isinstance(nested, str):
                                try:
                                    decoded = json.loads(nested)
                                except (TypeError, json.JSONDecodeError):
                                    continue
                                if isinstance(decoded, Mapping):
                                    found = find_leaf(decoded)
                                    if found:
                                        return found
                        return dict(value)

                    return find_leaf(payload)
            if not parsed_any:
                # Dispatcher receipts cap nested stdout at a fixed byte limit;
                # a truncated JSON envelope is still safe to project for the
                # small typed status fields required by this lane.
                recovered: dict[str, Any] = {}
                for key in ("status", "topic_count", "effective_topic_count", "fetched_at", "run_id"):
                    matches = re.findall(
                        rf'\\?"{re.escape(key)}\\?"\s*:\s*(?:"([^"]*)"|(\d+))',
                        candidate,
                    )
                    if not matches:
                        continue
                    value = matches[-1]
                    recovered[key] = value[0] if value[0] else int(value[1])
                if recovered:
                    return recovered
        return {}

    def _status_zsxq(self, research_date: str) -> dict[str, Any]:
        receipt_data = self._read_status_receipt(research_date, "0830")
        if receipt_data is None:
            return {
                "schema_version": "v3_5.zsxq_status_projection.v1",
                "status": "NOT_RUN",
                "receipt_status": "NOT_FOUND",
                "scheduled_slot": "0830",
                "independent": True,
                "topic_count": 0,
                "items": [],
                "cannot_confirm": ["ZSXQ_0830_RECEIPT_NOT_FOUND"],
            }
        receipt, receipt_path = receipt_data
        result = self._workload_result(receipt, "zsxq_0830")
        stdout_payload = self._stdout_payload(result)
        result_status = str(
            stdout_payload.get("status")
            or (result or {}).get("status")
            or receipt.get("status")
            or "NOT_RUN"
        ).upper()
        if result_status == "SUCCEEDED":
            result_status = "READY"
        topic_count = stdout_payload.get("topic_count")
        if isinstance(topic_count, bool) or not isinstance(topic_count, int):
            topic_count = 0
        cannot_confirm = list(stdout_payload.get("cannot_confirm") or [])
        return {
            "schema_version": "v3_5.zsxq_status_projection.v1",
            "status": result_status,
            "receipt_status": str(receipt.get("status") or result_status).upper(),
            "scheduled_slot": "0830",
            "independent": True,
            "source_role": "INDEPENDENT_ZSXQ_0830",
            "run_id": str(stdout_payload.get("run_id") or receipt.get("run_id") or ""),
            "fetched_at": str(stdout_payload.get("fetched_at") or ""),
            "topic_count": topic_count,
            "items": [],
            "receipt_path": receipt_path,
            "cannot_confirm": cannot_confirm,
        }

    def read_status_lane(self, research_date: str) -> dict[str, Any] | None:
        is_today = research_date == self.today_date()
        is_future = research_date > self.today_date()
        current_slot = "0000" if is_future else self.current_slot() if is_today else "2359"
        timeline: list[dict[str, Any]] = []
        for slot in _STATUS_TIMELINE_SLOTS:
            receipt_data = self._read_status_receipt(research_date, slot)
            receipt, receipt_path = receipt_data if receipt_data else (None, "")
            status_row = self._status_slot(
                receipt,
                slot=slot,
                receipt_path=receipt_path,
            )
            if receipt is None and (is_today or is_future) and int(slot) > int(current_slot):
                status_row.update(
                    {
                        "status": "NOT_DUE",
                        "receipt_status": "NOT_DUE",
                        "cannot_confirm": [],
                    }
                )
            timeline.append(status_row)
        zsxq = self._status_zsxq(research_date)
        if (
            zsxq.get("status") == "NOT_RUN"
            and (is_today or is_future)
            and int(current_slot) < 830
        ):
            zsxq.update(
                {
                    "status": "NOT_DUE",
                    "receipt_status": "NOT_DUE",
                    "cannot_confirm": [],
                }
            )
        receipt_root = self._status_receipt_root(research_date)
        # A status-only projection is valid only when today's dispatcher root
        # actually exists.  If there is no receipt evidence at all, callers
        # retain the normal typed NOT_MATERIALIZED response.
        if not receipt_root.is_dir() and zsxq.get("status") == "NOT_RUN":
            return None
        completed = sum(row["status"] in {"SUCCEEDED", "READY"} for row in timeline)
        failed = sum(row["status"] == "FAILED" for row in timeline)
        partial = sum(row["status"] == "PARTIAL" for row in timeline)
        not_run = sum(row["status"] == "NOT_RUN" for row in timeline)
        not_due = sum(row["status"] == "NOT_DUE" for row in timeline)
        latest = next(
            (row["slot"] for row in reversed(timeline) if row["status"] in {"SUCCEEDED", "READY", "PARTIAL"}),
            "",
        )
        return {
            "schema_version": "v3_5.research_intelligence_timeline.v1",
            "date_binding_policy": "explicit_research_date_with_page_context",
            "query_trade_date": research_date,
            "intelligence_date": research_date,
            "schedule_window": "07:00-24:00 (last trigger 23:00 covers 23:00-24:00)",
            "trigger_slots": list(_STATUS_TIMELINE_SLOTS),
            "slot_count": len(timeline),
            "completed_slot_count": completed,
            "failed_slot_count": failed,
            "partial_slot_count": partial,
            "not_run_slot_count": not_run,
            "not_due_slot_count": not_due,
            "latest_slot": latest,
            "latest_run_id": "",
            "latest_slot_matches_query_date": True,
            "source_root": "dispatcher/receipts/live",
            "slots": timeline,
            "zsxq_hourly": {
                "schema_version": "v3_5.zsxq_hourly_status.v1",
                "status": "STATUS_ONLY",
                "items": [],
                "item_count": 0,
                "topic_count": 0,
                "latest_slot": "",
                "slot_count": 0,
                "scheduled_0830": zsxq,
                "cannot_confirm": list(zsxq.get("cannot_confirm") or []),
            },
        }

    def update_diagnostic(self, research_date: str, *, artifact_verified: bool) -> dict[str, Any]:
        """Explain absence using exact-date receipts, not latest or wall-date data.

        Hash-chain integrity is not an independent process/transport witness.
        These fields never turn a status-only lane into an artifact.
        """
        now = shanghai_now()
        day = now.strftime("%Y%m%d")
        slot = now.strftime("%H%M")
        base: dict[str, Any] = {
            "research_date": research_date, "observed_at": now.isoformat(),
            "timezone": "Asia/Shanghai", "first_scheduled_slot": _STATUS_TIMELINE_SLOTS[0],
            "producer": "ops.run_hourly_research", "artifact_verified": artifact_verified,
            "expected_namespace": f"research/hourly/live/{research_date}",
            "receipt_namespace": f"receipts/live/{research_date}",
            "receipt_verification": "NO_EXACT_DATE_RECEIPT", "process_status": "CANNOT_CONFIRM",
            "receipt_run_id": "", "state": "EXECUTION_UNCONFIRMED",
            "message": "已到计划窗口，但无可核验的同日执行回执；上游或执行状态未确认，不等于已执行失败。",
        }
        try:
            ledger = ExecutionLedger(self.ledger_root)
            receipts = ledger.list_receipts(research_date, mode="LIVE")
            receipts = tuple(row for row in receipts
                if row.get("scheduled_date") == research_date and row.get("target_date") == research_date
                and (self._workload_result(row, "hourly_research") is not None
                     or "hourly_research" in (row.get("selected_workload_ids") or [])))
            if receipts:
                valid, _problems = ledger.verify_receipt_chain(research_date, mode="LIVE")
                if not valid:
                    base.update(state="RECEIPT_INVALID", receipt_verification="CANNOT_CONFIRM",
                                message="同日回执完整性校验未通过；不依据该回执确认成功或失败。")
                    return base
                latest = receipts[-1]
                base.update(receipt_verification="LEDGER_CHAIN_VERIFIED",
                            receipt_run_id=str(latest.get("run_id") or ""))
                result = self._workload_result(latest, "hourly_research") or latest
                result_status = str(result.get("status") or "").upper()
                base["receipt_status"] = result_status
                if result_status == "FAILED":
                    base.update(state="FAILED_RECEIPT", message="已核对同日回执链，执行器报告失败；保留旧产物的实际来源日期。")
                    return base
                if not artifact_verified and result_status in {"READY", "SUCCEEDED"}:
                    base.update(state="MATERIALIZATION_MISSING_AFTER_RECEIPT",
                                message="同日回执报告成功，但此数据根没有可核验的同日产物；须核对更新器输出根与物化链。")
                    return base
        except (OSError, ValueError, TypeError, KeyError):
            base.update(state="RECEIPT_INVALID", receipt_verification="CANNOT_CONFIRM",
                        message="同日回执无法安全读取；未回退其他目录或日期。")
            return base
        if artifact_verified:
            base.update(state="EXACT_ARTIFACT_AVAILABLE", message="已读取所示来源日的存储产物；不代表后续小时已经更新。")
        elif research_date > day or (research_date == day and slot < _STATUS_TIMELINE_SLOTS[0]):
            base.update(state="NOT_DUE", message="尚未到该日07:00首个小时研究时点；未产出本身不构成失败。")
        return base

    def read_latest_lane(
        self,
    ) -> tuple[dict[str, Any] | None, str, int]:
        archive = self.store.read_latest()
        hourly = self.hourly_store.read_latest()
        if hourly is not None and (
            archive is None
            or str(hourly["archive_date"]) >= str(archive["archive_date"])
        ):
            date = str(hourly["archive_date"])
            slots = self.hourly_store.list_slots(date, mode="LIVE")
            return hourly, (slots[-1] if slots else ""), len(slots)
        return archive, "", 0

    def read_exact_lane(
        self, archive_date: str
    ) -> tuple[dict[str, Any] | None, str, int]:
        hourly = self.hourly_store.read_latest_for_date(
            archive_date, mode="LIVE"
        )
        if hourly is not None:
            slot, payload = hourly
            slots = self.hourly_store.list_slots(archive_date, mode="LIVE")
            return payload, slot, len(slots)
        return self.store.read_exact(archive_date), "", 0

    def read_latest_event(self) -> dict[str, Any] | None:
        relative = (
            "research_module/runtime_outputs/events/"
            "latest_research_event.json"
        )
        candidate = self._resolve(relative)
        if not candidate.is_file():
            if candidate.exists():
                raise ValueError("invalid owned research event path")
            return None
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
            raise ValueError("invalid owned research event payload") from error
        if not isinstance(payload, Mapping):
            raise ValueError("invalid owned research event payload")
        if (
            payload.get("schema_version") != "v3_5.research_event.v1"
            or payload.get("write_policy") != "read_only"
            or payload.get("recommendation_status") != "RESEARCH_ONLY"
            or payload.get("production_allowed") is not False
            or payload.get("buy_gate_updated") is not False
            or payload.get("orders_sent") is not False
        ):
            raise ValueError("unsafe owned research event")
        event_id = payload.get("event_id")
        if not isinstance(event_id, str) or _EVENT_ID.fullmatch(event_id) is None:
            raise ValueError("owned research event invalid event_id")
        return dict(payload)


__all__ = ["ResearchLaneSource"]
