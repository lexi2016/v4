"""Read-only V4-owned research lane source over verified research archives.

The research decision-desk lane is served exclusively from the explicitly
bound ``data_root`` through exact archives and hourly artifacts plus an
optional V4-owned validated event artifact. Nothing reads the V3 research
module, assistant run logs, or legacy finance/ai sources; no event is ever
synthesized and no sibling root is searched. The bound root is disclosed only
as read-only provenance so a deployment can be audited.
"""
from __future__ import annotations

import json
import re
import hashlib
import gzip
import io
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from domains.research import project_legacy_source_gaps
from infrastructure.data_store import _sha256
from infrastructure.market_time import shanghai_now
from infrastructure.owned_path import resolve_owned_path
from infrastructure.owned_io import SafeRoot
from infrastructure.research_store import HourlyResearchStore, ResearchArchiveStore


_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,255}")
_OFFSET_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})"
)
_STATUS_TIMELINE_SLOTS = tuple(f"{hour:02d}00" for hour in range(7, 24))
_STATUS_RECEIPT_GLOB = "*.dispatch-receipt.json"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _execution_ledger_type():
    """Load scheduling support only for endpoints that actually read it."""
    from infrastructure.scheduling.execution_ledger import ExecutionLedger

    return ExecutionLedger


class ResearchLaneSource:
    """Projections over a verified ``ResearchArchiveStore``.

    The class is deliberately thin: the archive is already validated by
    ``validate_research_archive`` (manifest, payload SHA, receipt, schema,
    safety flags), so the lane reads the archive through
    ``ResearchArchiveStore.read_exact`` / ``read_latest`` and only projects.
    """

    def __init__(self, data_root: Path, *, ledger_root: Path | None = None, a_share_daily_root: Path | None = None,
                 original_chart_binding: Mapping[str, Any] | None = None) -> None:
        self.data_root = Path(data_root)
        self.a_share_daily_root = Path(a_share_daily_root).resolve() if a_share_daily_root is not None else None
        self.original_chart_binding = original_chart_binding
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
            "source_id": "V4_RESEARCH_DATA_ROOT",
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
        ledger = _execution_ledger_type()(self.ledger_root)
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
            ledger = _execution_ledger_type()(self.ledger_root)
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

    @staticmethod
    def _aware_source_time(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        raw = value.strip()
        if not _OFFSET_TIMESTAMP.fullmatch(raw):
            return ""
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return ""
        return raw if parsed.tzinfo is not None and parsed.utcoffset() is not None else ""

    def _bound_source_input(
        self, archive: Mapping[str, Any], *, slot: str
    ) -> dict[str, Any] | None:
        """Read an incoming input only when the verified archive binds its exact bytes."""
        archive_date = str(archive.get("archive_date") or "")
        source_digest = str(archive.get("source_input_sha256") or "").lower()
        if (
            not slot
            or not re.fullmatch(r"\d{8}", archive_date)
            or not re.fullmatch(r"[0-9a-f]{64}", source_digest)
        ):
            return None
        path = self._resolve(f"research/incoming/{archive_date}/{slot}.json")
        try:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != source_digest:
                return None
            source = json.loads(raw.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(source, Mapping):
            return None
        manifest = source.get("source_manifest")
        receipts = manifest.get("source_receipts") if isinstance(manifest, Mapping) else None
        if (
            source.get("schema_version") != "v3_research_lane.v2"
            or source.get("trade_date") != archive_date
            or source.get("slot") != slot
            or not isinstance(manifest, Mapping)
            or manifest.get("trade_date") != archive_date
            or manifest.get("hourly_slot") != slot
            or not isinstance(receipts, list)
            or not receipts
            or any(not isinstance(item, str) or not item.strip() for item in receipts)
            or len(receipts) != len(set(receipts))
        ):
            return None
        return dict(source)

    def _bound_zsxq_status(
        self, source: Mapping[str, Any], *, archive_date: str, slot: str
    ) -> tuple[str, dict[str, Any], str, bool] | None:
        """Authenticate the exact status receipt and its owned fetch artifacts.

        ``source_receipts`` contains an owner-relative status path, not proof by
        itself.  Resolve that exact path below the already-bound data root,
        check the status identity and success fields, and reconcile it with the
        run's summary/fetch-result files before exposing its fetch timestamp.
        """
        manifest = source.get("source_manifest")
        receipts = manifest.get("source_receipts") if isinstance(manifest, Mapping) else None
        expected = (
            f"research_module/runtime_outputs/zsxq_hourly/{archive_date}/{slot}/"
            f"v35_zsxq_hourly_status_{archive_date}_{slot}.json"
        )
        if not isinstance(receipts, list) or receipts != [expected]:
            return None
        try:
            status_path = self._resolve(expected)
            status_raw = status_path.read_bytes()
            status = json.loads(status_raw.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
        if not isinstance(status, Mapping):
            return None
        measured_sha = hashlib.sha256(status_raw).hexdigest()
        receipt_sha_declared = "source_receipt_sha256" in manifest
        declared_sha_value = manifest.get("source_receipt_sha256")
        declared_sha = (
            str(declared_sha_value).lower()
            if isinstance(declared_sha_value, str)
            else ""
        )
        if receipt_sha_declared and (
            not re.fullmatch(r"[0-9a-f]{64}", declared_sha)
            or measured_sha != declared_sha
        ):
            return None
        fetched_at = self._aware_source_time(status.get("fetched_at"))
        cutoff = self._aware_source_time(status.get("source_cutoff"))
        expected_cutoff = self._aware_source_time(
            f"{archive_date[:4]}-{archive_date[4:6]}-{archive_date[6:]}T"
            f"{slot[:2]}:{slot[2:]}:59+08:00"
        )
        fetched_dt = (
            datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).astimezone(_SHANGHAI)
            if fetched_at
            else None
        )
        cutoff_dt = (
            datetime.fromisoformat(cutoff.replace("Z", "+00:00")).astimezone(_SHANGHAI)
            if cutoff
            else None
        )
        expected_cutoff_dt = (
            datetime.fromisoformat(expected_cutoff.replace("Z", "+00:00")).astimezone(_SHANGHAI)
            if expected_cutoff
            else None
        )
        if (
            status.get("schema_version") != "v3_5.zsxq_hourly_delta.v1"
            or status.get("source") != "zsxq"
            or status.get("trade_date") != archive_date
            or status.get("slot") != slot
            or status.get("status_path") != expected
            or status.get("fetch_ok") is not True
            or status.get("status") != "READY"
            or not fetched_at
            or not cutoff
            or not expected_cutoff
            or fetched_dt is None
            or cutoff_dt is None
            or expected_cutoff_dt is None
            or fetched_dt > expected_cutoff_dt
            or cutoff_dt != expected_cutoff_dt
            or fetched_dt.strftime("%Y%m%d") != archive_date
            or status.get("production_allowed") is not False
            or status.get("buy_gate_updated") is not False
            or status.get("orders_sent") is not False
        ):
            return None
        run_id = str(status.get("latest_run_id") or "")
        if not re.fullmatch(rf"{archive_date}_{slot}00_[A-Za-z0-9_-]+", run_id):
            return None
        run_relative = f"external_sources/zsxq_hourly/{run_id}"
        paths = status.get("paths")
        if not isinstance(paths, Mapping) or paths.get("run_dir") != run_relative:
            return None

        def read_run_artifact(value: Any, name: str) -> dict[str, Any] | None:
            expected_relative = f"{run_relative}/{name}"
            if not isinstance(value, str) or not value:
                return None
            candidate = Path(value)
            if candidate.is_absolute():
                try:
                    relative = candidate.absolute().relative_to(
                        self.data_root.resolve()
                    ).as_posix()
                except ValueError:
                    return None
            else:
                relative = value
            if relative != expected_relative:
                return None
            try:
                artifact = self._resolve(relative)
                payload = json.loads(artifact.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return None
            return dict(payload) if isinstance(payload, Mapping) else None

        summary = read_run_artifact(paths.get("summary"), "zsxq_summary.json")
        fetch_result = read_run_artifact(
            paths.get("fetch_result"), "zsxq_recent_topics_fetch_result.json"
        )
        page_count = status.get("page_count")
        topic_count = status.get("topic_count")
        effective_count = status.get("effective_topic_count")
        if (
            summary is None
            or fetch_result is None
            or summary.get("ok") is not True
            or fetch_result.get("ok") is not True
            or fetch_result.get("success") is not True
            or fetch_result.get("page_count") != page_count
            or summary.get("raw_topic_count") != topic_count
            or summary.get("effective_topic_count") != effective_count
        ):
            return None
        return fetched_at, dict(status), measured_sha, receipt_sha_declared

    def _source_receipt_failure_reason(
        self, source_path: str, manifest: Mapping[str, Any], *, archive_date: str, slot: str
    ) -> str:
        try:
            receipt_path = self._resolve(source_path)
            raw = receipt_path.read_bytes()
        except (OSError, ValueError):
            return "SOURCE_RECEIPT_MISSING"
        declared_sha_value = manifest.get("source_receipt_sha256")
        if "source_receipt_sha256" in manifest:
            declared_sha = (
                str(declared_sha_value).lower()
                if isinstance(declared_sha_value, str)
                else ""
            )
            if not re.fullmatch(r"[0-9a-f]{64}", declared_sha):
                return "SOURCE_RECEIPT_SHA_INVALID"
            if hashlib.sha256(raw).hexdigest() != declared_sha:
                return "SOURCE_RECEIPT_SHA_MISMATCH"
        try:
            status = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "SOURCE_RECEIPT_UNREADABLE"
        if not isinstance(status, Mapping):
            return "SOURCE_RECEIPT_INVALID"
        if status.get("status") != "READY" or status.get("fetch_ok") is not True:
            return "SOURCE_RECEIPT_NOT_READY"
        fetched = self._aware_source_time(status.get("fetched_at"))
        cutoff = self._aware_source_time(
            f"{archive_date[:4]}-{archive_date[4:6]}-{archive_date[6:]}T"
            f"{slot[:2]}:{slot[2:]}:59+08:00"
        )
        fetched_dt = (
            datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(_SHANGHAI)
            if fetched else None
        )
        cutoff_dt = (
            datetime.fromisoformat(cutoff.replace("Z", "+00:00")).astimezone(_SHANGHAI)
            if cutoff else None
        )
        if fetched_dt is not None and cutoff_dt is not None and fetched_dt > cutoff_dt:
            return "SOURCE_RECEIPT_FETCHED_AFTER_SLOT"
        return "SOURCE_RECEIPT_RUN_EVIDENCE_UNVERIFIED"

    def _project_bound_source(self, archive: dict[str, Any], *, slot: str) -> dict[str, Any]:
        archive_date = str(archive.get("archive_date") or "")
        source = self._bound_source_input(archive, slot=slot)
        manifest_value = source.get("source_manifest") if source is not None else None
        manifest = manifest_value if isinstance(manifest_value, Mapping) else {}
        declared_receipts = manifest.get("source_receipts")
        receipts = (
            set(declared_receipts)
            if isinstance(declared_receipts, list)
            and all(isinstance(value, str) for value in declared_receipts)
            else set()
        )
        fetched_by_path: dict[str, str] = {}
        receipt_evidence_by_path: dict[str, dict[str, Any]] = {}
        failure_by_path: dict[str, str] = {}
        unavailable_reason = "SOURCE_INPUT_NOT_SHA_BOUND"
        if source is not None:
            unavailable_reason = "SOURCE_RECEIPT_DECLARATION_INVALID"
            for source_path in receipts:
                authenticated = self._bound_zsxq_status(
                    source, archive_date=archive_date, slot=slot
                )
                if authenticated is None or source_path != authenticated[1].get("status_path"):
                    failure_by_path[source_path] = self._source_receipt_failure_reason(
                        source_path, manifest, archive_date=archive_date, slot=slot
                    )
                    continue
                fetched_by_path[source_path] = authenticated[0]
                receipt_evidence_by_path[source_path] = {
                    "measured_status_receipt_sha256": authenticated[2],
                    "source_receipt_sha_binding": (
                        "DECLARED_MATCH"
                        if authenticated[3]
                        else "ORIGINAL_RECEIPT_SHA_NOT_DECLARED"
                    ),
                }

        raw_items = source.get("raw_items") if source is not None else None
        by_path: dict[str, set[str]] = {}
        invalid_paths: set[str] = set()
        raw_times_by_path: dict[str, list[dict[str, Any]]] = {}
        if isinstance(raw_items, list):
            for row in raw_items:
                if not isinstance(row, Mapping) or str(row.get("source_type") or "").strip().lower() != "zsxq":
                    continue
                source_path = str(row.get("source_path") or "").strip()
                if source_path not in receipts:
                    continue
                nested = row.get("raw_payload")
                raw_times_by_path.setdefault(source_path, []).append({
                    "crawl_time": row.get("crawl_time"),
                    "nested_crawl_time": nested.get("crawl_time") if isinstance(nested, Mapping) else None,
                })
                if (
                    not isinstance(nested, Mapping)
                    or row.get("trade_date") != archive_date
                    or nested.get("trade_date") != archive_date
                    or nested.get("slot") != slot
                    or nested.get("source_path") != source_path
                ):
                    invalid_paths.add(source_path)
                    continue
                outer_time = self._aware_source_time(row.get("crawl_time"))
                nested_time = self._aware_source_time(nested.get("crawl_time"))
                receipt_time = fetched_by_path.get(source_path, "")
                if not receipt_time:
                    continue
                if (
                    not outer_time
                    or outer_time != nested_time
                    or outer_time != receipt_time
                ):
                    invalid_paths.add(source_path)
                    continue
                by_path.setdefault(source_path, set()).add(receipt_time)

        fetched_by_path_sha: dict[str, str] = {}
        verified_path_by_sha: dict[str, str] = {}
        receipt_evidence_by_sha: dict[str, dict[str, Any]] = {}
        for source_path, times in by_path.items():
            if source_path not in invalid_paths and len(times) == 1:
                path_sha = hashlib.sha256(source_path.encode("utf-8")).hexdigest()
                fetched_by_path_sha[path_sha] = next(iter(times))
                verified_path_by_sha[path_sha] = source_path
                receipt_evidence_by_sha[path_sha] = receipt_evidence_by_path.get(
                    source_path, {}
                )

        projected_articles: list[dict[str, Any]] = []
        for article in archive.get("articles", []):
            if not isinstance(article, Mapping):
                continue
            projected = dict(article)
            if str(projected.get("source_type") or "").strip().lower() == "zsxq":
                source_path_sha = str(projected.get("source_path_sha256") or "").lower()
                original_capture_times = {
                    key: projected[key]
                    for key in ("fetched_at", "collected_at", "first_seen_at")
                    if key in projected
                }
                source_path = verified_path_by_sha.get(source_path_sha)
                fetched_at = fetched_by_path_sha.get(source_path_sha)
                if fetched_at and source_path:
                    projected["fetched_at"] = fetched_at
                    projected["collected_at"] = fetched_at
                    projected["first_seen_at"] = fetched_at
                    receipt_evidence = receipt_evidence_by_sha.get(source_path_sha, {})
                    original_receipt_sha_unbound = (
                        receipt_evidence.get("source_receipt_sha_binding")
                        == "ORIGINAL_RECEIPT_SHA_NOT_DECLARED"
                    )
                    projected["capture_time_evidence"] = {
                        "status": "VERIFIED",
                        "verification_basis": "EXACT_BOUND_INPUT_AND_RUN_RECEIPT",
                        "source_receipt_path": source_path,
                        **receipt_evidence,
                        "fetched_at": fetched_at,
                        "integrity_status": (
                            "CANNOT_CONFIRM" if original_receipt_sha_unbound else "VERIFIED"
                        ),
                        **(
                            {"cannot_confirm": ["ORIGINAL_RECEIPT_SHA_NOT_DECLARED"]}
                            if original_receipt_sha_unbound
                            else {}
                        ),
                    }
                else:
                    for key in ("fetched_at", "collected_at", "first_seen_at"):
                        projected.pop(key, None)
                    evidence: dict[str, Any] = {
                        "status": "UNVERIFIED",
                        "reason": unavailable_reason,
                    }
                    if original_capture_times:
                        evidence["raw_values"] = original_capture_times
                    matching_path = next(
                        (path for path in receipts if hashlib.sha256(path.encode("utf-8")).hexdigest() == source_path_sha),
                        None,
                    )
                    if matching_path:
                        evidence["source_receipt_path"] = matching_path
                        if matching_path in invalid_paths:
                            evidence["reason"] = "SOURCE_CAPTURE_TIME_MISMATCH"
                        else:
                            evidence["reason"] = failure_by_path.get(
                                matching_path, "SOURCE_CAPTURE_TIME_EVIDENCE_MISSING"
                            )
                        if raw_times_by_path.get(matching_path):
                            evidence["raw_values"] = {
                                **evidence.get("raw_values", {}),
                                "source_capture_times": raw_times_by_path[matching_path],
                            }
                    projected["capture_time_evidence"] = evidence
            projected_articles.append(projected)

        result = dict(archive)
        result["articles"] = projected_articles
        if source is not None and isinstance(source.get("cannot_confirm"), list):
            existing = [
                item for item in archive.get("cannot_confirm", [])
                if isinstance(item, str)
                and not re.fullmatch(r"LEGACY_SOURCE_CANNOT_CONFIRM_COUNT:\d+", item)
            ]
            if any(
                evidence.get("source_receipt_sha_binding")
                == "ORIGINAL_RECEIPT_SHA_NOT_DECLARED"
                for evidence in receipt_evidence_by_sha.values()
            ):
                existing.append("ORIGINAL_RECEIPT_SHA_NOT_DECLARED")
            result["cannot_confirm"] = sorted(
                set(existing) | set(project_legacy_source_gaps(source))
            )
        return result

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
            slot = slots[-1] if slots else ""
            return self._project_bound_source(hourly, slot=slot), slot, len(slots)
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
            return self._project_bound_source(payload, slot=slot), slot, len(slots)
        return self.store.read_exact(archive_date), "", 0

    def _a_product_root(self):
        if self.a_share_daily_root is None:
            return None
        return self.a_share_daily_root / "daily_products/a_share"

    def _original_chart_bytes(self, reference, *, binding=None):
        binding = self.original_chart_binding if binding is None else binding
        if (not isinstance(binding, Mapping) or not isinstance(reference, Mapping)
                or not isinstance(reference.get("path"), str) or not isinstance(reference.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", reference["sha256"])):
            raise ValueError("ORIGINAL_CHART_REFERENCE_INVALID")
        root = Path(binding["artifact_root"])
        path = Path(reference["path"])
        if (not root.is_absolute() or root.resolve(strict=True) != root
                or not path.is_absolute() or not path.is_relative_to(root)
                or path.resolve(strict=True) != path or path.is_symlink()):
            raise ValueError("ORIGINAL_CHART_REFERENCE_OUTSIDE_BOUND_ROOT")
        raw = SafeRoot(root).read_bytes(str(path.relative_to(root)), max_bytes=64 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            raise ValueError("ORIGINAL_CHART_REFERENCE_SHA_DRIFT")
        return raw

    def _a_chart_history_origin(self, product, descriptor, date, symbol):
        """Validate the exact ref delta; read full rows only for this requested stock."""
        chart_origin = descriptor.get("chart_origin_manifest")
        if chart_origin is None:
            return product
        origin_manifest = self._a_product_reference(chart_origin)
        origin = self._a_product_reference(origin_manifest["artifact"])
        excluded = {"row_refs", "artifact", "manifest", "available_dates", "original_charts", "history_sync"}
        declared = descriptor.get("history_updated_symbols")
        if ({k:v for k,v in origin.items() if k not in excluded} != {k:v for k,v in product.items() if k not in excluded}
                or origin_manifest.get("schema_version") != "v4.a_share.daily_product_manifest.v1"
                or origin_manifest.get("data_date") != date or origin_manifest.get("source_generation") != product["source_generation"]
                or origin_manifest.get("input_sha256") != product["source_identity"]["input_sha256"]
                or set(origin["row_refs"]) != set(product["row_refs"])
                or not isinstance(declared, list) or len(declared) != len(set(declared))):
            raise ValueError("ORIGINAL_CHART_NUMERIC_ORIGIN_CONFLICT")
        changed = {s for s in origin["row_refs"] if origin["row_refs"][s] != product["row_refs"][s]}
        if not changed or changed != set(declared) or not changed <= {row["symbol"] for row in product["rows"]}:
            raise ValueError("ORIGINAL_CHART_HISTORY_ORIGIN_DELTA_INVALID")
        if symbol in changed:
            old_row = self._a_product_reference(origin["row_refs"][symbol])
            new_row = self._a_product_reference(product["row_refs"][symbol])
            self._a_daily_checkpoint_binding(new_row, product, symbol, date)
            if ({k:v for k,v in old_row.items() if k not in {"statistics", "historical_coverage"}}
                    != {k:v for k,v in new_row.items() if k not in {"statistics", "historical_coverage"}}):
                raise ValueError("ORIGINAL_CHART_HISTORY_ORIGIN_ROW_CONFLICT")
        return {**origin, "manifest": chart_origin, "artifact": origin_manifest["artifact"]}

    def read_original_chart(self, date, symbol, *, generation=None, input_sha256=None, asset=None, asset_sha256=None):
        """Read only the explicitly bound, completed original-chart artifacts."""
        product = self.read_a_daily_product(date, include_display_names=False)
        current_product = product
        chart_origin = None
        binding = self.original_chart_binding
        if binding is None:
            root = self._a_product_root()
            descriptor = product.get("original_charts")
            if (root is None or not isinstance(descriptor, Mapping)
                    or descriptor.get("numeric_manifest") != product.get("manifest")):
                raise ValueError("ORIGINAL_CHART_OWNER_BINDING_NOT_CONFIGURED")
            binding = {"artifact_root": str(getattr(self, "original_chart_artifact_root", None) or root), "manifest": descriptor.get("manifest"), "receipt": descriptor.get("receipt")}
            chart_origin = descriptor.get("chart_origin_manifest")
            product = self._a_chart_history_origin(product, descriptor, date, symbol)
        if not isinstance(binding, Mapping):
            raise ValueError("ORIGINAL_CHART_BINDING_NOT_CONFIGURED")
        read = lambda ref: self._original_chart_bytes(ref, binding=binding)
        identity = product.get("source_identity") or {}
        if (product.get("status") not in ("READY", "PARTIAL_WITH_ROWS")
                or symbol not in {row.get("symbol") for row in product.get("rows", [])}
                or generation is not None and generation != product.get("source_generation")
                or input_sha256 is not None and input_sha256 != identity.get("input_sha256")):
            raise ValueError("ORIGINAL_CHART_PRODUCT_IDENTITY_CONFLICT")
        config_ref = product["source_config"]
        config_path = Path(config_ref["path"])
        if not config_path.is_absolute() or config_path.resolve(strict=True) != config_path:
            raise ValueError("ORIGINAL_CHART_CONFIG_PATH_INVALID")
        config_raw = SafeRoot(config_path.parent).read_bytes(config_path.name, max_bytes=2 * 1024 * 1024)
        if hashlib.sha256(config_raw).hexdigest() != config_ref["sha256"]:
            raise ValueError("ORIGINAL_CHART_CONFIG_SHA_DRIFT")
        config = json.loads(config_raw)
        if (config["formula"]["sha256"] != "d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac"
                or config["engine"]["sha256"] != "ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c"):
            raise ValueError("ORIGINAL_CHART_FORMULA_OR_ENGINE_CONFLICT")
        manifest = json.loads(read(binding["manifest"]))
        receipt = json.loads(read(binding["receipt"]))
        candidates = {row["symbol"] for row in product["rows"]}
        records = receipt.get("records")
        owner = receipt.get("owner_sidecar") is True
        errors = receipt.get("errors")
        if not isinstance(errors, list) or not isinstance(records, list):
            raise ValueError("ORIGINAL_CHART_COMPLETION_CONFLICT")
        failed = {row["symbol"] for row in errors} if owner else set()
        ready = candidates - failed
        if ((receipt.get("status") not in ("OWNER_CHARTS_COMPLETED", "OWNER_CHARTS_PARTIAL") if owner else receipt.get("status") != "MECHANICAL_247_DELIVERY_PASS")
                or receipt.get("expected") != len(candidates) or receipt.get("verified") != len(ready)
                or not failed <= candidates or len(failed) != len(errors) or (not owner and errors)
                or any(receipt.get(key) != [] for key in ("missing", "extra"))
                or len(records) != len(ready) or {row.get("symbol") for row in records} != ready
                or not isinstance(manifest.get("samples"), Mapping) or set(manifest["samples"]) != ready
                or any(manifest.get(key) is not value or receipt.get(key) is not value
                       for key, value in {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}.items())):
            raise ValueError("ORIGINAL_CHART_COMPLETION_CONFLICT")
        source_binding = receipt["source_binding"]
        expected = {"product": product["artifact"], "manifest": product["manifest"], "config": config_ref,
                    "formula": config["formula"], "engine": config["engine"]}
        if any(source_binding.get(key) != value for key, value in expected.items()):
            raise ValueError("ORIGINAL_CHART_COMPLETION_SOURCE_CONFLICT")
        if symbol in failed:
            raise ValueError("ORIGINAL_CHART_OWNER_TYPED_GAP:" + next(row.get("reason", "UNKNOWN") for row in errors if row["symbol"] == symbol))
        item = manifest["samples"][symbol]
        record = next(row for row in records if row["symbol"] == symbol)
        if (record.get("data_date") != date or record.get("source_generation") != product["source_generation"]
                or record.get("source_input_sha256") != identity["input_sha256"]
                or record.get("formula_sha256") != config["formula"]["sha256"]):
            raise ValueError("ORIGINAL_CHART_RECORD_IDENTITY_CONFLICT")
        refs = {"html": item["html"], "png": item["PNG"], "projection": item["projection"]}
        for kind, key in (("html", "html"), ("png", "PNG"), ("projection", "projection")):
            if any(refs[kind].get(part) != record[key].get(part) for part in ("path", "sha256")):
                raise ValueError("ORIGINAL_CHART_OUTPUT_REFERENCE_CONFLICT")
        raw = {kind: read(ref) for kind, ref in refs.items()}
        if refs["projection"]["path"].endswith(".gz"):
            with gzip.GzipFile(fileobj=io.BytesIO(raw["projection"])) as compressed:
                projection_raw = compressed.read(64 * 1024 * 1024 + 1)
        else:
            projection_raw = raw["projection"]
        if len(projection_raw) > 64 * 1024 * 1024:
            raise ValueError("ORIGINAL_CHART_PROJECTION_SIZE_LIMIT")
        projection = json.loads(projection_raw)
        formula = projection["formula_result"]
        source = projection["source"]
        if owner:
            retained_bytes = read(projection["source_cache"])
            with gzip.GzipFile(fileobj=io.BytesIO(retained_bytes)) as compressed:
                retained_raw = compressed.read(64 * 1024 * 1024 + 1)
            if len(retained_raw) > 64 * 1024 * 1024:
                raise ValueError("ORIGINAL_CHART_RETAINED_SIZE_LIMIT")
            retained = json.loads(retained_raw)
            calendar_raw = json.dumps(retained["calendar"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            if (retained.get("symbol") != symbol or retained.get("data_date") != date
                    or retained.get("identity") != identity or retained.get("config") != config_ref
                    or retained.get("bars_sha256") != projection["source_cache"].get("bars_sha256")
                    or hashlib.sha256(calendar_raw).hexdigest() != projection["source_cache"].get("calendar_sha256")
                    or retained.get("formula_result") != formula
                    or retained.get("bar_dates") != [row.get("trade_date") for row in formula.get("rows", [])]):
                raise ValueError("ORIGINAL_CHART_RETAINED_BINDING_CONFLICT")
        if (projection.get("symbol") != symbol or projection.get("data_date") != date
                or any(projection.get(key) is not value for key, value in
                       {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}.items())
                or source.get("generation_id") != product["source_generation"]
                or source.get("source_input_sha256") != identity["input_sha256"]
                or source.get("price_basis") != identity["basis"]["price_basis"]
                or source.get("volume_basis") != identity["basis"]["volume_basis"]
                or projection.get("source_cache") != record.get("source_cache")
                or record.get("product_row_ref") != product["row_refs"].get(symbol)
                or projection.get("product_row_ref") != product["row_refs"].get(symbol)
                or any(projection["lineage"].get(key) != value for key, value in expected.items())
                or formula.get("formula_sha256") != config["formula"]["sha256"] or formula.get("mode") != "prefix"
                or formula.get("field_count") != 51 or formula.get("drawing_count") != 22
                or len(formula.get("rows", [])) != item.get("rows") or not formula.get("rows")
                or formula["rows"][-1].get("trade_date") != int(date)
                or projection.get("unsupported_drawings") != []):
            raise ValueError("ORIGINAL_CHART_PROJECTION_IDENTITY_CONFLICT")
        answer = {"schema_version": "v4.a_share.original_chart.v1", "status": "READY", "symbol": symbol,
            "data_date": date, "source_generation": product["source_generation"], "input_sha256": identity["input_sha256"],
            "formula_sha256": config["formula"]["sha256"], "engine_sha256": config["engine"]["sha256"],
            "product_manifest": product["manifest"], "product_artifact": product["artifact"],
            "chart_manifest": binding["manifest"], "completion_receipt": binding["receipt"],
            "rows": item["rows"], "values_per_row": 51, "drawings_per_row": 22, "assets": refs,
            "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
        if chart_origin is not None:
            answer.update(product_manifest=current_product["manifest"], product_artifact=current_product["artifact"], chart_numeric_origin_manifest=chart_origin)
        if asset is not None:
            if asset not in refs or asset_sha256 != refs[asset]["sha256"]:
                raise ValueError("ORIGINAL_CHART_ASSET_SHA_CONFLICT")
            answer["_asset_bytes"] = raw[asset]
        return answer

    def _a_product_reference(self, reference):
        root = self._a_product_root()
        if (
            not isinstance(reference, Mapping)
            or not isinstance(reference.get("path"), str)
            or not reference.get("path")
            or not isinstance(reference.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", reference["sha256"])
        ):
            raise ValueError("A_DAILY_PRODUCT_REFERENCE_INVALID")
        path = Path(reference["path"])
        if root is None or not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path or not path.is_relative_to(root):
            raise ValueError("A_DAILY_PRODUCT_REFERENCE_OUTSIDE_BOUND_ROOT")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            raise ValueError("A_DAILY_PRODUCT_REFERENCE_SHA_DRIFT")
        value = json.loads(raw)
        if not isinstance(value, Mapping):
            raise ValueError("A_DAILY_PRODUCT_OBJECT_INVALID")
        if value.get("RESEARCH_ONLY") is not True or any(value.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent")):
            raise ValueError("A_DAILY_PRODUCT_SAFETY_UNBOUND")
        return value

    def _a_daily_checkpoint_binding(self, row, product, symbol, date):
        """Bind the whole stored row, including price statistics, to this product."""
        identity = product["source_identity"]
        qualification = row.get("qualification")
        statistics = row.get("statistics")
        asof = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        if (not isinstance(qualification, Mapping)
                or qualification.get("source_generation") != product["source_generation"]
                or qualification.get("symbol") != symbol or qualification.get("target_date") != date
                or not isinstance(statistics, Mapping) or statistics.get("asof") != asof
                or not isinstance(statistics.get("groups"), list) or not statistics["groups"]):
            raise ValueError("A_DAILY_SYMBOL_DETAIL_SOURCE_IDENTITY_CONFLICT")
        snapshot = identity.get("snapshot")
        if snapshot is not None and (not isinstance(snapshot, Mapping)
                or not snapshot.get("path") or not snapshot.get("sha256")
                or qualification.get("snapshot_path") != snapshot["path"]
                or qualification.get("snapshot_sha256") != snapshot["sha256"]):
            raise ValueError("A_DAILY_SYMBOL_DETAIL_SOURCE_IDENTITY_CONFLICT")
        config_ref = product.get("source_config")
        if (not isinstance(config_ref, Mapping) or not isinstance(config_ref.get("path"), str)
                or not config_ref["path"] or not isinstance(config_ref.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", config_ref["sha256"])):
            raise ValueError("A_DAILY_SYMBOL_DETAIL_FORMULA_IDENTITY_UNBOUND")
        # The producer's explicitly hash-bound config can live outside the
        # product directory. Read only that exact file; never infer a config.
        config_path = Path(config_ref["path"])
        if (not config_path.is_absolute() or config_path.is_symlink()
                or config_path.resolve(strict=True) != config_path):
            raise ValueError("A_DAILY_SYMBOL_DETAIL_FORMULA_IDENTITY_UNBOUND")
        config_raw = config_path.read_bytes()
        if hashlib.sha256(config_raw).hexdigest() != config_ref["sha256"]:
            raise ValueError("A_DAILY_SYMBOL_DETAIL_FORMULA_CONFIG_SHA_DRIFT")
        config = json.loads(config_raw)
        formula = config.get("formula") if isinstance(config, Mapping) else None
        if (not isinstance(formula, Mapping) or not isinstance(formula.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", formula["sha256"])):
            raise ValueError("A_DAILY_SYMBOL_DETAIL_FORMULA_IDENTITY_UNBOUND")
        basis = identity.get("basis")
        expected = {"generation": product["source_generation"], "input": identity["input_sha256"],
                    "asof": asof, "market": symbol[-2:], "formula": formula["sha256"],
                    "basis": basis.get("price_basis") if isinstance(basis, Mapping) else "QFQ_ASOF"}
        for group in statistics["groups"]:
            binding = group.get("source_identity") if isinstance(group, Mapping) else None
            if (not isinstance(binding, Mapping) or group.get("identity_status") != "BOUND"
                    or any(binding.get(key) != value for key, value in expected.items())
                    or not isinstance(binding.get("formula"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", binding["formula"])
                    or not isinstance(group.get("rule_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", group["rule_sha256"])
                    or binding.get("rule_sha256") != group["rule_sha256"]):
                raise ValueError("A_DAILY_SYMBOL_DETAIL_SOURCE_IDENTITY_CONFLICT")

    def _a_daily_display_names(self, index, product, reference, date):
        """Only a hash-bound, same-product display projection may fill empty names."""
        descriptors = index.get("display_names")
        descriptor = descriptors.get(date) if isinstance(descriptors, Mapping) else None
        if descriptor is None:
            return {}, None
        names = self._a_product_reference(descriptor)
        identity = product["source_identity"]
        selector = names.get("selector")
        if (names.get("schema_version") != "v4.a_share.daily_display_names.v1"
                or names.get("numeric_manifest") != reference or names.get("data_date") != date
                or names.get("source_generation") != product["source_generation"]
                or names.get("input_sha256") != identity["input_sha256"]
                or not isinstance(selector, Mapping)
                or selector.get("sha256") != identity.get("selector_artifact_sha256")
                or not isinstance(names.get("items"), Mapping)):
            raise ValueError("A_DAILY_DISPLAY_NAMES_IDENTITY_CONFLICT")
        for code, entry in names["items"].items():
            if (code not in product["row_refs"] or not isinstance(entry, Mapping)
                    or entry.get("symbol") != code or not isinstance(entry.get("name"), str)
                    or not entry["name"].strip() or not isinstance(entry.get("source_date"), str)
                    or not re.fullmatch(r"\d{8}", entry["source_date"]) or entry["source_date"] > date):
                raise ValueError("A_DAILY_DISPLAY_NAME_ROW_INVALID")
        return names["items"], descriptor

    @staticmethod
    def _a_daily_named_row(row, names, descriptor):
        if row is None or (isinstance(row.get("display_name"), str) and row["display_name"].strip()):
            return row
        entry = names.get(row.get("symbol"))
        return ({**row, "display_name": entry["name"], "display_name_source":
                 {"kind": "BOUND_SELECTOR_LAST_NONEMPTY_NAME", "source_date": entry["source_date"], "binding": descriptor}}
                if entry else row)

    def read_a_daily_product(self, date=None, symbol=None, *, include_display_names=True):
        root = self._a_product_root()
        if date is not None and not re.fullmatch(r"\d{8}", date):
            raise ValueError("A_DAILY_DATE_INVALID")
        if symbol is not None and not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", symbol):
            raise ValueError("A_DAILY_SYMBOL_INVALID")
        if root is None or not (root / "index.json").is_file():
            return {"schema_version":"v4.a_share.daily_product.v1", "status":"NOT_MATERIALIZED", "data_date":date, "rows":[], "available_dates":[]}
        index = json.loads((root / "index.json").read_text())
        if not isinstance(index, Mapping) or not isinstance(index.get("dates"), Mapping):
            raise ValueError("A_DAILY_PRODUCT_INDEX_INVALID")
        chosen = date or index.get("latest_date")
        if not isinstance(chosen, str) or not re.fullmatch(r"\d{8}", chosen):
            raise ValueError("A_DAILY_PRODUCT_INDEX_INVALID")
        reference = index.get("dates", {}).get(chosen)
        if reference is None:
            return {"schema_version":"v4.a_share.daily_product.v1", "status":"NOT_MATERIALIZED", "data_date":chosen, "rows":[], "available_dates":sorted(index.get("dates", {}))}
        manifest = self._a_product_reference(reference)
        product = self._a_product_reference(manifest["artifact"])
        identity = product.get("source_identity")
        if (not isinstance(identity, Mapping)
                or not isinstance(product.get("source_generation"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", product["source_generation"])
                or identity.get("generation") != product["source_generation"]
                or str(identity.get("asof")) != chosen
                or not isinstance(identity.get("input_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", identity["input_sha256"])):
            raise ValueError("A_DAILY_PRODUCT_SOURCE_IDENTITY_INVALID")
        if (manifest.get("schema_version") != "v4.a_share.daily_product_manifest.v1" or product.get("schema_version") != "v4.a_share.daily_product.v1"
                or manifest.get("data_date") != chosen or product.get("data_date") != chosen
                or manifest.get("source_generation") != product.get("source_generation")
                or manifest.get("input_sha256") != identity["input_sha256"]
                or manifest.get("sample_only") is not False or product.get("sample_only") is not False
                or manifest.get("processed_count") != product.get("processed_count")):
            raise ValueError("A_DAILY_PRODUCT_GENERATION_DATE_OR_COVERAGE_CONFLICT")
        sync = index.get("history_sync", {}).get(chosen)
        if sync is not None and (sync.get("numeric_manifest") != reference
                or sync.get("source_generation") != product["source_generation"]
                or sync.get("input_sha256") != identity["input_sha256"]
                or not isinstance(sync.get("candidate_symbols"), list)
                or not isinstance(sync.get("completed_symbols"), list)
                or not set(sync["completed_symbols"]) <= set(sync["candidate_symbols"])
                or set(sync["candidate_symbols"]) != {row["symbol"] for row in product["rows"]}):
            raise ValueError("HISTORY_SYNC_IDENTITY_CONFLICT")
        stock_sync = ({**sync, "status":"COMPLETE" if symbol in sync["completed_symbols"] else "IN_PROGRESS"}
                      if sync is not None and symbol in sync["candidate_symbols"] else None)
        names, name_binding = self._a_daily_display_names(index, product, reference, chosen) if include_display_names else ({}, None)
        if symbol is not None:
            row_refs = product.get("row_refs")
            if not isinstance(row_refs, Mapping):
                raise ValueError("A_DAILY_PRODUCT_ROW_REFERENCES_INVALID")
            row_ref = row_refs.get(symbol)
            match = self._a_product_reference(row_ref) if row_ref else None
            if match is not None and (match.get("symbol") != symbol or match.get("data_date") != chosen):
                raise ValueError("A_DAILY_SYMBOL_DETAIL_IDENTITY_CONFLICT")
            if match is not None:
                self._a_daily_checkpoint_binding(match, product, symbol, chosen)
            if match is None:
                rows = product.get("rows")
                if not isinstance(rows, list):
                    raise ValueError("A_DAILY_PRODUCT_ROWS_INVALID")
                if any(isinstance(row, Mapping) and row.get("symbol") == symbol for row in rows):
                    raise ValueError("A_DAILY_SYMBOL_DETAIL_REFERENCE_MISSING")
            return {"status":"READY" if match is not None else "NOT_IN_PROCESSED_UNIVERSE", "data_date":chosen, "source_generation":product["source_generation"], "source_identity":product["source_identity"], "manifest":reference, "row":self._a_daily_named_row(match, names, name_binding), **({"history_sync":stock_sync} if stock_sync is not None else {}), "research_only":True, "production_allowed":False,"buy_gate_updated":False,"orders_sent":False}
        chart_index = index.get("original_charts")
        descriptor = chart_index.get(chosen) if isinstance(chart_index, Mapping) else None
        return {k:v for k,v in product.items() if k != "all_rows"} | {"rows":[self._a_daily_named_row(row, names, name_binding) for row in product["rows"]], "available_dates":sorted(index["dates"]), "manifest":reference, "artifact":manifest["artifact"]} | ({"original_charts": descriptor} if descriptor is not None else {})

    def read_a_daily_company_materials(self, date, symbol, *, generation=None, input_sha256=None):
        """Read one previously received field-whitelisted shard, never its large source pack."""
        product = self.read_a_daily_product(date, include_display_names=False)
        if (not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", str(symbol))
                or symbol not in {row.get("symbol") for row in product.get("rows", [])}
                or generation is not None and generation != product.get("source_generation")
                or input_sha256 is not None and input_sha256 != product.get("source_identity", {}).get("input_sha256")):
            raise ValueError("COMPANY_MATERIALS_PRODUCT_IDENTITY_CONFLICT")
        index = json.loads((self._a_product_root() / "index.json").read_text())
        binding = index.get("company_materials", {}).get(date)
        if binding is None:
            return {"status":"NOT_MATERIALIZED", "symbol":symbol, "data_date":date, "research_only":True,
                    "production_allowed":False, "buy_gate_updated":False, "orders_sent":False}
        manifest = self._a_product_reference(binding)
        if (manifest.get("schema_version") != "v4.a_share.company_materials_index.v1"
                or manifest.get("numeric_manifest") != product["manifest"]
                or manifest.get("source_generation") != product["source_generation"]
                or manifest.get("input_sha256") != product["source_identity"]["input_sha256"]
                or manifest.get("data_date") != date or not isinstance(manifest.get("items"), Mapping)
                or set(manifest["items"]) != {row["symbol"] for row in product["rows"]}):
            raise ValueError("COMPANY_MATERIALS_BINDING_CONFLICT")
        shard = self._a_product_reference(manifest["items"][symbol])
        if (shard.get("schema_version") != "v4.a_share.company_materials.v1"
                or shard.get("symbol") != symbol or shard.get("data_date") != date
                or shard.get("numeric_manifest") != manifest.get("source_numeric_manifest", product["manifest"])
                or shard.get("source_generation") != product["source_generation"]
                or shard.get("input_sha256") != product["source_identity"]["input_sha256"]
                or any(k in shard for k in ("same_event_returns", "price_distribution", "statistics"))):
            raise ValueError("COMPANY_MATERIALS_SHARD_IDENTITY_CONFLICT")
        return {"status":"PARTIAL_RECEIVED", "symbol":symbol, "data_date":date,
                "source_generation":product["source_generation"], "input_sha256":product["source_identity"]["input_sha256"],
                "numeric_manifest":product["manifest"], "materials_manifest":binding,
                "material_ref":manifest["items"][symbol], "materials":shard,
                "research_only":True, "production_allowed":False, "buy_gate_updated":False, "orders_sent":False}

    def read_a_daily_event_cases(self, date, symbol, *, group="original", horizon="d2"):
        if group not in {"original","nav_smallk","nav_pullback","nav_breakout"} or horizon not in {"d2","d5"}:
            raise ValueError("EVENT_CASE_SELECTION_INVALID")
        detail = self.read_a_daily_product(date, symbol)
        if detail.get("status") != "READY":
            raise ValueError("EVENT_CASE_SYMBOL_UNBOUND")
        index = json.loads((self._a_product_root() / "index.json").read_text())
        binding = index.get("event_cases", {}).get(date)
        if binding is None:
            pending = detail.get("history_sync", {}).get("status") == "IN_PROGRESS"
            return {"status":"IN_PROGRESS" if pending else "NOT_MATERIALIZED", "cases":[], "symbol":symbol, "data_date":date,
                    "history_sync":detail.get("history_sync"),
                    "research_only":True,"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}
        manifest = self._a_product_reference(binding)
        if (manifest.get("schema_version") != "v4.a_share.event_cases_index.v1"
                or manifest.get("numeric_manifest") != detail["manifest"]
                or manifest.get("source_generation") != detail["source_generation"]
                or manifest.get("input_sha256") != detail["source_identity"]["input_sha256"]
                or manifest.get("data_date") != date or not isinstance(manifest.get("items"), Mapping)):
            raise ValueError("EVENT_CASE_MANIFEST_CONFLICT")
        row_ref = manifest["items"].get(symbol)
        if row_ref is None:
            pending = detail.get("history_sync", {}).get("status") == "IN_PROGRESS"
            return {"status":"IN_PROGRESS" if pending else "NOT_MATERIALIZED", "cases":[], "symbol":symbol, "data_date":date,
                    "history_sync":detail.get("history_sync"),
                    "research_only":True,"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}
        shard = self._a_product_reference(row_ref)
        stats_raw = json.dumps(detail["row"]["statistics"],ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
        if (shard.get("schema_version") != "v4.a_share.event_cases.v1" or shard.get("symbol") != symbol
                or shard.get("data_date") != date or shard.get("numeric_manifest") != manifest.get("case_numeric_origins", {}).get(symbol, detail["manifest"])
                or shard.get("source_generation") != detail["source_generation"]
                or shard.get("input_sha256") != detail["source_identity"]["input_sha256"]
                or shard.get("statistics_sha256") != hashlib.sha256(stats_raw).hexdigest()):
            raise ValueError("EVENT_CASE_SHARD_CONFLICT")
        selected = shard.get("groups", {}).get(group, {}).get(horizon)
        if not isinstance(selected, Mapping) or not isinstance(selected.get("cases"), list):
            raise ValueError("EVENT_CASE_GROUP_UNAVAILABLE")
        return {"status":"READY", "symbol":symbol, "data_date":date, "group":group, "horizon":horizon,
                "numeric_manifest":detail["manifest"], "source_generation":detail["source_generation"],
                "source_identity":detail["source_identity"], "projection":shard["projection"],
                "case_ref":row_ref, **selected,
                "research_only":True,"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}

    def read_a_daily_latest_event(self):
        root = self._a_product_root()
        if root is None or not (root / "events/latest.json").is_file():
            return None
        event = json.loads((root / "events/latest.json").read_text())
        if not isinstance(event, Mapping):
            raise ValueError("A_DAILY_EVENT_OBJECT_INVALID")
        if event.get("schema_version") != "v4.a_share.daily_completion.v1" or event.get("RESEARCH_ONLY") is not True or any(event.get(k) is not False for k in ("production_allowed","buy_gate_updated","orders_sent")):
            raise ValueError("A_DAILY_EVENT_SCHEMA_OR_SAFETY_INVALID")
        event_manifest = event.get("manifest")
        if not isinstance(event_manifest, Mapping):
            raise ValueError("A_DAILY_EVENT_MANIFEST_REFERENCE_INVALID")
        manifest = self._a_product_reference(event_manifest)
        if (event.get("artifact") != manifest.get("artifact") or any(event.get(k) != manifest.get(k) for k in ("data_date","source_generation","input_sha256","processed_count","source_universe_count","status"))):
            raise ValueError("A_DAILY_EVENT_MANIFEST_IDENTITY_CONFLICT")
        if "original_charts" in event:
            product = self.read_a_daily_product(event["data_date"])
            if event["original_charts"] != product.get("original_charts"):
                raise ValueError("A_DAILY_EVENT_CHART_DESCRIPTOR_CONFLICT")
        return event

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
