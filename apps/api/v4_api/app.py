from datetime import datetime
import hashlib
import importlib
import importlib.util
import inspect
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import BoundedSemaphore
import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from apps.api.v4_api.baimao_router import create_baimao_router
from apps.api.v4_api.preselection_router import create_preselection_router
from apps.api.v4_api.preselection_service import PreselectionPoolService
from apps.api.v4_api.research_lane_router import create_research_lane_router
from apps.api.v4_api.runtime_router import create_runtime_router
from apps.api.v4_api.runtime_graph_router import create_runtime_graph_router
from apps.api.v4_api.review_router import create_review_router
from apps.api.v4_api.manual_collection_router import create_manual_collection_router
from apps.api.v4_api.research_router import create_research_router
from contracts.stages import FROZEN_STAGE_IDS, STAGE_DEFINITIONS
from contracts.trading_safety import TRADING_SAFETY_FLAGS
from domains.preselection import date_catalog
from domains.stage_input_producer import ReadOnlyQuoteProvider, StageInputProducer
from domains.stages import StageRunner
from infrastructure.data_store import NativeDataStore
from infrastructure.futu_quote_provider import FutuQuoteProvider
from infrastructure.hkconnect_stage_replay_provider import HkConnectStageReplayProvider
from infrastructure.opening_second_filter_store import OpeningSecondFilterStore
from infrastructure.review_store import ReviewStore
from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.stage_quote_provider import StageQuoteProvider
from infrastructure.stage_store import StageStore
from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider
from stage_center.consumer import StageSelectionConsumer
from stage_center.research_read_binding import ApprovedResearchReadBinding, ResearchReadError
from apps.api.v4_api.evidence.loader import (
    row_dicts as _evidence_row_dicts,
    tuple_keyed as _evidence_tuple_keyed,
)

_STAGE_RESEARCH_READER_SHA256 = "c33a1452df34c7dcc7fc96e61b1177079c54c467164b7cb957d773f2d2e0ba05"


# One process-wide pool and admission limit: timed-out reads cannot spawn a
# new pool per request or leave an unbounded queue behind stalled readers.
_STAGE_BATCH_CAPACITY = 8
_stage_batch_executor = ThreadPoolExecutor(
    max_workers=_STAGE_BATCH_CAPACITY, thread_name_prefix="v4-stage-batch"
)
_stage_batch_slots = BoundedSemaphore(_STAGE_BATCH_CAPACITY)


def _bounded_stage_summaries(read_summary, ordered, *, workers, timeout_seconds):
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    slots = _stage_batch_slots
    pending = {}
    remaining = iter(ordered)
    summaries = {}
    exhausted = False
    try:
        while time.monotonic() < deadline:
            while not exhausted and len(pending) < workers and time.monotonic() < deadline:
                if not slots.acquire(blocking=False):
                    break
                try:
                    stage_id = next(remaining)
                except StopIteration:
                    slots.release()
                    exhausted = True
                    break
                try:
                    future = _stage_batch_executor.submit(read_summary, stage_id)
                except BaseException:
                    slots.release()
                    raise
                future.add_done_callback(lambda _future: slots.release())
                pending[future] = stage_id
            if not pending:
                # Saturation is an incomplete read, never an invitation to
                # queue more work or to bypass the response deadline.
                break
            done, _ = wait(pending, timeout=max(0.0, deadline - time.monotonic()),
                           return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                del pending[future]
                name, summary = future.result()
                if summary is not None:
                    summaries[name] = summary
    finally:
        for future in pending:
            future.cancel()
    return summaries


_V4_STATE_ROOT = (
    Path.home()
    / "Library"
    / "Application Support"
    / "com.lexi.v4.local"
    / "state"
)
_CANONICAL_MANAGER_RESEARCH_STATE_ROOT = _V4_STATE_ROOT / "manager_auto_research"

_DAY25_HK0930_BACKFILL_RUN_ID = "55742332ec504f119a54c42ce9cad3cd"
_DAY25_HK0930_BINDING_KEY = (
    "20260925",
    "STAGE_0930_0935",
    "HK_CONNECT",
    _DAY25_HK0930_BACKFILL_RUN_ID,
)
_APPROVED_EXACT_STAGE_BACKFILLS: dict[tuple[str, str, str, str], dict[str, Any]] = {
    _DAY25_HK0930_BINDING_KEY: {
        "selection_run_id": "run-00ed21b8213cc63c7c1bebc3",
        "artifact_id": "selection-00ed21b8213cc63c7c1bebc3",
        "raw_artifact_sha256": "02229d41078a562a3863124dc799c37c1c087759744d4254b640873c1b5adefd",
        "algorithm_id": "V3_STAGE_SELECTION_V1",
        "algorithm_sha256": "fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506",
        "selection_status": "PARTIAL_WITH_ROWS",
        "source_status": "PARTIAL_WITH_ROWS",
        "selected_rows": 10,
        "source_rows": 96,
        "cannot_confirm_count": 12,
        "selection_manifest_sha256": "8f8fa02aa165d53641f546bc64d6d8cfd43150e1aadfe4c95a21205ea58fbc01",
        "selection_receipt_sha256": "00d21a26efa9ff3b960a2765e5a4a4599ff9c7567338f942ffc18676dbbab217",
        "selection_artifact_sha256": "8e32219e33962113527f78f0d0a2bc44276a39345264dd2c968d533bc324ed01",
        "runner_receipt_sha256": "57c0ebadf08e372f2165b624d54b9287737451a9545cc11a9c2015e42c51deae",
        "required_evidence": (
            "historical_observation_contract=HK_STAGE0930_RESEARCH_ONLY",
            "historical_base_raw_sha256=eabaa273897b0db7261d0e0d3245493e75297e5f148edad665061d90fb5f6070",
            "historical_gap_fields_sha256=11e256bec4ee181f956bb2792260290b1e2b5784a9838ebef91b3074eebbcc3e",
            "historical_gap_csv_sha256=d02371d0d8fdb28fad944bc0881943ba1deb4899bf57b11f9a4f3d1adb6a7546",
            "historical_gap_receipt_sha256=1d1d6cbd74aff12d48cfa250551430ec8e7a046075a8769438c93e974375996a",
            "historical_base_source_id=futu_request_history_kline_none",
            "historical_d1_pool_sha256=c6202648a73d0103b2ec43e393618ca31e67183c730a4df4db018eced2cfacd0",
            "historical_formal_pit=false",
            "due_status=HISTORICAL_BACKFILL",
            "hk_observation_mode=HK_SECURITIES_OPEN_HK_CONNECT_CLOSED",
            "hk_d1_binding_mode=EXPLICIT_HK_STAGE0930_RESEARCH_TARGET_DATE",
            "hk_d1_source_trade_date=20260925",
            "hk_d1_source_signal_date=20260924",
            "hk_d1_binding_sha256=c6202648a73d0103b2ec43e393618ca31e67183c730a4df4db018eced2cfacd0",
            "selection_contract=V3_TOP10_RECOMMENDATION",
            "historical_observation=WATCH_ONLY_NO_BUY",
            "production_allowed=false",
            "buy_gate_updated=false",
            "orders_sent=false",
        ),
    }
}

_DAY24_HK0930_BACKFILL_RUN_ID = "1d3ab9f9bd3a44c3811bf1fed2b74108"
_APPROVED_EXACT_STAGE_BACKFILLS[
    ("20260924", "STAGE_0930_0935", "HK_CONNECT", _DAY24_HK0930_BACKFILL_RUN_ID)
] = {
    "selection_run_id": "run-1f781dcc3ea56ab3c3e97c70",
    "artifact_id": "selection-1f781dcc3ea56ab3c3e97c70",
    "raw_artifact_sha256": "709a5d00bb4507bd6cc32ad9bf1b4e0e4615fe702262b39088b6fad3505f10c1",
    "algorithm_id": "V3_STAGE_SELECTION_V1",
    "algorithm_sha256": "fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506",
    "selection_status": "PARTIAL_WITH_ROWS",
    "source_status": "PARTIAL_WITH_ROWS",
    "selected_rows": 10,
    "source_rows": 100,
    "cannot_confirm_count": 8,
    "selection_manifest_sha256": "21040d9758662b43892b2b64b9fd5fe13baf876b5f74bd928179317c5123ab1d",
    "selection_receipt_sha256": "c7abf5f56e6256eac0bb7cfef78422c4f1d9e0ce3cfe0f93f69768bf8f1f916e",
    "selection_artifact_sha256": "6c0d7edba26455714421a4af7b625573679416fc97ed8accea6a939508081c87",
    "runner_receipt_sha256": "70a9c5bb6637f14218d99a18c4f02e0cc7c18086f3a89056185c90a589e6bbfa",
    "required_evidence": (
        "historical_observation_contract=TDX_EXHQ_AFTERFACT_RESEARCH_ONLY",
        "historical_provider=pytdx_exhq",
        "historical_request_method=TdxExHq_API.get_instrument_bars",
        "historical_capture_after_target_cutoff=true",
        "historical_temporal_cutoff_safe=false",
        "historical_formal_stage_eligibility=CANNOT_CONFIRM",
        "historical_natural_time_capture=CANNOT_CONFIRM",
        "historical_pit_safe=false",
        "historical_target_date=20260924",
        "historical_signal_date=20260923",
        "historical_stage_id=STAGE_0930_0935",
        "historical_stage_window=09:31:00-09:35:00",
        "historical_d1_projection_sha256=fda1cd4b334699fc4df59658b443a01388f6bb4dfd29470d9c1baabd75ad72fc",
        "historical_d1_projection_receipt_sha256=ffa32388a978691c1a6c1d1ae580e0e69fa4691fb2aee62868eb1f7292d48fa5",
        "historical_d1_producer_artifact_sha256=30576eee9f0370c6956da6e41725d0720253e917a8e3741cce20f875b5e28f89",
        "historical_d1_producer_manifest_sha256=c10ecc440585f0546a28dc8faf52bcf3e198c378216e5164c022b96d4d428465",
        "historical_d1_producer_receipt_sha256=a96626f926b53a461039fce732658f765eea5383a63fe0830cbb21d7d780c73d",
        "historical_rank45_gap_receipt_sha256=e3ea5b867f591d83a65e59aa855275d83dae188a7de8634dfa8b6fc9b605cf6a",
        "historical_rank45_gap_code=HK.02915",
        "historical_rank45_gap_rank=45",
        "historical_rank45_gap_status=CANNOT_CONFIRM",
        "historical_input_minute_full_coverage_sha256=936d5381445aaf94f6ef11ca91cf219139461dad5df787cb0b781bf07435e20d",
        "historical_input_minute_batch_receipt_sha256=9eb1e45a668404e480127c62e2fcb42f9e148774ba2e1d53735e758270a69e78",
        "historical_input_minute_canary_sha256=70f83ef90c5545ce1fd53767b35c7d64dfb8d53f107fa8fd1ed49e6be871dcb0",
        "historical_input_minute_page_set_sha256=43de2248f4a8360ef82eae6ea7829d9847f8d824834dbc631cfdde26f2bde9c8",
        "historical_selection_action_boundary=NO_BUY",
        "historical_raw_bundle=OMITTED_HK_ONLY_RESEARCH_BACKFILL",
        "formal_pit=false",
        "production_allowed=false",
        "buy_gate_updated=false",
        "orders_sent=false",
    ),
}


# BEGIN MONTH_HK_AFTERFACT_R5_API_BINDINGS
_MONTH_HK_AFTERFACT_R5_BINDINGS = (
    {'date': '20260924',
 'stage_id': 'STAGE_1445_1500',
 'market': 'HK_CONNECT',
 'backfill_run_id': '2e2b255787324dc5a59207273ec236af',
 'selection_run_id': 'run-0dc43c41aed156986cb3bf6c',
 'artifact_id': 'selection-0dc43c41aed156986cb3bf6c',
 'raw_artifact_sha256': '59ee4e3ca3d030c0fb3ee19e40513a81e464760108cbd3851af4d95c93cba669',
 'algorithm_id': 'V3_STAGE_SELECTION_V1',
 'algorithm_sha256': 'fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506',
 'selection_status': 'PARTIAL_WITH_ROWS',
 'source_status': 'PARTIAL_WITH_ROWS',
 'selected_rows': 10,
 'source_rows': 100,
 'cannot_confirm_count': 3,
 'selection_manifest_sha256': 'd954ccf01b9c0a4d7468c4caf06e5c59113364068580c91e264b3d8a5b8f1355',
 'selection_receipt_sha256': '0f303ce47773bd5ae931c75ba3f29c57131571635adc65319b1f9d4ac5d430b3',
 'selection_artifact_sha256': '29118cec58eada14b6c4b34baef3c69b47d7564b6086ad135bd2211a3e0fec97',
 'runner_receipt_sha256': 'f60da5be99b92c2ec2da5559b48385bd7df248d618c04f8ec34c663ac8278d38',
 'required_evidence': ('buy_gate_updated=false',
                       'historical_capture_after_target_cutoff=true',
                       'historical_formal_stage_eligibility=CANNOT_CONFIRM',
                       'historical_natural_time_capture=CANNOT_CONFIRM',
                       'historical_pit_safe=false',
                       'historical_price_signal_date=20260923',
                       'historical_provider=pytdx_exhq',
                       'historical_source_page_set_sha256=a0f724f5df59bec2bbcccea6d68501aa2207f22e245e37a7c6a2f9b14d503627',
                       'historical_temporal_cutoff_safe=false',
                       'orders_sent=false',
                       'production_allowed=false',
                       'historical_fixed_cache_code_file_sha256=cd510cb9e49b4c06415c612104857ed3726fbb88d5a6733805a66cd61c0adca7',
                       'historical_cache_code_set_sha256=4395dcad079830e90c6dfafc401ebf8687a13dff31156aeb73bd8d37d2e747ae',
                       'historical_cache_observed_codes=100',
                       'historical_cache_missing_codes=0',
                       'historical_pool_artifact_path=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260924/hkconnect_d1_top100.json',
                       'historical_pool_artifact_sha256=50a014bb51a66ca5bf56853bcf25bc6dc2dacbda257a03e0bb0db2abd7448564',
                       'stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:b411392f6758ce0db7c26e32009dfedd671438920fa9d60d5aedb173b525863d',
                       'due_status=HISTORICAL_BACKFILL',
                       'historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1',
                       'hk_d1_source_trade_date=20260924',
                       'hk_d1_source_signal_date=20260923',
                       'hk_d1_binding_sha256=50a014bb51a66ca5bf56853bcf25bc6dc2dacbda257a03e0bb0db2abd7448564',
                       'hk_d1_sha256=50a014bb51a66ca5bf56853bcf25bc6dc2dacbda257a03e0bb0db2abd7448564',
                       'HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE',
                       'HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM',
                       'HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM',
                       'candidate_current_sha256=50a014bb51a66ca5bf56853bcf25bc6dc2dacbda257a03e0bb0db2abd7448564',
                       'candidate_run_id=hk-d1-50a014bb51a66ca5',
                       'hk_d1_json=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260924/hkconnect_d1_top100.json',
                       'hk_d1_membership=exact_date_top100',
                       'hk_acquisition_scope=EXACT_D1_TOP100',
                       'hk_d1_status=STRICT_0_2_READY',
                       'hk_d1_json_sha256=50a014bb51a66ca5bf56853bcf25bc6dc2dacbda257a03e0bb0db2abd7448564',
                       'hk_d1_model_id=prob_active',
                       'hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel',
                       'hk_d1_source_sha256=8ee3a43ebe014f4df7e65beb83271de79978c81e83558c908559c83a7f64291d',
                       'selection_contract=V3_TOP10_RECOMMENDATION',
                       'selection_mode=RESEARCH_ONLY',
                       'historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY',
                       'observation_status=OBSERVATION_UNVERIFIED',
                       'formal_stage_eligibility=CANNOT_CONFIRM',
                       'natural_time_capture=CANNOT_CONFIRM',
                       'formal_pit=false',
                       'algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506')},
    {'date': '20260930',
 'stage_id': 'STAGE_0930_0935',
 'market': 'HK_CONNECT',
 'backfill_run_id': '24fbfe97748743b592ba2a67e5844535',
 'selection_run_id': 'run-41ae5a132ca438e57c4890a3',
 'artifact_id': 'selection-41ae5a132ca438e57c4890a3',
 'raw_artifact_sha256': '2765126fe611e62db9be5b7072640649656dac70138a2f8282b418ff7b711ce7',
 'algorithm_id': 'V3_STAGE_SELECTION_V1',
 'algorithm_sha256': 'fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506',
 'selection_status': 'PARTIAL_WITH_ROWS',
 'source_status': 'PARTIAL_WITH_ROWS',
 'selected_rows': 10,
 'source_rows': 75,
 'cannot_confirm_count': 3,
 'selection_manifest_sha256': 'eef3db78753d35569a01b420dae31842beec4c628b46da5c624bf4b82c56ec8a',
 'selection_receipt_sha256': 'a01c6d088e1e7ed48ac27771b1804edb7daff53dbf27204d82f9f1d35089fd99',
 'selection_artifact_sha256': '396ebdd8d2dc57f0c2b476942288b90273978ad39bba29bc3a811c8fc22280aa',
 'runner_receipt_sha256': 'd4d023f94a4c03a43726616d111fb6708a8c51e5d69efb770dea2c8cfdcce0a1',
 'required_evidence': ('buy_gate_updated=false',
                       'historical_capture_after_target_cutoff=true',
                       'historical_formal_stage_eligibility=CANNOT_CONFIRM',
                       'historical_natural_time_capture=CANNOT_CONFIRM',
                       'historical_pit_safe=false',
                       'historical_price_signal_date=20260929',
                       'historical_provider=pytdx_exhq',
                       'historical_source_page_set_sha256=6327f9dad2494452f2a796e8b280593f74b2a7509ebea511ffe49d3913c64e56',
                       'historical_temporal_cutoff_safe=false',
                       'orders_sent=false',
                       'production_allowed=false',
                       'historical_fixed_cache_code_file_sha256=cd510cb9e49b4c06415c612104857ed3726fbb88d5a6733805a66cd61c0adca7',
                       'historical_cache_code_set_sha256=4395dcad079830e90c6dfafc401ebf8687a13dff31156aeb73bd8d37d2e747ae',
                       'historical_cache_observed_codes=75',
                       'historical_cache_missing_codes=25',
                       'historical_pool_artifact_path=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'historical_pool_artifact_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:53ab0e1dc6a67de6a6c437e5171dd5d73b45dd91c2f62955012c21d632b1783d',
                       'due_status=HISTORICAL_BACKFILL',
                       'historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1',
                       'hk_d1_source_trade_date=20260930',
                       'hk_d1_source_signal_date=20260929',
                       'hk_d1_binding_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE',
                       'HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM',
                       'HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM',
                       'candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'candidate_run_id=hk-d1-f45233cd1d30d04a',
                       'hk_d1_json=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'hk_d1_membership=exact_date_top100',
                       'hk_acquisition_scope=EXACT_D1_TOP100',
                       'hk_d1_status=STRICT_0_2_READY',
                       'hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_model_id=prob_active',
                       'hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel',
                       'hk_d1_source_sha256=8a548960a26268ec248d680466153acad0cfc1764b565d6cee06e9392590b666',
                       'selection_contract=V3_TOP10_RECOMMENDATION',
                       'selection_mode=RESEARCH_ONLY',
                       'historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY',
                       'observation_status=OBSERVATION_UNVERIFIED',
                       'formal_stage_eligibility=CANNOT_CONFIRM',
                       'natural_time_capture=CANNOT_CONFIRM',
                       'formal_pit=false',
                       'algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506')},
    {'date': '20260930',
 'stage_id': 'STAGE_0935_0940',
 'market': 'HK_CONNECT',
 'backfill_run_id': '97565b683daa4326b4e6ff0be514b152',
 'selection_run_id': 'run-bea22781e15ac63a1ca00d53',
 'artifact_id': 'selection-bea22781e15ac63a1ca00d53',
 'raw_artifact_sha256': 'f6e35dd7b469f27a05df43551227ed9482553460ccc25ae332f0bf2c7eb0f06c',
 'algorithm_id': 'V3_STAGE_SELECTION_V1',
 'algorithm_sha256': 'fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506',
 'selection_status': 'PARTIAL_WITH_ROWS',
 'source_status': 'PARTIAL_WITH_ROWS',
 'selected_rows': 10,
 'source_rows': 75,
 'cannot_confirm_count': 3,
 'selection_manifest_sha256': 'ec8de0b9206681f834d44b74948161995b51a8029b3e4e0a4c6baffbb4bd9d27',
 'selection_receipt_sha256': 'c8128088c42437910014ef8bf68976a7c67b99802109af14b209bd9c9d23f880',
 'selection_artifact_sha256': 'b74b35578c3b2a11ba0a44e60834eb1f225b85739e2ddf781987b525984417f2',
 'runner_receipt_sha256': 'caabf6a6b23234881484f2c3632c1cbd09139b24a736e59ecc70e1d41c59a713',
 'required_evidence': ('buy_gate_updated=false',
                       'historical_capture_after_target_cutoff=true',
                       'historical_formal_stage_eligibility=CANNOT_CONFIRM',
                       'historical_natural_time_capture=CANNOT_CONFIRM',
                       'historical_pit_safe=false',
                       'historical_price_signal_date=20260929',
                       'historical_provider=pytdx_exhq',
                       'historical_source_page_set_sha256=6327f9dad2494452f2a796e8b280593f74b2a7509ebea511ffe49d3913c64e56',
                       'historical_temporal_cutoff_safe=false',
                       'orders_sent=false',
                       'production_allowed=false',
                       'historical_fixed_cache_code_file_sha256=cd510cb9e49b4c06415c612104857ed3726fbb88d5a6733805a66cd61c0adca7',
                       'historical_cache_code_set_sha256=4395dcad079830e90c6dfafc401ebf8687a13dff31156aeb73bd8d37d2e747ae',
                       'historical_cache_observed_codes=75',
                       'historical_cache_missing_codes=25',
                       'historical_pool_artifact_path=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'historical_pool_artifact_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:d59bd2ef827dc5aa2abc0d0e2affce16de1cc032d74575008674876c33d38610',
                       'due_status=HISTORICAL_BACKFILL',
                       'historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1',
                       'hk_d1_source_trade_date=20260930',
                       'hk_d1_source_signal_date=20260929',
                       'hk_d1_binding_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE',
                       'HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM',
                       'HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM',
                       'candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'candidate_run_id=hk-d1-f45233cd1d30d04a',
                       'hk_d1_json=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'hk_d1_membership=exact_date_top100',
                       'hk_acquisition_scope=EXACT_D1_TOP100',
                       'hk_d1_status=STRICT_0_2_READY',
                       'hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_model_id=prob_active',
                       'hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel',
                       'hk_d1_source_sha256=8a548960a26268ec248d680466153acad0cfc1764b565d6cee06e9392590b666',
                       'selection_contract=V3_TOP10_RECOMMENDATION',
                       'selection_mode=RESEARCH_ONLY',
                       'historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY',
                       'observation_status=OBSERVATION_UNVERIFIED',
                       'formal_stage_eligibility=CANNOT_CONFIRM',
                       'natural_time_capture=CANNOT_CONFIRM',
                       'formal_pit=false',
                       'algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506')},
    {'date': '20260930',
 'stage_id': 'STAGE_0940_0945',
 'market': 'HK_CONNECT',
 'backfill_run_id': '9d4c90bfd94441d8a4c2e53868536998',
 'selection_run_id': 'run-526a374438b65032a0bacf0f',
 'artifact_id': 'selection-526a374438b65032a0bacf0f',
 'raw_artifact_sha256': '3173bae02bca046fa428415e9b5d5851c58b72aee1cbf4ae507dcaf41811e1e2',
 'algorithm_id': 'V3_STAGE_SELECTION_V1',
 'algorithm_sha256': 'fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506',
 'selection_status': 'PARTIAL_WITH_ROWS',
 'source_status': 'PARTIAL_WITH_ROWS',
 'selected_rows': 10,
 'source_rows': 75,
 'cannot_confirm_count': 3,
 'selection_manifest_sha256': '904e803f7cf8787e1212e21774d748b63750bd6bcdb7b0801abb7ec4e2568be6',
 'selection_receipt_sha256': '86f9aa7af7c504507cc55fdc48019c415d283ad911a8bde84dfb9979e2efe78a',
 'selection_artifact_sha256': 'e0e845f544ba11399e83b0e689143d0577086ef8baf1e0d405b40a1795b27572',
 'runner_receipt_sha256': '8ac264a3026a8609d663d13100a945d67e7980c3ae8e9201d36945f89fedcbbc',
 'required_evidence': ('buy_gate_updated=false',
                       'historical_capture_after_target_cutoff=true',
                       'historical_formal_stage_eligibility=CANNOT_CONFIRM',
                       'historical_natural_time_capture=CANNOT_CONFIRM',
                       'historical_pit_safe=false',
                       'historical_price_signal_date=20260929',
                       'historical_provider=pytdx_exhq',
                       'historical_source_page_set_sha256=6327f9dad2494452f2a796e8b280593f74b2a7509ebea511ffe49d3913c64e56',
                       'historical_temporal_cutoff_safe=false',
                       'orders_sent=false',
                       'production_allowed=false',
                       'historical_fixed_cache_code_file_sha256=cd510cb9e49b4c06415c612104857ed3726fbb88d5a6733805a66cd61c0adca7',
                       'historical_cache_code_set_sha256=4395dcad079830e90c6dfafc401ebf8687a13dff31156aeb73bd8d37d2e747ae',
                       'historical_cache_observed_codes=75',
                       'historical_cache_missing_codes=25',
                       'historical_pool_artifact_path=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'historical_pool_artifact_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:971f664792d511d7219b6ecfb0d3f3d58fa0cff66f789bf784086a9b5c9a6a40',
                       'due_status=HISTORICAL_BACKFILL',
                       'historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1',
                       'hk_d1_source_trade_date=20260930',
                       'hk_d1_source_signal_date=20260929',
                       'hk_d1_binding_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE',
                       'HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM',
                       'HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM',
                       'candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'candidate_run_id=hk-d1-f45233cd1d30d04a',
                       'hk_d1_json=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'hk_d1_membership=exact_date_top100',
                       'hk_acquisition_scope=EXACT_D1_TOP100',
                       'hk_d1_status=STRICT_0_2_READY',
                       'hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_model_id=prob_active',
                       'hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel',
                       'hk_d1_source_sha256=8a548960a26268ec248d680466153acad0cfc1764b565d6cee06e9392590b666',
                       'selection_contract=V3_TOP10_RECOMMENDATION',
                       'selection_mode=RESEARCH_ONLY',
                       'historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY',
                       'observation_status=OBSERVATION_UNVERIFIED',
                       'formal_stage_eligibility=CANNOT_CONFIRM',
                       'natural_time_capture=CANNOT_CONFIRM',
                       'formal_pit=false',
                       'algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506')},
    {'date': '20260930',
 'stage_id': 'STAGE_0945_1030',
 'market': 'HK_CONNECT',
 'backfill_run_id': '857db5b6e1614eb2b0686dd90825b77b',
 'selection_run_id': 'run-342bd3adc9a31929ef2f1041',
 'artifact_id': 'selection-342bd3adc9a31929ef2f1041',
 'raw_artifact_sha256': 'a4fe4373390fad7a8833bb1d0e9cac9897539f5ef8c541a8ee5762c2349b9ba4',
 'algorithm_id': 'V3_STAGE_SELECTION_V1',
 'algorithm_sha256': 'fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506',
 'selection_status': 'PARTIAL_WITH_ROWS',
 'source_status': 'PARTIAL_WITH_ROWS',
 'selected_rows': 10,
 'source_rows': 75,
 'cannot_confirm_count': 3,
 'selection_manifest_sha256': 'fda1a8fc98434669f604b82d4081cfeab9cf2cc2bf897afebb91f1303c14c353',
 'selection_receipt_sha256': 'ae703229cc12ca1f976a4a281cff96f81da9d11a005dcf89253df55601e391c0',
 'selection_artifact_sha256': '0abe4949ee05e82766dfd3cb1df5d3c9d0b76cb18d5d670c481c4b03b421dc7b',
 'runner_receipt_sha256': '5025e58c1c07211ed35448e9c633dabcc043850b9de2f967d2124830b93f0a51',
 'required_evidence': ('buy_gate_updated=false',
                       'historical_capture_after_target_cutoff=true',
                       'historical_formal_stage_eligibility=CANNOT_CONFIRM',
                       'historical_natural_time_capture=CANNOT_CONFIRM',
                       'historical_pit_safe=false',
                       'historical_price_signal_date=20260929',
                       'historical_provider=pytdx_exhq',
                       'historical_source_page_set_sha256=6327f9dad2494452f2a796e8b280593f74b2a7509ebea511ffe49d3913c64e56',
                       'historical_temporal_cutoff_safe=false',
                       'orders_sent=false',
                       'production_allowed=false',
                       'historical_fixed_cache_code_file_sha256=cd510cb9e49b4c06415c612104857ed3726fbb88d5a6733805a66cd61c0adca7',
                       'historical_cache_code_set_sha256=4395dcad079830e90c6dfafc401ebf8687a13dff31156aeb73bd8d37d2e747ae',
                       'historical_cache_observed_codes=75',
                       'historical_cache_missing_codes=25',
                       'historical_pool_artifact_path=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'historical_pool_artifact_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:103c38db33bfcf89ba748abbcbc8d85412abd1e7d44ebd4e4db20d7bfa5b4e12',
                       'due_status=HISTORICAL_BACKFILL',
                       'historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1',
                       'hk_d1_source_trade_date=20260930',
                       'hk_d1_source_signal_date=20260929',
                       'hk_d1_binding_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE',
                       'HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM',
                       'HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM',
                       'candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'candidate_run_id=hk-d1-f45233cd1d30d04a',
                       'hk_d1_json=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'hk_d1_membership=exact_date_top100',
                       'hk_acquisition_scope=EXACT_D1_TOP100',
                       'hk_d1_status=STRICT_0_2_READY',
                       'hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_model_id=prob_active',
                       'hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel',
                       'hk_d1_source_sha256=8a548960a26268ec248d680466153acad0cfc1764b565d6cee06e9392590b666',
                       'selection_contract=V3_TOP10_RECOMMENDATION',
                       'selection_mode=RESEARCH_ONLY',
                       'historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY',
                       'observation_status=OBSERVATION_UNVERIFIED',
                       'formal_stage_eligibility=CANNOT_CONFIRM',
                       'natural_time_capture=CANNOT_CONFIRM',
                       'formal_pit=false',
                       'algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506')},
    {'date': '20260930',
 'stage_id': 'STAGE_1300_1315',
 'market': 'HK_CONNECT',
 'backfill_run_id': '1037325de0d248c4bd4e42c90c21a572',
 'selection_run_id': 'run-0aa1980ab7d5290fa2f22627',
 'artifact_id': 'selection-0aa1980ab7d5290fa2f22627',
 'raw_artifact_sha256': 'eb00bbf2345ecb432e32e9b2e6e320e469ce74bf93df65e1f84e197b69de72f9',
 'algorithm_id': 'V3_STAGE_SELECTION_V1',
 'algorithm_sha256': 'fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506',
 'selection_status': 'PARTIAL_WITH_ROWS',
 'source_status': 'PARTIAL_WITH_ROWS',
 'selected_rows': 10,
 'source_rows': 75,
 'cannot_confirm_count': 3,
 'selection_manifest_sha256': '6403c6fd5fab859c4e696fc9b8a47d9588ecb75ed1b889c35b30dc01717cb652',
 'selection_receipt_sha256': 'fae6f8897610abf7b0417c322c57425fd440a2225145d1b8651705f95f73df1c',
 'selection_artifact_sha256': 'b1e543a1d3f57262b5eaa69c94b04bf8037a400aee23a8ebe60eb4428f7875d7',
 'runner_receipt_sha256': '920390fe6d77ad50ae711dca4a5d42e352232eef9d36e59115dd30f3bbe1265e',
 'required_evidence': ('buy_gate_updated=false',
                       'historical_capture_after_target_cutoff=true',
                       'historical_formal_stage_eligibility=CANNOT_CONFIRM',
                       'historical_natural_time_capture=CANNOT_CONFIRM',
                       'historical_pit_safe=false',
                       'historical_price_signal_date=20260929',
                       'historical_provider=pytdx_exhq',
                       'historical_source_page_set_sha256=6327f9dad2494452f2a796e8b280593f74b2a7509ebea511ffe49d3913c64e56',
                       'historical_temporal_cutoff_safe=false',
                       'orders_sent=false',
                       'production_allowed=false',
                       'historical_fixed_cache_code_file_sha256=cd510cb9e49b4c06415c612104857ed3726fbb88d5a6733805a66cd61c0adca7',
                       'historical_cache_code_set_sha256=4395dcad079830e90c6dfafc401ebf8687a13dff31156aeb73bd8d37d2e747ae',
                       'historical_cache_observed_codes=75',
                       'historical_cache_missing_codes=25',
                       'historical_pool_artifact_path=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'historical_pool_artifact_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:db9ee7770c0fc316d799a543bc196501fa955edc520d3151a23fed92ec15097d',
                       'due_status=HISTORICAL_BACKFILL',
                       'historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1',
                       'hk_d1_source_trade_date=20260930',
                       'hk_d1_source_signal_date=20260929',
                       'hk_d1_binding_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE',
                       'HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM',
                       'HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM',
                       'candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'candidate_run_id=hk-d1-f45233cd1d30d04a',
                       'hk_d1_json=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'hk_d1_membership=exact_date_top100',
                       'hk_acquisition_scope=EXACT_D1_TOP100',
                       'hk_d1_status=STRICT_0_2_READY',
                       'hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_model_id=prob_active',
                       'hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel',
                       'hk_d1_source_sha256=8a548960a26268ec248d680466153acad0cfc1764b565d6cee06e9392590b666',
                       'selection_contract=V3_TOP10_RECOMMENDATION',
                       'selection_mode=RESEARCH_ONLY',
                       'historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY',
                       'observation_status=OBSERVATION_UNVERIFIED',
                       'formal_stage_eligibility=CANNOT_CONFIRM',
                       'natural_time_capture=CANNOT_CONFIRM',
                       'formal_pit=false',
                       'algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506')},
    {'date': '20260930',
 'stage_id': 'STAGE_1445_1500',
 'market': 'HK_CONNECT',
 'backfill_run_id': '719031ad35c4442aa8d6c95acbd89401',
 'selection_run_id': 'run-2bfb8bc629ae98b3a3d2bd39',
 'artifact_id': 'selection-2bfb8bc629ae98b3a3d2bd39',
 'raw_artifact_sha256': '4240ae72349cc100fa16eaa18b2c7e7dd3da4c7d77912873768e98207c7c1af3',
 'algorithm_id': 'V3_STAGE_SELECTION_V1',
 'algorithm_sha256': 'fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506',
 'selection_status': 'PARTIAL_WITH_ROWS',
 'source_status': 'PARTIAL_WITH_ROWS',
 'selected_rows': 10,
 'source_rows': 75,
 'cannot_confirm_count': 3,
 'selection_manifest_sha256': '0fb2994677352d9c6698d5a6b79c895a9ebcb76bb5a1d7298600b81656b23a8e',
 'selection_receipt_sha256': '480611e002bea97607a556761e2bf03a820cd159f6763e7d6b94f2680569fe64',
 'selection_artifact_sha256': 'd38167f2d141f14c28ebb6fd774f24a9a1d5ca6dce1bf9f8701f45a91c635ecc',
 'runner_receipt_sha256': '6a22b0c6fdd8f783e86e92092d00fd27f2a4b0f62e1cd9e3402c17c4a57b953b',
 'required_evidence': ('buy_gate_updated=false',
                       'historical_capture_after_target_cutoff=true',
                       'historical_formal_stage_eligibility=CANNOT_CONFIRM',
                       'historical_natural_time_capture=CANNOT_CONFIRM',
                       'historical_pit_safe=false',
                       'historical_price_signal_date=20260929',
                       'historical_provider=pytdx_exhq',
                       'historical_source_page_set_sha256=6327f9dad2494452f2a796e8b280593f74b2a7509ebea511ffe49d3913c64e56',
                       'historical_temporal_cutoff_safe=false',
                       'orders_sent=false',
                       'production_allowed=false',
                       'historical_fixed_cache_code_file_sha256=cd510cb9e49b4c06415c612104857ed3726fbb88d5a6733805a66cd61c0adca7',
                       'historical_cache_code_set_sha256=4395dcad079830e90c6dfafc401ebf8687a13dff31156aeb73bd8d37d2e747ae',
                       'historical_cache_observed_codes=75',
                       'historical_cache_missing_codes=25',
                       'historical_pool_artifact_path=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'historical_pool_artifact_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:0b9821887655fd8231d2822406831a82f726020d18899db55a2d4ba92d17d22e',
                       'due_status=HISTORICAL_BACKFILL',
                       'historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1',
                       'hk_d1_source_trade_date=20260930',
                       'hk_d1_source_signal_date=20260929',
                       'hk_d1_binding_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE',
                       'HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM',
                       'HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM',
                       'candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'candidate_run_id=hk-d1-f45233cd1d30d04a',
                       'hk_d1_json=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'hk_d1_membership=exact_date_top100',
                       'hk_acquisition_scope=EXACT_D1_TOP100',
                       'hk_d1_status=STRICT_0_2_READY',
                       'hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_model_id=prob_active',
                       'hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel',
                       'hk_d1_source_sha256=8a548960a26268ec248d680466153acad0cfc1764b565d6cee06e9392590b666',
                       'selection_contract=V3_TOP10_RECOMMENDATION',
                       'selection_mode=RESEARCH_ONLY',
                       'historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY',
                       'observation_status=OBSERVATION_UNVERIFIED',
                       'formal_stage_eligibility=CANNOT_CONFIRM',
                       'natural_time_capture=CANNOT_CONFIRM',
                       'formal_pit=false',
                       'algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506')},
    {'date': '20260930',
 'stage_id': 'STAGE_1545_1555',
 'market': 'HK_CONNECT',
 'backfill_run_id': '032fcf8756b2413595ff1339cc67a39b',
 'selection_run_id': 'run-b49161cfe20e6fbfd4933268',
 'artifact_id': 'selection-b49161cfe20e6fbfd4933268',
 'raw_artifact_sha256': '0061df2351b05c0c8eac1223b20e53163fcfb2a647717a25c5ace527e659707d',
 'algorithm_id': 'V3_STAGE_SELECTION_V1',
 'algorithm_sha256': 'fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506',
 'selection_status': 'PARTIAL_WITH_ROWS',
 'source_status': 'PARTIAL_WITH_ROWS',
 'selected_rows': 10,
 'source_rows': 75,
 'cannot_confirm_count': 3,
 'selection_manifest_sha256': '9ff3ba1d91819a3ec747304f8f2e7be232f982b8a8b22b30e6a6e905cd3bb874',
 'selection_receipt_sha256': 'b5d9174cbf4093ea05de58fb4f1b98aad5cf479c81d793b1ec3da9afe8a72d7d',
 'selection_artifact_sha256': 'cbacf5f6f34f83cf02f7638d8ac2b19b0be3c51ad2e4e867899378ed68271cd1',
 'runner_receipt_sha256': '0669204cc043f0d222915a05da4e2e6e632c7d1c3be71633c8607381a7018288',
 'required_evidence': ('buy_gate_updated=false',
                       'historical_capture_after_target_cutoff=true',
                       'historical_formal_stage_eligibility=CANNOT_CONFIRM',
                       'historical_natural_time_capture=CANNOT_CONFIRM',
                       'historical_pit_safe=false',
                       'historical_price_signal_date=20260929',
                       'historical_provider=pytdx_exhq',
                       'historical_source_page_set_sha256=6327f9dad2494452f2a796e8b280593f74b2a7509ebea511ffe49d3913c64e56',
                       'historical_temporal_cutoff_safe=false',
                       'orders_sent=false',
                       'production_allowed=false',
                       'historical_fixed_cache_code_file_sha256=cd510cb9e49b4c06415c612104857ed3726fbb88d5a6733805a66cd61c0adca7',
                       'historical_cache_code_set_sha256=4395dcad079830e90c6dfafc401ebf8687a13dff31156aeb73bd8d37d2e747ae',
                       'historical_cache_observed_codes=75',
                       'historical_cache_missing_codes=25',
                       'historical_pool_artifact_path=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'historical_pool_artifact_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:40377d12647f10a448ad762393de61ee0ea861df5b0228786f00ae8632b3f8f2',
                       'due_status=HISTORICAL_BACKFILL',
                       'historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1',
                       'hk_d1_source_trade_date=20260930',
                       'hk_d1_source_signal_date=20260929',
                       'hk_d1_binding_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE',
                       'HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM',
                       'HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM',
                       'candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'candidate_run_id=hk-d1-f45233cd1d30d04a',
                       'hk_d1_json=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'hk_d1_membership=exact_date_top100',
                       'hk_acquisition_scope=EXACT_D1_TOP100',
                       'hk_stage_replay_root=/Users/lexi/Library/Application '
                       'Support/com.lexi.v4.local/state/data/stage_references',
                       'hk_d1_status=STRICT_0_2_READY',
                       'hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_model_id=prob_active',
                       'hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel',
                       'hk_d1_source_sha256=8a548960a26268ec248d680466153acad0cfc1764b565d6cee06e9392590b666',
                       'selection_contract=V3_TOP10_RECOMMENDATION',
                       'selection_mode=RESEARCH_ONLY',
                       'historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY',
                       'observation_status=OBSERVATION_UNVERIFIED',
                       'formal_stage_eligibility=CANNOT_CONFIRM',
                       'natural_time_capture=CANNOT_CONFIRM',
                       'formal_pit=false',
                       'algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506')},
    {'date': '20261005',
 'stage_id': 'STAGE_1545_1555',
 'market': 'HK_CONNECT',
 'backfill_run_id': 'dd0b08a26ea14cb6ba7423d8b75e09e5',
 'selection_run_id': 'run-e7bf02220e093c01612d38ff',
 'artifact_id': 'selection-e7bf02220e093c01612d38ff',
 'raw_artifact_sha256': '19c10594292041a9863aaae09a40932afb04587b4418d1fc73dfb2b7942ce7a9',
 'algorithm_id': 'V3_STAGE_SELECTION_V1',
 'algorithm_sha256': 'fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506',
 'selection_status': 'PARTIAL_WITH_ROWS',
 'source_status': 'PARTIAL_WITH_ROWS',
 'selected_rows': 10,
 'source_rows': 75,
 'cannot_confirm_count': 3,
 'selection_manifest_sha256': 'a2ac8143180e68470d2a752ee3a71cbcf824c8031f72beaf01c249057d0d390f',
 'selection_receipt_sha256': '17a5de074b599f06c1440b51f7b96f34cfc93aeab01b936d2e67bbe0c764852b',
 'selection_artifact_sha256': 'fb5412293f4533dd6269db591a7f154d925920790ae3340cddfd93cf1d5a3eec',
 'runner_receipt_sha256': '115c166cf7691349f61f50061aaeb0b87ebcaab7d99d3cbb31b4038947763dd7',
 'required_evidence': ('buy_gate_updated=false',
                       'historical_capture_after_target_cutoff=true',
                       'historical_formal_stage_eligibility=CANNOT_CONFIRM',
                       'historical_natural_time_capture=CANNOT_CONFIRM',
                       'historical_pit_safe=false',
                       'historical_price_signal_date=20261002',
                       'historical_provider=pytdx_exhq',
                       'historical_source_page_set_sha256=6327f9dad2494452f2a796e8b280593f74b2a7509ebea511ffe49d3913c64e56',
                       'historical_temporal_cutoff_safe=false',
                       'orders_sent=false',
                       'production_allowed=false',
                       'historical_fixed_cache_code_file_sha256=cd510cb9e49b4c06415c612104857ed3726fbb88d5a6733805a66cd61c0adca7',
                       'historical_cache_code_set_sha256=4395dcad079830e90c6dfafc401ebf8687a13dff31156aeb73bd8d37d2e747ae',
                       'historical_cache_observed_codes=75',
                       'historical_cache_missing_codes=25',
                       'historical_pool_artifact_path=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'historical_pool_artifact_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:8dca45c5ff3f550ee563b18af6ca023a61fc6cfc43c2379a3136a64fafbf60ac',
                       'due_status=HISTORICAL_BACKFILL',
                       'historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1',
                       'hk_d1_source_trade_date=20260930',
                       'hk_d1_source_signal_date=20260929',
                       'hk_d1_binding_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE',
                       'HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM',
                       'HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM',
                       'candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'candidate_run_id=hk-d1-20260930-f45233cd1d30d04a',
                       'hk_d1_json=/Users/lexi/Library/Application '
                       'Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json',
                       'hk_d1_membership=exact_date_top100',
                       'hk_d1_source_manifest_sha256=edd1e184dc540273ccfc098e1e998e466848c0e689e0458e0834ee6e0ee99359',
                       'hk_d1_source_receipt_sha256=49386238fdae8ca6687ee1a65ba58a3a008c8cf030b0142010ec5737f5f365dc',
                       'hk_observation_trade_date=20261005',
                       'hk_observation_eligibility_source_date=20260930',
                       'hk_observation_price_signal_date=20261002',
                       'hk_observation_mode=HK_SECURITIES_OPEN_HK_CONNECT_CLOSED',
                       'hk_acquisition_scope=EXACT_D1_TOP100',
                       'hk_stage_replay_root=/Users/lexi/Library/Application '
                       'Support/com.lexi.v4.local/state/data/stage_references',
                       'hk_d1_status=STRICT_0_2_READY',
                       'hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901',
                       'hk_d1_model_id=prob_active',
                       'hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel',
                       'hk_d1_source_sha256=8a548960a26268ec248d680466153acad0cfc1764b565d6cee06e9392590b666',
                       'selection_contract=V3_TOP10_RECOMMENDATION',
                       'selection_mode=RESEARCH_ONLY',
                       'historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY',
                       'observation_status=OBSERVATION_UNVERIFIED',
                       'formal_stage_eligibility=CANNOT_CONFIRM',
                       'natural_time_capture=CANNOT_CONFIRM',
                       'formal_pit=false',
                       'algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506')},
)
# END MONTH_HK_AFTERFACT_R5_API_BINDINGS
for _r5_binding in _MONTH_HK_AFTERFACT_R5_BINDINGS:
    _r5_key = (
        _r5_binding["date"],
        _r5_binding["stage_id"],
        _r5_binding["market"],
        _r5_binding["backfill_run_id"],
    )
    if _r5_key in _APPROVED_EXACT_STAGE_BACKFILLS:
        raise RuntimeError(f"duplicate exact stage backfill binding: {_r5_key}")
    _APPROVED_EXACT_STAGE_BACKFILLS[_r5_key] = {
        key: value
        for key, value in _r5_binding.items()
        if key not in {"date", "stage_id", "market", "backfill_run_id"}
    }


# R8 uses immutable exact-target D1 evidence for all affected date/stage cells.
# The source artifacts remain research-only; these bindings do not update shared pointers.
_MONTH_HK_AFTERFACT_R8_BINDING_ROWS = (('20260924',
  'STAGE_1445_1500',
  '35eb3a5b317f4958b3598800cca40da8',
  'run-0dc43c41aed156986cb3bf6c',
  'selection-0dc43c41aed156986cb3bf6c',
  '59ee4e3ca3d030c0fb3ee19e40513a81e464760108cbd3851af4d95c93cba669',
  '3b6c4a35c1d08c48b9211e8a16d3e098fe20b42ad3440308a58349546ca19255',
  '43bfd68be3bb1469f4057f49adf874c11f72b2a86fbc33a02a54cd6958e2f943',
  '29118cec58eada14b6c4b34baef3c69b47d7564b6086ad135bd2211a3e0fec97',
  'fc0ffa0c667a63ce30915cf3eb04e6eed62a98ef3f881ed87bc7a8b226c30271',
  'a0f724f5df59bec2bbcccea6d68501aa2207f22e245e37a7c6a2f9b14d503627'),
 ('20260930',
  'STAGE_0930_0935',
  '3b3ccac4efd34164898b03a32f725bc3',
  'run-c9239742568ab4a55f29d0ae',
  'selection-c9239742568ab4a55f29d0ae',
  '5cce7c5970f49de4b3aba661d540fd9cb59bd7240777dd1fa158e4b1d4a8fe49',
  '40f7b40e675b89ea575408b2c85fa4f250326396dd012f1b5b332b69df91b6dc',
  '23d30536bdd182099a54a495fb8ff10f0c8149319f89b764dee24d159ed7a96e',
  'cd5a09313984cc01769b2a9018fff05cb5958fc1f925e78a15a890e1f91c167a',
  'b99e79eda4e34f43a53cede89f7c806a49ba41cca0d629a95eb67543421fb337',
  '298ee8706062e0ea73fc870beb753648e81c12b9c4e2707b562191b6b6a2b883'),
 ('20260930',
  'STAGE_0935_0940',
  '69ca9cb32dae457b8e25907d9143329a',
  'run-4f0655c949daccf3bbfb0cd3',
  'selection-4f0655c949daccf3bbfb0cd3',
  'cbd62d606d4c014f22cde7ce1c6aae0f2d565e66ffeefaa7e203b0ee3a7a557e',
  '9b851c371b7177d011447ebc5285af8317d072c2edae7356a1ba4abe18290ccb',
  'aea774765d185989507292a580b7b983c1be62f6dbf94370d728ac85e0410448',
  '3feb34b2fe6bca5a892d05e8a794e31b8ab834367c06a2c6ecdba7c1dd5e0fed',
  '7dc23bff80ee9540387f25b44f506eab28a41b4e73490d306f026f3857b693f2',
  '298ee8706062e0ea73fc870beb753648e81c12b9c4e2707b562191b6b6a2b883'),
 ('20260930',
  'STAGE_0940_0945',
  'daee498d5ce24fe0ab0e79ab868542e4',
  'run-937a25d6c37aeda87043f541',
  'selection-937a25d6c37aeda87043f541',
  'd316cd0b6baea2fdea63ded274098ad0486f82466e1beb1981b35b86a6b9e5b6',
  '74efd1eec9e4e569e6521165efaf0b61493c66a0ebe95f19be611b5d26ca7fdd',
  '31865329da5fe1fd40b0db45e538aa9c9b6ff8fdd648b505cc06a051b5681dfb',
  '064c3210c5cb11259a76cf4dbd8ab10d519ee017af33c54fc056ecd2b9e40257',
  '5bf8d84805c2bbd52843143b737b42f751717caedf716defbd3267c4d18dc416',
  '298ee8706062e0ea73fc870beb753648e81c12b9c4e2707b562191b6b6a2b883'),
 ('20260930',
  'STAGE_0945_1030',
  '7cdf858132ae406582254433257dd9ff',
  'run-b65ce45537312ff4130a72b9',
  'selection-b65ce45537312ff4130a72b9',
  '73927f2a3f2425210dec62ae4f7f14333a0b1f85ff8d110239c03ea15065ab21',
  '6fa8e1bc23cf7456740271e231fc98e0b7c88e4fa8fcaeeb2f37cadf802ef60c',
  'a0cad9494f0e75e9f7752aaac8dcb39b852d5e840e6664805e4de3240ad03a3b',
  '8ae27cb3993b018c25a25db0a2916c7de4b81d4e7334f7d192caeb0b385aefad',
  '5292e5dc820f58f4a51fa7ff4b381d46481055521dca522186765e99d285be0d',
  '298ee8706062e0ea73fc870beb753648e81c12b9c4e2707b562191b6b6a2b883'),
 ('20260930',
  'STAGE_1300_1315',
  'ac09423194c041d7954336c275fe873e',
  'run-0bf0c5fb245398416d7353d9',
  'selection-0bf0c5fb245398416d7353d9',
  '6b507c656a3d7b6bf431e2de1ec02c09525f43e39afc80d96e6dc2d1baa70283',
  '52d8c9674a4efb2d3256d9dc95a14a5a0837c7a3ee410658836b1acebb565b0a',
  '8fd4521d644d3344d81d3e6e7dec7c2147abe104afa7bf0a660d77b0c6ea9a96',
  '3889b6b5a9a2dac9365630d6bc4ddb6d6087303a60d7a0de94b30947e6dd5f6a',
  'ddde6b017978c9a3df173a3e1579a30dcc55d61d34d36cbf972e126e40683aa4',
  '298ee8706062e0ea73fc870beb753648e81c12b9c4e2707b562191b6b6a2b883'),
 ('20260930',
  'STAGE_1445_1500',
  'b73d909ac91444d2b1fec331f1b1f57e',
  'run-1d979dff9aad0c5df8d26ea7',
  'selection-1d979dff9aad0c5df8d26ea7',
  'b8de882a59460a4ce9e4b4e9f16e2969bb9c778f14300dbe9726084b37fdb295',
  '74ce117059bc6c51d158a62d0baf7a7d24c9a11ef89464c0e01393ce8173c72b',
  'eb3903143feb24eafb5a371082bfa6e03358bcb1faf461a405b1409d1f177a71',
  'd38167f2d141f14c28ebb6fd774f24a9a1d5ca6dce1bf9f8701f45a91c635ecc',
  '8069f766351ae5ffc044c5055fea9225f6fd17428443c9c68113a622d647ed7e',
  '298ee8706062e0ea73fc870beb753648e81c12b9c4e2707b562191b6b6a2b883'),
 ('20260930',
  'STAGE_1545_1555',
  '7d580097d5c34220a4c15af07dae0909',
  'run-58c20b4f8c308bb6136e6cb2',
  'selection-58c20b4f8c308bb6136e6cb2',
  'f7b0caa38e77e9e8a0efeba64c82bb7cbfd99d3462fec857eed3593add06767f',
  'f274fa931456e460dac3823d4f18d6c1e177053e121e7bed3600ec263b95f94c',
  '1b13d8a00630893927d4d979a3cb909a6daf66e7e4e42f0e49bc2374451eabb9',
  'cbacf5f6f34f83cf02f7638d8ac2b19b0be3c51ad2e4e867899378ed68271cd1',
  '72e356cb7f5218a6375f904986e9e9b5985791d0b3e4a2c1254d3ef4c8d30320',
  '298ee8706062e0ea73fc870beb753648e81c12b9c4e2707b562191b6b6a2b883'),
 ('20261005',
  'STAGE_0930_0935',
  '2235446241f5442cb084de73a4eade6d',
  'run-417e0324a0ee76a2f803fe6d',
  'selection-417e0324a0ee76a2f803fe6d',
  '189a716e36ac4b955d8b26b3a7948d5caeaa9a6681ab5425e86cae6cf9e236ed',
  'd7117e5f0e5527f1bdb26c879efcdb63f0d4dcef86afd8f2de0f3d0ef7587153',
  'ed2baabe033f32fdeaf57923af3a9938c2ff094b93cd64c0c602f2659dacd2a4',
  '8a3ab852cb81d86af11225eb41401c2dbe2f1e90590672c2b2778f0008fa3a56',
  '81d2b979304755c2ee657a83510eaf6d06932b4978f235878b84c955c8a73f28',
  'fb71c5f844c94d85ccbf0348d570f35fdfe20de30a798e1985fb2d127f49d0c4'),
 ('20261005',
  'STAGE_0935_0940',
  '7348e6c78fb848ef9a2b6b9315c8b4e2',
  'run-a0127c67c5abcff66b931fa3',
  'selection-a0127c67c5abcff66b931fa3',
  'fbe4188f283177d9264e99867805aa34f82abf4e11bf45ed373690806d186ec4',
  'cd3427c7b74e844f38b56d6ebeda17234b4fe4bbd835300f983fe8963aea9e27',
  '51c872b56ffd695e2486b846a9f60b485fad8ae864d2acef825cbdd733b4cbeb',
  'ad272e0fca8e7920923f09c38b41316c7a65d778b306a21b1106edba7f955ca5',
  'e9a14a7a58810f1e7b700c51c6099ebb6b4f5241fa53ef999fb6fe7a68fa791a',
  'fb71c5f844c94d85ccbf0348d570f35fdfe20de30a798e1985fb2d127f49d0c4'),
 ('20261005',
  'STAGE_0940_0945',
  '55100431269d4959b2df40ee7e2838b7',
  'run-d176d40688534d5489d6f425',
  'selection-d176d40688534d5489d6f425',
  'b2c5e0b9f64034362e4bb26f2d560c39b0a434c10d498c26bf1c08fa6d56472a',
  '66e182717a35675eba435ab8e5aedb75a2b5af2c0394db762325cf4692d44a43',
  '6531dcd77064e002893cdf857597fb1a1c94843e45fc19b110d72975554557c6',
  'b8026d3071e28a91524713731809ed7ce4e147c690d45710765c32a2ca86686f',
  'fa0355e5d7a61d582412092e12d9f07f7119a2c3c3f639632152bb539b30d140',
  'fb71c5f844c94d85ccbf0348d570f35fdfe20de30a798e1985fb2d127f49d0c4'),
 ('20261005',
  'STAGE_0945_1030',
  '74724302febe442a873af56d09c8efca',
  'run-ae6edceac734d1088d5f24ec',
  'selection-ae6edceac734d1088d5f24ec',
  '3435db8d7eee6e8465013c33959f72fd7114c7d52d817adb5340bcbf24dcd4ed',
  '60ffaae338806a2c58a1469707dc0bf7ea3a5019935f84531db14ff3a3fcaab8',
  'f3f8d1827a6b9bbee5eeb3190443942b80ffbca35ae7c7c17f010e3a4fb7174b',
  '900317875d532e0f5096712fd220a1fd8b2fc539b84d3453042b1b1ebed9b71e',
  '4561a918a4856fbf9c02c86fe02ff30457f6112b950d6d765a519d5bfddab449',
  'fb71c5f844c94d85ccbf0348d570f35fdfe20de30a798e1985fb2d127f49d0c4'),
 ('20261005',
  'STAGE_1300_1315',
  '02a579db287747dc8a0c2b5155243af9',
  'run-aa837cb7c841867298047236',
  'selection-aa837cb7c841867298047236',
  'fcaabdaee3321843bbbb1f0b86938b1b619384c08ebeb822761123452b879f1a',
  'a74dbb765ff80bbbe75d3a8e71103ebe949b5c73c2aa1a25c97dbdb14485278b',
  'c4c3238d9a395b4ddf72b357974f8e15a34d9911478ff1b99f768707766f8ad6',
  'ed1b080a6046e7dab4a89d24a2838c86aa54ceef15dd185ee0949154afc32555',
  'f0000a3ab5760feccd67cb329326c6ed3751c32e1686f2a2bad90c772a875f37',
  'fb71c5f844c94d85ccbf0348d570f35fdfe20de30a798e1985fb2d127f49d0c4'),
 ('20261005',
  'STAGE_1445_1500',
  '61bf8cb857264457a09c796add942fd3',
  'run-910673fc367e27b1ea0b4d8a',
  'selection-910673fc367e27b1ea0b4d8a',
  '10663c04e4c7a4762564f0432e6406ea214b6e6737cb008045e7b1ae024d71d7',
  'e272b2d6c3f378843dac198f43030fbf20b2de573492ed735749236d849ee971',
  'e3a9022db15718e940b0885f52526e8c5a53bed8146b286aa7838b58142e6458',
  'ed2792ff47449953b8fa20f9b85f7d3f12c56f8c3eedcf2a9fe8117781081892',
  'ccb484b93e578fecc54b471522499782e97504477eaa47e941a5e3d452c50620',
  'fb71c5f844c94d85ccbf0348d570f35fdfe20de30a798e1985fb2d127f49d0c4'),
 ('20261005',
  'STAGE_1545_1555',
  '20533c360d024aa7a286cd5506385b84',
  'run-05fc0a0cc5a8581c6a0ed8cc',
  'selection-05fc0a0cc5a8581c6a0ed8cc',
  '953cc5cf25da321c10a40a8097a58720aeccf5237c5a16380ade4908e0868ac8',
  '694106cea8309a998d262fef28836ea61ac4754b2e0e4767c6f5503dc9532c4e',
  '73e562b6710f9663281f0150c5157f816c13262a54918bd107dbe6c71dfc4b0b',
  'eb1197da4af9e9410c07ce52a1db3b9741e3b9462096039fe9b94cdc1ca5673d',
  'd86860b34c6a1eaf5347b042034a81638dcdf99f8db6757d4fe3b38f53171c46',
  'fb71c5f844c94d85ccbf0348d570f35fdfe20de30a798e1985fb2d127f49d0c4'))
_HK_R8_POOL_EVIDENCE = {
    "20260924": {
        "pool_sha256": "50a014bb51a66ca5bf56853bcf25bc6dc2dacbda257a03e0bb0db2abd7448564",
        "pool_source_sha256": "8ee3a43ebe014f4df7e65beb83271de79978c81e83558c908559c83a7f64291d",
        "source_date": "20260924",
        "signal_date": "20260923",
        "price_signal_date": "20260923",
        "source_run_id": "hk-d1-50a014bb51a66ca5",
        "page_set_sha256": "a0f724f5df59bec2bbcccea6d68501aa2207f22e245e37a7c6a2f9b14d503627",
    },
    "20260930": {
        "pool_sha256": "f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
        "pool_source_sha256": "8a548960a26268ec248d680466153acad0cfc1764b565d6cee06e9392590b666",
        "source_date": "20260930",
        "signal_date": "20260929",
        "price_signal_date": "20260929",
        "source_run_id": "hk-d1-f45233cd1d30d04a",
        "page_set_sha256": "298ee8706062e0ea73fc870beb753648e81c12b9c4e2707b562191b6b6a2b883",
    },
    "20261005": {
        "pool_sha256": "8799c7ef056981549204ece5958222acad92204bfbf9ba5f12ef26bae57dad01",
        "pool_source_sha256": "1d25a2f8c225d58faf060a9ee01dd861f5101b683f072d553c209abddcafddb5",
        "source_date": "20261005",
        "signal_date": "20261002",
        "price_signal_date": "20261002",
        "source_run_id": "hk-d1-8799c7ef05698154",
        "page_set_sha256": "fb71c5f844c94d85ccbf0348d570f35fdfe20de30a798e1985fb2d127f49d0c4",
    },
}
_HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE = _evidence_tuple_keyed("hk_r8_observation_mode")
_HK_R8_COMMON_REQUIRED_EVIDENCE = (
    "historical_provider=pytdx_exhq",
    "historical_capture_after_target_cutoff=true",
    "historical_temporal_cutoff_safe=false",
    "historical_formal_stage_eligibility=CANNOT_CONFIRM",
    "historical_natural_time_capture=CANNOT_CONFIRM",
    "historical_pit_safe=false",
    "historical_supplemental_batch_receipt_sha256=d15a83a7e201e79817c313960463479746c2a99cec31eef28dfd3286cd7b6738",
    "historical_fixed_cache_code_file_sha256=cd510cb9e49b4c06415c612104857ed3726fbb88d5a6733805a66cd61c0adca7",
    "historical_cache_code_set_sha256=4395dcad079830e90c6dfafc401ebf8687a13dff31156aeb73bd8d37d2e747ae",
    "historical_cache_observed_codes=100",
    "historical_cache_missing_codes=0",
    "due_status=HISTORICAL_BACKFILL",
    "historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1",
    "hk_d1_membership=exact_date_top100",
    "hk_acquisition_scope=EXACT_D1_TOP100",
    "hk_d1_status=STRICT_0_2_READY",
    "hk_d1_model_id=prob_active",
    "hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel",
    "selection_contract=V3_TOP10_RECOMMENDATION",
    "selection_mode=RESEARCH_ONLY",
    "historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY",
    "observation_status=OBSERVATION_UNVERIFIED",
    "formal_stage_eligibility=CANNOT_CONFIRM",
    "natural_time_capture=CANNOT_CONFIRM",
    "formal_pit=false",
    "algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506",
    "production_allowed=false",
    "buy_gate_updated=false",
    "orders_sent=false",
)

def _hk_r8_required_evidence(
    trade_date: str,
    stage_id: str,
    pool: Mapping[str, str],
    source_page_set_sha256: str,
    observation_mode_sha256: str,
) -> tuple[str, ...]:
    if _HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE.get((trade_date, stage_id)) != observation_mode_sha256:
        raise ValueError(f"R8 observation contract digest is not bound to {trade_date}/{stage_id}")
    pool_path = _V4_STATE_ROOT / "data" / "preselection_pools" / trade_date / "hkconnect_d1_top100.json"
    required = [
        *_HK_R8_COMMON_REQUIRED_EVIDENCE,
        f"historical_price_signal_date={pool['price_signal_date']}",
        f"historical_source_page_set_sha256={source_page_set_sha256}",
        f"historical_pool_artifact_path={pool_path}",
        f"historical_pool_artifact_sha256={pool['pool_sha256']}",
        f"stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:{observation_mode_sha256}",
        f"hk_d1_source_trade_date={pool['source_date']}",
        f"hk_d1_source_signal_date={pool['signal_date']}",
        f"hk_d1_binding_sha256={pool['pool_sha256']}",
        f"hk_d1_sha256={pool['pool_sha256']}",
        f"candidate_current_sha256={pool['pool_sha256']}",
        f"candidate_run_id={pool['source_run_id']}",
        f"hk_d1_json={pool_path}",
        f"hk_d1_json_sha256={pool['pool_sha256']}",
        f"hk_d1_source_sha256={pool['pool_source_sha256']}",
        "HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE",
        "HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM",
        "HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM",
    ]
    if trade_date == "20261005":
        required.extend((
            "hk_d1_binding_mode=MANIFEST_BOUND_AFTERFACT_EXACT_TARGET_DATE",
            f"hk_afterfact_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:{observation_mode_sha256}",
        ))
    return tuple(required)

_MONTH_HK_AFTERFACT_R8_BINDINGS = tuple(
    {
        "date": date,
        "stage_id": stage_id,
        "market": "HK_CONNECT",
        "backfill_run_id": backfill_run_id,
        "selection_run_id": selection_run_id,
        "artifact_id": artifact_id,
        "raw_artifact_sha256": raw_artifact_sha256,
        "algorithm_id": "V3_STAGE_SELECTION_V1",
        "algorithm_sha256": "fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506",
        "selection_status": "PARTIAL_WITH_ROWS",
        "source_status": "PARTIAL_WITH_ROWS",
        "selected_rows": 10,
        "source_rows": 100,
        "cannot_confirm_count": 3,
        "selection_manifest_sha256": manifest_sha256,
        "selection_receipt_sha256": selection_receipt_sha256,
        "selection_artifact_sha256": selection_artifact_sha256,
        "runner_receipt_sha256": runner_receipt_sha256,
        "observation_mode_sha256": _HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE[(date, stage_id)],
        "required_evidence": _hk_r8_required_evidence(
            date,
            stage_id,
            _HK_R8_POOL_EVIDENCE[date],
            source_page_set_sha256,
            _HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE[(date, stage_id)],
        ),
    }
    for (
        date, stage_id, backfill_run_id, selection_run_id, artifact_id,
        raw_artifact_sha256, manifest_sha256, selection_receipt_sha256,
        selection_artifact_sha256, runner_receipt_sha256, source_page_set_sha256,
    ) in _MONTH_HK_AFTERFACT_R8_BINDING_ROWS
)
_HK_R8_BINDING_BY_DATE_STAGE = {
    (item["date"], item["stage_id"]): item for item in _MONTH_HK_AFTERFACT_R8_BINDINGS
}

# Revoke the 10/05 15:45 R5 wrapper: it was bound to the 09/30 pool.
# Its immutable artifact and receipt remain available in the original evidence store.
_REVOKED_HK_STAGE_BACKFILL_KEYS = {
    ("20261005", "STAGE_1545_1555", "HK_CONNECT", "dd0b08a26ea14cb6ba7423d8b75e09e5"),
}
for _revoked_key in _REVOKED_HK_STAGE_BACKFILL_KEYS:
    _APPROVED_EXACT_STAGE_BACKFILLS.pop(_revoked_key, None)

for _r8_binding in _MONTH_HK_AFTERFACT_R8_BINDINGS:
    _r8_key = (
        _r8_binding["date"],
        _r8_binding["stage_id"],
        _r8_binding["market"],
        _r8_binding["backfill_run_id"],
    )
    if _r8_key in _APPROVED_EXACT_STAGE_BACKFILLS:
        raise RuntimeError(f"duplicate exact stage backfill binding: {_r8_key}")
    _APPROVED_EXACT_STAGE_BACKFILLS[_r8_key] = {
        key: value
        for key, value in _r8_binding.items()
        if key not in {"date", "stage_id", "market", "backfill_run_id"}
    }

# R9 adds 87 exact target-pool after-fact observation bindings. The source
# artifacts are immutable evidence candidates; ordinary reads compose them
# read-only and never publish to shared selection pointers.
_HK_R9_POOL_EVIDENCE = {'20260907': {'code_set_sha256': 'e282b4db0f77ca555eea50c55ab7398863d582ad3e4c9423cdcd4bad222b8f96',
              'pool_manifest_sha256': '8c68aeab43831af0eb6a5c8439ce5d9289095f6a2b497e19e210a510f5b4ee6b',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v35.local/state/data/preselection_pools/20260907/hkconnect_d1_top100.json',
              'pool_receipt_sha256': '6b7763f3a1abb27afad0d13fae42967645a3275fc62c9b4679d70d0f363792bc',
              'pool_sha256': 'a3edf9a33bf8344ef4543e118c8171336264f17d5929f9a7f06e2a58badcc384',
              'signal_date': '20260904',
              'source_date': '20260907',
              'source_run_id': 'hk-d1-a3edf9a33bf8344e',
              'source_sha256': '34424331022b65b47163544dd851402dc9a3d775f3faff526314e6b4d45e59a2'},
 '20260908': {'code_set_sha256': '903db0edd5c21e035ee82a619a92ef61e6e34b333ace0d138b0aee3f77f4a1f7',
              'pool_manifest_sha256': 'ae23f331688c43a953e77ae98e9f5a218def05787c6637928da524114dc5e358',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v35.local/state/data/preselection_pools/20260908/hkconnect_d1_top100.json',
              'pool_receipt_sha256': '338e0430f4c4010a0ec8c01f1215883d9cb530390eedc986ce3f3b3e4e9dd81f',
              'pool_sha256': '9b11fd7f192801552902e406045ee520a19d5a6b373c60a790f6925a30afa3bb',
              'signal_date': '20260907',
              'source_date': '20260908',
              'source_run_id': 'hk-d1-9b11fd7f19280155',
              'source_sha256': '7e4978a2337d90ef7a9b66033188ebfc542a065042f50cc28de39a0496c8ef00'},
 '20260909': {'code_set_sha256': '7ae472d85426c54e879d15be255c7f6a8c0fde67042fb024f58bc449e89b87db',
              'pool_manifest_sha256': 'bedadc60f6515937efe19f60c93fe676ddc2454087bc3780322f9e072c2109dc',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v35.local/state/data/preselection_pools/20260909/hkconnect_d1_top100.json',
              'pool_receipt_sha256': '5af4c0e9c03b9fdfd7df6abc8df161cdc46ea96398b2b0419cbba7133dfd2a1a',
              'pool_sha256': '72d3b18d18e7c402eabb4c030d98d2b3ddd8079383c3e3f4c3ed6e57618feb65',
              'signal_date': '20260908',
              'source_date': '20260909',
              'source_run_id': 'hk-d1-72d3b18d18e7c402',
              'source_sha256': '315595df733365d4b73885fd4e56a27644e1a54255552a342faf44f1d4180a72'},
 '20260910': {'code_set_sha256': '7fd6e487c67612ddf0c047e23ac08b69dbad35b8db5233991bb8b302d2f3d1b9',
              'pool_manifest_sha256': 'd219d6d62872549598573231292e7a14016a9d09cd1121f78a3655f5fa5c5ee2',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v35.local/state/data/preselection_pools/20260910/hkconnect_d1_top100.json',
              'pool_receipt_sha256': '2d0a57ad8c94cbe5d33fb1c5e9b56e7a58a574cf9d7261e97db0761f133da3ea',
              'pool_sha256': '2a514ccf092ba41a03a864098f204e15154acbfcb049b8b36c89e138f9f47304',
              'signal_date': '20260909',
              'source_date': '20260910',
              'source_run_id': 'hk-d1-2a514ccf092ba41a',
              'source_sha256': '77e6996021aaf320fefba6c43ec25d31db88ac392e87150b4c962fd250794593'},
 '20260911': {'code_set_sha256': '508db177627340b456ce44bdb92f5ee42bd19a9ceceed3549f4b871e1598aa93',
              'pool_manifest_sha256': 'c3ab9e60dddd1a1874be9c122285ac45a094c346551979ea7aa0e8cfd3c046b2',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v35.local/state/data/preselection_pools/20260911/hkconnect_d1_top100.json',
              'pool_receipt_sha256': 'e0ad3b7279948d30ee5b68e5b6326320b84f9ff5adc18a05d5b993f6a9875fe5',
              'pool_sha256': 'fa90437cbb0988a156b78c70281b8201aa305aa698921ff99662cd33b03690bd',
              'signal_date': '20260910',
              'source_date': '20260911',
              'source_run_id': 'hk-d1-fa90437cbb0988a1',
              'source_sha256': '94905013337883f8c52c9c8fe3636b89e1b08a336147eeb1d602e9a9a6f1914c'},
 '20260914': {'code_set_sha256': '5fe73e8febe7a131c398b911564cfa05396bb9943479f5ba661a075e57f23417',
              'pool_manifest_sha256': '96c9f6c8f8085f531bfbb26921c57836bb53b0098b4110b34e7eba9db800568b',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v4.local/state/data/preselection_pools/20260914/hkconnect_d1_top100.json',
              'pool_receipt_sha256': 'f8e8bea7188acb8fd55db82e9d30c7aa281a3c0ed4635cbdd62d0cc886cdc5b1',
              'pool_sha256': 'beba5c0c39bf78ca01415485db146a0259ad6558cc74501a6125b7ae19cb2d02',
              'signal_date': '20260911',
              'source_date': '20260914',
              'source_run_id': 'hk-d1-beba5c0c39bf78ca',
              'source_sha256': '149d5edcd7d3c2b4a564e46967f4b0d22cff79ff6b918acaffe085f3e4df6d91'},
 '20260915': {'code_set_sha256': '212a42b5e56e5cd7fb3ab75125237775d07a3764bf7f09ca5614fa1c927ed2de',
              'pool_manifest_sha256': '3435f8ce38d8ff1e4f1b5ab864e470ff0e2cc1ab1a657515a57686f54a757098',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v4.local/state/data/preselection_pools/20260915/hkconnect_d1_top100.json',
              'pool_receipt_sha256': '1a1effa9ff4bc1523bd8a2f7b2ab49a7e08b9c7752aabab721b062cf054eb063',
              'pool_sha256': 'f59e2c47637d1f4cb2283394e9dbd6fa5c396789601d9bf8fb6db45a170dd91b',
              'signal_date': '20260914',
              'source_date': '20260915',
              'source_run_id': 'hk-d1-f59e2c47637d1f4c',
              'source_sha256': '187b259de24d898f02a97f0500690993118cb18c6c79cc97de8ff43309b35534'},
 '20260916': {'code_set_sha256': 'fa22d9a1e37d43ef039837857aa2505a5562686285ea457dfa7b1a59f0cd69c4',
              'pool_manifest_sha256': '4835c50466347fff3adbd2f45c220a9a192031b36f198e7dd78682fbe43c75e2',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v4.local/state/data/preselection_pools/20260916/hkconnect_d1_top100.json',
              'pool_receipt_sha256': 'aa454faad343b63f4d48569a2af2dc2be200e6df38d06d9f4b67f760d7e1a0b5',
              'pool_sha256': '474bbc703cc1c45e3d3bea39ea0d649b523c7706f3e02fdbea25d1734da52f5f',
              'signal_date': '20260915',
              'source_date': '20260916',
              'source_run_id': 'hk-d1-474bbc703cc1c45e',
              'source_sha256': '54a6e1245a5de9402c61e1f19108a992f09bfb9108cf48a5afca2d0f02769447'},
 '20260917': {'code_set_sha256': '8eda436d7a7a9b3dee8051e700585de6b0d3b9a134b7183802c59c869f071cd7',
              'pool_manifest_sha256': '66561e7bbc891e9a0b2317ab9107301eb87bf9a408ca06673a5e04cc40d46ef5',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v4.local/state/data/preselection_pools/20260917/hkconnect_d1_top100.json',
              'pool_receipt_sha256': '9759f2d8218e9f3c55b144c05434b9f3f2169259fe7eb6f3fe9a2f3bcb071831',
              'pool_sha256': 'f0d425d355df4cdacb5d0e77ec4798ed83b468cf97d30a2fe333b8ebfab9e470',
              'signal_date': '20260916',
              'source_date': '20260917',
              'source_run_id': 'hk-d1-f0d425d355df4cda',
              'source_sha256': 'ce24544643020aafff2bf05d295add1c559787778723688479c27ce6451fe030'},
 '20260918': {'code_set_sha256': 'd3dd24a11a1f9670cb754869d0173f0fe690078e4b6c542dbcf72055be99cf37',
              'pool_manifest_sha256': '9552a91e012620875217135b08ac7472ff05c3fa60becebe87d0ad2ff99bec5e',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v4.local/state/data/preselection_pools/20260918/hkconnect_d1_top100.json',
              'pool_receipt_sha256': '12ef7b967634677a6a76759f41c770fc16a4b950eae95c12a2526ba9ef7d1be3',
              'pool_sha256': '87304841ab06ba4778547fcd9744427ccd73b31c0482861e02d42bd1959e5f24',
              'signal_date': '20260917',
              'source_date': '20260918',
              'source_run_id': 'hk-d1-87304841ab06ba47',
              'source_sha256': 'c3dfa04e3b4a6a03aed7e98152f52e993a9945fd094f4a43ab8d3d8b1c16a890'},
 '20260922': {'code_set_sha256': '1f4a63a44899d43b2b821fd10ea17ca18303751bc838e586c658cdd826d8de64',
              'pool_manifest_sha256': '7517f005249a7ee7a1d2def70a2c2df48c191e42d02567c9c522dbf1d8b70ae4',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v35.local/state/data/preselection_pools/20260922/hkconnect_d1_top100.json',
              'pool_receipt_sha256': 'd6a9eb58df0220901d962da3c6139ee866233c7cc88e5a24f267570f2becbf16',
              'pool_sha256': '499908ce213e00c31dc487e9a47f904b91a49f3cc817f549b2f6021c29105ffb',
              'signal_date': '20260921',
              'source_date': '20260922',
              'source_run_id': 'hk-d1-499908ce213e00c3',
              'source_sha256': 'd39bcce29b75693656783e00ecb0c4a62fb54dd58c47616c52c303ffd3c99c79'},
 '20260923': {'code_set_sha256': 'c15c86d9d0dee9f092dd75e285112ca03e0064653ad0f8ab6585cde41f52a744',
              'pool_manifest_sha256': '8c3871d1793d50d66eb503e89d4612de3702ac245b07500de33203d4206871b7',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v35.local/state/data/preselection_pools/20260923/hkconnect_d1_top100.json',
              'pool_receipt_sha256': '20bdfa7490919220b75a1dbc8f395b92e986de9791045ff9d341c246ab62c741',
              'pool_sha256': 'c8d0cf45d9c8a99c44a4a568b4d1e26cb0f50fa48d7124e3f0ddecf8e267ded2',
              'signal_date': '20260922',
              'source_date': '20260923',
              'source_run_id': 'hk-d1-c8d0cf45d9c8a99c',
              'source_sha256': 'f0822dbbf4b638351f4655f2a82d47af4bb0dc82ed40025ce4d61d73521e9cc2'},
 '20260929': {'code_set_sha256': 'd4a294e18d5e0399a8410e833b4535dc8b1c3423af9d30aba0703b899d5f86a8',
              'pool_manifest_sha256': 'b0f06ae4d85c34018a0a5cc05034776f8035414fa63d0284931349ce966c3acf',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v35.local/state/data/preselection_pools/20260929/hkconnect_d1_top100.json',
              'pool_receipt_sha256': 'a809f6379462fed4fd1ffeaf3a1116d635af9c0dff19fe307147eb22a3be8b27',
              'pool_sha256': 'd94eae4903aa09088f88d954d358869e7c1ac991782488ad62fd3bec40eeaaf3',
              'signal_date': '20260928',
              'source_date': '20260929',
              'source_run_id': 'hk-d1-d94eae4903aa0908',
              'source_sha256': '83940e1da0914b2b90c96ce65f241154403502da65e4cacca6023e79e0a13dbb'},
 '20261002': {'code_set_sha256': '78bb7af3f8e2b165170325734e1c3bc43de12deb1d95b0b2365ed2b1a77d2181',
              'pool_manifest_sha256': '56989eb471718751e8f64335bc5c38af015cf9d147732e24ab5617fc647b7529',
              'pool_path': '/Users/lexi/Library/Application '
                           'Support/com.lexi.v35.local/state/data/preselection_pools/20261002/hkconnect_d1_top100.json',
              'pool_receipt_sha256': '9da167bbe73e78c3d0cf0f3376ccf71c41a6988a53d2ebc97d07b7288ee9483b',
              'pool_sha256': '9486b32cd8290994e1bf82cd15863fb7d0c00100bd52f1f6eb5d03af80b72077',
              'signal_date': '20260930',
              'source_date': '20261002',
              'source_run_id': 'hk-d1-9486b32cd8290994',
              'source_sha256': 'b6038d1eba2cc7c005451d0b208c90985eddfe8442321547f036c359a2636654'}}
_MONTH_HK_AFTERFACT_R9_STAGE_ROWS = _evidence_row_dicts("hk_afterfact_r9_stage_rows")

def _hk_r9_required_evidence(row: Mapping[str, Any], pool: Mapping[str, str]) -> tuple[str, ...]:
    required = [
        "buy_gate_updated=false",
        "historical_capture_after_target_cutoff=true",
        f"historical_capture_batch_receipt_sha256={row['capture_batch_receipt_sha256']}",
        "historical_formal_stage_eligibility=CANNOT_CONFIRM",
        "historical_natural_time_capture=CANNOT_CONFIRM",
        "historical_pit_safe=false",
        f"historical_price_signal_date={pool['signal_date']}",
        "historical_provider=pytdx_exhq",
        f"historical_source_page_set_sha256={row['source_page_set_sha256']}",
        "historical_temporal_cutoff_safe=false",
        "orders_sent=false",
        "production_allowed=false",
        f"historical_target_pool_code_set_sha256={pool['code_set_sha256']}",
        f"historical_capture_observed_pool_codes={row['observed_rows']}",
        f"historical_capture_missing_pool_codes={row['missing_rows']}",
        f"historical_pool_artifact_path={pool['pool_path']}",
        f"historical_pool_artifact_sha256={pool['pool_sha256']}",
        f"stage_center_observation_mode={row['observation_mode_marker']}",
        "due_status=HISTORICAL_BACKFILL",
        "historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1",
        f"hk_d1_source_trade_date={pool['source_date']}",
        f"hk_d1_source_signal_date={pool['signal_date']}",
        f"hk_d1_binding_sha256={pool['pool_sha256']}",
        f"hk_d1_sha256={pool['pool_sha256']}",
        f"candidate_current_sha256={pool['pool_sha256']}",
        f"candidate_run_id={pool['source_run_id']}",
        f"hk_d1_json={pool['pool_path']}",
        "hk_d1_membership=exact_date_top100",
        "hk_acquisition_scope=EXACT_D1_TOP100",
        "hk_d1_status=STRICT_0_2_READY",
        f"hk_d1_json_sha256={pool['pool_sha256']}",
        f"hk_d1_source_sha256={pool['source_sha256']}",
        "selection_contract=V3_TOP10_RECOMMENDATION",
        "selection_mode=RESEARCH_ONLY",
        "historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY",
        "observation_status=OBSERVATION_UNVERIFIED",
        "formal_stage_eligibility=CANNOT_CONFIRM",
        "natural_time_capture=CANNOT_CONFIRM",
        "formal_pit=false",
        "algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506",
    ]
    if row["date"] == "20260907":
        required.append(
            f"historical_target_pool_artifact_sha256={pool['pool_sha256']}"
        )
    if row["date"] != "20260907":
        required.extend((
            f"historical_target_d1_manifest_sha256={pool['pool_manifest_sha256']}",
            f"historical_target_d1_receipt_sha256={pool['pool_receipt_sha256']}",
        ))
    required.extend(row["missing_evidence_markers"])
    return tuple(required)

_MONTH_HK_AFTERFACT_R9_BINDINGS = tuple(
    {
        **row,
        "market": "HK_CONNECT",
        "algorithm_id": "V3_STAGE_SELECTION_V1",
        "algorithm_sha256": "fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506",
        "selection_status": "PARTIAL_WITH_ROWS",
        "source_status": "PARTIAL_WITH_ROWS",
        "source_rows": row["source_rows"],
        "required_evidence": _hk_r9_required_evidence(
            row, _HK_R9_POOL_EVIDENCE[row["date"]]
        ),
        "pool_artifact_sha256": _HK_R9_POOL_EVIDENCE[row["date"]]["pool_sha256"],
        "pool_manifest_sha256": _HK_R9_POOL_EVIDENCE[row["date"]]["pool_manifest_sha256"],
        "pool_receipt_sha256": _HK_R9_POOL_EVIDENCE[row["date"]]["pool_receipt_sha256"],
        "pool_code_set_sha256": _HK_R9_POOL_EVIDENCE[row["date"]]["code_set_sha256"],
        "pool_path": _HK_R9_POOL_EVIDENCE[row["date"]]["pool_path"],
        "pool_signal_date": _HK_R9_POOL_EVIDENCE[row["date"]]["signal_date"],
    }
    for row in _MONTH_HK_AFTERFACT_R9_STAGE_ROWS
)
_HK_R9_BINDING_BY_DATE_STAGE = {
    (item["date"], item["stage_id"]): item
    for item in _MONTH_HK_AFTERFACT_R9_BINDINGS
}

_HK_MORNING_SELECTION_RECOVERY_REQUIRED_EVIDENCE = (
    "recovery_mode=HISTORICAL_BACKFILL",
    "due_status=HISTORICAL_BACKFILL",
    "HISTORICAL_BACKFILL",
    "selection_mode=BACKFILL",
    "observation_status=OBSERVATION_UNVERIFIED",
    "observation_contract=HK_MORNING_SELECTION_REPROJECTION_R1",
    "historical_capture_after_target_cutoff=true",
    "historical_temporal_cutoff_safe=false",
    "historical_formal_stage_eligibility=CANNOT_CONFIRM",
    "historical_natural_time_capture=CANNOT_CONFIRM",
    "historical_pit_safe=false",
    "historical_orderbook=CANNOT_CONFIRM",
    "recovery_original_failure=HK_ACTIVE_SNAPSHOT_UNAVAILABLE",
    "production_allowed=false",
    "buy_gate_updated=false",
    "orders_sent=false",
)
_HK_MORNING_SELECTION_RECOVERY_ROWS = (
    {
        "stage_id": "STAGE_0930_0935",
        "backfill_run_id": "hk-morning-20261016-stage-0930-v1",
        "selection_run_id": "run-e8a2024a09a9c2f5f2e94312",
        "artifact_id": "selection-e8a2024a09a9c2f5f2e94312",
        "raw_artifact_sha256": "1c850296885d7516151ea658f81ef1afd3706047664005f3568de86a4acad777",
        "original_manifest_sha256": "831b93b360bd61e1bf65f9704844e5a32ef98f7af2e5bd12dd0494eaaa0fb85d",
        "original_receipt_sha256": "5be67f93b87e7c262f5b840e7a51d343c341720ed277bc86b366c53823fb0792",
        "selection_manifest_sha256": "f2c6a24eb3104b1cb4e95c8d69cc125678be920283d80523ab2e3b8b7b4a627a",
        "selection_receipt_sha256": "7c97a711f9e07b0d85933138f4e47089644fe00de4e68a9420c24e3488505bd1",
        "selection_artifact_sha256": "64da4a35c08c0fd194b751d14ee681c4e192e64542054440d7b357166207d0e2",
        "runner_receipt_sha256": "7705fd6b8393e2cbe2dfebdd12bead7d370511ce24c01440ca161ab1edb659af",
        "source_evidence_sha256": "3467ddde3ed8c612e077d61d8bf9d288765f41c84f18ca14a1c168077d2d31f2",
    },
    {
        "stage_id": "STAGE_0935_0940",
        "backfill_run_id": "hk-morning-20261016-stage-0935-v1",
        "selection_run_id": "run-ccc20f037cc139b83f8a3f7c",
        "artifact_id": "selection-ccc20f037cc139b83f8a3f7c",
        "raw_artifact_sha256": "a71b46e70063bfa2c9665eec341680cd88d6c9bc6bb358cb9966a999702ee26c",
        "original_manifest_sha256": "b9a099fb646ee9654f1200906cb2558e37bc7ba87ec40e6ab7e5cd25e6211b7c",
        "original_receipt_sha256": "9d8444d33e119193521aab0d43901e8a181603d13f2433c750dda87d20602783",
        "selection_manifest_sha256": "c6a427472e3d22f464c8c4f71c147c76394d591cc034408bf69ebcb934b44d83",
        "selection_receipt_sha256": "10b6f0d7deff4a0863e893893d51115983d78e7c4a603b544286265a773ce546",
        "selection_artifact_sha256": "ed05e2eb54592992be63aa9bb842e10443fa4c9b2bacda1d989bd52898f1a09b",
        "runner_receipt_sha256": "e6c3ea14d193a3cdc6f4a622b0c55d7176087316da1d4d3217dbe175f5eb0b60",
        "source_evidence_sha256": "c99e8481604fcb9280c1c428e7eae4cc67c5a1efb3dea81bfc4444496906e072",
    },
    {
        "stage_id": "STAGE_0940_0945",
        "backfill_run_id": "hk-morning-20261016-stage-0940-v1",
        "selection_run_id": "run-9f5dbc39a836451324721acf",
        "artifact_id": "selection-9f5dbc39a836451324721acf",
        "raw_artifact_sha256": "6c273dcd40a7de66a10c523b9345171565d866c64c6c33b6c39c713ea7914655",
        "original_manifest_sha256": "d27bcf81f1622bb85a5033c01986688d98e38a3a6c82eda2a977a95fdaaf2d23",
        "original_receipt_sha256": "e0564cc51f362e19f3de119c6c62376f37623e4773f6689321170df02e10c743",
        "selection_manifest_sha256": "ba2f1ea44b9e348e1d3de61b4bcb9ac8cc38fbd71d3537ce9c2a4feb4e75b937",
        "selection_receipt_sha256": "126085edf5155e4861c1d3fb4a47fe88b9fd338746e713237889c134c0d839e9",
        "selection_artifact_sha256": "c4e4720a38ea2de6d2bb0b40ca6a0356289cab33825890f6329056567dedb950",
        "runner_receipt_sha256": "64573855d3ed3a4e7454dd27cbd207fa4d1bf95e238f4e7510404bcf662d749d",
        "source_evidence_sha256": "ba4e0c1d97d166789eed605cde6cdd0753a75558c196e34c6db06201426dad2b",
    },
    {
        "stage_id": "STAGE_0945_1030",
        "backfill_run_id": "hk-morning-20261016-stage-0945-v1",
        "selection_run_id": "run-181ddc8bd8047a502234b698",
        "artifact_id": "selection-181ddc8bd8047a502234b698",
        "raw_artifact_sha256": "c7e8bfcae1e969874e8291e58b7cbcebddd0ac1c9a38435257b45ccaed1ab794",
        "original_manifest_sha256": "e3214b8e79cc32c249f7970cf2b221f6150c33c8df225bfe421a61454975593a",
        "original_receipt_sha256": "b5af283cebd60428599247c2e3f5d954fae530b477e1be10e2d7f8e12beb0612",
        "selection_manifest_sha256": "4479d731a796b0ef6e2065c92dab98da3b88462b334cdd31d32e7e2e11908e13",
        "selection_receipt_sha256": "ac37537b8bab1e0fbd02dd836b17f23dedbf98a7e5a159b4e80a67204b6dacca",
        "selection_artifact_sha256": "0e8ecec964d6b9827dd07eba568c3c9318e3ee622abbd7801a6b50daa67c903b",
        "runner_receipt_sha256": "b286e07ed50e8b8c806661939cb4c2b441d28f0fd1bf627925a908f8145e7ec0",
        "source_evidence_sha256": "f2cbaa26f106c7b59cdc7574fdcb91507f4ddca2e780b8f331382442f3fa4832",
    },
)
_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE = {
    ("20261016", row["stage_id"]): {
        **row,
        "market": "HK_CONNECT",
        "algorithm_id": "V3_STAGE_SELECTION_V1",
        "algorithm_sha256": "f2991c472b17742acfd3adb81458ff13826f99dfb7b8a223ad8d6a5dfbbd1a1e",
        "selection_status": "PARTIAL_WITH_ROWS",
        "source_status": "CANNOT_CONFIRM",
        "requested_rows": 100,
        "source_rows": 100,
        "selected_rows": 10,
        "missing_rows": 0,
        "missing_codes": (),
        "cannot_confirm_count": 1,
        "required_evidence": _HK_MORNING_SELECTION_RECOVERY_REQUIRED_EVIDENCE,
    }
    for row in _HK_MORNING_SELECTION_RECOVERY_ROWS
}
for _hk_morning_binding in _HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE.values():
    _hk_morning_key = (
        "20261016",
        _hk_morning_binding["stage_id"],
        "HK_CONNECT",
        _hk_morning_binding["backfill_run_id"],
    )
    if _hk_morning_key in _APPROVED_EXACT_STAGE_BACKFILLS:
        raise RuntimeError(f"duplicate exact stage backfill binding: {_hk_morning_key}")
    _APPROVED_EXACT_STAGE_BACKFILLS[_hk_morning_key] = {
        key: value
        for key, value in _hk_morning_binding.items()
        if key not in {
            "stage_id",
            "original_manifest_sha256",
            "original_receipt_sha256",
        }
    }

# These nine legacy observations were captured from the live ordinary reader
# and its verified SelectionStore entries. Their HK D1 markers consistently
# identify a different pool from the exact target-date candidate below. Keep
# the compatibility boundary pinned to each old run, artifact, pool path, and
# SelectionStore manifest/receipt identity. In particular, candidate_current
# markers are intentionally not treated as HK D1 pool aliases.
_HK_R9_LEGACY_STALE_POOL_CONTRACTS = {
    "20260914": {
        "pool_sha256": "5efc2b292418f062c9d3acce6bb3c47ded90eff3c80f753311deb1e5b6ca81ed",
        "pool_path": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/preselection_pools/20260914/hkconnect_d1_top100.json",
        "source_trade_date": None,
        "source_signal_date": None,
        "binding_sha256": None,
    },
    "20261002": {
        "pool_sha256": "f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
        "pool_path": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/preselection_pools/20260930/hkconnect_d1_top100.json",
        "source_trade_date": "20260930",
        "source_signal_date": "20260929",
        "binding_sha256": "f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
    },
}
_HK_R9_LEGACY_STALE_LANE_IDENTITIES = {
    ("20260914", "STAGE_0930_0935"): {
        "run_id": "run-ddebe6065cd641562d3c98cf",
        "artifact_id": "selection-ddebe6065cd641562d3c98cf",
        "raw_artifact_sha256": "376143acf36ee74c3c62c799e8f4c533b79fc6a74a3e8581c5cf5d9f1148da94",
        "selection_artifact_sha256": "5b1603976188ffedaff797973320415a55b6cfec614f53e1b8892df94e2c35b9",
        "selection_manifest_sha256": "03d9937adaffc40b879b6a173ee95ccefae612c34b92fbe58995ef70b82b4d67",
        "selection_receipt_sha256": "bfc4f20cb94998c68c5fd71cebf8e9de86693810be416750837ab499cd422c29",
        "requested_rows": 100,
        "source_rows": 99,
        "observation_count": 10,
    },
    ("20260914", "STAGE_0935_0940"): {
        "run_id": "run-f754096694ad081a4c1be700",
        "artifact_id": "selection-f754096694ad081a4c1be700",
        "raw_artifact_sha256": "7ce0e02268a5fa2370304dee8645bae0e2093e513d4d15f4411961a98aa16965",
        "selection_artifact_sha256": "b8635ed884fefe876dfedb85936cb059c8ab551a02bd363af50b7d5bf32f7046",
        "selection_manifest_sha256": "a0ea55d19a11c2b1086d536d8a4e947714be57140d26b2e2a31de560533e43e0",
        "selection_receipt_sha256": "15667a53038a19e37729b7ca424adc7e60b0d339f53ca0cb141c684488e3bc2a",
        "requested_rows": 100,
        "source_rows": 99,
        "observation_count": 10,
    },
    ("20260914", "STAGE_0940_0945"): {
        "run_id": "run-762102f832912b5c3eba93c4",
        "artifact_id": "selection-762102f832912b5c3eba93c4",
        "raw_artifact_sha256": "d75c50e6579261393ac480e66e0e5e6e5f6c67d20143e7db58c5ca55053c91fd",
        "selection_artifact_sha256": "6d9afff2d240a67bd67012b414c1b404e7901d4ead7325a12edbb7ad548bc918",
        "selection_manifest_sha256": "d136b81561d58c3f44c4db801576b5b4c927bcd6ffb29f7d3668bf078d7bb8ca",
        "selection_receipt_sha256": "8e446c5066e0c15c70a58bdc9d48ead4e8155f1d8d80c7aecce8cec8631ba95d",
        "requested_rows": 100,
        "source_rows": 99,
        "observation_count": 10,
    },
    ("20260914", "STAGE_0945_1030"): {
        "run_id": "run-34cecc7adf0c099e6438f665",
        "artifact_id": "selection-34cecc7adf0c099e6438f665",
        "raw_artifact_sha256": "210d90e915de4e495b50545a3b06c803773ec3310d5b74a7a076e1d815fd70ae",
        "selection_artifact_sha256": "fa0d9a43683c23b1b803a0816d80b0a5b6c48c6cb99114859af98908710f6c6b",
        "selection_manifest_sha256": "de38f6f660cdd11451009b9c5424e1b9529c85ca2fc0fbbca86af12cf2e42605",
        "selection_receipt_sha256": "c3c445ee9d321c0245ce7721ec3e57ee95b41b2fbc861c4f937de8718c65e24b",
        "requested_rows": 100,
        "source_rows": 99,
        "observation_count": 10,
    },
    ("20260914", "STAGE_1300_1315"): {
        "run_id": "run-098cfa4c85b2a45cc3bb6f73",
        "artifact_id": "selection-098cfa4c85b2a45cc3bb6f73",
        "raw_artifact_sha256": "22cbd1dc00b32a6238840d43ddee3ad163547aeebcb2f27f15f6286dbe5c0d34",
        "selection_artifact_sha256": "ea990e08437b0a358bdc59877904e8cce8e08a1b70ef10108809df1e3095263d",
        "selection_manifest_sha256": "c8e0778ebf4ba5209847e106d7fa952c281637384854ccada480e4258d67fc08",
        "selection_receipt_sha256": "07c1658a3284bddc260e24bfeedfcf0179ea096033b9a1764d09f282059e39ca",
        "requested_rows": 100,
        "source_rows": 99,
        "observation_count": 10,
    },
    ("20260914", "STAGE_1445_1500"): {
        "run_id": "run-6b5e1f0bdea67ed9c2e4ebca",
        "artifact_id": "selection-6b5e1f0bdea67ed9c2e4ebca",
        "raw_artifact_sha256": "4b4dae2c8854b39e4b518c1b6bbb023e330ff889699d314300753e527f0f6ee3",
        "selection_artifact_sha256": "693edb804e828fd3c4ae63b3d97fe5311d6b0ab79463fc740e25527f771fb6cb",
        "selection_manifest_sha256": "538eab784d1ed420d87e0d322570c5206487242ec7971d2019de6b2afd19b2b0",
        "selection_receipt_sha256": "6ce094c2613b51e29b01773438d6d7b3955e7c1b7ed7cc25bf81725fc4e645ee",
        "requested_rows": 100,
        "source_rows": 99,
        "observation_count": 10,
    },
    ("20261002", "STAGE_1300_1315"): {
        "run_id": "run-c54d3c6ebf6aab8c3b972491",
        "artifact_id": "selection-c54d3c6ebf6aab8c3b972491",
        "raw_artifact_sha256": "8f2a1d886b59d45d3f90d6d26e5a5fc9c7578fed97609ed42e50d134ef7ec13a",
        "selection_artifact_sha256": "289f8b79fe63f401fb933d4a29bf8a5e0bacead0d6c7234c7e818efe1664c42d",
        "selection_manifest_sha256": "125c9beb951e5177d67baf2463127b5347599c634c23b5cacf97339f9e8bdaa7",
        "selection_receipt_sha256": "16fa584e093fedfa8b75669b6ef59ea841ebdaea7d6bc43070fa35c765ee6cc8",
        "requested_rows": 100,
        "source_rows": 100,
        "observation_count": 10,
    },
    ("20261002", "STAGE_1445_1500"): {
        "run_id": "run-7c9d106a75703472c9f1a202",
        "artifact_id": "selection-7c9d106a75703472c9f1a202",
        "raw_artifact_sha256": "6b6d739b7d52adebd137f1dfff785d83cd7d3dfc867e37c9957aad904bb28179",
        "selection_artifact_sha256": "362f43d40b711eb57d821bd447e8dc9fbe23df40ea8d3164b2b4d0b63301d7df",
        "selection_manifest_sha256": "bc2dd14b8b6947d0e2f2745225734b9c89e26744a6549555d3b8c24cdc8e2ebd",
        "selection_receipt_sha256": "859346ab581fbae28ea973054011749b286b8de3c29f7fab34f3ea0ce99adc80",
        "requested_rows": 100,
        "source_rows": 100,
        "observation_count": 10,
    },
    ("20261002", "STAGE_1545_1555"): {
        "run_id": "run-d4e2e669cf2bd4fb1f572779",
        "artifact_id": "selection-d4e2e669cf2bd4fb1f572779",
        "raw_artifact_sha256": "434ea250c413770aa4f584d737b66666dca21bc37c36fc5da5936052c91a1177",
        "selection_artifact_sha256": "1f56fa22b1e95c926229e9ea438163186e2b39bc0e2765c001358eaeb637d555",
        "selection_manifest_sha256": "fa861d31404eb59f8788e3f50e39ea197eb779244e6862469e6df9c984d627e8",
        "selection_receipt_sha256": "54220679a950ff06c3b94427e61f0f35630ce3e1d51bbc588f3de71d12a23933",
        "requested_rows": 2,
        "source_rows": 2,
        "observation_count": 2,
    },
}
_HK_R9_LEGACY_STALE_POOL_KEYS = frozenset(_HK_R9_LEGACY_STALE_LANE_IDENTITIES)
for _r9_binding in _MONTH_HK_AFTERFACT_R9_BINDINGS:
    _r9_key = (
        _r9_binding["date"],
        _r9_binding["stage_id"],
        _r9_binding["market"],
        _r9_binding["backfill_run_id"],
    )
    if _r9_key in _APPROVED_EXACT_STAGE_BACKFILLS:
        raise RuntimeError(f"duplicate exact stage backfill binding: {_r9_key}")
    _APPROVED_EXACT_STAGE_BACKFILLS[_r9_key] = {
        key: value
        for key, value in _r9_binding.items()
        if key not in {"date", "stage_id", "market", "backfill_run_id"}
    }

def _resolve_exact_backfill_selection_root(selection_root: Path | str, run_id: str) -> Path:
    """Resolve one pinned run-scoped store without following namespace symlinks."""
    configured_root = Path(selection_root).expanduser()
    if configured_root.is_symlink():
        raise HTTPException(status_code=404, detail="backfill selection namespace is unavailable")
    try:
        root = configured_root.resolve(strict=True)
        backfill_root = root / "backfill"
        run_root = backfill_root / run_id
        if (
            not root.is_dir()
            or backfill_root.is_symlink()
            or backfill_root.resolve(strict=True) != backfill_root
            or not backfill_root.is_dir()
            or run_root.is_symlink()
            or run_root.resolve(strict=True) != run_root
            or run_root.resolve(strict=True).parent != backfill_root
            or not run_root.is_dir()
        ):
            raise HTTPException(status_code=404, detail="backfill selection run is unavailable")
    except (OSError, RuntimeError):
        raise HTTPException(status_code=404, detail="backfill selection run is unavailable")
    return run_root


def _new_scoped_stage_selection_consumer(
    root: Path | str,
    shared_consumer: StageSelectionConsumer,
) -> StageSelectionConsumer:
    """Build a run-scoped consumer across supported release constructor names."""
    parameters = inspect.signature(StageSelectionConsumer).parameters
    accepts_keywords = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    kwargs: dict[str, Any] = {}
    if "a_name_pool_root" in parameters or accepts_keywords:
        kwargs["a_name_pool_root"] = shared_consumer.a_name_pool_root
    else:
        raise TypeError("StageSelectionConsumer lacks a_name_pool_root support")

    receipt_root = shared_consumer.runner_receipt_root
    if "runner_receipt_root" in parameters:
        kwargs["runner_receipt_root"] = receipt_root
    elif "execution_receipt_root" in parameters:
        kwargs["execution_receipt_root"] = receipt_root
    elif accepts_keywords:
        kwargs["runner_receipt_root"] = receipt_root
    else:
        raise TypeError("StageSelectionConsumer lacks a runner receipt root parameter")
    return StageSelectionConsumer(root, **kwargs)


def _resolve_manager_research_state_root(
    manager_research_state_root: Path | str | None,
    data_root: Path | str | None,
) -> Path:
    """Resolve the manager lane below its one canonical state root.

    ``V4_DATA_ROOT`` points at the shared host data tree and is also passed as
    ``data_root`` by the live launcher.  The manager product has its own
    sibling state directory, so that host argument must not become a nested
    manager store.  A noncanonical explicit data root remains isolated for
    embedded tests and callers; the dedicated manager argument and env
    override always take precedence.
    """

    if manager_research_state_root is not None:
        return Path(manager_research_state_root)
    env_state_root = os.environ.get("V4_MANAGER_RESEARCH_STATE_ROOT")
    if env_state_root:
        return Path(env_state_root)
    if data_root is not None:
        explicit_data_root = Path(data_root).expanduser()
        if explicit_data_root.resolve() == (_V4_STATE_ROOT / "data").resolve():
            return _CANONICAL_MANAGER_RESEARCH_STATE_ROOT
        return explicit_data_root / "manager_auto_research"
    return _CANONICAL_MANAGER_RESEARCH_STATE_ROOT


class _RevalidatingStaticFiles(StaticFiles):
    """Serve HTML entry points with revalidation, hashed assets as usual.

    A cached HTML document can reference a hashed asset that a later release
    no longer ships, so documents must be revalidated (``no-cache``) instead
    of being served from heuristic freshness; content-hashed assets keep
    their default caching because their names change with their bytes.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["cache-control"] = "no-cache"
        return response


def _strict_date(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise HTTPException(status_code=422, detail="date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="date must be a real calendar date") from error
    return value



# Exact saved 20261023 observation inputs; this grants no formal/PIT eligibility.
_HK_MORNING_HISTORY_20261023 = {'STAGE_0930_0935': {'files': {'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0930_0935/run-c189009adf3a4eebf481d892/artifact.csv': '701da95236a8fbe1182a2a9764472794f2429963721ffdcdf4b646a0c42e3659',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0930_0935/run-c189009adf3a4eebf481d892/manifest.json': '57d86298fd5741a95315e311711d409ac8a4f6a728bc3f27d51fcf85190984f9',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0930_0935/run-c189009adf3a4eebf481d892/receipt.json': '38c146f3a37c308c01d891bf66774132666c7cb5db3923bfbcac8c74c69d0f22',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0930_0935/20261023-hk_connect_1min_stage_0930_0935-25052d0e78115a0f/artifact.csv': 'f6892dd0a6f0da01fc4e79a9d3c3f64eb6f3fff3fad33e8be44f08a3dfb65a43',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0930_0935/20261023-hk_connect_1min_stage_0930_0935-25052d0e78115a0f/manifest.json': 'a3c1da782b5d6a5af2455e938f2c937c02439789f03638f4f98b509d1a9fce6e',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0930_0935/20261023-hk_connect_1min_stage_0930_0935-25052d0e78115a0f/receipt.json': 'b05faa232b96866af443cb61b8db1d525f7e1dda92cd0844acc24e73cbf721b9',
                               'raw/.futu_minute_captures/20261023/STAGE_0930_0935/e9ce6abc61df40333566c34985d52b5797c925173d820c503e87f54c47c29706.json': 'e9ce6abc61df40333566c34985d52b5797c925173d820c503e87f54c47c29706',
                               'receipts/20261023/STAGE_0930_0935/receipt.json': '9d460bf292ae29da6badaba9f9be5786eb4d8d58aa658ce510bf9e13339f9b4f'},
                     'selection_manifest': 'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0930_0935/run-c189009adf3a4eebf481d892/manifest.json',
                     'raw_manifest': 'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0930_0935/20261023-hk_connect_1min_stage_0930_0935-25052d0e78115a0f/manifest.json',
                     'raw_artifact': 'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0930_0935/20261023-hk_connect_1min_stage_0930_0935-25052d0e78115a0f/artifact.csv',
                     'capture_relative': 'raw/.futu_minute_captures/20261023/STAGE_0930_0935/e9ce6abc61df40333566c34985d52b5797c925173d820c503e87f54c47c29706.json',
                     'capture_sha256': 'e9ce6abc61df40333566c34985d52b5797c925173d820c503e87f54c47c29706',
                     'run_id': 'run-c189009adf3a4eebf481d892',
                     'captured_at': '2026-10-23T11:03:25.217128+08:00',
                     'cutoff_at': '2026-10-23T09:35:05+08:00',
                     'window_start': '2026-10-23 09:31:00',
                     'window_end': '2026-10-23 09:35:00',
                     'bars_per_code': 5},
 'STAGE_0935_0940': {'files': {'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0935_0940/run-3365f6cb264f0a04cf63eb2d/artifact.csv': '6e52e72acfaf6626724484b9d931bcbafb1dd7577a27af5a6a697bbe1671a2a0',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0935_0940/run-3365f6cb264f0a04cf63eb2d/manifest.json': 'b5e37cda6e032c60046edec7fa1accb0fefdf9315b5112c0facfb0fae45acf3a',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0935_0940/run-3365f6cb264f0a04cf63eb2d/receipt.json': '8ea0642b67cdaeaf80efe34048493684ebce1805e72458a5ce9fb7331fca67d6',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0935_0940/20261023-hk_connect_1min_stage_0935_0940-ec46e1bfdca87326/artifact.csv': 'f8070e1f4a6c758137a525d7f709f769728f737094b13dc57debd2dc649986fe',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0935_0940/20261023-hk_connect_1min_stage_0935_0940-ec46e1bfdca87326/manifest.json': '69eade2952a355a4d357bb168637c0160e92fc7516de9003c4546e20947f050f',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0935_0940/20261023-hk_connect_1min_stage_0935_0940-ec46e1bfdca87326/receipt.json': '62baf4a9a04055d6e4392fa2fa8dab7b1002139728ef33f3a9125b41fd6818bf',
                               'raw/.futu_minute_captures/20261023/STAGE_0935_0940/dcaa4928ca97bf110e76e0c034d7b1fd0155724f49e3f84ebaa27408e9964759.json': 'dcaa4928ca97bf110e76e0c034d7b1fd0155724f49e3f84ebaa27408e9964759',
                               'receipts/20261023/STAGE_0935_0940/receipt.json': '2796c68a950bbae12730cf927d1b31ec818f2812919ec063c55721f8fb5511cf'},
                     'selection_manifest': 'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0935_0940/run-3365f6cb264f0a04cf63eb2d/manifest.json',
                     'raw_manifest': 'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0935_0940/20261023-hk_connect_1min_stage_0935_0940-ec46e1bfdca87326/manifest.json',
                     'raw_artifact': 'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0935_0940/20261023-hk_connect_1min_stage_0935_0940-ec46e1bfdca87326/artifact.csv',
                     'capture_relative': 'raw/.futu_minute_captures/20261023/STAGE_0935_0940/dcaa4928ca97bf110e76e0c034d7b1fd0155724f49e3f84ebaa27408e9964759.json',
                     'capture_sha256': 'dcaa4928ca97bf110e76e0c034d7b1fd0155724f49e3f84ebaa27408e9964759',
                     'run_id': 'run-3365f6cb264f0a04cf63eb2d',
                     'captured_at': '2026-10-23T11:04:35.595295+08:00',
                     'cutoff_at': '2026-10-23T09:40:05+08:00',
                     'window_start': '2026-10-23 09:36:00',
                     'window_end': '2026-10-23 09:40:00',
                     'bars_per_code': 5},
 'STAGE_0940_0945': {'files': {'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0940_0945/run-02a055be59ac29221881ecc1/artifact.csv': 'bf21d7ab87b3952b8d660778245252c0fdd566c70a8e41ef3a5caa4bb3790ccc',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0940_0945/run-02a055be59ac29221881ecc1/manifest.json': 'eae87f78c78e11f525a525cc7c3cae8e54d2d4bef8f9d79da578b1c7fc69bfb6',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0940_0945/run-02a055be59ac29221881ecc1/receipt.json': 'eceda83c242390c80146dc5ea6dfa00a1bc6dd89bb4bd3adff88665dffbe77c2',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0940_0945/20261023-hk_connect_1min_stage_0940_0945-7d3c2222b765740f/artifact.csv': '4e011cb4d14e5116ab0696cbe499cef951985786623b80dcebe2969b7375b6b9',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0940_0945/20261023-hk_connect_1min_stage_0940_0945-7d3c2222b765740f/manifest.json': 'fa48d6d3c34b3f221fe601fe35875182d8c9c2e6a5f60b02bd8deabafd6b8e97',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0940_0945/20261023-hk_connect_1min_stage_0940_0945-7d3c2222b765740f/receipt.json': '20aaece7a864b6902e57a2326653f533a4fd1e5d84f6bbe8118c1e33e6839e93',
                               'raw/.futu_minute_captures/20261023/STAGE_0940_0945/dabdbcccfd0234c9b6bf51d2dc4c331447fa8c8fbc8e43405d69dccfedc84cea.json': 'dabdbcccfd0234c9b6bf51d2dc4c331447fa8c8fbc8e43405d69dccfedc84cea',
                               'receipts/20261023/STAGE_0940_0945/receipt.json': '8b84f04d86dc978cd6622c99decb3dbbdc9e33d03ec01123d7618b61e851ca38'},
                     'selection_manifest': 'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0940_0945/run-02a055be59ac29221881ecc1/manifest.json',
                     'raw_manifest': 'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0940_0945/20261023-hk_connect_1min_stage_0940_0945-7d3c2222b765740f/manifest.json',
                     'raw_artifact': 'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0940_0945/20261023-hk_connect_1min_stage_0940_0945-7d3c2222b765740f/artifact.csv',
                     'capture_relative': 'raw/.futu_minute_captures/20261023/STAGE_0940_0945/dabdbcccfd0234c9b6bf51d2dc4c331447fa8c8fbc8e43405d69dccfedc84cea.json',
                     'capture_sha256': 'dabdbcccfd0234c9b6bf51d2dc4c331447fa8c8fbc8e43405d69dccfedc84cea',
                     'run_id': 'run-02a055be59ac29221881ecc1',
                     'captured_at': '2026-10-23T11:05:08.649061+08:00',
                     'cutoff_at': '2026-10-23T09:45:05+08:00',
                     'window_start': '2026-10-23 09:41:00',
                     'window_end': '2026-10-23 09:45:00',
                     'bars_per_code': 5},
 'STAGE_0945_1030': {'files': {'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0945_1030/run-00601d8e8688ada1f675d798/artifact.csv': '65cd3535437703c80e89b76920bb473833dd4614d290b97eda493cf1d75e709a',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0945_1030/run-00601d8e8688ada1f675d798/manifest.json': 'afb32532f9f5ebf418ade4f5acff47a485be0619c168dac49948c22d5b90ade4',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0945_1030/run-00601d8e8688ada1f675d798/receipt.json': '96e696894c67c74f97ed115b42e2d7df0c2793e52dccdb072a5eb91036274fe0',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0945_1030/20261023-hk_connect_1min_stage_0945_1030-9f734f90eb4ef4ac/artifact.csv': '8a3210d20ae0d7cd0bea61ae3b98d586a4e8e23124d56a8bbd4d9c22482029b3',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0945_1030/20261023-hk_connect_1min_stage_0945_1030-9f734f90eb4ef4ac/manifest.json': '1548b6314b181c0f14b88a80312e0d3797990d2ed54e5925c38a2fa85e15a92d',
                               'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0945_1030/20261023-hk_connect_1min_stage_0945_1030-9f734f90eb4ef4ac/receipt.json': '78cf3347e5fa7e91a09a0d86d56c06a80246c17d3a1f2d809b47e8b7d1e5c963',
                               'raw/.futu_minute_captures/20261023/STAGE_0945_1030/c8a3dcb835a8a3b639a500a53c3a4eacfeae0721e07fee543718614d5a733460.json': 'c8a3dcb835a8a3b639a500a53c3a4eacfeae0721e07fee543718614d5a733460',
                               'receipts/20261023/STAGE_0945_1030/receipt.json': 'b97055c40b2944559a524a01037cae52841643070084203cbaef9c825cc5e823'},
                     'selection_manifest': 'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0945_1030/run-00601d8e8688ada1f675d798/manifest.json',
                     'raw_manifest': 'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0945_1030/20261023-hk_connect_1min_stage_0945_1030-9f734f90eb4ef4ac/manifest.json',
                     'raw_artifact': 'raw/runs/20261023/HK_CONNECT_1MIN_STAGE_0945_1030/20261023-hk_connect_1min_stage_0945_1030-9f734f90eb4ef4ac/artifact.csv',
                     'capture_relative': 'raw/.futu_minute_captures/20261023/STAGE_0945_1030/c8a3dcb835a8a3b639a500a53c3a4eacfeae0721e07fee543718614d5a733460.json',
                     'capture_sha256': 'c8a3dcb835a8a3b639a500a53c3a4eacfeae0721e07fee543718614d5a733460',
                     'run_id': 'run-00601d8e8688ada1f675d798',
                     'captured_at': '2026-10-23T11:05:50.283826+08:00',
                     'cutoff_at': '2026-10-23T10:30:00+08:00',
                     'window_start': '2026-10-23 09:46:00',
                     'window_end': '2026-10-23 10:29:00',
                     'bars_per_code': 44}}

_HK_MORNING_HISTORY_SAFE_PACKETS = {'STAGE_0930_0935': {'files': {'derived_raw.csv': '79c431cbfba8b87b7697b96150eb0ead54c94afd14753a0e65217426f327cb7e',
                               'observation_receipt.json': '2b1984c1347464048707b040e0d73dfcf974006fe3c7bf8c00dcbeb4abbd2c4a',
                               'provenance.json': '8692bdfae393de032eaae829848ded1eb1059b77121af3b425bbbe4033af4d14',
                               'selection/selection_latest.json': 'c75ce537291bc1675bf245fe13e617c9d4476c1b57d2d24f0b7224adec21b409',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0930_0935/run-418f15f2beca8fef1c0b986e/artifact.csv': 'ac3a091fd6f213f5dcc880b33737f7d87e1624f4eb160b1e1b31fa200d28712d',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0930_0935/run-418f15f2beca8fef1c0b986e/manifest.json': 'ef573bf94741185288dcc241312147bd88a35cb206edb98c01912a800de18d90',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0930_0935/run-418f15f2beca8fef1c0b986e/receipt.json': '82e2d93cd0a0625a55f7a2f72dbff69da62892ced51470bd2997f8169eeb55f9'},
                     'selection_run_id': 'run-418f15f2beca8fef1c0b986e',
                     'window_start': '2026-10-23 09:31:00',
                     'window_end': '2026-10-23 09:34:00',
                     'bars_per_code': 4},
 'STAGE_0935_0940': {'files': {'derived_raw.csv': '7412095d3bc2ebbb5e0b99dcd68140d7f7d239bd5ba16ed105b78f960f0f8844',
                               'observation_receipt.json': 'fce74ac9201a70768cf0532f3ae777e0167ec130d981cbbae1f01242bb19ed69',
                               'provenance.json': '8692bdfae393de032eaae829848ded1eb1059b77121af3b425bbbe4033af4d14',
                               'selection/selection_latest.json': '3c559b18159d4d29559e0b0ef34a18df29ceaa7ceab711a59e378701321c7cf4',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0935_0940/run-220305b51cdbc8c6dcf661d0/artifact.csv': '773534448ff06d297536517d2bd79c7e24afce9c3f697b34910477e2ee9849ec',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0935_0940/run-220305b51cdbc8c6dcf661d0/manifest.json': '4bfc1f9889ae1c0f4fea9cc933af5888a1b97e9a55a5e672e2dc6d8e2673d002',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0935_0940/run-220305b51cdbc8c6dcf661d0/receipt.json': '9471f5b3bcd4e5b8d9083b5960930539fa30946602f68c504516fc2eb6c9cbcf'},
                     'selection_run_id': 'run-220305b51cdbc8c6dcf661d0',
                     'window_start': '2026-10-23 09:36:00',
                     'window_end': '2026-10-23 09:39:00',
                     'bars_per_code': 4},
 'STAGE_0940_0945': {'files': {'derived_raw.csv': '23b740ab2cdb7b85a24d4f11acdc1956a13e0027f0d01c8ff541daeda643a7a9',
                               'observation_receipt.json': '6c68cb52aeb1e0230bb01e3299bbaaf85c05012e0f92cd18167ef901b7ff2578',
                               'provenance.json': '8692bdfae393de032eaae829848ded1eb1059b77121af3b425bbbe4033af4d14',
                               'selection/selection_latest.json': 'ee02a86b3c72e892c5ca9dd1df4b032fc01d6958323f667f18c49396e661d7ab',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0940_0945/run-c20b5937969e33c36510e94f/artifact.csv': '6917ddeb0c43f6e5a0a7a28204062708d24ef6cd06a1b73fc1790eabeaab9bef',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0940_0945/run-c20b5937969e33c36510e94f/manifest.json': '65e5119e7ebaa203fd174c87f8e2e262525a31297a937cdcf72984865c7bcaf5',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0940_0945/run-c20b5937969e33c36510e94f/receipt.json': 'dde981f4e97c797b7967f25764c7234374d025ab3afbbedf2773e0408c00cd60'},
                     'selection_run_id': 'run-c20b5937969e33c36510e94f',
                     'window_start': '2026-10-23 09:41:00',
                     'window_end': '2026-10-23 09:44:00',
                     'bars_per_code': 4},
 'STAGE_0945_1030': {'files': {'derived_raw.csv': '0030c37c07627c00528a6740df1579dc034bd410e2a8fb776218c4d0c5fcdbd6',
                               'observation_receipt.json': '12ae9f02fd8f340a418a1302fe2665e75176635824d8c09fbc56cef14c6f0166',
                               'provenance.json': '8692bdfae393de032eaae829848ded1eb1059b77121af3b425bbbe4033af4d14',
                               'selection/selection_latest.json': '7f3a35356ec84e5f06c04889a913d2ba8038f78681a4d2c84330235e10bf8afc',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0945_1030/run-39eb622c15067fbe1775b711/artifact.csv': '65cd3535437703c80e89b76920bb473833dd4614d290b97eda493cf1d75e709a',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0945_1030/run-39eb622c15067fbe1775b711/manifest.json': '2c88829cdcc4e172fed87d48d0dc05f5ea43ff89ba48e85f67100635bc66fe4d',
                               'selection/selection_runs/20261023/HK_CONNECT_SELECTION_STAGE_0945_1030/run-39eb622c15067fbe1775b711/receipt.json': '03e20c0f8dbd76e806f7775061990399aa6895d238f4944f49f9b23b1070d42a'},
                     'selection_run_id': 'run-39eb622c15067fbe1775b711',
                     'window_start': '2026-10-23 09:46:00',
                     'window_end': '2026-10-23 10:29:00',
                     'bars_per_code': 44}}

def _hk_morning_history_observation(
    selection_root: Path | None, pool_root: Path, market_payload: Mapping[str, Any],
    rows: list[dict], *, trade_date: str, stage_id: str,
) -> dict[str, Any]:
    """Verify saved bars and original scorer output for the approved dated observation.

    Read only: no acquisition, scoring, repair or fallback. Bar labels and the
    late capture clock remain distinct from the requested stage cutoff.
    """
    import csv
    import io
    import json
    import math

    binding = _HK_MORNING_HISTORY_20261023.get(stage_id) if trade_date == "20261023" else None
    if binding is None or selection_root is None:
        return {}
    root = Path(selection_root).parent
    try:
        # Verify full immutable trios and the cache before interpreting any values.
        documents: dict[str, bytes] = {}
        for relative, expected in binding["files"].items():
            path = root / relative
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                return {}
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                return {}
            documents[relative] = raw
        manifest = json.loads(documents[binding["selection_manifest"]])
        envelope = manifest["selection_envelope"]
        for key in ("trade_date", "stage_id", "market", "run_id", "artifact_id",
                    "algorithm_id", "algorithm_sha256", "raw_artifact_sha256",
                    "selection_status", "source_status", "requested_rows", "source_rows",
                    "selected_rows", "missing_symbols", "cannot_confirm", "source_evidence"):
            if market_payload.get(key) != envelope.get(key):
                return {}
        if (envelope["trade_date"] != trade_date or envelope["stage_id"] != stage_id
                or envelope["market"] != "HK_CONNECT" or envelope["run_id"] != binding["run_id"]
                or market_payload.get("status") != "PARTIAL_WITH_ROWS"
                or envelope["selection_status"] != "PARTIAL_WITH_ROWS"
                or envelope["source_status"] != "CANNOT_CONFIRM"
                or envelope["cannot_confirm"] != ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
                or envelope["missing_symbols"] or envelope["requested_rows"] != 100
                or envelope["source_rows"] != 100 or envelope["selected_rows"] != 10
                or len(rows) != 10):
            return {}
        # Consumer adds only the display order. All scorer values must be identical.
        if [{k: v for k, v in row.items() if k != "order"} for row in rows] != envelope["rows"]:
            return {}
        if any(row.get("formal_eligible") is not False or row.get("action_level") != "NO_BUY"
               or row.get("source_mode") != "HK_CONNECT_FOUR_LANE"
               or row.get("trade_status") not in {"NO_TRADE", "WATCH_ONLY"} for row in rows):
            return {}
        if any(envelope.get(key) is not False for key in
               ("production_allowed", "buy_gate_updated", "orders_sent")):
            return {}
        pool_bytes = (Path(pool_root) / "preselection_pools/20261023/hkconnect_d1_top100.json").read_bytes()
        if hashlib.sha256(pool_bytes).hexdigest() != "e8921f1eadf3cbac3d63fe2b012e5c9ac25652af08a68681886fc179b540dbef":
            return {}
        pool = json.loads(pool_bytes)
        codes = {row["code_norm"] for row in pool["rows"]}
        if (len(codes) != 100 or len(pool["rows"]) != 100 or pool["market"] != "HK"
                or pool["target_date"] != trade_date or pool["signal_date"] != "20261022"
                or pool["status"] != "STRICT_0_2_READY"):
            return {}
        capture = json.loads(documents[binding["capture_relative"]])
        if (capture["market"] != "HK_CONNECT" or capture["trade_date"] != trade_date
                or capture["stage_id"] != stage_id or capture["adjustment"] != "NONE"
                or capture["captured_at"] != binding["captured_at"]
                or capture["errors"] or capture["no_data_codes"]
                or len(capture["codes"]) != 100 or set(capture["codes"]) != codes):
            return {}
        cutoff = datetime.fromisoformat(binding["cutoff_at"])
        captured = datetime.fromisoformat(capture["captured_at"])
        # Bind the requested cutoff to the frozen stage definition, not caller data.
        if binding["cutoff_at"] != f"2026-10-23T{STAGE_DEFINITIONS[stage_id]['cutoff']}+08:00":
            return {}
        if captured <= cutoff:
            return {}
        raw_manifest = json.loads(documents[binding["raw_manifest"]])
        if (raw_manifest["trade_date"] != trade_date or raw_manifest["stage_id"] != stage_id
                or raw_manifest["market"] != "HK_CONNECT" or raw_manifest["source_id"] != "futu"
                or raw_manifest["temporal_cutoff_safe"] is not False
                or raw_manifest["artifact_sha256"] != envelope["raw_artifact_sha256"]):
            return {}
        safe = _HK_MORNING_HISTORY_SAFE_PACKETS[stage_id]
        packet_root = Path(selection_root) / "historical_observations/20261023" / stage_id
        packet: dict[str, bytes] = {}
        for relative, expected in safe["files"].items():
            path = packet_root / relative
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                return {}
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                return {}
            packet[relative] = raw
        from stage_center.selection import SelectionStore
        observed = SelectionStore(packet_root / "selection").read_verified(trade_date, stage_id, "HK_CONNECT")
        if (observed["run_id"] != safe["selection_run_id"] or len(observed["rows"]) != 10
                or observed["algorithm_sha256"] != envelope["algorithm_sha256"]
                or observed["source_status"] != "CANNOT_CONFIRM"
                or observed["selection_status"] != "PARTIAL_WITH_ROWS"
                or observed["requested_rows"] != 100 or observed["source_rows"] != 100
                or any(row.get("formal_eligible") is not False or row.get("action_level") != "NO_BUY"
                       for row in observed["rows"])
                or any(observed.get(key) is not False for key in
                       ("production_allowed", "buy_gate_updated", "orders_sent"))):
            return {}
        bars = {code: [] for code in codes}
        for bar in capture["rows"]:
            if safe["window_start"] <= bar["time_key"] <= safe["window_end"]:
                if bar["code"] not in codes:
                    return {}
                if any(not math.isfinite(float(bar[key])) for key in
                       ("open", "high", "low", "close", "volume", "turnover", "last_close")):
                    return {}
                bars[bar["code"]].append(bar)
        raw_rows = list(csv.DictReader(io.StringIO(packet["derived_raw.csv"].decode("utf-8-sig"))))
        if len(raw_rows) != 100 or {row["code"] for row in raw_rows} != codes:
            return {}
        for raw_row in raw_rows:
            code_bars = sorted(bars[raw_row["code"]], key=lambda bar: bar["time_key"])
            if (len(code_bars) != safe["bars_per_code"]
                    or len({bar["time_key"] for bar in code_bars}) != len(code_bars)
                    or code_bars[0]["time_key"] != safe["window_start"]
                    or code_bars[-1]["time_key"] != safe["window_end"]
                    or raw_row["trade_date"] != trade_date
                    or raw_row["window_start"] != safe["window_start"]
                    or raw_row["window_end"] != safe["window_end"]
                    or int(raw_row["bar_count"]) != len(code_bars)):
                return {}
            aggregate = {
                "open_price": code_bars[0]["open"], "last_price": code_bars[-1]["close"],
                "high_price": max(bar["high"] for bar in code_bars),
                "low_price": min(bar["low"] for bar in code_bars),
                "volume": sum(bar["volume"] for bar in code_bars),
                "turnover": sum(bar["turnover"] for bar in code_bars),
            }
            if any(not math.isclose(float(raw_row[key]), float(value), rel_tol=1e-9, abs_tol=1e-6)
                   for key, value in aggregate.items()):
                return {}
        return {
            "label": "早盘历史回放观察 / 缺失原时点盘口 / 非正式阶段结果",
            "source_id": "FUTU_K_1M", "raw_source_id": "futu", "adjustment": "NONE",
            "trade_date": trade_date, "stage_id": stage_id, "selection_run_id": observed["run_id"], "original_selection_run_id": binding["run_id"],
            "artifact_id": observed["artifact_id"], "raw_artifact_sha256": observed["raw_artifact_sha256"],
            "algorithm_id": observed["algorithm_id"], "algorithm_sha256": observed["algorithm_sha256"],
            "source_evidence": observed["source_evidence"],
            "_rows": [{**row, "order": index + 1} for index, row in enumerate(observed["rows"])],
            "capture_sha256": binding["capture_sha256"], "captured_at": capture["captured_at"],
            "asof_cutoff": binding["cutoff_at"], "captured_after_cutoff": True,
            "bar_label_start": safe["window_start"], "bar_label_end": safe["window_end"],
            "bar_interval_semantics": "CANNOT_CONFIRM", "stage_window_coverage": "CONSERVATIVE_INTERSECTION_ONLY", "boundary_bars_excluded": True,
            "bars_per_code": safe["bars_per_code"], "window_bar_count": sum(map(len, bars.values())),
            "d1_membership_count": 100, "formal_eligible": False, "natural": False,
            "active_snapshot_available": False, "temporal_cutoff_safe": False,
            "missing_fields": ["order_book", "volume_ratio", "native_update_time", "native_snapshot"],
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        }
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError):
        return {}


_STAGE_TIMELINE_MARKET_KEYS = (
    "status",
    "display_mode",
    "source_status",
    "requested_rows",
    "source_rows",
    "selection_manifest_receipt_verified",
    "observation_count",
)


def _project_stage_timeline_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the fields the stage timeline renders.

    The summary is copied from the same projection the single-stage route
    returns, so the compact timeline payload and the full stage view cannot
    disagree. Stock rows, source evidence and the snapshot/evidence bodies are
    deliberately dropped: they were ~96% of each stage response.
    """
    markets = payload.get("markets")
    compact_markets: dict[str, dict[str, Any]] = {}
    if isinstance(markets, Mapping):
        for market in ("A", "HK"):
            summary = markets.get(market)
            if isinstance(summary, Mapping):
                compact_markets[market] = {
                    key: summary.get(key) for key in _STAGE_TIMELINE_MARKET_KEYS
                }

    def _snapshot_side(value: Any, rows_key: str) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        side: dict[str, Any] = {"status": value.get("status")}
        side_markets = value.get("markets")
        picked = side_markets.get("A_SHARE") if isinstance(side_markets, Mapping) else None
        if isinstance(picked, Mapping):
            side["markets"] = {
                "A_SHARE": {
                    key: picked.get(key)
                    for key in ("mode", rows_key, "captured_at")
                }
            }
        return side

    execution = payload.get("execution_evidence")
    compact_execution = None
    if isinstance(execution, Mapping):
        compact_execution = {
            key: execution.get(key) for key in ("status", "due_status")
        }

    stage = payload.get("stage")
    compact_stage = None
    if isinstance(stage, Mapping):
        compact_stage = {
            key: stage.get(key)
            for key in ("stage_id", "label", "window", "status", "display_status")
        }

    summary: dict[str, Any] = {
        "schema_version": payload.get("schema_version"),
        "trade_date": payload.get("trade_date"),
        "stage_id": payload.get("stage_id"),
        "status": payload.get("status"),
        "stage": compact_stage,
        "markets": compact_markets,
        "execution_evidence": compact_execution,
        "selected_a_rows": payload.get("selected_a_rows"),
        "selected_hk_rows": payload.get("selected_hk_rows"),
        "selected_total_rows": payload.get("selected_total_rows"),
        "selection_mode": payload.get("selection_mode"),
        "snapshot_reselection": _snapshot_side(payload.get("snapshot_reselection"), "selected_rows"),
        "snapshot_recovery": _snapshot_side(payload.get("snapshot_recovery"), "observed_rows"),
    }
    for flag in TRADING_SAFETY_FLAGS:
        summary[flag] = payload.get(flag, False)
    summary["RESEARCH_ONLY"] = payload.get("RESEARCH_ONLY", True)
    summary["write_performed"] = payload.get("write_performed", False)
    return summary


def create_app(
    data_root: Path | None = None,
    quote_provider: ReadOnlyQuoteProvider | None = None,
    shared_data_root: Path | str | None = None,
    ledger_root: Path | None = None,
    stage_center_selection_root: Path | None = None,
    current_date: str | None = None,
    manager_research_state_root: Path | str | None = None,
    manager_research_observation_reader: Any | None = None,
    manager_research_source_provider: Any | None = None,
    research_data_root: Path | str | None = None,
    research_ledger_root: Path | str | None = None,
    morning_news_data_root: Path | str | None = None,
    preselection_source_root: Path | str | None = None,
    stage_center_research_binding_path: Path | str | None = None,
    stage_center_research_binding_sha256: str | None = None,
    manager_workbench_config: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="V4", version="0.1.0")
    store = NativeDataStore(data_root or Path.cwd() / ".runtime" / "data")
    review_store = ReviewStore(store.root)
    configured_research_root = research_data_root or os.environ.get("V4_RESEARCH_DATA_ROOT")
    resolved_research_root = Path(configured_research_root).expanduser() if configured_research_root else store.root
    configured_pool_source = (
        preselection_source_root or os.environ.get("V4_PRESELECTION_SOURCE_ROOT")
    )
    resolved_pool_source = (
        Path(configured_pool_source).expanduser()
        if configured_pool_source
        else store.root
    )
    configured_morning_news_root = (
        morning_news_data_root or os.environ.get("V4_MORNING_NEWS_DATA_ROOT")
    )
    configured_research_ledger = research_ledger_root
    if configured_research_ledger:
        resolved_research_ledger = Path(configured_research_ledger).expanduser()
    elif ledger_root is not None and not configured_research_root:
        # Preserve the existing single-root application contract for callers
        # that have not configured a separate research producer root.
        resolved_research_ledger = Path(ledger_root).expanduser()
    else:
        resolved_research_ledger = resolved_research_root.parent / "dispatcher"
    research_source = ResearchLaneSource(
        resolved_research_root,
        ledger_root=resolved_research_ledger,
    )
    configured_selection_root = stage_center_selection_root
    shared_selection_consumer = (
        StageSelectionConsumer(
            configured_selection_root,
            a_name_pool_root=resolved_pool_source,
        )
        if configured_selection_root is not None
        else None
    )
    approved_research_reader = (
        ApprovedResearchReadBinding(
            binding_path=(stage_center_research_binding_path
                          if stage_center_research_binding_path is not None
                          else Path(__file__).resolve().parents[3] / "stage_center/approved_research_read.json"),
            history_root=configured_selection_root,
            api_root=Path(__file__).resolve().parents[3],
            expected_reader_sha256=_STAGE_RESEARCH_READER_SHA256,
            expected_binding_sha256=stage_center_research_binding_sha256,
            a_name_pool_root=shared_selection_consumer.a_name_pool_root,
        ) if shared_selection_consumer is not None else None
    )
    if shared_selection_consumer is None:
        stage_store = StageStore(store.root)
        resolved_quote_provider = quote_provider or StageQuoteProvider(
            primary=FutuQuoteProvider(),
            a_replay=TdxMinuteReplayProvider(),
            references=stage_store,
            hk_replay=HkConnectStageReplayProvider(),
        )
        stage_runner = StageRunner(
            stage_store,
            input_producer=StageInputProducer(
                store,
                stage_store,
                resolved_quote_provider,
            ),
            opening_second_filter_store=OpeningSecondFilterStore(store.root),
        )
    else:
        # Explicit shared-root mode is read-only: do not instantiate a quote
        # provider, input producer, or StageRunner writer path at all.
        stage_runner = None

    def shared_selection_unconfigured(trade_date: str, stage_id: str) -> dict:
        return {
            "schema_version": "stage_center.selection_consumer.v1",
            "response_source": "SHARED_STAGE_CENTER",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "status": "CANNOT_CONFIRM",
            "markets": {},
            "selection_markets": {},
            "market_summaries": {},
            "unified_rows": [],
            "artifact_id": None,
            "bundle_artifact_id": None,
            "cannot_confirm": ["SHARED_STAGE_CENTER_NOT_CONFIGURED"],
            "write_performed": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _catalog() -> dict:
        return date_catalog(
            store,
            current_date=current_date,
            stage_selection_root=configured_selection_root,
            preselection_source_root=(
                resolved_pool_source if configured_pool_source else None
            ),
            # Navigation readers share one read-only projection; the verified
            # scans behind it are the slowest part of the first page load.
            use_cache=True,
        )

    def _stage_projection_status(
        markets: Mapping[str, Mapping[str, Any]],
        fallback: Any,
    ) -> str:
        """Reduce market statuses without hiding a lane-level evidence gap."""
        statuses = {str(item.get("status") or "CANNOT_CONFIRM") for item in markets.values()}
        has_rows = any(int(item.get("selected_rows") or item.get("candidate_count") or 0) > 0 for item in markets.values())
        if not statuses:
            return str(fallback or "CANNOT_CONFIRM")
        if statuses == {"READY"}:
            return "READY"
        if statuses == {"READY_EMPTY"}:
            return "READY_EMPTY"
        if "CANNOT_CONFIRM" in statuses:
            return "PARTIAL_WITH_ROWS" if has_rows else "CANNOT_CONFIRM"
        if "PARTIAL_WITH_ROWS" in statuses or str(fallback) == "PARTIAL_WITH_ROWS":
            return "PARTIAL_WITH_ROWS"
        return str(fallback or "PARTIAL_WITH_ROWS")

    def _legacy_hk_consumer_rows_match(rows: list[dict], bound_rows: Any) -> bool:
        """Allow only the existing consumer's exact positional order projection."""
        if not isinstance(bound_rows, list) or len(rows) != len(bound_rows):
            return False
        for position, (row, original) in enumerate(zip(rows, bound_rows), 1):
            if not isinstance(row, dict) or not isinstance(original, dict):
                return False
            if type(row.get("order")) is not int or row["order"] != position:
                return False
            if "order" in original:
                if type(original["order"]) is not int or original["order"] != position or row != original:
                    return False
            elif {key: value for key, value in row.items() if key != "order"} != original:
                return False
        return True

    def _legacy_hk_pit_observation(
        market_payload: Mapping[str, Any], rows: list[dict], *, trade_date: str, stage_id: str,
    ) -> bool:
        """Read-only compatibility for R1's PIT-only raw-status regression."""
        if (configured_selection_root is None
                or stage_id not in {"STAGE_1300_1315", "STAGE_1445_1500"}
                or market_payload.get("status") != "PARTIAL_WITH_ROWS"
                or market_payload.get("selection_status") != "PARTIAL_WITH_ROWS"
                or market_payload.get("source_status") != "CANNOT_CONFIRM"
                or market_payload.get("cannot_confirm") != ["HK_FUTU_CAPTURE_NOT_BEFORE_STAGE_CUTOFF"]
                or market_payload.get("requested_rows") != 100
                or market_payload.get("source_rows") != 100
                or market_payload.get("selected_rows") != 10 or len(rows) != 10
                or market_payload.get("missing_symbols")):
            return False
        try:
            from infrastructure.owned_io import SafeRoot
            from stage_center.selection import SelectionStore
            from ops.verify_stage_execution import validate_execution_inputs
            selection_root = Path(configured_selection_root).resolve(strict=True)
            stage_root = selection_root.parent
            bound = SelectionStore(selection_root).read_verified(trade_date, stage_id, "HK_CONNECT")
            if any(market_payload.get(key) != bound.get(key) for key in (
                    "artifact_id", "run_id", "raw_artifact_sha256", "source_status", "selection_status",
                    "source_rows", "requested_rows", "selected_rows", "source_evidence", "cannot_confirm")):
                return False
            if not _legacy_hk_consumer_rows_match(rows, bound.get("rows")):
                return False
            receipt_raw = SafeRoot(stage_root / "receipts").read_bytes(
                f"{trade_date}/{stage_id}/receipt.json", max_bytes=16 * 1024 * 1024)
            inputs = validate_execution_inputs(
                trade_date=trade_date, stage_id=stage_id, receipt_root=stage_root / "receipts",
                raw_root=stage_root / "raw", selection_root=selection_root,
                expected_receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
                hk_d1_root=store.root,
                preselection_source_root=resolved_pool_source if configured_pool_source else None,
                hk_second_filter_root=store.root / "opening_second_filter",
                shared_research_root=Path(configured_morning_news_root) if configured_morning_news_root else None,
            )
            return bool(inputs["raw_artifact"]["sha256"] == market_payload["raw_artifact_sha256"]
                        and inputs["source_reconciliation"]["raw_rows"] == 100
                        and inputs["source_reconciliation"]["selected_rows"] == 10
                        and inputs["source_time_facts"]["pit_status"] == "CANNOT_CONFIRM")
        except Exception:
            return False

    def _hk_morning_selection_recovery_observation(
        market_payload: Mapping[str, Any],
        rows: list[dict],
        *,
        trade_date: str,
        stage_id: str,
    ) -> bool:
        binding = _HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE.get(
            (trade_date, stage_id)
        )
        if binding is None:
            return False
        evidence = market_payload.get("source_evidence")
        if not isinstance(evidence, (list, tuple)) or any(
            not isinstance(item, str) for item in evidence
        ):
            return False
        if hashlib.sha256("\n".join(evidence).encode("utf-8")).hexdigest() != binding[
            "source_evidence_sha256"
        ]:
            return False
        if (
            market_payload.get("market") != "HK_CONNECT"
            or market_payload.get("status") != "PARTIAL_WITH_ROWS"
            or market_payload.get("selection_status") != "PARTIAL_WITH_ROWS"
            or market_payload.get("source_status") != "CANNOT_CONFIRM"
            or market_payload.get("run_id") != binding["selection_run_id"]
            or market_payload.get("artifact_id") != binding["artifact_id"]
            or market_payload.get("raw_artifact_sha256") != binding["raw_artifact_sha256"]
            or market_payload.get("algorithm_id") != binding["algorithm_id"]
            or market_payload.get("algorithm_sha256") != binding["algorithm_sha256"]
            or market_payload.get("requested_rows") != 100
            or market_payload.get("source_rows") != 100
            or market_payload.get("selected_rows") != 10
            or market_payload.get("missing_symbols")
            or market_payload.get("cannot_confirm") != ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
            or market_payload.get("backfill_run_id") != binding["backfill_run_id"]
            or market_payload.get("selection_manifest_sha256") != binding["selection_manifest_sha256"]
            or market_payload.get("selection_receipt_sha256") != binding["selection_receipt_sha256"]
            or market_payload.get("selection_artifact_sha256") != binding["selection_artifact_sha256"]
            or market_payload.get("runner_receipt_sha256") != binding["runner_receipt_sha256"]
            or market_payload.get("selection_manifest_receipt_verified") is not True
            or market_payload.get("runner_receipt_verified") is not True
            or len(rows) != 10
            or any(
                marker not in evidence
                for marker in binding["required_evidence"]
            )
        ):
            return False
        seen_codes: set[str] = set()
        seen_ranks: set[int] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                return False
            code = str(row.get("code") or "")
            rank = row.get("rank")
            if (
                not code
                or code in seen_codes
                or isinstance(rank, bool)
                or not isinstance(rank, int)
                or rank <= 0
                or rank in seen_ranks
                or row.get("formal_eligible") is not False
                or row.get("action_level") != "NO_BUY"
                or row.get("trade_status") not in {"NO_TRADE", "WATCH_ONLY"}
                or row.get("status") != row.get("trade_status")
                or row.get("source_mode") != "HK_CONNECT_FOUR_LANE"
            ):
                return False
            seen_codes.add(code)
            seen_ranks.add(rank)
        return "HK_ACTIVE_SNAPSHOT_UNAVAILABLE" in evidence

    def _hk_display_mode(
        market_payload: Mapping[str, Any],
        rows: list[dict],
        execution_market: Mapping[str, Any] | None,
        *,
        legacy_pit_observation: bool = False,
        morning_selection_recovery: bool = False,
    ) -> tuple[str, list[str]]:
        """Only call HK rows formal after selection and execution binding agree."""
        status = str(market_payload.get("status") or "CANNOT_CONFIRM")
        selection_status = str(market_payload.get("selection_status") or status)
        reasons = [str(item) for item in market_payload.get("cannot_confirm") or []]
        # Display PIT qualifiers without turning valid partial rows into data errors.
        reasons.extend(item.split("=", 1)[1] for item in market_payload.get("source_evidence") or []
                       if isinstance(item, str) and item.startswith("futu_pit_cannot_confirm=")
                       and item.split("=", 1)[1] in {
                           "HK_FUTU_CAPTURE_NOT_BEFORE_STAGE_CUTOFF", "HK_FUTU_FULL_CHAIN_PIT_UNVERIFIED",
                           "HK_FUTU_CAPTURE_CLOCK_UNAVAILABLE", "HK_FUTU_CAPTURE_CLOCK_DATE_MISMATCH"})
        identity_present = all(
            isinstance(market_payload.get(field), str) and market_payload.get(field)
            for field in ("artifact_id", "run_id", "raw_artifact_sha256")
        )
        requested_rows = market_payload.get("requested_rows")
        source_rows = market_payload.get("source_rows")
        selected_rows = market_payload.get("selected_rows")
        source_evidence = market_payload.get("source_evidence")
        complete_empty_evidence = (
            isinstance(requested_rows, int)
            and not isinstance(requested_rows, bool)
            and requested_rows >= 0
            and isinstance(source_rows, int)
            and not isinstance(source_rows, bool)
            and source_rows == requested_rows
            and isinstance(selected_rows, int)
            and not isinstance(selected_rows, bool)
            and selected_rows == 0
            and market_payload.get("source_status") in {"READY", "READY_EMPTY"}
            and isinstance(source_evidence, (list, tuple))
            and any(isinstance(item, str) and item.strip() for item in source_evidence)
            and not market_payload.get("missing_symbols")
            and not market_payload.get("cannot_confirm")
        )
        verified_empty = (
            status == "READY_EMPTY"
            and selection_status == "READY_EMPTY"
            and market_payload.get("source_status") in {"READY", "READY_EMPTY"}
            and identity_present
            and not rows
            and complete_empty_evidence
            and not reasons
        )
        if verified_empty:
            return "READY_EMPTY", []

        if status == "READY_EMPTY":
            if not complete_empty_evidence:
                reasons.append("HK_READY_EMPTY_INPUT_OR_SOURCE_EVIDENCE_INCOMPLETE")
            if market_payload.get("source_status") not in {"READY", "READY_EMPTY"}:
                reasons.append("HK_READY_EMPTY_SOURCE_STATUS_NOT_READY")
            if selection_status != "READY_EMPTY":
                reasons.append("HK_READY_EMPTY_SELECTION_STATUS_MISMATCH")
            if not identity_present:
                reasons.append("SELECTION_ARTIFACT_MISSING_OR_INVALID")
            return "CANNOT_CONFIRM", list(dict.fromkeys(reasons))

        if status == "CANNOT_CONFIRM" or not identity_present:
            if not reasons:
                reasons.append("SELECTION_ARTIFACT_MISSING_OR_INVALID")
            return "CANNOT_CONFIRM", reasons

        if (
            status not in {"READY", "PARTIAL_WITH_ROWS"}
            or selection_status not in {"READY", "PARTIAL_WITH_ROWS"}
            or (market_payload.get("source_status") not in {"READY", "PARTIAL_WITH_ROWS"}
                and not legacy_pit_observation
                and not morning_selection_recovery)
        ):
            reasons.append("HK_SELECTION_OR_SOURCE_STATUS_NOT_READY")
            return "CANNOT_CONFIRM", list(dict.fromkeys(reasons))

        if legacy_pit_observation:
            return "OBSERVATION_UNVERIFIED", list(dict.fromkeys(reasons + [
                "HK_LEGACY_PIT_ONLY_OBSERVATION_INPUTS_REVALIDATED",
                "HK_FULL_CHAIN_PIT_AND_FORMAL_ELIGIBILITY_CANNOT_CONFIRM",
            ]))

        if morning_selection_recovery:
            return "OBSERVATION_UNVERIFIED", list(dict.fromkeys(reasons + [
                "HK_MORNING_SELECTION_OBSERVATION_REPROJECTED",
                "HK_CAPTURE_AFTER_STAGE_CUTOFF_PIT_UNSAFE",
                "HK_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM",
                "HK_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM",
            ]))

        execution = execution_market if isinstance(execution_market, Mapping) else {}
        binding = execution.get("selection_binding")
        unsafe_rows = any(
            isinstance(row, Mapping) and row.get("formal_eligible") is False
            for row in rows
        )
        selection_ready = (
            status == "READY"
            and selection_status == "READY"
            and not reasons
        )
        execution_bound = binding == "BOUND_TO_VERIFIED_SELECTION"
        if selection_ready and execution_bound and rows and not unsafe_rows:
            return "FORMAL", []

        if selection_ready and not rows:
            reasons.append("HK_READY_SELECTION_HAS_NO_ROWS")

        if unsafe_rows:
            reasons.append("HK_FORMAL_ELIGIBILITY_FALSE")
        if not execution_bound:
            execution_reasons = execution.get("reasons")
            reasons.extend(str(item) for item in execution_reasons or [])
            reasons.append(f"HK_EXECUTION_SELECTION_BINDING_{binding or 'CANNOT_CONFIRM'}")
        if not selection_ready:
            reasons.append(f"HK_SELECTION_STATUS_{status}")
        return ("OBSERVATION_UNVERIFIED" if rows else "CANNOT_CONFIRM"), list(dict.fromkeys(reasons))

    def project_shared_selection(
        payload: dict,
        limit: int = 50,
        *,
        ordinary_hk_display: bool = False,
    ) -> dict:
        source_failure = None
        if payload.get("stage_id") == "STAGE_0925":
            try:
                from infrastructure.runtime_graph.current import load_config
                from stage_center.consumer import read_a_opening_source_failure
                config = load_config()
                if Path(config["stage_selection_root"]) == configured_selection_root:
                    source_failure = read_a_opening_source_failure(
                        payload, config=config,
                    )
            except (OSError, ValueError, KeyError, TypeError):
                pass  # Unbound/missing evidence retains the original unknown.
        canonical_markets = dict(payload.get("markets", {}))
        hk_unknown = canonical_markets.get("HK_CONNECT")
        if isinstance(hk_unknown, Mapping) and (
            all(hk_unknown.get(key) == "CANNOT_CONFIRM"
                for key in ("status", "selection_status", "source_status"))
            and all(hk_unknown.get(key) is None for key in
                    ("requested_rows", "source_rows", "selected_rows", "artifact_id", "run_id"))
            and hk_unknown.get("rows") == []
            and isinstance(hk_unknown.get("cannot_confirm"), list)
            and hk_unknown.get("selection_manifest_receipt_verified") in (None, False)
        ):
            from stage_center.consumer import _invalid_market
            hk_unknown = dict(hk_unknown)
            standard = _invalid_market("HK_CONNECT")["cannot_confirm"]
            causes = hk_unknown["cannot_confirm"]
            hk_unknown["cannot_confirm"] = [reason for reason in standard if reason not in causes] + causes
            hk_unknown["selection_manifest_receipt_verified"] = False
            canonical_markets["HK_CONNECT"] = hk_unknown
        selection_markets = canonical_markets
        frontend_markets: dict[str, dict] = {}
        unified_rows: list[dict] = []
        aliases = {"A_SHARE": "A", "HK_CONNECT": "HK"}
        execution_markets = (
            (payload.get("execution_evidence") or {}).get("markets") or {}
        )
        backfill_provenance_fields = frozenset(
            {
                "selection_mode",
                "selection_run_id",
                "backfill_run_id",
                "backfill_run_ids",
                "selection_manifest_sha256",
                "selection_receipt_sha256",
                "selection_artifact_sha256",
                "selection_manifest_receipt_verified",
                "runner_receipt_verified",
                "runner_receipt_status",
                "runner_receipt_sha256",
                "recovery_provenance",
            }
        )
        for canonical_market, market_payload in canonical_markets.items():
            alias = aliases.get(canonical_market, canonical_market)
            rows = list(market_payload.get("rows") or [])[:limit]
            if canonical_market == "A_SHARE":
                from stage_center.news_link_projection import project_news_links
                rows = project_news_links(
                    rows, market_payload, trade_date=str(payload.get("trade_date") or ""),
                    morning_root=configured_morning_news_root,
                )
            projected_rows = rows
            frontend_markets[alias] = {
                key: market_payload.get(key)
                for key in (
                    "market",
                    "RESEARCH_ONLY",
                    "status",
                    "selection_status",
                    "artifact_id",
                    "run_id",
                    "algorithm_id",
                    "algorithm_sha256",
                    "raw_artifact_sha256",
                    "source_status",
                    "requested_rows",
                    "source_rows",
                    "selected_rows",
                    "coverage_ratio",
                    "source_evidence",
                    "missing_symbols",
                    "cannot_confirm",
                    "name_authority_status",
                    "name_authority_source",
                    "name_authority_receipt_sha256",
                    "name_authority_selector_sha256",
                    "name_authority_source_sha256",
                    "name_authority_selector_sha_source",
                    "name_authority_pool_ids",
                    "name_authority_applied_count",
                    "name_authority_missing_count",
                    "name_authority_error",
                    "selection_mode",
                    "selection_run_id",
                    "backfill_run_id",
                    "backfill_run_ids",
                    "selection_manifest_sha256",
                    "selection_receipt_sha256",
                    "selection_artifact_sha256",
                    "selection_manifest_receipt_verified",
                    "runner_receipt_verified",
                    "runner_receipt_status",
                    "runner_receipt_sha256",
                    "recovery_provenance",
                    "superseded_source",
                    "quarantined_source",
                )
                if key not in backfill_provenance_fields or key in market_payload
            }
            frontend_markets[alias]["candidate_count"] = len(rows)
            frontend_markets[alias]["rows"] = rows
            if canonical_market == "A_SHARE" and source_failure is not None:
                frontend_markets[alias].update(source_failure)
            if canonical_market == "HK_CONNECT" and ordinary_hk_display:
                history_observation = _hk_morning_history_observation(
                    configured_selection_root, resolved_pool_source, market_payload, rows,
                    trade_date=str(payload.get("trade_date") or ""),
                    stage_id=str(payload.get("stage_id") or ""),
                )
                if history_observation:
                    rows = history_observation.pop("_rows")
                    projected_rows = rows
                    frontend_markets[alias].update({
                        key: history_observation[key] for key in (
                            "selection_run_id", "artifact_id", "raw_artifact_sha256",
                            "algorithm_id", "algorithm_sha256", "source_evidence")
                    })
                    frontend_markets[alias]["run_id"] = history_observation["selection_run_id"]
                    frontend_markets[alias]["rows"] = rows
                    # The original formal/source failure remains independently visible.
                    frontend_markets[alias]["original_formal_selection"] = {
                        key: market_payload.get(key) for key in (
                            "run_id", "artifact_id", "status", "selection_status", "source_status",
                            "raw_artifact_sha256", "cannot_confirm")
                    }
                    if selection_markets is canonical_markets:
                        selection_markets = dict(canonical_markets)
                    selection_markets[canonical_market] = {**market_payload, "rows": []}
                display_mode, display_reasons = _hk_display_mode(
                    market_payload, rows, execution_markets.get(canonical_market),
                    legacy_pit_observation=_legacy_hk_pit_observation(
                        market_payload, rows, trade_date=str(payload.get("trade_date") or ""),
                        stage_id=str(payload.get("stage_id") or "")),
                    morning_selection_recovery=bool(history_observation) or _hk_morning_selection_recovery_observation(
                        market_payload,
                        rows,
                        trade_date=str(payload.get("trade_date") or ""),
                        stage_id=str(payload.get("stage_id") or ""),
                    ),
                )
                if history_observation:
                    frontend_markets[alias].update({
                        "historical_observation": history_observation,
                        "formal_count": 0, "formal_eligible": False, "natural": False,
                        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
                    })
                    display_reasons = list(dict.fromkeys(display_reasons + [
                        history_observation["label"],
                        "来源 FUTU_K_1M；历史分钟线；原时点盘口/量比/原生更新时间缺失",
                        f"实际采集 {history_observation['captured_at']}；阶段截止 {history_observation['asof_cutoff']}",
                        f"原始bar标签 {history_observation['bar_label_start']}—{history_observation['bar_label_end']}；每只{history_observation['bars_per_code']}根×100只；已排除边界bar，仅保守交集，分钟标签语义待确认",
                    ]))
                frontend_markets[alias]["display_mode"] = display_mode
                frontend_markets[alias]["display_reasons"] = display_reasons
                frontend_markets[alias]["observation_count"] = (
                    len(rows) if display_mode != "CANNOT_CONFIRM" else None
                )
                if display_mode == "CANNOT_CONFIRM":
                    projected_rows = []
                    frontend_markets[alias]["rows"] = projected_rows
                    frontend_markets[alias]["candidate_count"] = None
                    frontend_markets[alias]["status"] = "CANNOT_CONFIRM"
                    frontend_markets[alias]["selected_rows"] = None
                    if selection_markets is canonical_markets:
                        selection_markets = dict(canonical_markets)
                    selection_markets[canonical_market] = {
                        **market_payload,
                        "rows": [],
                    }
                elif display_mode == "OBSERVATION_UNVERIFIED":
                    # These rows have a valid selection identity and source
                    # status, but remain observations because formal or
                    # execution evidence is incomplete. Keep their count
                    # visible without promoting their eligibility or action.
                    frontend_markets[alias]["status"] = "PARTIAL_WITH_ROWS"
            for row in projected_rows:
                unified_rows.append(
                    {
                        **dict(row),
                        "market": alias,
                        "symbol": row.get("code"),
                        "selection_rank": row.get("rank"),
                    }
                )
        a_rows = frontend_markets.get("A", {}).get("rows", [])
        hk_rows = frontend_markets.get("HK", {}).get("rows", [])
        selected_a = len(a_rows)
        hk_display_mode = frontend_markets.get("HK", {}).get("display_mode")
        selected_hk = (
            None if hk_display_mode == "CANNOT_CONFIRM"
            else len(hk_rows)
        )
        selected_total = None if selected_hk is None else selected_a + selected_hk
        stage_id = payload.get("stage_id")
        stage_definition = STAGE_DEFINITIONS.get(stage_id, {})
        stage_status = _stage_projection_status(frontend_markets, payload.get("status", "CANNOT_CONFIRM"))
        cannot_confirm: list[str] = [str(item) for item in payload.get("cannot_confirm") or []]
        for market, market_payload in frontend_markets.items():
            market_status = str(market_payload.get("status") or "CANNOT_CONFIRM")
            reasons = list(market_payload.get("cannot_confirm") or ())
            if market == "HK":
                reasons.extend(market_payload.get("display_reasons") or ())
                reasons = list(dict.fromkeys(reasons))
            if not reasons and market_status == "CANNOT_CONFIRM":
                reasons = [f"{market}_SELECTION_CANNOT_CONFIRM"]
            # A lane can have rows and still carry a hard evidence boundary.
            # Keep every lane reason visible at the stage boundary; the
            # status reducer above deliberately remains PARTIAL_WITH_ROWS.
            for reason in reasons:
                value = f"{market}:{reason}"
                if value not in cannot_confirm:
                    cannot_confirm.append(value)
        result = {
            **payload,
            "status": stage_status,
            "selection_markets": selection_markets,
            "markets": frontend_markets,
            "market_summaries": frontend_markets,
            "unified_rows": unified_rows,
            "cannot_confirm": cannot_confirm,
            "stage": {
                "stage_id": stage_id,
                "label": stage_definition.get("label", stage_id),
                "window": stage_definition.get("window", ""),
                "status": stage_status,
                "display_status": (
                    stage_status + "；港股历史回放观察·未验证；分钟线事后采集；缺原时点盘口、量比/原生更新时间；边界分钟未计入；不能证明原时点选股结果"
                    if frontend_markets.get("HK", {}).get("historical_observation")
                    else stage_status
                ),
                "cannot_confirm": cannot_confirm,
            },
            "selected_a_rows": selected_a,
            "selected_hk_rows": selected_hk,
            "selected_total_rows": selected_total,
            "selection_mode": "SHARED_STAGE_CENTER_READ_ONLY",
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        # Current names are display evidence only.  Original news/research
        # enrichment above has already finished using its original inputs.
        from domains._preselection_parts.source_validation import project_a_display_names
        return project_a_display_names(
            result, str(payload.get("trade_date") or ""), resolved_pool_source,
        )

    def _quarantine_known_hk_auction_pool_mismatch(
        payload: dict, trade_date: str, stage_id: str
    ) -> dict:
        """Hide only the pinned 10/05 auction artifact proven to use the wrong D1 pool."""
        if (
            trade_date != "20261005"
            or stage_id != "STAGE_0925"
            or shared_selection_consumer is None
        ):
            return payload
        market = (payload.get("markets") or {}).get("HK_CONNECT")
        if not isinstance(market, Mapping):
            return payload
        try:
            key = shared_selection_consumer.store._key(trade_date, stage_id, "HK_CONNECT")
            entry = shared_selection_consumer.store._latest().get("entries", {}).get(key)
        except (OSError, ValueError, TypeError, KeyError):
            return payload
        source_evidence = list(market.get("source_evidence") or ())
        required_source = {
            "candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
            "hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
            "hk_d1_source_trade_date=20260930",
            "hk_observation_trade_date=20261005",
        }
        if (
            not isinstance(entry, Mapping)
            or entry.get("trade_date") != trade_date
            or entry.get("stage_id") != stage_id
            or entry.get("market") != "HK_CONNECT"
            or entry.get("run_id") != "run-6a45f94febaf762962082e81"
            or entry.get("artifact_sha256") != "abea293be53b9114f2835ed94d6e52bdc33a54debe51891f102edcb05102357d"
            or entry.get("manifest_sha256") != "25398bdf783d2916aa8aa64c0581071d99d8c7a85ebbdb8b6fbc3b4dbed08177"
            or entry.get("receipt_sha256") != "8bed1cd1e889cea9fa26c107c159018c2b1614aa0d54029ef1c483c8da0e40dc"
            or market.get("run_id") != entry.get("run_id")
            or not required_source.issubset(set(source_evidence))
        ):
            return payload

        quarantined = dict(market)
        quarantined_rows = list(market.get("rows") or ())
        reasons = list(market.get("cannot_confirm") or ())
        if "HK_D1_TARGET_POOL_MISMATCH" not in reasons:
            reasons.append("HK_D1_TARGET_POOL_MISMATCH")
        quarantined.update(
            {
                "status": "CANNOT_CONFIRM",
                "selection_status": "CANNOT_CONFIRM",
                "selected_rows": None,
                "rows": [],
                "cannot_confirm": reasons,
                "quarantined_source": {
                    "status": "CANNOT_CONFIRM",
                    "reason": "HK_D1_TARGET_POOL_MISMATCH",
                    "artifact_sha256": entry["artifact_sha256"],
                    "manifest_sha256": entry["manifest_sha256"],
                    "receipt_sha256": entry["receipt_sha256"],
                    "artifact_relative": entry.get("artifact_relative"),
                    "run_id": entry["run_id"],
                    "source_selected_rows": len(quarantined_rows),
                    "source_requested_rows": market.get("requested_rows"),
                    "source_rows": market.get("source_rows"),
                    "source_evidence": source_evidence,
                    "source_pool_sha256": "f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
                    "target_pool_sha256": "8799c7ef056981549204ece5958222acad92204bfbf9ba5f12ef26bae57dad01",
                    "rows_retained_in_verified_source_artifact": True,
                },
            }
        )
        markets = dict(payload.get("markets") or {})
        markets["HK_CONNECT"] = quarantined
        result = dict(payload)
        result["markets"] = markets
        return result

    def _read_exact_target_hk_override(
        payload: dict,
        trade_date: str,
        stage_id: str,
        limit: int,
        binding: Mapping[str, Any],
        *,
        source_label: str,
        target_pool_sha256: str,
        superseded_source_reason: str | None = None,
    ) -> dict:
        try:
            exact = stage_workbench(
                date=trade_date,
                stage=stage_id,
                limit=limit,
                market="HK_CONNECT",
                backfill_run_id=binding["backfill_run_id"],
            )
        except HTTPException as error:
            # These frozen historical composite reads have independently verified
            # A-share trios. An invalid HK override must not hide that A lane;
            # the explicit HK read above still rejects its invalid binding.
            if error.status_code != 409 or (trade_date, stage_id) not in {
                ('20260918', 'STAGE_0930_0935'),
                ('20260918', 'STAGE_0935_0940'),
                ('20260918', 'STAGE_0940_0945'),
                ('20260918', 'STAGE_0945_1030'),
                ('20260918', 'STAGE_1300_1315'),
                ('20260918', 'STAGE_1445_1500'),
                ('20260922', 'STAGE_0935_0940'),
                ('20260922', 'STAGE_0940_0945'),
                ('20260922', 'STAGE_0945_1030'),
                ('20260924', 'STAGE_0930_0935'),
                ('20260924', 'STAGE_1445_1500'),
                ('20260929', 'STAGE_0930_0935'),
                ('20260929', 'STAGE_0935_0940'),
                ('20260929', 'STAGE_0940_0945'),
                ('20260929', 'STAGE_0945_1030'),
                ('20260929', 'STAGE_1300_1315'),
                ('20260929', 'STAGE_1445_1500'),
                ('20260930', 'STAGE_0930_0935'),
                ('20260930', 'STAGE_0935_0940'),
                ('20260930', 'STAGE_0940_0945'),
                ('20260930', 'STAGE_0945_1030'),
                ('20260930', 'STAGE_1300_1315'),
                ('20260930', 'STAGE_1445_1500'),
            }:
                raise
            markets = dict(payload.get("markets") or {})
            a_market = markets.get("A_SHARE")
            if not isinstance(a_market, Mapping) or not (
                a_market.get("selection_manifest_receipt_verified") is True
                and int(a_market.get("selected_rows") or 0) > 0
            ):
                raise
            from stage_center.consumer import _invalid_market_with_reason
            denied = _invalid_market_with_reason(
                "HK_CONNECT", "EXACT_TARGET_HK_BINDING_INVALID"
            )
            denied["cannot_confirm"].append(str(error.detail))
            denied["recovery_provenance"] = {
                "mode": "BACKFILL_BINDING_REJECTED",
                "backfill_run_id": binding["backfill_run_id"],
                "source": source_label,
                "http_status": error.status_code,
            }
            markets["HK_CONNECT"] = denied
            result = dict(payload)
            result.update(markets=markets, artifact_id=None,
                          bundle_artifact_id=None, run_id=None)
            execution = dict(payload.get("execution_evidence") or {})
            execution_markets = dict(execution.get("markets") or {})
            execution_markets["HK_CONNECT"] = {
                "status": "CANNOT_CONFIRM", "execution_verified": False,
                "natural_verified": False,
                "cannot_confirm": list(denied["cannot_confirm"]),
            }
            execution.update(markets=execution_markets,
                             execution_verified=False, natural_verified=False)
            result["execution_evidence"] = execution
            return result
        exact_markets = exact.get("selection_markets")
        exact_hk = exact_markets.get("HK_CONNECT") if isinstance(exact_markets, Mapping) else None
        if not isinstance(exact_hk, Mapping):
            raise HTTPException(status_code=409, detail="approved exact-target HK candidate is unavailable")

        markets = dict(payload.get("markets") or {})
        prior_hk = markets.get("HK_CONNECT")
        hk_market = dict(exact_hk)
        if isinstance(prior_hk, Mapping) and prior_hk.get("run_id") != hk_market.get("run_id"):
            superseded_source = {
                "status": "SUPERSEDED_BY_EXACT_TARGET_D1_RESEARCH_CANDIDATE",
                "displayed_as_valid_observation": False,
                "artifact_id": prior_hk.get("artifact_id"),
                "run_id": prior_hk.get("run_id"),
                "raw_artifact_sha256": prior_hk.get("raw_artifact_sha256"),
                "requested_rows": prior_hk.get("requested_rows"),
                "source_rows": prior_hk.get("source_rows"),
                "selected_rows": prior_hk.get("selected_rows"),
                "source_evidence": list(prior_hk.get("source_evidence") or ()),
            }
            if superseded_source_reason is not None:
                superseded_source["replacement_reason"] = superseded_source_reason
                superseded_source["target_pool_sha256"] = target_pool_sha256
            hk_market["superseded_source"] = superseded_source
        markets["HK_CONNECT"] = hk_market
        result = dict(payload)
        result.update(
            {
                "markets": markets,
                "RESEARCH_ONLY": True,
                "artifact_id": None,
                "bundle_artifact_id": None,
                "run_id": None,
                "market_readback_bindings": {
                    "scope": "DATE_STAGE_MARKET_SCOPED_READ_ONLY",
                    "trade_date": trade_date,
                    "stage_id": stage_id,
                    "markets": {
                        "HK_CONNECT": {
                            "source": source_label,
                            "backfill_run_id": binding["backfill_run_id"],
                            "run_id": hk_market.get("run_id"),
                            "requested_rows": hk_market.get("requested_rows"),
                            "source_rows": hk_market.get("source_rows"),
                            "selected_rows": hk_market.get("selected_rows"),
                            "raw_artifact_sha256": hk_market.get("raw_artifact_sha256"),
                            "selection_manifest_sha256": hk_market.get("selection_manifest_sha256"),
                            "runner_receipt_sha256": hk_market.get("runner_receipt_sha256"),
                            "target_pool_sha256": target_pool_sha256,
                        }
                    },
                    "single_bundle_artifact_id": None,
                },
            }
        )
        if binding.get("requested_rows") is not None:
            result["market_readback_bindings"]["markets"]["HK_CONNECT"].update(
                {
                    "candidate_batch_receipt_sha256": binding[
                        "candidate_batch_receipt_sha256"
                    ],
                    "candidate_receipt_sha256": binding[
                        "candidate_receipt_sha256"
                    ],
                    "candidate_manifest_sha256": binding[
                        "candidate_manifest_sha256"
                    ],
                    "candidate_source_evidence_sha256": binding[
                        "source_evidence_sha256"
                    ],
                    "missing_rows": binding["missing_rows"],
                    "missing_codes": list(binding["missing_codes"]),
                    "missing_reason_by_code": dict(
                        binding["missing_reason_by_code"]
                    ),
                }
            )
        prior_execution = dict(payload.get("execution_evidence") or {})
        execution_markets = dict(prior_execution.get("markets") or {})
        exact_execution = exact.get("execution_evidence")
        exact_execution_markets = (
            exact_execution.get("markets") if isinstance(exact_execution, Mapping) else None
        )
        exact_execution_hk = (
            exact_execution_markets.get("HK_CONNECT")
            if isinstance(exact_execution_markets, Mapping)
            else None
        )
        if isinstance(exact_execution_hk, Mapping):
            execution_markets["HK_CONNECT"] = dict(exact_execution_hk)
        else:
            execution_markets["HK_CONNECT"] = {
                "status": "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED",
                "selection_binding": "BOUND_TO_VERIFIED_SELECTION",
                "runner_receipt_verified": hk_market.get("runner_receipt_verified") is True,
                "runner_receipt_sha256": hk_market.get("runner_receipt_sha256"),
                "execution_verified": False,
                "natural_verified": False,
                "cannot_confirm": [
                    "HK_BACKFILL_EXECUTION_MARKET_DETAILS_NOT_EXPOSED_BY_SELECTION_CONSUMER"
                ],
            }
        prior_execution.update(
            {
                "markets": execution_markets,
                "scope": "READ_ONLY_MARKET_SCOPED_SELECTION_COMPOSITION",
                "status": "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED",
                "execution_verified": False,
                "natural_verified": False,
                "cannot_confirm": [
                    "NO_SINGLE_A_HK_EXECUTION_RECEIPT_FOR_MARKET_SCOPED_READBACK"
                ],
            }
        )
        prior_execution.pop("observed_sha256", None)
        prior_execution.pop("receipt_sha256_binding", None)
        result["execution_evidence"] = prior_execution
        return result

    def _read_r8_exact_target_hk_override(
        payload: dict, trade_date: str, stage_id: str, limit: int
    ) -> dict | None:
        binding = _HK_R8_BINDING_BY_DATE_STAGE.get((trade_date, stage_id))
        if binding is None:
            return None
        return _read_exact_target_hk_override(
            payload,
            trade_date,
            stage_id,
            limit,
            binding,
            source_label="APPROVED_EXACT_TARGET_D1_AFTERFACT_CANDIDATE_R8",
            target_pool_sha256=_HK_R8_POOL_EVIDENCE[trade_date]["pool_sha256"],
        )

    def _read_r9_exact_target_hk_override(
        payload: dict, trade_date: str, stage_id: str, limit: int
    ) -> dict | None:
        binding = _HK_R9_BINDING_BY_DATE_STAGE.get((trade_date, stage_id))
        if binding is None:
            return None
        markets = payload.get("markets")
        prior_hk = markets.get("HK_CONNECT") if isinstance(markets, Mapping) else None
        rows = prior_hk.get("rows") if isinstance(prior_hk, Mapping) else None
        legacy_stale = _HK_R9_LEGACY_STALE_LANE_IDENTITIES.get(
            (trade_date, stage_id)
        )
        replace_for_legacy_pool_mismatch = False
        if isinstance(prior_hk, Mapping):
            # R9 may repair a missing lane or replace a verified nonempty lane
            # only when its exact pool provenance proves it belongs to a
            # different target pool. Preserve an effective ordinary result
            # when it is already bound to this date's target pool. If the
            # consumer found this exact R9 backfill run because no ordinary
            # lane existed, apply the exact route binding without marking that
            # same candidate as a superseded source.
            if prior_hk.get("backfill_run_id") == binding["backfill_run_id"]:
                replace_existing = True
            elif (
                rows == []
                and prior_hk.get("status") == "CANNOT_CONFIRM"
                and prior_hk.get("selected_rows") in (None, 0)
            ):
                replace_existing = True
            elif isinstance(rows, list) and rows and legacy_stale is not None:
                legacy_contract = _HK_R9_LEGACY_STALE_POOL_CONTRACTS.get(trade_date)
                target_pool = _HK_R9_POOL_EVIDENCE.get(trade_date)
                evidence = prior_hk.get("source_evidence")

                def marker_values(name: str) -> list[str]:
                    prefix = f"{name}="
                    return [
                        marker.partition("=")[2]
                        for marker in evidence
                        if isinstance(marker, str) and marker.startswith(prefix)
                    ] if isinstance(evidence, list) else []

                def marker_matches(name: str, expected: str | None) -> bool:
                    values = marker_values(name)
                    return values == ([expected] if expected is not None else [])

                try:
                    latest = shared_selection_consumer.store._latest()
                    latest_key = shared_selection_consumer.store._key(
                        trade_date, stage_id, "HK_CONNECT"
                    )
                    current_entry = latest.get("entries", {}).get(latest_key)
                except (AttributeError, OSError, ValueError, TypeError, KeyError):
                    current_entry = None

                observation_count = prior_hk.get("observation_count")
                selected_rows = prior_hk.get("selected_rows")
                count_evidence = (
                    observation_count
                    if isinstance(observation_count, int)
                    and not isinstance(observation_count, bool)
                    else selected_rows
                )
                count_matches = (
                    isinstance(count_evidence, int)
                    and not isinstance(count_evidence, bool)
                    and count_evidence == legacy_stale["observation_count"]
                    and len(rows) == count_evidence
                    and (
                        observation_count is None
                        or observation_count == count_evidence
                    )
                    and (selected_rows is None or selected_rows == count_evidence)
                )
                entry_matches = isinstance(current_entry, Mapping) and all(
                    current_entry.get(field) == expected
                    for field, expected in (
                        ("trade_date", trade_date),
                        ("stage_id", stage_id),
                        ("market", "HK_CONNECT"),
                        ("run_id", legacy_stale["run_id"]),
                        ("artifact_sha256", legacy_stale["selection_artifact_sha256"]),
                        ("manifest_sha256", legacy_stale["selection_manifest_sha256"]),
                        ("receipt_sha256", legacy_stale["selection_receipt_sha256"]),
                    )
                ) and all(
                    current_entry.get(flag) is False
                    for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
                )
                target_matches = (
                    isinstance(target_pool, Mapping)
                    and binding.get("pool_artifact_sha256") == target_pool.get("pool_sha256")
                    and binding.get("pool_path") == target_pool.get("pool_path")
                    and binding.get("pool_signal_date") == target_pool.get("signal_date")
                    and target_pool.get("source_date") == trade_date
                    and target_pool.get("pool_sha256") != legacy_contract.get("pool_sha256")
                ) if isinstance(legacy_contract, Mapping) else False
                legacy_source_matches = (
                    isinstance(legacy_contract, Mapping)
                    and marker_matches("hk_d1_sha256", legacy_contract.get("pool_sha256"))
                    and marker_matches("hk_d1_json_sha256", legacy_contract.get("pool_sha256"))
                    and marker_matches("hk_d1_json", legacy_contract.get("pool_path"))
                    and marker_matches(
                        "hk_d1_source_trade_date",
                        legacy_contract.get("source_trade_date"),
                    )
                    and marker_matches(
                        "hk_d1_source_signal_date",
                        legacy_contract.get("source_signal_date"),
                    )
                    and marker_matches(
                        "hk_d1_binding_sha256",
                        legacy_contract.get("binding_sha256"),
                    )
                )
                optional_display_mode = prior_hk.get("display_mode")
                replace_for_legacy_pool_mismatch = all(
                    (
                        trade_date in _HK_R9_LEGACY_STALE_POOL_CONTRACTS,
                        prior_hk.get("run_id") == legacy_stale["run_id"],
                        prior_hk.get("artifact_id") == legacy_stale["artifact_id"],
                        prior_hk.get("raw_artifact_sha256") == legacy_stale["raw_artifact_sha256"],
                        prior_hk.get("status") in {"READY", "PARTIAL_WITH_ROWS"},
                        prior_hk.get("selection_status", "PARTIAL_WITH_ROWS")
                        in {"READY", "PARTIAL_WITH_ROWS"},
                        optional_display_mode in (None, "OBSERVATION_UNVERIFIED"),
                        prior_hk.get("requested_rows") == legacy_stale["requested_rows"],
                        prior_hk.get("source_rows") == legacy_stale["source_rows"],
                        entry_matches,
                        target_matches,
                        legacy_source_matches,
                        count_matches,
                    )
                )
                replace_existing = replace_for_legacy_pool_mismatch
            elif (
                isinstance(rows, list)
                and rows
                and prior_hk.get("status") in {"READY", "PARTIAL_WITH_ROWS"}
                and prior_hk.get("selected_rows") == len(rows)
            ):
                source_evidence = prior_hk.get("source_evidence")
                pool_markers = [
                    marker.partition("=")[2]
                    for marker in source_evidence
                    if isinstance(marker, str)
                    and marker.startswith("historical_pool_artifact_sha256=")
                ] if isinstance(source_evidence, list) else []
                existing_pool_sha256 = pool_markers[0] if len(pool_markers) == 1 else ""
                is_sha256 = (
                    len(existing_pool_sha256) == 64
                    and all(character in "0123456789abcdefABCDEF" for character in existing_pool_sha256)
                )
                replace_existing = (
                    is_sha256
                    and existing_pool_sha256.lower()
                    != str(binding["pool_artifact_sha256"]).lower()
                )
            else:
                replace_existing = False
            if not replace_existing:
                return None
        return _read_exact_target_hk_override(
            payload,
            trade_date,
            stage_id,
            limit,
            binding,
            source_label=(
                "APPROVED_MONTH_HK_EXACT_TARGET_D1_AFTERFACT_R9_LEGACY_POOL_REPAIR"
                if replace_for_legacy_pool_mismatch
                else "APPROVED_MONTH_HK_EXACT_TARGET_D1_AFTERFACT_R9"
            ),
            target_pool_sha256=binding["pool_artifact_sha256"],
            superseded_source_reason=(
                "EXACT_PINNED_LEGACY_HK_D1_POOL_MISMATCH"
                if replace_for_legacy_pool_mismatch
                else None
            ),
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, bool]:
        return dict(TRADING_SAFETY_FLAGS)

    @app.get("/api/v4/meta/stages")
    def stage_metadata() -> dict:
        return {
            "stages": list(FROZEN_STAGE_IDS),
            "definitions": [
                {"stage_id": stage_id, **STAGE_DEFINITIONS[stage_id]}
                for stage_id in FROZEN_STAGE_IDS
            ],
        }

    @app.get("/api/v1/runs/date-list")
    def run_date_list(date: str | None = None) -> dict:
        requested = _strict_date(date) if date is not None else None
        response = {
            **_catalog(),
            "review_dates": review_store.list_dates(),
            "research_dates": research_source.list_dates(),
            "research_source": research_source.binding(),
        }
        # ``stage_artifacts`` and ``independent_pool_evidence`` are navigation
        # inputs only: they feed the date lists above and have no client or
        # server consumer. Serializing them added ~2.4 MB to this response.
        response.pop("stage_artifacts", None)
        response.pop("independent_pool_evidence", None)
        response["requested_date"] = requested
        response["selected_date"] = requested or response["navigation_date"]
        # Reuse the existing read-only validator. A configured string alone is
        # not proof of a running release; no path or exception detail is exposed.
        from infrastructure.scheduling.dispatcher import validate_release_identity
        identity = {"application": "V4", "status": "CANNOT_CONFIRM",
                    "release_id": "", "process_status": "CANNOT_CONFIRM"}
        try:
            verified = validate_release_identity()
            identity.update(status="MANIFEST_EXECUTION_FILES_VERIFIED",
                            release_id=verified["release_id"],
                            manifest_sha256=verified["release_manifest_sha256"])
        except (OSError, ValueError, TypeError, KeyError):
            pass
        response["runtime_identity"] = identity
        return response

    app.include_router(create_preselection_router(
        PreselectionPoolService(
            store,
            configured_pool_source=bool(configured_pool_source),
            resolved_pool_source=resolved_pool_source,
        ),
        get_catalog=_catalog,
        validate_date=_strict_date,
    ))

    def _read_hk_morning_selection_recovery_override(
        payload: dict,
        trade_date: str,
        stage_id: str,
        limit: int,
    ) -> dict | None:
        binding = _HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE.get(
            (trade_date, stage_id)
        )
        if binding is None:
            return None
        try:
            from stage_center.selection import SelectionStore

            if configured_selection_root is None:
                return None
            store = SelectionStore(configured_selection_root)
            original = store.read_verified(trade_date, stage_id, "HK_CONNECT")
            verified = store._verify_run(
                trade_date, stage_id, "HK_CONNECT", binding["selection_run_id"]
            )
            if not isinstance(original, Mapping):
                return None
            original_rows = original.get("rows")
            if (
                original.get("run_id") != binding["selection_run_id"]
                or original.get("artifact_id") != binding["artifact_id"]
                or original.get("raw_artifact_sha256") != binding["raw_artifact_sha256"]
                or original.get("algorithm_id") != binding["algorithm_id"]
                or original.get("algorithm_sha256") != binding["algorithm_sha256"]
                or original.get("source_status") != "CANNOT_CONFIRM"
                or original.get("selection_status") != "PARTIAL_WITH_ROWS"
                or original.get("requested_rows") != 100
                or original.get("source_rows") != 100
                or original.get("selected_rows") != 10
                or original.get("missing_symbols")
                or original.get("cannot_confirm") != ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
                or not isinstance(original_rows, list)
                or len(original_rows) != 10
            ):
                return None
            if (
                verified.get("manifest_sha256") != binding["original_manifest_sha256"]
                or verified.get("receipt_sha256") != binding["original_receipt_sha256"]
                or verified.get("artifact_sha256") != binding["selection_artifact_sha256"]
            ):
                return None
            markets = payload.get("markets")
            prior_hk = markets.get("HK_CONNECT") if isinstance(markets, Mapping) else None
            if isinstance(prior_hk, Mapping) and any(
                prior_hk.get(field) not in (None, expected)
                for field, expected in (
                    ("run_id", binding["selection_run_id"]),
                    ("artifact_id", binding["artifact_id"]),
                    ("raw_artifact_sha256", binding["raw_artifact_sha256"]),
                )
            ):
                return None
            # The ordinary consumer hides rows for CANNOT_CONFIRM. Reattach the
            # verified exact identity only for supersession comparison; the
            # exact backfill route supplies the displayed observation rows.
            payload = dict(payload)
            markets = dict(markets or {})
            markets["HK_CONNECT"] = {
                "market": "HK_CONNECT",
                "status": original["selection_status"],
                "selection_status": original["selection_status"],
                "source_status": original["source_status"],
                "artifact_id": original["artifact_id"],
                "run_id": original["run_id"],
                "raw_artifact_sha256": original["raw_artifact_sha256"],
                "requested_rows": original["requested_rows"],
                "source_rows": original["source_rows"],
                "selected_rows": original["selected_rows"],
                "source_evidence": list(original.get("source_evidence") or []),
                "missing_symbols": list(original.get("missing_symbols") or []),
                "cannot_confirm": list(original.get("cannot_confirm") or []),
                "rows": list(original_rows),
            }
            payload["markets"] = markets
            result = _read_exact_target_hk_override(
                payload,
                trade_date,
                stage_id,
                limit,
                {
                    "backfill_run_id": binding["backfill_run_id"],
                    # The candidate is an exact selection-row projection; it does
                    # not claim a new full-pool acquisition or missing-code list.
                    "requested_rows": None,
                },
                source_label="HK_MORNING_PRECAPTURE_OBSERVATION_REPROJECTION_R1",
                target_pool_sha256="78646320d1140bb574b6aee66c9bd6b51f57ca0797fd96e4f2775e245a57efd8",
            )
            result["markets"]["HK_CONNECT"]["trade_date"] = trade_date
            result["markets"]["HK_CONNECT"]["stage_id"] = stage_id
            return result
        except (OSError, ValueError, TypeError, KeyError):
            return None
        except HTTPException as error:
            if error.status_code in {404, 409}:
                return None
            raise

    @app.get("/api/v4/workbench/stage")
    def stage_workbench(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        limit: int = Query(default=10, ge=1, le=50),
        market: str | None = None,
        backfill_run_id: str | None = None,
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        # The optional release-owned binding handles only its exact approved
        # date/stage/run. All ordinary history and legacy exact bindings below
        # retain their original configured root and verification contract.
        morning_binding = _HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE.get(
            (selected, stage)
        )
        is_exact_morning_backfill = (
            market == "HK_CONNECT"
            and isinstance(morning_binding, Mapping)
            and morning_binding.get("backfill_run_id") == backfill_run_id
        )
        if (
            approved_research_reader is not None
            and ((market is None) == (backfill_run_id is None))
            and not is_exact_morning_backfill
        ):
            try:
                research_payload = approved_research_reader.get(
                    selected, stage, markets=None if market is None else (market,),
                    backfill_run_id=backfill_run_id,
                )
            except ResearchReadError as error:
                # The optional research package covers BOTH A and HK. Its
                # rejected A is never authenticated by this fallback: read the
                # independent ordinary A trio through the unchanged verifier.
                if (selected, stage) == ("20261009", "STAGE_0930_0935") and (
                    market is None and backfill_run_id is None
                    and shared_selection_consumer is not None
                ):
                    ordinary = shared_selection_consumer.get(
                        selected, stage, markets=("A_SHARE",), allow_backfill=True
                    )
                    a_market = (ordinary.get("markets") or {}).get("A_SHARE")
                    if isinstance(a_market, Mapping) and (
                        a_market.get("selection_manifest_receipt_verified") is True
                        and int(a_market.get("selected_rows") or 0) > 0
                        and len(a_market.get("rows") or []) == a_market["selected_rows"]
                    ):
                        from stage_center.consumer import _invalid_market_with_reason
                        denied = _invalid_market_with_reason(
                            "HK_CONNECT", "APPROVED_RESEARCH_BINDING_INVALID"
                        )
                        denied["cannot_confirm"].append(str(error))
                        result = dict(ordinary)
                        result["markets"] = {"A_SHARE": a_market, "HK_CONNECT": denied}
                        result.update(artifact_id=None, bundle_artifact_id=None, run_id=None)
                        result["optional_override_failure"] = {
                            "scope": ["A_SHARE", "HK_CONNECT"],
                            "reason": str(error),
                            "fallback": "INDEPENDENT_VERIFIED_ORDINARY_A_TRIO_ONLY",
                            "rejected_research_A_used": False,
                        }
                        execution = dict(ordinary.get("execution_evidence") or {})
                        execution_markets = dict(execution.get("markets") or {})
                        execution_markets["HK_CONNECT"] = {
                            "status": "CANNOT_CONFIRM", "execution_verified": False,
                            "natural_verified": False,
                            "cannot_confirm": list(denied["cannot_confirm"]),
                        }
                        execution.update(markets=execution_markets,
                                         execution_verified=False, natural_verified=False)
                        result["execution_evidence"] = execution
                        return project_shared_selection(result, limit, ordinary_hk_display=True)
                raise HTTPException(status_code=409, detail="approved research read binding is unavailable or invalid") from error
            if research_payload is not None:
                response = project_shared_selection(research_payload, limit, ordinary_hk_display=True)
                # The existing HK display intentionally withholds a formal
                # selected count. Verified research rows still make this
                # exact composed response partial when its other lane fails.
                if research_payload.get("status") == "PARTIAL_WITH_ROWS":
                    response["status"] = "PARTIAL_WITH_ROWS"
                    response["stage"].update(status="PARTIAL_WITH_ROWS", display_status="PARTIAL_WITH_ROWS")
                if market is not None:
                    response.update(market=market, selection_mode="HISTORICAL_BACKFILL_READ_ONLY",
                                    response_source="SHARED_STAGE_CENTER_BACKFILL")
                return response
        if market is not None or backfill_run_id is not None:
            if market is None or backfill_run_id is None:
                raise HTTPException(status_code=422, detail="market and backfill_run_id must be supplied together")
            binding = _APPROVED_EXACT_STAGE_BACKFILLS.get(
                (selected, stage, market, backfill_run_id)
            )
            if binding is None:
                raise HTTPException(status_code=404, detail="backfill selection identity is unavailable")
            if configured_selection_root is None or shared_selection_consumer is None:
                raise HTTPException(status_code=404, detail="backfill selection namespace is unavailable")

            scoped_root = _resolve_exact_backfill_selection_root(
                configured_selection_root, backfill_run_id
            )
            backfill_consumer = _new_scoped_stage_selection_consumer(
                scoped_root,
                shared_selection_consumer,
            )
            try:
                envelope = backfill_consumer.store.read_verified(selected, stage, market)
                latest = backfill_consumer.store._latest()
                entry = latest.get("entries", {}).get(
                    backfill_consumer.store._key(selected, stage, market)
                )
                payload = backfill_consumer.get(selected, stage, markets=(market,))
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise HTTPException(status_code=409, detail="backfill selection identity is invalid") from error

            market_payload = (payload.get("markets") or {}).get(market)
            if not isinstance(entry, Mapping) or not isinstance(market_payload, Mapping):
                raise HTTPException(status_code=409, detail="backfill selection identity is invalid")
            morning_binding = _HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE.get(
                (selected, stage)
            )
            is_morning_observation = (
                market == "HK_CONNECT"
                and isinstance(morning_binding, Mapping)
                and morning_binding.get("backfill_run_id") == backfill_run_id
            )
            rows = (
                envelope.get("rows") or []
                if is_morning_observation
                else market_payload.get("rows") or []
            )
            source_evidence = envelope.get("source_evidence") or []
            cannot_confirm = envelope.get("cannot_confirm") or []
            expected_identity = {
                "trade_date": selected,
                "stage_id": stage,
                "market": market,
                "run_id": binding["selection_run_id"],
                "artifact_id": binding["artifact_id"],
                "raw_artifact_sha256": binding["raw_artifact_sha256"],
                "algorithm_id": binding["algorithm_id"],
                "algorithm_sha256": binding["algorithm_sha256"],
                "selection_status": binding["selection_status"],
                "source_status": binding["source_status"],
            }
            if any(envelope.get(field) != expected for field, expected in expected_identity.items()):
                raise HTTPException(status_code=409, detail="backfill selection identity is invalid")
            if (
                entry.get("run_id") != binding["selection_run_id"]
                or entry.get("manifest_sha256") != binding["selection_manifest_sha256"]
                or entry.get("receipt_sha256") != binding["selection_receipt_sha256"]
                or entry.get("artifact_sha256") != binding["selection_artifact_sha256"]
                or len(rows) != binding["selected_rows"]
                or len(envelope.get("rows") or []) != binding["selected_rows"]
                or envelope.get("selected_rows") != binding["selected_rows"]
                or envelope.get("source_rows") != binding["source_rows"]
                or not isinstance(cannot_confirm, list)
                or len(cannot_confirm) != binding["cannot_confirm_count"]
                or not isinstance(source_evidence, list)
                or any(not isinstance(marker, str) for marker in source_evidence)
                or any(marker not in source_evidence for marker in binding["required_evidence"])
                or (
                    binding.get("requested_rows") is not None
                    and (
                        envelope.get("requested_rows") != binding["requested_rows"]
                        or (
                            not is_morning_observation
                            and market_payload.get("requested_rows")
                            != binding["requested_rows"]
                        )
                        or binding["requested_rows"] - binding["source_rows"]
                        != binding.get("missing_rows")
                        or binding.get("missing_rows")
                        != len(binding.get("missing_codes") or ())
                    )
                )
                or (
                    binding.get("source_evidence_sha256") is not None
                    and hashlib.sha256(
                        "\n".join(source_evidence).encode("utf-8")
                    ).hexdigest()
                    != binding["source_evidence_sha256"]
                )
                or any(envelope.get(flag) is not False for flag in TRADING_SAFETY_FLAGS)
                or any(
                    not isinstance(row, Mapping)
                    or row.get("formal_eligible") is not False
                    or row.get("action_level") != "NO_BUY"
                    or row.get("trade_status") not in {"NO_TRADE", "WATCH_ONLY"}
                    or row.get("status") != row.get("trade_status")
                    or row.get("source_mode") != "HK_CONNECT_FOUR_LANE"
                    for row in rows
                )
            ):
                raise HTTPException(status_code=409, detail="backfill selection safety or SHA binding is invalid")

            runner_receipt_verified, runner_receipt_sha256 = (
                backfill_consumer._verify_backfill_runner_receipt(
                    trade_date=selected,
                    stage_id=stage,
                    market=market,
                    backfill_run_id=backfill_run_id,
                    envelope=envelope,
                )
            )
            if (
                runner_receipt_verified is not True
                or runner_receipt_sha256 != binding["runner_receipt_sha256"]
            ):
                raise HTTPException(status_code=409, detail="backfill runner receipt identity is invalid")

            if is_morning_observation:
                from stage_center.selection import SelectionStore

                try:
                    original = SelectionStore(configured_selection_root)._verify_run(
                        selected,
                        stage,
                        "HK_CONNECT",
                        morning_binding["selection_run_id"],
                    )
                except (OSError, ValueError, TypeError, KeyError) as error:
                    raise HTTPException(
                        status_code=409,
                        detail="original morning selection identity is invalid",
                    ) from error
                original_envelope = original.get("envelope")
                if (
                    not isinstance(original_envelope, Mapping)
                    or original.get("manifest_sha256")
                    != morning_binding["original_manifest_sha256"]
                    or original.get("receipt_sha256")
                    != morning_binding["original_receipt_sha256"]
                    or original.get("artifact_sha256")
                    != morning_binding["selection_artifact_sha256"]
                    or any(
                        original_envelope.get(field) != envelope.get(field)
                        for field in (
                            "run_id",
                            "artifact_id",
                            "raw_artifact_sha256",
                            "algorithm_id",
                            "algorithm_sha256",
                            "rows",
                        )
                    )
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="morning observation differs from original selection",
                    )
                market_payload.update(
                    {
                        "market": "HK_CONNECT",
                        "status": envelope["selection_status"],
                        "selection_status": envelope["selection_status"],
                        "source_status": envelope["source_status"],
                        "artifact_id": envelope["artifact_id"],
                        "run_id": envelope["run_id"],
                        "algorithm_id": envelope["algorithm_id"],
                        "algorithm_sha256": envelope["algorithm_sha256"],
                        "raw_artifact_sha256": envelope["raw_artifact_sha256"],
                        "requested_rows": envelope["requested_rows"],
                        "source_rows": envelope["source_rows"],
                        "selected_rows": envelope["selected_rows"],
                        "coverage_ratio": envelope["coverage_ratio"],
                        "source_evidence": list(source_evidence),
                        "missing_symbols": list(envelope.get("missing_symbols") or []),
                        "cannot_confirm": list(cannot_confirm),
                        "rows": list(envelope["rows"]),
                    }
                )
                market_payload.update(
                {
                    "selection_mode": "BACKFILL",
                    "backfill_run_id": backfill_run_id,
                    "backfill_run_ids": [backfill_run_id],
                    "selection_manifest_sha256": binding["selection_manifest_sha256"],
                    "selection_receipt_sha256": binding["selection_receipt_sha256"],
                    "selection_artifact_sha256": binding["selection_artifact_sha256"],
                    "selection_manifest_receipt_verified": True,
                    "runner_receipt_verified": True,
                    "runner_receipt_status": "VERIFIED",
                    "runner_receipt_sha256": runner_receipt_sha256,
                    "recovery_provenance": {
                        "mode": "BACKFILL",
                        "backfill_run_id": backfill_run_id,
                        "selection_manifest_receipt_verified": True,
                        "runner_receipt_verified": True,
                        "runner_receipt_status": "VERIFIED",
                        "runner_receipt_sha256": runner_receipt_sha256,
                    },
                }
            )
            if binding.get("requested_rows") is not None and not is_morning_observation:
                market_payload.update(
                    {
                        "target_pool_sha256": binding["pool_artifact_sha256"],
                        "candidate_receipt_sha256": binding["candidate_receipt_sha256"],
                        "candidate_manifest_sha256": binding["candidate_manifest_sha256"],
                        "candidate_source_evidence_sha256": binding[
                            "source_evidence_sha256"
                        ],
                        "candidate_source_coverage": {
                            "requested_rows": binding["requested_rows"],
                            "observed_rows": binding["source_rows"],
                            "missing_rows": binding["missing_rows"],
                            "missing_codes": list(binding["missing_codes"]),
                            "missing_reason_by_code": dict(
                                binding["missing_reason_by_code"]
                            ),
                        },
                    }
                )
            response = project_shared_selection(
                payload, limit, ordinary_hk_display=True
            )
            response.update(
                {
                    "mode": "BACKFILL",
                    "backfill_run_id": backfill_run_id,
                    "market": market,
                    "selection_mode": "HISTORICAL_BACKFILL_READ_ONLY",
                    "response_source": "SHARED_STAGE_CENTER_BACKFILL",
                    "RESEARCH_ONLY": True,
                    "write_performed": False,
                    **TRADING_SAFETY_FLAGS,
                }
            )
            return response
        if shared_selection_consumer is not None:
            hk_morning_recovery_slot = (
                selected == "20261016"
                and (selected, stage)
                in _HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE
            )
            payload = shared_selection_consumer.get(
                selected, stage, allow_backfill=not hk_morning_recovery_slot
            )
            payload = _quarantine_known_hk_auction_pool_mismatch(
                payload, selected, stage
            )
            hk_morning_override = _read_hk_morning_selection_recovery_override(
                payload, selected, stage, limit
            )
            if hk_morning_override is not None:
                return project_shared_selection(
                    hk_morning_override, limit, ordinary_hk_display=True
                )
            r8_override = _read_r8_exact_target_hk_override(
                payload, selected, stage, limit
            )
            if r8_override is not None:
                return project_shared_selection(
                    r8_override, limit, ordinary_hk_display=True
                )
            r9_override = _read_r9_exact_target_hk_override(
                payload, selected, stage, limit
            )
            if r9_override is not None:
                return project_shared_selection(
                    r9_override, limit, ordinary_hk_display=True
                )
            if selected == "20260924" and stage == "STAGE_0930_0935":
                day24_run_id = "1d3ab9f9bd3a44c3811bf1fed2b74108"
                day24_binding_key = (
                    selected,
                    stage,
                    "HK_CONNECT",
                    day24_run_id,
                )
                if day24_binding_key in _APPROVED_EXACT_STAGE_BACKFILLS:
                    try:
                        exact_hk = stage_workbench(
                            date=selected,
                            stage=stage,
                            limit=limit,
                            market="HK_CONNECT",
                            backfill_run_id=day24_run_id,
                        )
                    except HTTPException as error:
                        a_market = (payload.get("markets") or {}).get("A_SHARE")
                        if error.status_code != 409 or not isinstance(a_market, Mapping) or not (
                            a_market.get("selection_manifest_receipt_verified") is True
                            and int(a_market.get("selected_rows") or 0) > 0
                            and len(a_market.get("rows") or []) == a_market["selected_rows"]
                        ):
                            raise
                        from stage_center.consumer import _invalid_market_with_reason
                        denied = _invalid_market_with_reason(
                            "HK_CONNECT", "EXACT_TARGET_HK_BINDING_INVALID"
                        )
                        denied["cannot_confirm"].append(str(error.detail))
                        denied["recovery_provenance"] = {
                            "mode": "BACKFILL_BINDING_REJECTED",
                            "backfill_run_id": day24_run_id,
                            "source": "DAY24_EXACT_HK_OVERRIDE",
                            "http_status": error.status_code,
                        }
                        result = dict(payload)
                        markets = dict(payload.get("markets") or {})
                        markets["HK_CONNECT"] = denied
                        result.update(markets=markets, artifact_id=None,
                                      bundle_artifact_id=None, run_id=None)
                        execution = dict(payload.get("execution_evidence") or {})
                        execution_markets = dict(execution.get("markets") or {})
                        execution_markets["HK_CONNECT"] = {
                            "status": "CANNOT_CONFIRM", "execution_verified": False,
                            "natural_verified": False,
                            "cannot_confirm": list(denied["cannot_confirm"]),
                        }
                        execution.update(markets=execution_markets,
                                         execution_verified=False, natural_verified=False)
                        result["execution_evidence"] = execution
                        return project_shared_selection(result, limit, ordinary_hk_display=True)
                    exact_markets = exact_hk.get("selection_markets")
                    exact_market = (
                        exact_markets.get("HK_CONNECT")
                        if isinstance(exact_markets, Mapping)
                        else None
                    )
                    exact_execution = exact_hk.get("execution_evidence")
                    exact_execution_markets = (
                        exact_execution.get("markets")
                        if isinstance(exact_execution, Mapping)
                        else None
                    )
                    exact_execution_market = (
                        exact_execution_markets.get("HK_CONNECT")
                        if isinstance(exact_execution_markets, Mapping)
                        else None
                    )
                    if not isinstance(exact_market, Mapping):
                        raise HTTPException(
                            status_code=409,
                            detail="approved market-scoped backfill identity is invalid",
                        )

                    canonical_markets = dict(payload.get("markets") or {})
                    a_market = canonical_markets.get("A_SHARE") or {}
                    canonical_markets["HK_CONNECT"] = dict(exact_market)
                    for market_payload in canonical_markets.values():
                        if isinstance(market_payload, dict):
                            market_payload["RESEARCH_ONLY"] = True
                    payload = dict(payload)
                    payload["RESEARCH_ONLY"] = True
                    payload["markets"] = canonical_markets
                    # A and HK retain their own verified source identities; this
                    # read-only composition does not claim a shared bundle.
                    payload["artifact_id"] = None
                    payload["bundle_artifact_id"] = None
                    payload["run_id"] = None
                    payload["market_readback_bindings"] = {
                        "scope": "DATE_STAGE_MARKET_SCOPED_READ_ONLY",
                        "trade_date": selected,
                        "stage_id": stage,
                        "markets": {
                            "A_SHARE": {
                                "source": "SHARED_STAGE_CENTER_CURRENT_SELECTION",
                                "run_id": a_market.get("run_id"),
                                "requested_rows": a_market.get("requested_rows"),
                                "source_rows": a_market.get("source_rows"),
                                "selected_rows": a_market.get("selected_rows"),
                            },
                            "HK_CONNECT": {
                                "source": "APPROVED_STAGE_CENTER_BACKFILL",
                                "backfill_run_id": day24_run_id,
                                "run_id": exact_market.get("run_id"),
                                "requested_rows": exact_market.get("requested_rows"),
                                "source_rows": exact_market.get("source_rows"),
                                "selected_rows": exact_market.get("selected_rows"),
                                "runner_receipt_sha256": exact_market.get(
                                    "runner_receipt_sha256"
                                ),
                            },
                        },
                        "single_bundle_artifact_id": None,
                    }

                    combined_execution = dict(
                        payload.get("execution_evidence") or {}
                    )
                    combined_execution_markets = dict(
                        combined_execution.get("markets") or {}
                    )
                    if isinstance(exact_execution_market, Mapping):
                        combined_execution_markets["HK_CONNECT"] = dict(
                            exact_execution_market
                        )
                    else:
                        # The scoped selection path has independently verified
                        # the runner receipt even though this consumer does not
                        # expose the matching execution-market detail row.
                        # Keep that binding visible without claiming natural or
                        # formal execution verification.
                        runner_verified = exact_market.get(
                            "runner_receipt_verified"
                        ) is True
                        combined_execution_markets["HK_CONNECT"] = {
                            "status": "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED",
                            "selection_binding": (
                                "BOUND_TO_VERIFIED_SELECTION"
                                if runner_verified
                                else "CANNOT_CONFIRM"
                            ),
                            "runner_receipt_verified": runner_verified,
                            "runner_receipt_sha256": exact_market.get(
                                "runner_receipt_sha256"
                            ),
                            "execution_verified": False,
                            "natural_verified": False,
                            "cannot_confirm": [
                                "HK_BACKFILL_EXECUTION_MARKET_DETAILS_NOT_EXPOSED_BY_SELECTION_CONSUMER"
                            ],
                        }
                    combined_execution["markets"] = combined_execution_markets
                    combined_execution[
                        "scope"
                    ] = "READ_ONLY_MARKET_SCOPED_SELECTION_COMPOSITION"
                    combined_execution[
                        "status"
                    ] = "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED"
                    combined_execution["execution_verified"] = False
                    combined_execution["natural_verified"] = False
                    combined_execution.pop("observed_sha256", None)
                    combined_execution.pop("receipt_sha256_binding", None)
                    # Reasons from the ordinary, unscoped aggregate cannot
                    # describe this A+HK composition: keep uncertainty on each
                    # market entry and only assert the shared-receipt gap here.
                    combined_execution["cannot_confirm"] = [
                        "NO_SINGLE_A_HK_EXECUTION_RECEIPT_FOR_MARKET_SCOPED_READBACK"
                    ]
                    payload["execution_evidence"] = combined_execution
            return project_shared_selection(
                payload,
                limit,
                ordinary_hk_display=True,
            )
        return stage_runner.read_workbench(selected, stage, limit)

    @app.post("/api/v4/workbench/stage/ensure")
    def stage_workbench_ensure(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        force: bool = False,
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if shared_selection_consumer is not None:
            return project_shared_selection(
                shared_selection_consumer.ensure(selected, stage, force=force),
                limit=50,
                ordinary_hk_display=True,
            )
        return stage_runner.ensure(selected, stage, force=force)

    @app.get("/api/v4/workbench/stage-batch")
    def stage_workbench_batch(
        date: str | None = None,
        stages: str | None = None,
    ) -> dict:
        """Timeline summaries for several stages in one round trip."""
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        requested = [item for item in (stages or "").split(",") if item]
        if any(stage_id not in FROZEN_STAGE_IDS for stage_id in requested):
            raise HTTPException(status_code=422, detail="unknown stage")
        ordered = [
            stage_id
            for stage_id in FROZEN_STAGE_IDS
            if not requested or stage_id in requested
        ]

        def _summary_for(stage_id: str) -> tuple[str, dict | None]:
            try:
                payload = stage_workbench(selected, stage_id, 50)
            except HTTPException:
                return stage_id, None
            except (OSError, ValueError, TypeError, KeyError):
                return stage_id, None
            return stage_id, _project_stage_timeline_summary(payload)

        summaries: dict[str, dict] = {}
        if ordered:
            workers = min(
                len(ordered),
                max(1, int(os.environ.get("V4_STAGE_BATCH_WORKERS", "8") or "8")),
            )
            timeout_seconds = float(os.environ.get("V4_STAGE_BATCH_TIMEOUT_SECONDS", "12") or "12")
            summaries = _bounded_stage_summaries(
                _summary_for, ordered, workers=min(workers, _STAGE_BATCH_CAPACITY),
                timeout_seconds=timeout_seconds,
            )

        return {
            "schema_version": "v4.stage_timeline_batch.v1",
            "trade_date": selected,
            "stages": summaries,
            **dict(TRADING_SAFETY_FLAGS),
            "RESEARCH_ONLY": True,
            "write_performed": False,
        }

    @app.get("/api/v4/stage-center/selection")
    def shared_stage_selection(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if shared_selection_consumer is None:
            return shared_selection_unconfigured(selected, stage)
        return project_shared_selection(
            shared_selection_consumer.get(selected, stage),
            limit,
            ordinary_hk_display=True,
        )

    @app.get("/api/v4/manager/stage-selection")
    def manager_stage_selection(
        date: str | None = None,
        stage: str | None = None,
        market: str | None = None,
        limit: int = Query(default=50, ge=1, le=50),
    ) -> dict:
        """Read the manager's exact HK_CONNECT stage lane only.

        The shared stage-center route remains a compatibility projection for
        its historical scheduled-market response.  This dedicated route is a
        narrower boundary for the manager consumer and never falls back to
        the unified or A-share lane.
        """
        if date is None:
            raise HTTPException(status_code=422, detail="date is required")
        selected = _strict_date(date)
        if stage != "STAGE_0935_0940":
            raise HTTPException(status_code=422, detail="stage must be STAGE_0935_0940")
        if market != "HK_CONNECT":
            raise HTTPException(status_code=422, detail="market must be HK_CONNECT")
        if shared_selection_consumer is None:
            return shared_selection_unconfigured(selected, stage)
        return project_shared_selection(
            shared_selection_consumer.get(selected, stage, markets=("HK_CONNECT",)),
            limit,
        )

    @app.post("/api/v4/stage-center/selection/ensure")
    def shared_stage_selection_ensure(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        force: bool = False,
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if shared_selection_consumer is None:
            return shared_selection_unconfigured(selected, stage)
        return project_shared_selection(
            shared_selection_consumer.ensure(selected, stage, force=force),
            limit=200,
            ordinary_hk_display=True,
        )

    app.include_router(
        create_runtime_router(
            store.root,
            ledger_root=ledger_root,
            stage_selection_root=configured_selection_root,
            current_date=current_date,
        )
    )
    app.include_router(create_runtime_graph_router(store.root))
    app.include_router(create_manual_collection_router(
        Path(os.environ.get("V4_REVIEW_CORE_CLOSE_ROOT") or store.root),
        stage_selection_root=configured_selection_root,
    ))
    app.include_router(create_review_router(
        store.root,
        hk_close_root=os.environ.get("V4_REVIEW_CORE_CLOSE_ROOT") or None,
        review_root=os.environ.get("V4_DAILY_REVIEW_ROOT"),
        generation_bindings_path=os.environ.get("V4_REVIEW_GENERATION_BINDINGS_PATH"),
        generation_bindings_sha256=os.environ.get("V4_REVIEW_GENERATION_BINDINGS_SHA256"),
        intraday_root=os.environ.get("V4_INTRADAY_RESEARCH_ROOT"),
    ))
    app.include_router(
        create_research_router(
            store.root,
            # Legacy article/day/hourly GETs use the same explicit producer
            # binding as the decision-desk lane; selection/materialization
            # ownership stays on the V4 consumer root inside the router.
            research_read_root=resolved_research_root,
            wechat_archive_root=os.environ.get("V4_WECHAT_ARCHIVE_ROOT"),
            shared_data_root=os.environ.get("V4_A_SHARE_HISTORY_DATA_ROOT"),
        )
    )

    # Research is an owned V4 read-only slice.  Register the compatibility
    # routes unconditionally so a caller does not need the removed V3 module
    # roots or the legacy router signature.  Missing archives remain typed
    # NOT_MATERIALIZED responses from the owned stores.
    app.include_router(create_baimao_router(store.root))
    app.include_router(
        # Only the GET-only research decision-desk lane consumes the explicit
        # producer root.  The legacy-compatible research router above keeps
        # its V4 store root for any materialization/write owner.
        create_research_lane_router(
            resolved_research_root,
            shared_data_root=shared_data_root,
            morning_news_data_root=configured_morning_news_root,
            ledger_root=resolved_research_ledger,
            # US digest already writes the native data store.  Do not move the
            # independent research lane, morning news or external-news reader.
            us_market_data_root=store.root,
        )
    )

    # The new manager is the sole manager write owner in this application.
    from v4.manager_workbench.binding import api_config, assemble_api
    manager_config = api_config(
        manager_root=_resolve_manager_research_state_root(manager_research_state_root, data_root),
        shared_root=(os.environ.get("V4_MANAGER_SCREEN_AUTHORITY_ROOT")
                     or os.environ.get("V4_MANAGER_SECURITY_MASTER_ROOT") or shared_data_root),
        stage_root=configured_selection_root,
        us_root=store.root,
        relation_root=Path(__file__).resolve().parents[3],
        injected=manager_workbench_config,
    )
    assemble_api(app, config=manager_config)

    # Explicit bounded HKEX source capture reuses its original owner/store.
    # It does not assemble the removed manager router or ordinary model jobs.
    from v4.manager_research.hkex_runtime import assemble_hkex_announcements_api
    assemble_hkex_announcements_api(
        app, manager_root=manager_config.manager_root,
        security_master_root=(os.environ.get("V4_MANAGER_SECURITY_MASTER_ROOT") or manager_config.shared_root),
    )

    # Read-only user-authorized opening slice before all static catchalls.
    from apps.api.v4_api.research_panel_mount import register_opening_research
    register_opening_research(app, module_role="combined", selection_root=configured_selection_root)

    preview_root = Path(__file__).resolve().parents[2] / "web" / "preview"
    if preview_root.is_dir():
        app.mount("/preview", StaticFiles(directory=preview_root, html=True), name="preview")

    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if dist.is_dir():
        app.mount("/", _RevalidatingStaticFiles(directory=dist, html=True), name="web")

    from infrastructure.api_namespace import install_legacy_aliases
    install_legacy_aliases(app)

    return app
