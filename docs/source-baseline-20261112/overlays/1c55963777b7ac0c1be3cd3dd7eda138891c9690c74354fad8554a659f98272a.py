"""One explicit operator request, existing collectors, and an owned receipt.

No scheduler or market-data source lives here. Roots are bound by the server;
the browser supplies only an exact date and one of two frozen targets.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo

from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.interprocess_lock import _pid_is_alive
from infrastructure.owned_io import SafeRoot

STAGE8 = "STAGE_1545_1555"
TZ = ZoneInfo("Asia/Shanghai")
SAFETY = {"RESEARCH_ONLY": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}
TERMINAL = {"READY", "REUSED", "SNAPSHOT_CAPTURED", "PARTIAL", "CANNOT_CONFIRM"}
_CONFIG_KEYS = {"candidate_acquisition_root", "raw_root", "selection_root", "receipt_root",
                "hk_d1_root", "preselection_source_root", "hk_second_filter_root",
                "hk_full_universe_root", "hk_auction_root", "hk_stage_replay_root",
                "shared_data_root", "python_path", "v4_research_data_root", "v4_morning_news_root"}

# Fixed program, server-bound interpreter/cwd, JSON stdin. No shell or client code.
_OWNER_PROGRAM = '''
import json, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path.cwd()))
from stage_center.runner import StageCenterRunner, build_production_config
request = json.loads(sys.stdin.read(65536))
runner = StageCenterRunner(build_production_config(**request["config"]))
now = datetime.now(ZoneInfo("Asia/Shanghai"))
date = request["date"]
stage = "STAGE_1545_1555"
if request["phase"] == "PRECAPTURE":
    if date != now.strftime("%Y%m%d") or not "15:50:00" <= now.strftime("%H:%M:%S") <= "15:55:00":
        raise ValueError("CAPTURE_WINDOW_EXPIRED")
    result = runner._prepare_hk_active_snapshots(date, now, stage_id=stage, historical_backfill=False)
else:
    if date > now.strftime("%Y%m%d") or (date == now.strftime("%Y%m%d") and now.strftime("%H:%M:%S") < "15:55:05"):
        raise ValueError("STAGE_CUTOFF_NOT_REACHED")
    result = runner.tick(date, now, stage_id=stage, historical_backfill=True, historical_markets=("HK_CONNECT",))
print("V4_MANUAL_COLLECTION_RESULT=" + json.dumps(result, ensure_ascii=False, allow_nan=False))
'''


def _reason_codes(values) -> list[str]:
    """Keep audit codes and simple stage/count qualifiers, never provider bodies."""
    result = []
    for value in values:
        parts = str(value).split(":")
        code = parts[0] if re.fullmatch(r"[A-Z][A-Z0-9_]+", parts[0]) else "SOURCE_VALIDATION_GAP"
        if len(parts) > 1 and re.fullmatch(r"[A-Z0-9_/-]{1,80}", parts[1]):
            code += ":" + parts[1]
        if code not in result:
            result.append(code)
    return result


class CollectionRefused(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class ManualCollectionService:
    def __init__(self, data_root: Path, *, stage_selection_root: Path | str | None = None,
                 stage_config_path: Path | str | None = None, state_root: Path | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.data_root = Path(data_root)
        self.selection_root = stage_selection_root
        self.state_root = state_root or self.data_root.parent / "manual_collection"
        self.clock = clock or (lambda: datetime.now(TZ))
        self.stage_config: dict[str, str] | None = None
        self.stage_owner_root: str | None = None
        self.stage_owner_python: str | None = None
        self.owner_identity: dict[str, Any] = {}
        self.config_error = ""
        self.config_sha = ""
        if stage_config_path:
            try:
                raw = Path(stage_config_path).read_bytes()
                config = json.loads(raw)
                if not isinstance(config, dict):
                    raise ValueError("invalid server binding")
                owner_root = config.pop("stage_owner_root", None)
                owner_python = config.pop("stage_owner_python", None)
                if bool(owner_root) != bool(owner_python):
                    raise ValueError("incomplete stage owner")
                if owner_root and (not isinstance(owner_root, str) or not Path(owner_root).is_absolute()
                                   or not Path(owner_root).is_dir() or not isinstance(owner_python, str)
                                   or not Path(owner_python).is_absolute() or not Path(owner_python).is_file()):
                    raise ValueError("invalid stage owner")
                if owner_root:
                    owner_path = Path(owner_root)
                    owner_config_raw = (owner_path / "stage_center_tick_config.json").read_bytes()
                    release_id = json.loads(owner_config_raw).get("release_id")
                    if release_id != owner_path.parent.name:
                        raise ValueError("stage owner release identity mismatch")
                    source_names = ("stage_center/runner.py", "stage_center/hk_stage8/snapshot.py",
                                    "stage_center/hk_stage8/precapture.py")
                    self.owner_identity = {"source_root": owner_root, "python": owner_python,
                        "release_id": release_id, "authority_config_sha256": hashlib.sha256(owner_config_raw).hexdigest(),
                        "source_sha256": {name: hashlib.sha256((owner_path / name).read_bytes()).hexdigest() for name in source_names}}
                if (not isinstance(config, dict) or set(config) - _CONFIG_KEYS
                        or not {"candidate_acquisition_root", "raw_root", "selection_root", "receipt_root",
                                "hk_d1_root", "shared_data_root", "python_path"}.issubset(config)
                        or any(not isinstance(value, str) or not Path(value).is_absolute()
                               for value in config.values())):
                    raise ValueError("invalid server binding")
                if stage_selection_root is None or Path(config["selection_root"]).resolve() != Path(stage_selection_root).resolve():
                    raise ValueError("selection root differs from read API")
                self.stage_config = config
                self.stage_owner_root, self.stage_owner_python = owner_root, owner_python
                self.config_sha = hashlib.sha256(raw).hexdigest()
            except (OSError, ValueError, TypeError):
                self.config_error = "阶段采集服务端绑定无效，需核对当前采集 owner。"

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("server clock must be timezone aware")
        return value.astimezone(TZ)

    def _validate(self, date: str, target: str, stage_id: str | None) -> str:
        if not isinstance(date, str) or not re.fullmatch(r"\d{8}", date):
            raise CollectionRefused("INVALID_DATE", "请选择有效的交易日期。")
        try:
            datetime.strptime(date, "%Y%m%d")
        except ValueError as error:
            raise CollectionRefused("INVALID_DATE", "交易日期无效。") from error
        now = self._now()
        if date > now.strftime("%Y%m%d"):
            raise CollectionRefused("FUTURE_DATE", "未来日期不能补采。")
        if target not in {"HK_STAGE", "HK_CLOSE"} or (target == "HK_STAGE" and stage_id != STAGE8) or (target == "HK_CLOSE" and stage_id is not None):
            raise CollectionRefused("TARGET_UNSUPPORTED", "本次仅支持港股阶段8和港股收盘补采。")
        from stage_center.calendar import resolve_market_states, TradingDayState
        state = resolve_market_states(date).get("hk_securities")
        if state != TradingDayState.FULL_TRADING_DAY:
            raise CollectionRefused("HK_CALENDAR_UNAVAILABLE", "该日期为港股休市、半日市或日历未确认，本入口不能补采。")
        if target == "HK_CLOSE":
            return "CLOSE"
        if date == now.strftime("%Y%m%d") and "15:50:00" <= now.strftime("%H:%M:%S") <= "15:55:00":
            return "PRECAPTURE"
        if date == now.strftime("%Y%m%d") and now.strftime("%H:%M:%S") < "15:50:00":
            raise CollectionRefused("CAPTURE_WINDOW_NOT_REACHED", "阶段8采集窗口为当日15:50至15:55，尚未到达。")
        if date == now.strftime("%Y%m%d") and now.strftime("%H:%M:%S") < "15:55:05":
            raise CollectionRefused("STAGE_CUTOFF_NOT_REACHED", "阶段8选股截止时间15:55:05尚未到达，不能提前回放。")
        return "REPLAY"

    def _io(self) -> SafeRoot:
        return SafeRoot(self.state_root)

    def _write(self, relative: str, value: Mapping[str, Any]) -> None:
        self._io().write_bytes(relative, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                                    allow_nan=False) + "\n").encode())

    def read(self, job_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise FileNotFoundError("unknown collection job")
        job = json.loads(self._io().read_bytes(f"jobs/{job_id}.json", max_bytes=256 * 1024))
        if job["status"] not in TERMINAL and not _pid_is_alive(job.get("owner_pid", 0)):
            job["recovery_required"] = True
            if _pid_is_alive(job.get("child_pid", 0)):
                job.update(message="原服务已退出，采集owner仍在执行；保留锁定任务，需核对最终回执。")
            else:
                job.update(status="CANNOT_CONFIRM", message="服务中断，未取得有效最终回执；保留原产物，需核对后恢复。",
                           cannot_confirm=["INTERRUPTED_COLLECTION_REQUIRES_RECONCILIATION"])
        return job

    def start(self, date: str, target: str, stage_id: str | None = None) -> dict[str, Any]:
        phase = self._validate(date, target, stage_id)
        key = hashlib.sha256(f"{date}:{target}:{stage_id}:{phase}".encode()).hexdigest()
        with owned_interprocess_lock(self.state_root / ".claim", timeout_seconds=1,
                                     timeout_message="COLLECTION_BUSY"):
            try:
                pointer = json.loads(self._io().read_bytes(f"slots/{key}.json"))
                prior = self.read(pointer["job_id"])
            except FileNotFoundError:
                prior = None
            if prior is not None:
                # An interrupted/unknown attempt is kept for operator reconciliation.
                # Explicit retries after a terminal failure are bounded and rate limited.
                if (prior.get("recovery_required") or prior["status"] != "CANNOT_CONFIRM" or prior["attempt"] >= 3
                        or self._now() < datetime.fromisoformat(prior["retry_after"])):
                    return prior
            try:
                active = json.loads(self._io().read_bytes("owner_active.json"))
                if _pid_is_alive(active.get("pid", 0)):
                    raise CollectionRefused("COLLECTION_BUSY", "既有采集owner仍在执行，请查看原任务。")
            except FileNotFoundError:
                pass
            lease = owned_interprocess_lock(self.state_root / ".execution", timeout_seconds=0.01,
                                            timeout_message="COLLECTION_BUSY")
            try:
                lease.__enter__()
            except ValueError as error:
                raise CollectionRefused("COLLECTION_BUSY", "已有补采正在执行，请稍后查看结果。") from error
            now = self._now()
            job = {"job_id": uuid4().hex, "trade_date": date, "target": target,
                   "stage_id": stage_id, "phase": phase, "status": "PENDING",
                   "step": "等待执行", "attempt": 1 if prior is None else prior["attempt"] + 1,
                   "created_at": now.isoformat(), "deadline_at": (now + timedelta(minutes=5)).isoformat(),
                   "retry_after": (now + timedelta(seconds=30)).isoformat(),
                   "message": "补采请求已登记。", "cannot_confirm": [], "result": {},
                   "origin": "CONTROLLED_MANUAL_COLLECTION", "natural_verified": False,
                   "owner_pid": os.getpid(),
                   "stage_config_sha256": self.config_sha, **SAFETY}
            job["stage_owner_identity"] = self.owner_identity
            try:
                self._write(f"jobs/{job['job_id']}.json", job)
                self._write(f"slots/{key}.json", {"job_id": job["job_id"]})
                threading.Thread(target=self._run, args=(dict(job), lease), daemon=True,
                                 name=f"manual-collection-{job['job_id'][:8]}").start()
            except BaseException:
                lease.__exit__(None, None, None)
                raise
            return job

    def _step(self, job: dict[str, Any], step: str) -> None:
        if self._now() > datetime.fromisoformat(job["deadline_at"]):
            raise CollectionRefused("COLLECTION_BUDGET_EXCEEDED", "补采超过本次时间预算，保留已完成产物，未继续后续步骤。")
        job.update(status="RUNNING", step=step)
        self._write(f"jobs/{job['job_id']}.json", job)

    def _run(self, job: dict[str, Any], lease: Any) -> None:
        try:
            self._validate(job["trade_date"], job["target"], job["stage_id"])
            if job["target"] == "HK_CLOSE":
                self._close(job)
            else:
                self._stage(job)
        except CollectionRefused as error:
            job.update(status="CANNOT_CONFIRM", message=error.message, cannot_confirm=[error.code])
        except Exception as error:
            # Do not reflect provider exception bodies, filesystem roots or credentials.
            code = "EXISTING_COLLECTION_CHAIN_FAILED"
            if isinstance(error, ValueError):
                text = str(error)
                token = text.split(":", 1)[0]
                if re.fullmatch(r"[A-Z][A-Z0-9_]+", token):
                    code = token
                elif "restricted to the current trade date" in text:
                    code = "HISTORICAL_CLOSE_SNAPSHOT_UNAVAILABLE"
                elif "final close cutoff not reached" in text:
                    code = "HK_CLOSE_CUTOFF_NOT_REACHED"
                elif "full HK Connect coverage required" in text:
                    code = "HK_CLOSE_COVERAGE_INCOMPLETE"
            elif isinstance(error, RuntimeError) and str(error).startswith("FUTU_"):
                code = str(error).split(":", 1)[0]
            messages = {
                "HISTORICAL_CLOSE_SNAPSHOT_UNAVAILABLE": "历史日缺少可复用收盘快照，不能用今日行情补成历史收盘。",
                "HK_CLOSE_CUTOFF_NOT_REACHED": "当日16:10收盘采集时间尚未到达。",
                "HK_CLOSE_COVERAGE_INCOMPLETE": "收盘采集未覆盖完整港股通股票池，未发布不完整快照。",
                "FUTU_GET_MARKET_SNAPSHOT_FAILED": "行情快照请求失败，请核对行情连接后再重试。",
                "FUTU_GET_PLATE_STOCK_FAILED": "港股通股票池请求失败，请核对行情连接后再重试。",
            }
            job.update(status="CANNOT_CONFIRM", message=messages.get(code, "既有采集链未通过校验，未确认补齐。"), cannot_confirm=[code],
                       error_type=type(error).__name__)
        finally:
            job["finished_at"] = self._now().isoformat()
            try:
                self._write(f"jobs/{job['job_id']}.json", job)
            finally:
                lease.__exit__(None, None, None)

    def _close(self, job: dict[str, Any]) -> None:
        from ops.collect_hkconnect_close_snapshot import collect_close_snapshot
        from ops.build_close_review import build_close_review
        from infrastructure.review_store import ReviewStore
        self._step(job, "核对缓存 / 采集港股通收盘数据")
        capture = collect_close_snapshot(job["trade_date"], data_root=self.data_root, now=self._now())
        snapshot = capture["snapshot"]
        job["result"] = {"snapshot_status": snapshot.get("status"),
                         "snapshot_publication": capture["publication"].get("status"),
                         "snapshot_sha256": capture["publication"].get("sha256"),
                         "same_date_row_count": snapshot.get("same_date_row_count"),
                         "universe_count": snapshot.get("universe_count"),
                         "coverage_ratio": snapshot.get("coverage_ratio")}
        self._step(job, "读取 / 生成收盘复盘")
        existing = ReviewStore(self.data_root).read_reference(job["trade_date"])
        if existing is not None:
            if existing.get("close_source_sha256") != capture["publication"].get("sha256"):
                raise CollectionRefused("EXISTING_REVIEW_SOURCE_MISMATCH", "已有复盘与当前收盘快照的来源SHA不同，保留原记录，需核对。")
            review, publication = existing, {"status": "IDEMPOTENT_REUSE"}
        else:
            built = build_close_review(self.data_root, job["trade_date"], stage_selection_root=self.selection_root)
            review, publication = built["review"], built["publication"]
        status = review.get("status")
        reasons = _reason_codes(review.get("cannot_confirm") or [])
        job["result"].update(review_status=status, review_publication=publication.get("status"),
                             missing_stages=list(review.get("missing_stages") or []))
        if status in {"READY", "MODEL_REVIEW_READY"} and not reasons:
            job.update(status="REUSED" if existing is not None else "READY",
                       message="已复用完整收盘数据及复盘。" if existing is not None else "收盘采集和复盘已生成。")
        else:
            job.update(status="PARTIAL" if status in {"READY", "PARTIAL", "MODEL_REVIEW_READY", "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE"} else "CANNOT_CONFIRM",
                       message="收盘数据已取得，复盘仍有缺口。", cannot_confirm=reasons)

    def _new_runner(self):
        from stage_center.runner import StageCenterRunner, build_production_config
        if self.stage_config is None:
            raise CollectionRefused("STAGE_SERVER_BINDING_UNAVAILABLE",
                                    self.config_error or "当前阶段采集 owner 尚未绑定。")
        return StageCenterRunner(build_production_config(**self.stage_config))

    def _invoke_owner(self, job: dict[str, Any]):
        if self.stage_config is None:
            raise CollectionRefused("STAGE_SERVER_BINDING_UNAVAILABLE", "阶段采集owner绑定未确认。")
        env = dict(os.environ)
        env.pop("PYTHONHOME", None)
        root = Path(self.stage_owner_root)
        for name, expected in self.owner_identity["source_sha256"].items():
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
                raise CollectionRefused("STAGE_OWNER_SOURCE_CHANGED", "固定采集owner源码发生变化，需重新核对绑定。")
        if hashlib.sha256((root / "stage_center_tick_config.json").read_bytes()).hexdigest() != self.owner_identity["authority_config_sha256"]:
            raise CollectionRefused("STAGE_OWNER_CONFIG_CHANGED", "固定采集owner配置发生变化，需重新核对绑定。")
        env.update(PYTHONPATH=os.pathsep.join((str(root / "upstreams"), str(root))),
                   V4_APP_ROOT=str(root), REVIEW_CORE_PACKAGE_ROOT=str(root / "upstreams"),
                   V4_REVIEW_CORE_PACKAGE_ROOT=str(root / "upstreams"),
                   V4_RELEASE_ID=self.owner_identity["release_id"])
        process = subprocess.Popen([self.stage_owner_python, "-c", _OWNER_PROGRAM],
                                   cwd=self.stage_owner_root, env=env, shell=False,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        job["child_pid"] = process.pid
        active = {"pid": process.pid, "job_id": job["job_id"]}
        try:
            # Child blocks on stdin until its durable ownership is recorded.
            self._write("owner_active.json", active)
            self._write(f"jobs/{job['job_id']}.json", job)
        except BaseException:
            process.stdin.close()  # EOF refuses execution; never kill a healthy collector.
            raise
        request = json.dumps({"config": self.stage_config, "date": job["trade_date"], "phase": job["phase"]}).encode()
        try:
            # The HTTP request has already returned a job id. The sole worker
            # keeps its lease while the owner runs, including slow healthy calls.
            stdout, _stderr = process.communicate(request)
            prefix = b"V4_MANUAL_COLLECTION_RESULT="
            lines = [line[len(prefix):] for line in stdout.splitlines() if line.startswith(prefix)]
            if process.returncode != 0 or len(lines) != 1 or len(lines[0]) > 1024 * 1024:
                raise CollectionRefused("STAGE_OWNER_RESULT_UNAVAILABLE", "采集owner未返回有效最终结果，未确认补齐。")
            result = json.loads(lines[0])
            if not isinstance(result, (dict, list)):
                raise CollectionRefused("STAGE_OWNER_RESULT_INVALID", "采集owner返回结果格式无效。")
            return result
        finally:
            raw = (json.dumps(active, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
            self._io().unlink_if_same("owner_active.json", raw)

    def _stage(self, job: dict[str, Any]) -> None:
        if self.stage_config is None:
            raise CollectionRefused("STAGE_SERVER_BINDING_UNAVAILABLE",
                                    self.config_error or "当前阶段采集owner尚未绑定，尚不能核对该日期缓存。")
        if job["phase"] == "PRECAPTURE":
            self._step(job, "采集阶段8原窗口快照")
            if self._validate(job["trade_date"], "HK_STAGE", STAGE8) != "PRECAPTURE":
                raise CollectionRefused("CAPTURE_WINDOW_EXPIRED", "阶段8快照窗口已结束，不能用晚间行情补采。")
            captured = (self._invoke_owner(job) if self.stage_owner_root else
                        self._new_runner()._prepare_hk_active_snapshots(
                            job["trade_date"], self._now(), stage_id=STAGE8, historical_backfill=False))
            if not captured:
                raise CollectionRefused("CAPTURE_WINDOW_UNAVAILABLE", "原窗口采集未产生有效回执。")
            row = captured[0]
            if any(row.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
                raise CollectionRefused("SNAPSHOT_SAFETY_FLAGS_INVALID", "阶段快照研究安全边界未确认。")
            job["result"] = {key: row.get(key) for key in ("status", "active_snapshot_sha256", "requested_rows",
                                                         "returned_rows", "write_performed")}
            if row.get("status") in {"READY", "IDEMPOTENT_REUSE", "NOOP_ALREADY_VERIFIED"}:
                job.update(status="SNAPSHOT_CAPTURED", message="阶段快照已采集；尚未生成阶段选股结果。")
            else:
                job.update(status="PARTIAL" if row.get("status") == "PARTIAL_WITH_ROWS" else "CANNOT_CONFIRM", message="原窗口快照仍有缺口，未确认补齐。",
                           cannot_confirm=_reason_codes(row.get("cannot_confirm") or ["SNAPSHOT_NOT_READY"]))
            return
        self._step(job, "核对阶段8精确历史回放")
        config = self.stage_config or {}
        replay_root = config.get("hk_stage_replay_root")
        name = f"hkconnect_rtdata_stage_replay_{job['trade_date']}_{STAGE8}.csv"
        replay = Path(replay_root) / job["trade_date"] / STAGE8 / name if replay_root else None
        if replay is None or not replay.is_file():
            raise CollectionRefused("HK_STAGE8_EXACT_RTDATA_REPLAY_UNAVAILABLE",
                                    "原15:50至15:55窗口已结束，未找到可追溯的阶段8精确回放；晚间行情不能补成原时段。")
        replay_raw = SafeRoot(Path(replay_root)).read_bytes(f"{job['trade_date']}/{STAGE8}/{name}", max_bytes=16 * 1024 * 1024)
        replay_sha = hashlib.sha256(replay_raw).hexdigest()
        self._step(job, "用既有精确回放生成独立补采结果")
        result = (self._invoke_owner(job) if self.stage_owner_root else
                  self._new_runner().tick(job["trade_date"], self._now(), stage_id=STAGE8,
                                          historical_backfill=True, historical_markets=("HK_CONNECT",)))
        after_raw = SafeRoot(Path(replay_root)).read_bytes(f"{job['trade_date']}/{STAGE8}/{name}", max_bytes=16 * 1024 * 1024)
        if hashlib.sha256(after_raw).hexdigest() != replay_sha:
            raise CollectionRefused("REPLAY_INPUT_CHANGED", "精确回放输入在本次运行期间发生变化，保留产物，未确认补齐。")
        if any(result.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
            raise CollectionRefused("RUNNER_SAFETY_FLAGS_INVALID", "阶段回放返回的研究安全边界未确认。")
        market = (result.get("markets") or {}).get("HK_CONNECT") or {}
        status = market.get("selection_status") or market.get("status") or result.get("status")
        job["result"] = {"selection_status": status, "backfill_run_id": result.get("backfill_run_id"),
                         "run_id": market.get("run_id"), "selected_rows": market.get("selected_rows"),
                         "source_rows": market.get("source_rows"), "selection_mode": "BACKFILL",
                         "natural_verified": False, "input_replay_sha256": replay_sha}
        reasons = _reason_codes(market.get("cannot_confirm") or result.get("cannot_confirm") or [])
        job.update(status="PARTIAL" if status in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS"} else "CANNOT_CONFIRM",
                   message="历史观察结果已生成，保留为BACKFILL；原自然阶段回执不变。" if status in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS"}
                   else "精确回放未通过既有阶段校验。", cannot_confirm=reasons)
