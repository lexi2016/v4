from datetime import datetime
import hashlib
import importlib
import importlib.util
import inspect
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from apps.api.v35_api.baimao_router import create_baimao_router
from apps.api.v35_api.manager_research_router import create_manager_research_router
from apps.api.v35_api.manager_workbench_router import create_manager_workbench_router, ManagerWorkbenchResearchReader
from apps.api.v35_api.research_lane_router import create_research_lane_router
from apps.api.v35_api.runtime_router import create_runtime_router
from apps.api.v35_api.runtime_graph_router import create_runtime_graph_router
from apps.api.v35_api.review_router import create_review_router
from apps.api.v35_api.research_router import create_research_router
from contracts.stages import FROZEN_STAGE_IDS, STAGE_DEFINITIONS
from contracts.trading_safety import TRADING_SAFETY_FLAGS
from domains import preselection as preselection_domain
from domains.preselection import OPTIONAL_DAILY_POOL_IDS, date_catalog, preselection
from domains.stage_input_producer import ReadOnlyQuoteProvider, StageInputProducer
from domains.stages import StageRunner
from infrastructure.data_store import NativeDataStore
from infrastructure.futu_quote_provider import FutuQuoteProvider
from infrastructure.hkconnect_stage_replay_provider import HkConnectStageReplayProvider
from infrastructure.opening_second_filter_store import OpeningSecondFilterStore
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.review_store import ReviewStore
from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.stage_quote_provider import StageQuoteProvider
from infrastructure.stage_store import StageStore
from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider
from stage_center.consumer import StageSelectionConsumer


_MANAGER_RESEARCH_RUNTIME_PACKAGE = "_v4_manager_research_runtime"
_V35_STATE_ROOT = (
    Path.home()
    / "Library"
    / "Application Support"
    / "com.lexi.v35.local"
    / "state"
)
_CANONICAL_MANAGER_RESEARCH_STATE_ROOT = _V35_STATE_ROOT / "manager_auto_research"

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
_HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE = {
    ("20260924", "STAGE_1445_1500"): "d0c64a11d1b833ace8ae0a6105ea04e27d15bb2cf694f7dfdc08900f56213753",
    ("20260930", "STAGE_0930_0935"): "ca23560921e64600f616d1db1a69feb504e63d0ccdd578232babe5212c149cc4",
    ("20260930", "STAGE_0935_0940"): "522d6515dd35add084793c1f01d1c8bb1fd62b3d263e7d54359590549ef4db59",
    ("20260930", "STAGE_0940_0945"): "6cf31b1fdb49737a73e8a9657b94c6f1ff4de9b8f3c398eccb59e37db42b0194",
    ("20260930", "STAGE_0945_1030"): "3316c2abe88388e6faf59c314b2801a2fc8d93b11cbe68826303e18a13600a92",
    ("20260930", "STAGE_1300_1315"): "42ad12f2953b2cbae8fcc9594067af54b01e15a7af2134ecc761246c7ae656fe",
    ("20260930", "STAGE_1445_1500"): "2821b24a4be12d0aa199d1e8e60d8cc7a5a1367211e67cbb9c677da72b4a8888",
    ("20260930", "STAGE_1545_1555"): "6e63ea8d3ebf1839a53e3c738f494a6ba9d622447d6d86d6b2cfdda5fa2c33d8",
    ("20261005", "STAGE_0930_0935"): "e9318ba27b8fa90b2f0d03c0fa52f6171676ee88b4e42607ed8567740ceb572d",
    ("20261005", "STAGE_0935_0940"): "84ef7159af547b908f220c2f8dddeb226a61c2f882c504e0f79b9629e3857d86",
    ("20261005", "STAGE_0940_0945"): "843f65f610dff7be1c223d7e6a8ff4e6bb7d90b7a42f99c671946667b750c68b",
    ("20261005", "STAGE_0945_1030"): "cd50cd6c9492de8d5e0bc9893e1dc8639a4b05ffc4164f7818d935c354b158b8",
    ("20261005", "STAGE_1300_1315"): "c010adbfd20d70a8e742af04b19f819ac96edcfe8b936fd529f7a6d40e94e8c9",
    ("20261005", "STAGE_1445_1500"): "1665f1e3d7bc06efa1cfc88844e8ca777ed262aa11b6c1353cd35e0464f97ff1",
    ("20261005", "STAGE_1545_1555"): "d71ab63d6a1059b6ca23561c1c042a5c833c7f82fe64f74abefaca4ffc0f37e6",
}
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
    pool_path = _V35_STATE_ROOT / "data" / "preselection_pools" / trade_date / "hkconnect_d1_top100.json"
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
_MONTH_HK_AFTERFACT_R9_STAGE_ROWS = ({'artifact_id': 'selection-111be81b1cd3665353c0a946',
  'backfill_run_id': 'dd7ac56121134ac9a141b338cbf5f60a',
  'candidate_batch_receipt_sha256': 'ec5c4b0bb91816db5903c7a38107fcca821c50a75c6ee9668415f0331a1d3746',
  'candidate_manifest_sha256': '75e52082dca82bfb4af31f8d7d42297dd212cfe80903a7b90607084cd52ef247',
  'candidate_receipt_sha256': '27bdd5f7ba375f03a50fe4c2c44ee779cc54b44794bb09516a47ed0313268c14',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': 'dab9a0b34cf316e56ffd56b47274f27083b754d57fe736d125444910813392a3',
  'date': '20260907',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_empty_page_HK.02670=EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:4780d95c14af495448671b2ce97a0fcb2381cb785a5d67573e0ec55edf374cb0',
  'observed_rows': 99,
  'raw_artifact_sha256': '3ef4ee60d8dae9da27344dc3847ef86e2d3c4fa1f6d633d8332d95ff08e6a060',
  'requested_rows': 100,
  'runner_receipt_sha256': '679e76d8911b42e28aefcc1e1bee04bff699c324020be02d279965081ca80b9d',
  'selected_rows': 10,
  'selection_artifact_sha256': '03d0f727bc3166c3b47a9dade37e84ed0a4032e9f454a30496533d1361bb7df6',
  'selection_manifest_sha256': 'b6b88ccac0fcec409c020bf474a5d02d721ee7807284c79aa48c398d0d3cc1af',
  'selection_receipt_sha256': '8cf35acad4257c1ee09548d58e2a436abc38edec7c8c65607896f2903a2f6e76',
  'selection_run_id': 'run-111be81b1cd3665353c0a946',
  'source_evidence_sha256': '8b1528055df290917082299504b9a60635b656cfcbc03696556a170b173bfe9b',
  'source_page_set_sha256': '126b1c7bce535de0347e3c7c9a941209a7b20b944862f3c1de20da57e111dde6',
  'source_rows': 99,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-c596bb94daa8b98a83c70dc0',
  'backfill_run_id': '1450a6d112b54914afed23ffcda4273e',
  'candidate_batch_receipt_sha256': 'ec5c4b0bb91816db5903c7a38107fcca821c50a75c6ee9668415f0331a1d3746',
  'candidate_manifest_sha256': '8dc4a5da320938a6db83b73e10bb4f0c158f712e677176809fb3268379f5f1e0',
  'candidate_receipt_sha256': '03d6f923f7169858edd638b1e20c3ca10cca242978e1f9fb57790f13be127364',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': 'dab9a0b34cf316e56ffd56b47274f27083b754d57fe736d125444910813392a3',
  'date': '20260907',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_empty_page_HK.02670=EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:8eb63dfe5f165d60fae0482f28653d371d01b39864d288bb6f2759ca12657fd4',
  'observed_rows': 99,
  'raw_artifact_sha256': '504f2f5655ea1959bb6e326491f76494cd475aa5512e5f51da734009473ec109',
  'requested_rows': 100,
  'runner_receipt_sha256': '7d5b33e3478a5f4588dd1489a14820907cdea016141af172442421d6711d7ece',
  'selected_rows': 10,
  'selection_artifact_sha256': 'cbafffc288deeeec4a5bc83f1f1eaad0c36d7e1504ee23ac26fa4266145a1e98',
  'selection_manifest_sha256': 'af9c53876174ea59935b68d5d422b14e0741d70231e91fcdd7ebce5813c1cf7a',
  'selection_receipt_sha256': 'e40f8eef33ab4572c71c98d7383c44a41f788f0903934e3580b5f4f8daab10d4',
  'selection_run_id': 'run-c596bb94daa8b98a83c70dc0',
  'source_evidence_sha256': '17c53e089553a56443e5ba3e4783037efbc826ebc7424f232ddd3f94fbb7f612',
  'source_page_set_sha256': '126b1c7bce535de0347e3c7c9a941209a7b20b944862f3c1de20da57e111dde6',
  'source_rows': 99,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-01265386e61cab1366ae80c8',
  'backfill_run_id': 'f58f404cdc0e423f82852e19156888ce',
  'candidate_batch_receipt_sha256': 'ec5c4b0bb91816db5903c7a38107fcca821c50a75c6ee9668415f0331a1d3746',
  'candidate_manifest_sha256': '7a2018de7053ecd6c4fcb5027e3bab94d3adebde81ad5794443fe5de07118009',
  'candidate_receipt_sha256': '861d7697a2ad7e245759c9661d6c53eb2db169ac97e9b4dd63a9a9520c7fb603',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': 'dab9a0b34cf316e56ffd56b47274f27083b754d57fe736d125444910813392a3',
  'date': '20260907',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_empty_page_HK.02670=EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:97a13952cfa940bb187afece1c25956c0280fa862234f6dc7d37fe9cd5d809ff',
  'observed_rows': 99,
  'raw_artifact_sha256': '8fd5ebe1a4596a92012d12e1448f9f03eb022f36387b19c31f05dcdb4a353a42',
  'requested_rows': 100,
  'runner_receipt_sha256': 'ee9863ab7de7601e7f7088f679075874219ae1a7706e9bc58297534a636ec954',
  'selected_rows': 10,
  'selection_artifact_sha256': 'e5da2536b8204379486a8b9e22fb888f66b476c9c2adbf507f3e75962eb9b6b5',
  'selection_manifest_sha256': '542d4dea453bff21c82d3a5f29b787096356d5a6de779fec82e9f17e18ba60f3',
  'selection_receipt_sha256': 'e1333fc8df46143a74754a61468eaf696f19c4813bdbf8a58121aa2d52e1bbf4',
  'selection_run_id': 'run-01265386e61cab1366ae80c8',
  'source_evidence_sha256': '79228c309676d485c21111be8e531b871321e55a12114e1e8207e1b07669eb17',
  'source_page_set_sha256': '126b1c7bce535de0347e3c7c9a941209a7b20b944862f3c1de20da57e111dde6',
  'source_rows': 99,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-d53c3e513ddf3675dd11c2f7',
  'backfill_run_id': '67d508ab466443faa97a9b4a86c8c419',
  'candidate_batch_receipt_sha256': 'ec5c4b0bb91816db5903c7a38107fcca821c50a75c6ee9668415f0331a1d3746',
  'candidate_manifest_sha256': 'baa6b5d0b28726fd82d0ea94551d273922c34cd486bbb8c3db52f0047e159633',
  'candidate_receipt_sha256': '0a7dc148abb8907248e47ca85c90be1645a98ad2b9fbcb62a868a374f93bc260',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': 'dab9a0b34cf316e56ffd56b47274f27083b754d57fe736d125444910813392a3',
  'date': '20260907',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_empty_page_HK.02670=EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:2570a9cec8f2666c75c067dc8d83f54203adc7c24a4bb653bec78b351e9bcd24',
  'observed_rows': 99,
  'raw_artifact_sha256': 'e441a8ddede521d764067ba395a5953d3d6898c84f94fdb138554e1264f6ffb7',
  'requested_rows': 100,
  'runner_receipt_sha256': '3eb2f49d669cd25bdf5e48fb510ebc07deb86e587c0534193fca32d38aadcc91',
  'selected_rows': 10,
  'selection_artifact_sha256': '6852168ba6a1457a356e1e17ddc5e4a8c0538da77fd2ae2f70453b2314f4f24b',
  'selection_manifest_sha256': 'ec65bba2171d7afc52770d2801fe9232c6597b18bf8bff64656d63946e8175db',
  'selection_receipt_sha256': '533998eab91302c391986c35124ab5e4fdeeb8d1afb5396181f1a08162dfba32',
  'selection_run_id': 'run-d53c3e513ddf3675dd11c2f7',
  'source_evidence_sha256': 'b48912bc337414a0935bd31da6e00de670951a7d350a288e89ba1ac57b432ce4',
  'source_page_set_sha256': '126b1c7bce535de0347e3c7c9a941209a7b20b944862f3c1de20da57e111dde6',
  'source_rows': 99,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-fc5236e0385156b7e15066d6',
  'backfill_run_id': '8c00bbb1b899487998058b817c74b6d8',
  'candidate_batch_receipt_sha256': 'ec5c4b0bb91816db5903c7a38107fcca821c50a75c6ee9668415f0331a1d3746',
  'candidate_manifest_sha256': '15e01916ecee3e3d93c506cbc2b9dec2d6c32adb041004b5a1eb0c1690212273',
  'candidate_receipt_sha256': '39ca71074e9ea5adab2372b11f7d773c577fbc9e49d43cebb2c959ee460e0242',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': 'dab9a0b34cf316e56ffd56b47274f27083b754d57fe736d125444910813392a3',
  'date': '20260907',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_empty_page_HK.02670=EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:58d00e6cd0091b1fce34bbf801e264b4644bfc00bcb09b342d3684acce0c15cd',
  'observed_rows': 99,
  'raw_artifact_sha256': '321bded5ce51cc99a1dd7ffb19ea3585d8d6abfb52a8e8253333977b48f57fd7',
  'requested_rows': 100,
  'runner_receipt_sha256': '147d039594f65dc838a364bb2b79e06bb11f263861010e55dbf268308a06d158',
  'selected_rows': 10,
  'selection_artifact_sha256': 'f6523475a85aeb89af0e7c1d3e276fd53887fe742840473c76ebf0ea69504f22',
  'selection_manifest_sha256': '470a8f8167c7de94a778b277d412480026614a606f563a297af8c5abe8aae58e',
  'selection_receipt_sha256': '6210a76b0b152137ba6e8b962321f78eabc04fb9fdc7ff37b38942fdd6b1cfb7',
  'selection_run_id': 'run-fc5236e0385156b7e15066d6',
  'source_evidence_sha256': '5868ed226291789907d230aa5511c036ccfab8e4ba1b84ab4bfbcb0816878025',
  'source_page_set_sha256': '126b1c7bce535de0347e3c7c9a941209a7b20b944862f3c1de20da57e111dde6',
  'source_rows': 99,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-ed315f4c5e6284aad9a18f30',
  'backfill_run_id': '49bb15a60e5a45e5a6aada1a0a4febec',
  'candidate_batch_receipt_sha256': 'ec5c4b0bb91816db5903c7a38107fcca821c50a75c6ee9668415f0331a1d3746',
  'candidate_manifest_sha256': '069f4c8507c5a09f711ae9b0c427010a752c9178c59299a0075ea6a3295a8cb2',
  'candidate_receipt_sha256': 'cffb0fb3ee8ce19b59aaebbc96433f42c4b22625b4cf4fe25d4f66d2300dd18a',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': 'dab9a0b34cf316e56ffd56b47274f27083b754d57fe736d125444910813392a3',
  'date': '20260907',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_empty_page_HK.02670=EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:c83be0429a6ab909dba920b52a59ef360969165d0560284b2f623495877ddfd1',
  'observed_rows': 99,
  'raw_artifact_sha256': '2a8c4073c507dcae44704228846c67857ae4eaff75ceaa443c3e7090ea8ef1ff',
  'requested_rows': 100,
  'runner_receipt_sha256': '2be1cffd223f7c4fcb36d9af68bee08e9f05d2d1c7755153910b008dbe8a8bb7',
  'selected_rows': 10,
  'selection_artifact_sha256': 'f3884991d38f85bd54b5a6b957db481dfe939ce9e19582d5f5dd4c0f27e41155',
  'selection_manifest_sha256': '24fc2b87b922a7b76c479e5fc846e8b027ed384bc7d8574a43aafaa6688575cc',
  'selection_receipt_sha256': 'b134b8092750862eceb75b69d90da189a162155b40666e24dfad393ff8c2b617',
  'selection_run_id': 'run-ed315f4c5e6284aad9a18f30',
  'source_evidence_sha256': '742a254de5cb65ec485a042fbf42c7e98da5080f52a2a10b7e026e349093d09d',
  'source_page_set_sha256': '126b1c7bce535de0347e3c7c9a941209a7b20b944862f3c1de20da57e111dde6',
  'source_rows': 99,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-740790713fc66c3b0fc387a6',
  'backfill_run_id': '45abca82c8df4686a327f09e520e824d',
  'candidate_batch_receipt_sha256': 'ec5c4b0bb91816db5903c7a38107fcca821c50a75c6ee9668415f0331a1d3746',
  'candidate_manifest_sha256': 'b275be689ae351872b5803cddc70120e78f603235d365dc9ba5279740f83c2bd',
  'candidate_receipt_sha256': 'bad0ba20fd238347999371370e81e348850f1922edb4dec91f5ef93f0b5c5abb',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': 'dab9a0b34cf316e56ffd56b47274f27083b754d57fe736d125444910813392a3',
  'date': '20260907',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_empty_page_HK.02670=EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:529e93918c9cea51b1e51432c6e4643b8efad0927e6cdc06d1841028987a8709',
  'observed_rows': 99,
  'raw_artifact_sha256': 'fdd298f0a7c9ba831a445f00c36a219c6d3bed734d2878bfd90756aa9a936538',
  'requested_rows': 100,
  'runner_receipt_sha256': 'b920bd0592efe9e378ba14bc930d69a0e025617e4d0426a8a7a261a2354e8a5b',
  'selected_rows': 10,
  'selection_artifact_sha256': '495f52c6eedb70f9af7eb82b89fc7abb3aa7bdddaf025cdcfa6e3ae54755021f',
  'selection_manifest_sha256': 'c71b520e1a55020d4aec0028d5cf38ac7798907cffe6e3010626aaf53af534c7',
  'selection_receipt_sha256': '162c75c7ac99f70e49327221709d0e7042501d48878c295a926d1d65ff3e8775',
  'selection_run_id': 'run-740790713fc66c3b0fc387a6',
  'source_evidence_sha256': '98049b476dc6a6fbcf505f44bff74b74fd64b59110c4857edc0376ad15a74d34',
  'source_page_set_sha256': '126b1c7bce535de0347e3c7c9a941209a7b20b944862f3c1de20da57e111dde6',
  'source_rows': 99,
  'stage_id': 'STAGE_1545_1555'},
 {'artifact_id': 'selection-4d1c843b366ce24ecc6b0cde',
  'backfill_run_id': '2c7030b14f644cbdb89911411e804e2a',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'a5818bd83b3a1207887e63ce97c7ab5173513543a4ffbf398c2cf3e8b1d5b72f',
  'candidate_receipt_sha256': 'e818def0c5cb768d2af968b482056ce8c5008a62e8830c00195fd6062fa51d9a',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260908',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:45aa63712de835c35ae938a80784b9da602324ece7da27d92896d29490cc178a',
  'observed_rows': 99,
  'raw_artifact_sha256': '91dd8de445d5c738cde4142690daf97b895a957ded7a9a053cd1ac368847e87a',
  'requested_rows': 100,
  'runner_receipt_sha256': 'd7f7a5a49521528d9318e651e012ab4a9e9057378e9c5d0ecbbfc2b81605cbcf',
  'selected_rows': 10,
  'selection_artifact_sha256': '1572810d90371a3d31441d00a7144d1c3577ce8493e660591b83cfdd35d22bb4',
  'selection_manifest_sha256': 'ab2d053cd429f7b28f51e239b876481054e625ab3b043716bed87c22b9622b4e',
  'selection_receipt_sha256': 'a152517cfedc8175133e6fb1b5058ec0d77447711e58618933603093253da859',
  'selection_run_id': 'run-4d1c843b366ce24ecc6b0cde',
  'source_evidence_sha256': '67482d06eadc49409b8a36d65e7ad3048ef1d2f25b24dcbf7acc2210d049d0a5',
  'source_page_set_sha256': 'eba926f72e948d7fe34a29405137849a443bfa0ac5eedd422c00760b323b5201',
  'source_rows': 99,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-26190c6ee3919765038a3de2',
  'backfill_run_id': '2e301c570b1643a39cba3ec318404f63',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '1bd79b34387288815b49b4da3dd988c83724469b0e5ad3d702bcda9b144c01e4',
  'candidate_receipt_sha256': 'abb7246015d27f131ae45af2feb13194fd62e3d4e5c007c96ffed63b9d9b8494',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260908',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:68c7c7d161efe21a45dd7f72b6399e2b377e5629cd704532143567d2e5c85663',
  'observed_rows': 99,
  'raw_artifact_sha256': '9c7ed172b67661b0868c2276d1cf9282e43b52900d29a3f0ccd86e31253ac79c',
  'requested_rows': 100,
  'runner_receipt_sha256': 'afea9a6afba6f4ea88809609633e2432fd4b48648feaa6e06762256fcd6e45c9',
  'selected_rows': 10,
  'selection_artifact_sha256': 'ad6bfff2916673f7fc52a2c005e21bb081154f9f63c89d8e5c37bf66418331fe',
  'selection_manifest_sha256': 'c46c87088e5c34921c9c15139f735f724d1bdc457ec7c0a67a23bfddc7150d56',
  'selection_receipt_sha256': 'bc2b8560de9cc24f83e9a03e3df5c9fae384576db5cb199b3f2d749c3b7a878a',
  'selection_run_id': 'run-26190c6ee3919765038a3de2',
  'source_evidence_sha256': '74ed5302c9df12b8489cc72f99d70e12b6fd911e8d726a8f1e5c5a63e63f8e54',
  'source_page_set_sha256': 'eba926f72e948d7fe34a29405137849a443bfa0ac5eedd422c00760b323b5201',
  'source_rows': 99,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-fe716c77f4dd9e4fa43f86cc',
  'backfill_run_id': '4fefe4babbe6469992afafc0a2d30998',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '6ef6558442115a80b49c7f33bb97e4ba1248c4c6a2721c3c9e7f73d5a32f36ab',
  'candidate_receipt_sha256': '6116ee517e23d51e1f8c57401674e2ed7149e38e3ff194a8839b0c2b757b1037',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260908',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:b3013716b6ef7b43ec513e01d17f1e4b077e1488d5bda304a58c16aaef0afacf',
  'observed_rows': 99,
  'raw_artifact_sha256': '521630e2150fbe49ed9fb6986b86e579a680210b83417f04591b56789968a161',
  'requested_rows': 100,
  'runner_receipt_sha256': '996db5767d7d355411b539fa57f863f5a97990ac0382b601b613ed5c94b5c27a',
  'selected_rows': 10,
  'selection_artifact_sha256': '3454a2e8204cb555c82b0363c14661f5bddd3eef3e82afc55d49d99f03803ad3',
  'selection_manifest_sha256': '0b53d71c585ea5e5ccff6eeff766e68faad40e3257b3345fdf403f5af9789a9f',
  'selection_receipt_sha256': 'a40d75f8e9b263d83f939756038ace6623c4cb2540b45881dfd764af069d590f',
  'selection_run_id': 'run-fe716c77f4dd9e4fa43f86cc',
  'source_evidence_sha256': '3adc019d1645c61f12a9af5b06c7a0e925ce04e5e39184e54b6afae92c9d2ba8',
  'source_page_set_sha256': 'eba926f72e948d7fe34a29405137849a443bfa0ac5eedd422c00760b323b5201',
  'source_rows': 99,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-5452f8ef82a94165c8129e1b',
  'backfill_run_id': 'ea38f1d0382f4f5b8dcb40e0bb8f3bb3',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'bdf82286af0dd4f354a60996741f0ef51e6da604f9117e93215788e0b5180745',
  'candidate_receipt_sha256': 'fba06b2cbb24a71d455d26dbcb918eaef3d62cedd9aa93d93164d9b3da044c26',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260908',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:922164c96ed01d8fb989022874e99f42b8eb69cf95d4b46c6ee78a5f6291acc6',
  'observed_rows': 99,
  'raw_artifact_sha256': 'ebc4f1145ae2db109924d216e393483ea210fdd01fe97a4ea1a3efd20b4de6e0',
  'requested_rows': 100,
  'runner_receipt_sha256': '0b2e849bffbb7bc3ac3256d5855abff5178a01fb57e52fa287bd757bd072a3cb',
  'selected_rows': 10,
  'selection_artifact_sha256': 'ab92a8b60dc564a547663e8905de54ef0cdf7ccbad800a24b4e39cdda83a99a2',
  'selection_manifest_sha256': '4cc1d99e8dfe6e060a0f8fa1e2e7eaa8e73e924e7638a344371510097b178be9',
  'selection_receipt_sha256': 'd90b6db5e06f773589570a71dd45f60f26554d8205b825bc7f34c5bbc757fd92',
  'selection_run_id': 'run-5452f8ef82a94165c8129e1b',
  'source_evidence_sha256': '00b446ecf4e11e613d5954b5362ce35db7b82d9562dce9cf1a1d550f1bec146a',
  'source_page_set_sha256': 'eba926f72e948d7fe34a29405137849a443bfa0ac5eedd422c00760b323b5201',
  'source_rows': 99,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-b675674e00e5659c447ea7c2',
  'backfill_run_id': '17d78ebb37824f6dbda4ce8f0922ade4',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'bf646a7626d4664c9c70c2d65c1e59ab19edee915424785b847ae9703d8f619a',
  'candidate_receipt_sha256': '07b70200713775b68e1a067a4bccd09f9f4e2c6a67940af91bd6d8d243ac446c',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260908',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:67309f4030f8f2dd7a702e3d3b5bc0fab3020e07a86b98efb4700ac1b6503302',
  'observed_rows': 99,
  'raw_artifact_sha256': '9f16e249c2c274654dd11729a5a5386f70f1e9858389ce161ab1086fb9f83d5a',
  'requested_rows': 100,
  'runner_receipt_sha256': '88341e65f4c8580bded9f580f1be0a0f2c5a5a08c660c9ed112816489c2585a7',
  'selected_rows': 10,
  'selection_artifact_sha256': 'a6c7ec59c768801c35f1bcdbf6120d002a33722d5ecff1e58a1a68ee45464703',
  'selection_manifest_sha256': '8c7192cd7de52faf6efef6da8190d37ae8fcd131d5497860254a3b87a0926a8a',
  'selection_receipt_sha256': '3988c6b5ff6dfa2c3225634ebba65b305a5e80da97ea489d44f1652dae231050',
  'selection_run_id': 'run-b675674e00e5659c447ea7c2',
  'source_evidence_sha256': 'dff0b51a37385bd57e3a4e8f5fa87953230146e323736a1a54f343632c42d9be',
  'source_page_set_sha256': 'eba926f72e948d7fe34a29405137849a443bfa0ac5eedd422c00760b323b5201',
  'source_rows': 99,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-50636b5bddc37e4525aa2664',
  'backfill_run_id': '71ed6d73f4074c68aeeb21f9e3882034',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '88fbf08feb5558fd5847682c968e5430aa8888ba926a590daf1dcc25299764a2',
  'candidate_receipt_sha256': 'b8fb2c4bc9365737912d924cb008c5b48a6ce403064d53b63ef0e417f20b393b',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260908',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:2198607db9fcc3af49b1abdac2be6c4ad4917f0420e2e20c7e31ddef7a6013cc',
  'observed_rows': 99,
  'raw_artifact_sha256': '0a399dc825cf1fce215a7d37b6b6b63d5ae22ba3cb655e4d90875a694dd05caf',
  'requested_rows': 100,
  'runner_receipt_sha256': '7466746f195931fc1be6285b9f67eeaf6cd1f5e4a23a6dcd1903030a0efa4cce',
  'selected_rows': 10,
  'selection_artifact_sha256': 'cf5b434b922baf9cf0b94adb0a1ba7b9517ee30b80a496a1d5aa911e21ecf3a2',
  'selection_manifest_sha256': 'd7ad066e9ede3e629e58dca6065477fe91708a956ebc74bbc63020f6e046e4f5',
  'selection_receipt_sha256': '6efb1f3ab00d85d7af2a1719660122b047cdeee8f211c93f39297ac3a26a8ef7',
  'selection_run_id': 'run-50636b5bddc37e4525aa2664',
  'source_evidence_sha256': '692d8507686bea1e4a94a4a720ec2aa8da252590ebdd3b40db18e424032d57ed',
  'source_page_set_sha256': 'eba926f72e948d7fe34a29405137849a443bfa0ac5eedd422c00760b323b5201',
  'source_rows': 99,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-def67e085f51ff85c78377d4',
  'backfill_run_id': '86ecef6c3f314f93999440b53470269a',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'ffcf0ba76e1a5a4a3e3d006e69dd57a154b9c2536cdc4acf1526ba674a29062c',
  'candidate_receipt_sha256': '5bbbedb414dfb70bc720335907aa467b2bc97ecac72e7560055c3a8396d444c1',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260908',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:71f44dc60a892d5fff4837ce5980c8a6162651e5272fa682e9814d677fd2fa6d',
  'observed_rows': 99,
  'raw_artifact_sha256': 'd81fdfff83e197e00f4ddb2999b06c6a59aad39fac212234f08eac983159f718',
  'requested_rows': 100,
  'runner_receipt_sha256': '3f55d7384769bc43153514e4d4ec48a2126d9848aaade48789fb771a5f7845f0',
  'selected_rows': 10,
  'selection_artifact_sha256': '915abdaef1043025fe8330f657dc870663189eabbbb7accd5026295ea60e6b3b',
  'selection_manifest_sha256': '38c1915399f8acd98ae41c718cb7f0e2fb2c12e0ddec70dde8aed49e9f3a0f55',
  'selection_receipt_sha256': '40e68e4fdbcbae999866d45dd3b97d3594ff73ab91121d586890bfcf1e1c8cd5',
  'selection_run_id': 'run-def67e085f51ff85c78377d4',
  'source_evidence_sha256': 'bd52afa134055625ba25e0e07fcca66be0635509f45575321d7495f99c1c025c',
  'source_page_set_sha256': 'eba926f72e948d7fe34a29405137849a443bfa0ac5eedd422c00760b323b5201',
  'source_rows': 99,
  'stage_id': 'STAGE_1545_1555'},
 {'artifact_id': 'selection-8aa9f25630480192287cc631',
  'backfill_run_id': '568648fcfbc648c39d4de81772b4faf3',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '718124d74a7711cca616525762097d6b9959573c4831634b24fd7c01839068a4',
  'candidate_receipt_sha256': '41f47af9271b329fac86253e86af886aceee343fb096b27295d013e733112bf4',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260909',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:52949e38ce79b18760c74ef6d27a0ff1623e45d1d8952b012d8f01dd76ccf120',
  'observed_rows': 99,
  'raw_artifact_sha256': '00f6cba9ad85c51cb3241dfe1f55fb4932d99d3042ae5f90c144c734eb17cd30',
  'requested_rows': 100,
  'runner_receipt_sha256': 'b6a3774353e7a926b9b66bab580c653a8685c2688f3865fb4034cc6cb31063c9',
  'selected_rows': 10,
  'selection_artifact_sha256': 'f7356d0324ee8977954ae98f0e41de43567c17c3166d4e1829765eeaf61e1473',
  'selection_manifest_sha256': 'dfdd5741a671e1a4fddd890de5054898f2b46391b5128918da6cfcaba31fea0a',
  'selection_receipt_sha256': 'c5f6dde16aaa8c11d084e159a13aff952b7e83ed56d3e8cb5f7106e85b863d45',
  'selection_run_id': 'run-8aa9f25630480192287cc631',
  'source_evidence_sha256': 'dd8441f8763fe4397959c216fea25e91b3bc543796368f6890f93c7e5da61616',
  'source_page_set_sha256': '774f2737c6b97597fec1f7442318e3abfefdd0d70cc5a112baae5deb93279bc5',
  'source_rows': 99,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-7057f73dbd6ec0b247a2dc19',
  'backfill_run_id': '1ce601c492aa4c479c3b98647d4e5e3a',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '86c31c4b547eb47d4354958b3e7ec60cd059b224d544f852fbc05e0f3cfb814f',
  'candidate_receipt_sha256': '486f0449d45234a46c1d1cb018820d90347529f8010f8e1608fbc7fa44e298b1',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260909',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:91a14600f3e9903dabfebea3cd6f330da02ac18cbcb7e17f694b6d05e83cee81',
  'observed_rows': 99,
  'raw_artifact_sha256': '86b91c6d6d8011f0dd8d5b373b4ea7dfcb696e44ed1ceae71b190c88f45ddff8',
  'requested_rows': 100,
  'runner_receipt_sha256': 'e1958abd2c1e216f544ebbcb14704f0d59d6043366a2fbed90b0fc7c1abc3bfb',
  'selected_rows': 10,
  'selection_artifact_sha256': 'c234b4a25b335d7174697e377257e855bc0835a5d73fa92552f270a3f6d26e69',
  'selection_manifest_sha256': 'c4a2b9a17cdefd982a29e94248a5cc820386bf37874a5931a86ecfd3bfab761f',
  'selection_receipt_sha256': '09f741e8332293327825b05c56675f755bf1a97ec920745707dc3dfdaa4bd401',
  'selection_run_id': 'run-7057f73dbd6ec0b247a2dc19',
  'source_evidence_sha256': 'a936628b8dd7ef699656ca3db1b1eca674e3db4b98840127f5a3cc664a578442',
  'source_page_set_sha256': '774f2737c6b97597fec1f7442318e3abfefdd0d70cc5a112baae5deb93279bc5',
  'source_rows': 99,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-89925416830dd37e997f4132',
  'backfill_run_id': 'a8087ec724244b579c2b4cc3211312e6',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '6acb7617a4abd28a022e7103105b910d69f08fb790d505c6bfb8ffb0ba095ddf',
  'candidate_receipt_sha256': '75ce06ee8a12b8cbee4cc6d252e5373eff47b5396150bf588afa04a9079fab8e',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260909',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:c2b0c3bee3a525a87d3b02c105dbabc1c3689633dd17918590cf753b15cf6d21',
  'observed_rows': 99,
  'raw_artifact_sha256': 'dd67ff56ac62b76f363d2f530426b85fa56d9734964bbebea972e3d59ac01fe7',
  'requested_rows': 100,
  'runner_receipt_sha256': '4b0537e2a000dc3b2fd6fb57e3b7d1ce9c97a59f45f1c552007957f97610acff',
  'selected_rows': 10,
  'selection_artifact_sha256': '031b0731eefa11e9a7044de6c9a08a6240f6c8ae7662c7f6b80b9f22b9d1fc86',
  'selection_manifest_sha256': '27d9b1db880c8360cc5256f327e76be2c6ef25ca45a5ac891a0d205e61d1ea83',
  'selection_receipt_sha256': '3c3ca1b715db30e02c20a3309b11a918ecf4fcd9c4b05651e4e5a59ec30a52f5',
  'selection_run_id': 'run-89925416830dd37e997f4132',
  'source_evidence_sha256': '75e50203963a8e9ed7bfda6263747cc22bf6653bd1fd7574e0d653868db26800',
  'source_page_set_sha256': '774f2737c6b97597fec1f7442318e3abfefdd0d70cc5a112baae5deb93279bc5',
  'source_rows': 99,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-b341119728693004eb790297',
  'backfill_run_id': 'db44e3f439854cedbcddbb3116adf83a',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '259b22b45bc3aeb373473d0ba3477d0a4a99d84f3f2f13fa1f04d54830ed7ca3',
  'candidate_receipt_sha256': '5b62eadb1ec5f6d045d00f31e66608a2297b80d2e3a278cb8898f927b3dc1414',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260909',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:c666f73b3b1f836d4ed5b9395deff0b69b28d13a29362e2666c96406aa7e7103',
  'observed_rows': 99,
  'raw_artifact_sha256': '1904b880308576e1d89b799dcd252e8d4e30d13fbc2feae590c4042cf16347fd',
  'requested_rows': 100,
  'runner_receipt_sha256': '2d9f38c393c4a467a35f77941174a2b88aea9dfa0ef5da345527710a430873b7',
  'selected_rows': 10,
  'selection_artifact_sha256': 'f77f08cb74481f550d6f8f7d7dd8e10fa04dd276e4e0d7e66e99ffc8eb8d8b8c',
  'selection_manifest_sha256': '0814b8ab97eb03b29112d3720553722d3b2c63be2d5ce922e6f29d8b2420cef0',
  'selection_receipt_sha256': '3ce740ff55242ea2657794ba949b61c2a092bd843cc6d6510c515c6019b67aea',
  'selection_run_id': 'run-b341119728693004eb790297',
  'source_evidence_sha256': '7c5ea3e87a042d5b014ea80487c693af3c9d52e62a6ffc74205101333ece9c59',
  'source_page_set_sha256': '774f2737c6b97597fec1f7442318e3abfefdd0d70cc5a112baae5deb93279bc5',
  'source_rows': 99,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-f0c93afcfe931a081b71ff10',
  'backfill_run_id': '9cbe190258e340b7840fb0fe17eb58b1',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '262c71e5318d4f7396211870ef74ccf2c0ba67fe04ac089acc467a408b9d93a3',
  'candidate_receipt_sha256': '84f6fcfa51a0bfa11e0518cda645e234d2afa440279aff7e37b348479cecdc5c',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260909',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:3f511bc425046767a31187c3a7b47713a6c464fd14a3995c1870776891d217fe',
  'observed_rows': 99,
  'raw_artifact_sha256': 'f23370ae68dc5f5c791c4aeed3cff3770af354f476f61a45888ec73d779ebb10',
  'requested_rows': 100,
  'runner_receipt_sha256': '2a08cff0ebdfe75ac189421a473a7eb2bb2ff76c2a495b1a6ce5afa5eb67c9bf',
  'selected_rows': 10,
  'selection_artifact_sha256': 'aba1d89caa0ab5bc9911700e69126532637e233c9f7847d4b8b0f8a65d3845be',
  'selection_manifest_sha256': '81d8d306763ce7ae40b48bc4381cf8a2cb792ec1f2f0b559408ea90f4808f4c2',
  'selection_receipt_sha256': '32537097b9a36807d8f51e77206fe79f03a96c42a44ea8afc2acccfe5ecfc85f',
  'selection_run_id': 'run-f0c93afcfe931a081b71ff10',
  'source_evidence_sha256': '1b12f37f2c61383fa908b3e2ef6a343c1536d7e582f24662e6a9ed926fb6c66f',
  'source_page_set_sha256': '774f2737c6b97597fec1f7442318e3abfefdd0d70cc5a112baae5deb93279bc5',
  'source_rows': 99,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-aaa6f661ecbc4dd364851dae',
  'backfill_run_id': 'fadbae334e6742d2b32d25df6147c308',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '439981bc88f9b50aee191775900dff2fa33b2af24cb5d84e0c8bfabfb1ccf79b',
  'candidate_receipt_sha256': '2d00051cba11818da23a00545ecf7b8b7327fbba4d582d0ecab4bfb19b8429f5',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260909',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:6dddb6daa1e8077ff1c6a59355050070652b5330a010aa76681a733fda99c566',
  'observed_rows': 99,
  'raw_artifact_sha256': 'e9f9f35ab5ac6a5ad413fe1fcde8cb1ddfa06acc0a648f54a591e04bf660fa63',
  'requested_rows': 100,
  'runner_receipt_sha256': '775b607883c51eae70fb8ada066100d750b2a93ca92e7a8c072dabb4cd18a3ae',
  'selected_rows': 10,
  'selection_artifact_sha256': '63ac281476e32c12adf1dc1b68af86fc4e15e10d498a3fcc250db77c29b56fc3',
  'selection_manifest_sha256': 'e8d8e2aa43117dbc8f69697562444ecfb1e973d9f068bdf700b3a2c4806eacff',
  'selection_receipt_sha256': '527b2ca9807ad0b72cca083c50b791a8cca95baafea3e4023e58d4da48c6e00e',
  'selection_run_id': 'run-aaa6f661ecbc4dd364851dae',
  'source_evidence_sha256': '0aa6a5d938d1096e68da64554313269f46485d2831f5c9c9211df27bb14b9850',
  'source_page_set_sha256': '774f2737c6b97597fec1f7442318e3abfefdd0d70cc5a112baae5deb93279bc5',
  'source_rows': 99,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-720b9375b47ec593fdd93514',
  'backfill_run_id': 'd7b8efc695c44447b194211551d36121',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'd26e146ccbfb4980113c6c079c72fce3fddcf1d6b68702d7090bba612c5a92ff',
  'candidate_receipt_sha256': '4185f9f1131405fbb67ef21eb5fae3b2b9f3a60c591ea238e6dd2a5a4d053d20',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260909',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:dc8b1b7ee072c0e189162f50aed445bc42a7af9cd4a0b969ef12bc9d9089889c',
  'observed_rows': 99,
  'raw_artifact_sha256': '41145d1467adc41b9d74d5e3cdedef5008d23b7069a09acf253041e8250ee365',
  'requested_rows': 100,
  'runner_receipt_sha256': 'f4366c425f879e84bd156ab3bfc3dae11208ab05068dc2e44af18955b108ae5c',
  'selected_rows': 10,
  'selection_artifact_sha256': '05a6919382898ec4be6a3285bf903e9909556ccb179386f13dd3f4250a56fb3a',
  'selection_manifest_sha256': '8c1e079d6c2cf133843c61d3348e62d32c5a861a85092996d9ce6602890ca34b',
  'selection_receipt_sha256': 'b74658efc8366314e4e22b2a37c5f4a157a7a5d360775b2138b9581ab7e5e926',
  'selection_run_id': 'run-720b9375b47ec593fdd93514',
  'source_evidence_sha256': '8035bb543115b0e51e1d347705610608bf83e311c70f2323e825e7bb0e900dae',
  'source_page_set_sha256': '774f2737c6b97597fec1f7442318e3abfefdd0d70cc5a112baae5deb93279bc5',
  'source_rows': 99,
  'stage_id': 'STAGE_1545_1555'},
 {'artifact_id': 'selection-3ad02fd214dc1cb5eac0b7df',
  'backfill_run_id': '0e58f5eb966f477d8cbba0359abb8b5f',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '9ce69f26cde91aaceec09968bcbcdd0a79a2b7405043b7b742160fba623b7ae0',
  'candidate_receipt_sha256': '58dfcc9a3582934305056d52f64d411e7eac7711bacc633c178157124dacfc64',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260910',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:b8f82bffde4b053a46e40390af2c684b8da83df2870382a8ef2b7806d20ec3cb',
  'observed_rows': 99,
  'raw_artifact_sha256': 'ad41bf422e59a6d8ac6c6eb28ddae520d12927b7bc4e4c01813eb52dcdb1acdb',
  'requested_rows': 100,
  'runner_receipt_sha256': 'd043c76d034457692de12a5c46057226a721dc26072cc26a87b603a86c36e15c',
  'selected_rows': 10,
  'selection_artifact_sha256': '60715e5533bf1e16fe78a83f057923638003882cb77ce29e7a07df5673ae987e',
  'selection_manifest_sha256': '761f9e97a89c66415270b4e12165f7dc20bcf69e6409722638bf20143cb696ab',
  'selection_receipt_sha256': '58722da81c110e77decf1e26609611d8dad0751775f4ec27c4cc42711a0b9848',
  'selection_run_id': 'run-3ad02fd214dc1cb5eac0b7df',
  'source_evidence_sha256': '2e612413c87131770e0604fc2d702a51d5aceaba4890c1f80a0b0f809ebc30f1',
  'source_page_set_sha256': 'e7fb57d915eb0ad96467c736ba2ae92800ab9bcb26d3801b0188dccab7e805f1',
  'source_rows': 99,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-f37c40d4f9f0af0e2e4e282c',
  'backfill_run_id': '99ac28b20da3435f8264565392213d93',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '722f6d0e9e9c6b7fbabb7d65dccaf932ed32a5fc15fb13aa9bd49f5035f10a28',
  'candidate_receipt_sha256': '15184f6abfbfd5aca5d71090db30c84c0829db66145e93e7e7f68240a32d6132',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260910',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:293ce334108aa2a02702f3fbf4ec6f835c59abd6262b278fbbb2be9aacd19df4',
  'observed_rows': 99,
  'raw_artifact_sha256': '4aee8a383a7fbb07b44413a3a9e4e9eeed93471d4dcf89e91db058de3b38cc6a',
  'requested_rows': 100,
  'runner_receipt_sha256': '6778c102b1ba0ca5b8de1d7069f1f1f9cf6e4db89c00474128b9d84aa8bfab90',
  'selected_rows': 10,
  'selection_artifact_sha256': '29db3305eaca963f5d998a92593475ea32cdd5a066edea932a176226b7491d14',
  'selection_manifest_sha256': '0d3f0598c5879d3c36157e01d7860abc0880ef19b909b94d06768f126953e3f8',
  'selection_receipt_sha256': 'eba686fc19f157366e437ddbca592c576288fb4663d14d9e2feb4651ce61ad92',
  'selection_run_id': 'run-f37c40d4f9f0af0e2e4e282c',
  'source_evidence_sha256': 'd46d276f077b98dc888d3ad930cca9c2a77d43f1a74c5a83511175cde951339b',
  'source_page_set_sha256': 'e7fb57d915eb0ad96467c736ba2ae92800ab9bcb26d3801b0188dccab7e805f1',
  'source_rows': 99,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-8cdea90e53760ff3438c50cc',
  'backfill_run_id': 'a9909344522e46ac937370f21875cfe3',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '353f177fd99e0ad2011a92889ea927d7edcfeab089ab8bab8d15e578aaab1ccb',
  'candidate_receipt_sha256': 'be2db01fd80e31e9f3fc75bfc3c4d5a7e900cace0ca7a1727c893e2a4cfcc5dc',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260910',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:42a6779a6a8063ff191c6771cd78e70a0798649f54ce6aef85e8e9bb7a565c70',
  'observed_rows': 99,
  'raw_artifact_sha256': 'cf941aa8c6d791ef690d4e67d95460a4da6b25eb70f0026d4d882da27d5dec8c',
  'requested_rows': 100,
  'runner_receipt_sha256': '17efbc7a36aa1dad677ed64e849fdac43ff7844c535e8b4e1eb85c9b60ff993c',
  'selected_rows': 10,
  'selection_artifact_sha256': '7d0d50659d67a69f991fdbc93cf4fac841acb2202de64c19a325c3fd91494fe4',
  'selection_manifest_sha256': '32f34e08b18ed015a59dcad67b5bdfacefabeca3690a34ce8f61c2ee26b08498',
  'selection_receipt_sha256': 'e3529d1aae0fc5b641ffcf189032148ce09a22ac10fc37be2e27b677034a65e5',
  'selection_run_id': 'run-8cdea90e53760ff3438c50cc',
  'source_evidence_sha256': '468660e99565995b84a4e58104407a8f4eeb39fd8546c567766e69ccbaa87ab5',
  'source_page_set_sha256': 'e7fb57d915eb0ad96467c736ba2ae92800ab9bcb26d3801b0188dccab7e805f1',
  'source_rows': 99,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-4a08672d8b46a1306ed245ba',
  'backfill_run_id': '0f22000a61784399a963797bf9d132ec',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'a214a4bf09cf8b8a3b5dd49af9aeb3d60d422c6555805b05b46d8453b5fa34a8',
  'candidate_receipt_sha256': '48d54b500a65640d0738004e89ddb60dea8dbe8493342671e0d690c6652dad80',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260910',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:e7cf8a983c628c06d0df1bc2f4019ba8ce84b61b115133feb047d4bbcb36dae8',
  'observed_rows': 99,
  'raw_artifact_sha256': 'ab915d6b1227bc63604c2ddd399a909eb44ae93fea9ae83aa70e2766579076d9',
  'requested_rows': 100,
  'runner_receipt_sha256': '6146ff29b875625759183bd2aeddb04979452c511f7b37fd1ce69e62601da7ca',
  'selected_rows': 10,
  'selection_artifact_sha256': '640058e0870d6489fa3db6fa07855341bb41b543447bface4e60911ccf091fbd',
  'selection_manifest_sha256': '9413df1c6cc4156ea5fb35fe533e92bda9c2fdea882d5b4888472df7fceda7ee',
  'selection_receipt_sha256': '496dea48593b259206647cf1964c478c17378a31344c160ce02bf9a70a5801ff',
  'selection_run_id': 'run-4a08672d8b46a1306ed245ba',
  'source_evidence_sha256': '4bbeb583e994c96d16d96d78583113831d3e312de5a1605e1e7622a9eb82111d',
  'source_page_set_sha256': 'e7fb57d915eb0ad96467c736ba2ae92800ab9bcb26d3801b0188dccab7e805f1',
  'source_rows': 99,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-7de203d2669e21bf43b086a5',
  'backfill_run_id': '59d1ad49feb945cf9c2aab3f43f58a6c',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'a9b713aaa56ef685b650e0e4af0c08d67cfd8bce508fcb9c494a1969b7730830',
  'candidate_receipt_sha256': 'd65dd81af262173e8bfc99c4f7d325624c93a54eabcb8136d8b1f5220cc37afe',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260910',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:fa8bb656e8e4d9cf0dc4f95269d6d531fa213f62af61e68d3b13074b57189443',
  'observed_rows': 99,
  'raw_artifact_sha256': 'a4d3275be1b719af16c291538a027bbe893cc0f377c800771227db13f5a261a9',
  'requested_rows': 100,
  'runner_receipt_sha256': 'dd08c5e87d2a4cc610140d1223c9bf3de3a100e8fe194ef70802ea902b66ae14',
  'selected_rows': 10,
  'selection_artifact_sha256': 'bbb8a47a31dd26c7193804eee19a87a10205634e4b598f5e360f9709bf37a739',
  'selection_manifest_sha256': '5cbab81866a2c92d09fbf9a11b62a6be26487527a0bb97e759ecf0f748bd6236',
  'selection_receipt_sha256': 'a3f7df287f438ccf2664a83e399b2670453d8d1b47a761023631764af1205949',
  'selection_run_id': 'run-7de203d2669e21bf43b086a5',
  'source_evidence_sha256': 'a975215696dd91e7e9be81465b8c0e1c3812cc5588e7c8e14bd5e0d81c4a9711',
  'source_page_set_sha256': 'e7fb57d915eb0ad96467c736ba2ae92800ab9bcb26d3801b0188dccab7e805f1',
  'source_rows': 99,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-de807e516574c3c0f8a6084f',
  'backfill_run_id': 'c599452c28bf48a7b3bede0d795c2540',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'd1094330f959316014a0292ed5ff6b9f2dc51a75c9bac2ce3c58e896d80244d2',
  'candidate_receipt_sha256': 'c0fafea6472e2668a1897b8156351a96716ca1fc6ee6933b6dee749fb46deaba',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260910',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:cdc84e67d39e7e3865202bcb867762f306d041e6ddae8dcbdb5c3805cd3dcecc',
  'observed_rows': 99,
  'raw_artifact_sha256': '55d2fbbb5914027eaef303cd922fabcb798078ce96da7b7a1a189639d7d3cbbf',
  'requested_rows': 100,
  'runner_receipt_sha256': '10df00796cc7f9d28469138563e8d364eab6fca0cc1e8356e65b447cc210d69c',
  'selected_rows': 10,
  'selection_artifact_sha256': 'ea11427fde4ff3a3ed8f7ecdf1a4b7a9a9ecc4190cf30b5cacfcde388f705d8d',
  'selection_manifest_sha256': '31a03df8daa83bb7a7b0d621ee0be60d8ccd91a385a7ba51115736036fe601c1',
  'selection_receipt_sha256': 'f4b69ddb0a8d2875fa91be747abf81d773fd4d082b67000df95832dffb91c799',
  'selection_run_id': 'run-de807e516574c3c0f8a6084f',
  'source_evidence_sha256': 'cec2ece7e528358eaa1b4096d7c15ab184d68782e373a099b00e606fbd278b1c',
  'source_page_set_sha256': 'e7fb57d915eb0ad96467c736ba2ae92800ab9bcb26d3801b0188dccab7e805f1',
  'source_rows': 99,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-7612b5c779f33e159573caab',
  'backfill_run_id': 'addfb4b1e4ae42108d59098d3ea6b12b',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '5d813d536e9ffa624c62b4cdbf1efbfb6800dde7523129942f3c074a83b7ed72',
  'candidate_receipt_sha256': 'c557acfdaaaba138701bc278ea3d76cc387ed78b683f92452a17a74f3edf3fec',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260910',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:17c130f6c4540bcbb6b7652896e66029640e7fe1e5e1eeaa4b811f68488aeb5b',
  'observed_rows': 99,
  'raw_artifact_sha256': '5680af05efbe3ddcea7ffd348ae64f0ffecd4d6fbb6987145c1b9c71120893bc',
  'requested_rows': 100,
  'runner_receipt_sha256': 'e9c2d5666c767f97538566b718e85e70d24185a8070ab187d03e25ad70b8471f',
  'selected_rows': 10,
  'selection_artifact_sha256': '27d6e419a0fecaba48c35ad4091e0989257018f37ddf9a491892ad439d9831f8',
  'selection_manifest_sha256': 'd0330f8a17afa04b278c898111d9ec8c5d0253d4d456010370847b8608ce6794',
  'selection_receipt_sha256': '51e18892a80be39699f604265b96f0bb9d5edca176fdae3fce59136dc4dd672a',
  'selection_run_id': 'run-7612b5c779f33e159573caab',
  'source_evidence_sha256': 'd3fcaeb0e0ce6ad869627e2f23a202945e1a22608b996a3658e178cbad718c49',
  'source_page_set_sha256': 'e7fb57d915eb0ad96467c736ba2ae92800ab9bcb26d3801b0188dccab7e805f1',
  'source_rows': 99,
  'stage_id': 'STAGE_1545_1555'},
 {'artifact_id': 'selection-ce51a634bce9312c04935f08',
  'backfill_run_id': '90d5efc7a2d44d60a0b20a975b5ccfd1',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '6a2055a103a7085b33a971b7aadd60e13a6d185080a4efa2a5018ed27784ff48',
  'candidate_receipt_sha256': '4e4d345c835fa1c40634df75fec09990218f3d13190cfae0c2f725e74d594df7',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260911',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:f09cd4e50d801cf3f8020bf0150bf8b506b106baf6d27404142163ca143c55a4',
  'observed_rows': 99,
  'raw_artifact_sha256': 'e6da3ed6437ee2ef66a8a561c32223a1c73340ea28d82a0cea0d2e1abb8db4be',
  'requested_rows': 100,
  'runner_receipt_sha256': 'c4cd4ae14e68dc2fed4b08192c7c84ef5ecda5b11e8f8c50f7932061c46f6833',
  'selected_rows': 10,
  'selection_artifact_sha256': 'b4445a48c3e83823255877fc83583c2b40fd6c537a2d706413624935876ffa68',
  'selection_manifest_sha256': '6eb5b5817ea21e96fd320eeff2dcfde467e17f677687d1be08a8ad3ea348630e',
  'selection_receipt_sha256': 'da46f90a8625b94abe087c08dd81a792d52b9e75eca2164fdbfde92eedab90d8',
  'selection_run_id': 'run-ce51a634bce9312c04935f08',
  'source_evidence_sha256': '82e5d78c3ee871d9779d772a81ac3335dd4de329c930ed8bb3d3d26aa4cb690e',
  'source_page_set_sha256': '64c7af261b4c8aa52d0af27be24a012e2496e2df225fd4f7bca1eef91a98da38',
  'source_rows': 99,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-2c8b8087318145cfbdc54186',
  'backfill_run_id': '9afd609353e04b0589f545e55ce7562b',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '00a873e045db2690dabfc8e9619cf7d3fc6379e767ecfe5cc918449ea6120256',
  'candidate_receipt_sha256': '0bcc08e7b15b9dea673f6864eddbeb7c900b387ee1d0aa04c6721c1a7f27fc92',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260911',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:73d4acfa88316b4bdadc14aa60c45788ad56a3fb7eebcec54bab99f63570f4cd',
  'observed_rows': 99,
  'raw_artifact_sha256': 'ccf656815bb95d2062ee29f9e43f7deadbbca8311d99d492810adac08b21703e',
  'requested_rows': 100,
  'runner_receipt_sha256': '716b029fe6c08817aef08a0657343755c801b7f02753afd55704ca0147db8499',
  'selected_rows': 10,
  'selection_artifact_sha256': '62d0d1b89075ef16fe8bce0941fce30c135f302f772736bfdf5babc67b39523b',
  'selection_manifest_sha256': '6b1159776debef0077a4c62264e8194874561eb340f54e1be95f49e63ad34eed',
  'selection_receipt_sha256': 'a2a4dd682a0e6899b53abf4032c7fcd9b5a67bd3ddfcf2cb8c819536d47eae38',
  'selection_run_id': 'run-2c8b8087318145cfbdc54186',
  'source_evidence_sha256': 'e388195a252e2013430e4f9d587a3a26c5ffd0ee9f94bb303ed113c77878ff38',
  'source_page_set_sha256': '64c7af261b4c8aa52d0af27be24a012e2496e2df225fd4f7bca1eef91a98da38',
  'source_rows': 99,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-94a9ef2a8e02603df7a281b7',
  'backfill_run_id': '5875477b814f4ac09ed345c15b4bedf7',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'fc9a2f304a01e2c2b866047334836b6fcc3ecb1427d521c27a03f0d39bdb8085',
  'candidate_receipt_sha256': '0bb1f6acd875b87b37412f33b55e9e1962784dc01ce2329a6646d3a1ff4e5de5',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260911',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:b2def258726d322000afb1e0da1abe467fa85f49c9e0eed349581fb2474f6d0d',
  'observed_rows': 99,
  'raw_artifact_sha256': '06a987e0373468c46a1d0564b3849c1f744bbc1f835bf3f61a5eda901a2a64a8',
  'requested_rows': 100,
  'runner_receipt_sha256': 'b49b88b7feaa7193159562311077db28fe79ca0573a1e0871d81948b1cedf828',
  'selected_rows': 10,
  'selection_artifact_sha256': 'f42bb46366ec7d1b5b050f08373b501ac701bee1d26c2d126a17d4576feb44e6',
  'selection_manifest_sha256': '9d0ce945c740f1100961f33a0a47afc2b6f2a6452cdac5177835ad38ddd3e169',
  'selection_receipt_sha256': '9a1212326f0663063031e407106511a5bfb559120312c14af6aa1c79a8bb3843',
  'selection_run_id': 'run-94a9ef2a8e02603df7a281b7',
  'source_evidence_sha256': 'dfe47419089b101ec856d12bba6f3a985d957780a880466d1ccff84f585d232d',
  'source_page_set_sha256': '64c7af261b4c8aa52d0af27be24a012e2496e2df225fd4f7bca1eef91a98da38',
  'source_rows': 99,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-4974512e8bc511f1bdeb8147',
  'backfill_run_id': '4d878634a6804dd9a02779694103d93f',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '44327a5b5032da7788515962b1a4483855becf6629e4d6ea12af2de17ddbca08',
  'candidate_receipt_sha256': '8196c25f8878c850f1906d58033f8e18474a431a515e6a52934b400dae8aa569',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260911',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:5b645800158d48500b58cac3451631949f7e8442b3fa33ff269a12bdf2cf781e',
  'observed_rows': 99,
  'raw_artifact_sha256': '8bf953438ac0dc4fde15a442fb035d382cfe9f7d798804caf92d028ac0fc5389',
  'requested_rows': 100,
  'runner_receipt_sha256': 'e03d5e8ff87cfe363bb8114f40abeac5fb3114f4df29a9a78418ab844910d8bb',
  'selected_rows': 10,
  'selection_artifact_sha256': '3205979c3e5d561e51d0d78e89f4a24bf334b6028c0de9b4eb3f3963f744eb3f',
  'selection_manifest_sha256': 'd1a3851c9280afa1c9e1ff99d57a30517a5b7d6751a5f67dad9da75a417f03ff',
  'selection_receipt_sha256': '5501f96c1daf3d68477af7213219ba07dae8fa07453dc8da8b169499bad5bb85',
  'selection_run_id': 'run-4974512e8bc511f1bdeb8147',
  'source_evidence_sha256': '38cbcdbd801a614dee21e5b1b18ba10c02d43b0614fa15ce4ca54782ae370ec5',
  'source_page_set_sha256': '64c7af261b4c8aa52d0af27be24a012e2496e2df225fd4f7bca1eef91a98da38',
  'source_rows': 99,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-ec8fb1893d22e56b1559a4be',
  'backfill_run_id': 'bee7a0da4bc941ecb865ccf8a4118087',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '942cd7e501182f66ee925a42924fd3e318c7a597e97a3a2fd1a2cb1bb2484c9b',
  'candidate_receipt_sha256': '0b097b58f2ab0c98af70d8e813418744fde3008f9401eb5f8aba7f964de714db',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260911',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:b327fb946743108a98ba97896837a7b8f02e6ec21358c95562b27e4abdf23059',
  'observed_rows': 99,
  'raw_artifact_sha256': '1a541a344664f7473b8db74179c17d880013563d3acc44c0641e5b1dea5367a0',
  'requested_rows': 100,
  'runner_receipt_sha256': '8d8c4bda71bfc1674997cf4b1ef37fb5d0cb598098bc749e61e0b931ec19da20',
  'selected_rows': 10,
  'selection_artifact_sha256': '36002389cd53c35b9df5155ea3c2d34f5d27ce06e752b14cf3a474c824194479',
  'selection_manifest_sha256': '90397160e28e2d965bbf11a255857ae4813f658586139d1d86132db6f6fcd86b',
  'selection_receipt_sha256': '1cc9f43663bf3879ef7013736361c971442fc86f51f515f2bb2e6f7ff8309191',
  'selection_run_id': 'run-ec8fb1893d22e56b1559a4be',
  'source_evidence_sha256': 'a4954e5913205508cd7e0a040bb9d7fcf71c742dfcac40464f03f3c1c7e10eb6',
  'source_page_set_sha256': '64c7af261b4c8aa52d0af27be24a012e2496e2df225fd4f7bca1eef91a98da38',
  'source_rows': 99,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-d401ac4921667af61a2cd740',
  'backfill_run_id': '67fa8ebdec4b4521bc1f38cbc1008308',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '4ccdd5e80ad414145aa21a22e658dd8ed72c8729e493201e0bbceb22a2a9d881',
  'candidate_receipt_sha256': 'a05eab26bb59ad319b7f16c63b1984b7a79fe69d9e210090329d4372cbafc900',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260911',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:ea76fb1161a9dc4d2874721e65d2ebf5eda09593f6ebf0528c790e2657553e5e',
  'observed_rows': 99,
  'raw_artifact_sha256': 'beff5cbd0dcc75a0c687492cfa6252538fe0c3cb580a9426bd4c98f89838744f',
  'requested_rows': 100,
  'runner_receipt_sha256': '38e08024001a7bbd98803d1e4b20a8192f27293054c6e1a194fb036281a5ffff',
  'selected_rows': 10,
  'selection_artifact_sha256': '1638955b6caa5cf2743dff1a27b4351d8875bb2b5f73f066dfb01bed7756a1ea',
  'selection_manifest_sha256': '902e84a5879fe0a3640205cb42b468ee181d798b903760c9d782219622b028ab',
  'selection_receipt_sha256': '90b65f04077b43b4a8f270064756c18af9ca118bd8c38662615bacde411a0edc',
  'selection_run_id': 'run-d401ac4921667af61a2cd740',
  'source_evidence_sha256': '30383ac2078e3e8823e24450f0515eebc9f3214368ece17dda3511080032caac',
  'source_page_set_sha256': '64c7af261b4c8aa52d0af27be24a012e2496e2df225fd4f7bca1eef91a98da38',
  'source_rows': 99,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-8b4f1bd4ae487ccfd29faa41',
  'backfill_run_id': '0873c6c07fa34822ba40bea5921e68bf',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '33e5d4aba6d9156589f8419b54f8ecefb4d6de3c0ee3b6e33c46b2f54e1c35fa',
  'candidate_receipt_sha256': 'fa67b0ec4741ced4ca20d03c3a531e7cfa5da18bc76ca396c2034b5264dd3d10',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260911',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:b007899378966ae9f291ab3bdb4ed6cc49819c560509586718e060855f7c81b3',
  'observed_rows': 99,
  'raw_artifact_sha256': 'b9e14df07d9806341d05da68ec82213126fc341142c1ed9a563f5ecfcbb1d15e',
  'requested_rows': 100,
  'runner_receipt_sha256': 'ae62ce6e59789b65a80dd53a990f3dde155f0df5ff057f7e3b0ea75218ea6cae',
  'selected_rows': 10,
  'selection_artifact_sha256': '5225821649e4fcd7bf5e260166b9ed2c0c1450645454f1731b07c49546ab5c4e',
  'selection_manifest_sha256': '24a3f6166fe678daba83a0c7b6426fa25b94ecd84ec412770787fc928b5f147e',
  'selection_receipt_sha256': '3dfbee2dfa2563bbd9302a117e12fe56b4b933898d108a5993f887c2e77e3327',
  'selection_run_id': 'run-8b4f1bd4ae487ccfd29faa41',
  'source_evidence_sha256': 'de9272c3760dbf946db7c6f61e71a42a9132344bd659bc389019ddd24819a02f',
  'source_page_set_sha256': '64c7af261b4c8aa52d0af27be24a012e2496e2df225fd4f7bca1eef91a98da38',
  'source_rows': 99,
  'stage_id': 'STAGE_1545_1555'},
 {'artifact_id': 'selection-80eb7c918abf41a1e78eb980',
  'backfill_run_id': '447186d2e9604badb62b3203ec086615',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'caa9e8159db20dd2ad14587c25dc82a7bc45f6904abf9544899ace7d5fb7f77c',
  'candidate_receipt_sha256': '93721ce2ff56106575ed9808a769d486622d81ac7dc9190334d7d9029495c43f',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260914',
  'missing_codes': ('HK.01196', 'HK.02670'),
  'missing_evidence_markers': ('historical_capture_missing_HK.01196=TARGET_STAGE_MINUTE_ROWS_MISSING',
                               'historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'),
  'missing_reason_by_code': {'HK.01196': 'TARGET_STAGE_MINUTE_ROWS_MISSING',
                             'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 2,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:49201209e80339656947f24e046e2d775d52cb4d6e6939064f30a142c1d678fa',
  'observed_rows': 98,
  'raw_artifact_sha256': 'd42ade7e2ab12f9604b9fb4b71d99c8a9b22ff01f3a300005d031579d5c98d5e',
  'requested_rows': 100,
  'runner_receipt_sha256': 'eabb80ae903a899de4de9ab9f42d367ff0566fe45509129a4481a8728ad30e8a',
  'selected_rows': 10,
  'selection_artifact_sha256': '91028f7ac56a877df83dd7efeb86df6cff5cdfc945371f1cdfad4c8e36522c7a',
  'selection_manifest_sha256': '42a31442d2dc5c8300f9aa22858991e17e50c1beb33475e2604d0e18c95ca808',
  'selection_receipt_sha256': '632f90588c205cb96ea66d69cb70d06b826e5fae80e41152eb597b461e71029f',
  'selection_run_id': 'run-80eb7c918abf41a1e78eb980',
  'source_evidence_sha256': '871dc4642696a1ea54046f4e8894e42e8e0ed07ebed3a90d30d010f01eed9d24',
  'source_page_set_sha256': '3783f559f01dab5ccc2c6a88d7e5c3b00ae1d831720749f2a28c64ebac6d6fb9',
  'source_rows': 98,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-5d3e2a4f52f1f80d6df94361',
  'backfill_run_id': '64505b6333da43378d3d14211607f825',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '22446c2eef556ffff76846a669cac6b8d897881f7b27888752e471311c8f304c',
  'candidate_receipt_sha256': 'fa34c29ec823747e1cb58c00ef2f104a16dddd806a18654d63ab7992a54bd3e4',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260914',
  'missing_codes': ('HK.01196', 'HK.02670'),
  'missing_evidence_markers': ('historical_capture_missing_HK.01196=TARGET_STAGE_MINUTE_ROWS_MISSING',
                               'historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'),
  'missing_reason_by_code': {'HK.01196': 'TARGET_STAGE_MINUTE_ROWS_MISSING',
                             'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 2,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:f03f04a1683577197e9f07551f7b9acd92817f59e4b03d5698178f442e18f2e0',
  'observed_rows': 98,
  'raw_artifact_sha256': '0db3f77f7ef8b9c89dfecfbe50883a97e532ef73c6229cc5537ed2ee8a33c23a',
  'requested_rows': 100,
  'runner_receipt_sha256': '614c79e04bd3118a0293a8e0af956b12c1833669cf1393f6c2d302daa62681ad',
  'selected_rows': 10,
  'selection_artifact_sha256': 'c46e95430986d9bc95989734db28aafc12ce755a04dc9f8d9e52b6d3925ffe1e',
  'selection_manifest_sha256': '435ccf6e0002341f35326ccdcff39a01b8c796a4cea607a889e53b5db9d2adb5',
  'selection_receipt_sha256': '232a308f0abf1ffd05b6e368b9e46020209e68347ed33930d933a5ac1b239f46',
  'selection_run_id': 'run-5d3e2a4f52f1f80d6df94361',
  'source_evidence_sha256': '11f9a5c255a2d1fa1eaf43132476ee41a795a02419d300f661f26c1459551250',
  'source_page_set_sha256': '3783f559f01dab5ccc2c6a88d7e5c3b00ae1d831720749f2a28c64ebac6d6fb9',
  'source_rows': 98,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-3057585b1835e7390f5a0e1a',
  'backfill_run_id': '2b42385ef9e443cdb167937a6c3b4f3d',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '593a8acf0a82cad9063e16bcd994e7f32d5350cb2db440fea2f4d021e54f0680',
  'candidate_receipt_sha256': '5c9b18777481f31b39658d1f8dcbb3718cb06cb45aec7cf2c19b9cdb7f8992e9',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260914',
  'missing_codes': ('HK.01196', 'HK.02670'),
  'missing_evidence_markers': ('historical_capture_missing_HK.01196=TARGET_STAGE_MINUTE_ROWS_MISSING',
                               'historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'),
  'missing_reason_by_code': {'HK.01196': 'TARGET_STAGE_MINUTE_ROWS_MISSING',
                             'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 2,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:66d95835aa26c0e864aa3de4e775fe13d822de60cca77e7cc3765ddf992c09fd',
  'observed_rows': 98,
  'raw_artifact_sha256': '2913a8de9d6f60987dfc6ef3ba4e364ee833208e9835c0471238473b92c83da8',
  'requested_rows': 100,
  'runner_receipt_sha256': 'cc574393eecf2f1b9e967bc8e350b27d4c99cfc09fe4db2c0e3ecc2bea37eb1f',
  'selected_rows': 10,
  'selection_artifact_sha256': 'd831f07c301f59459e1e8696523f58f5c2e29fb71995e58af41f4b4c9393b771',
  'selection_manifest_sha256': '66e6f0828722fde343830b7362b6f2df9303ac37a33f5e1dbe62955bbb34582f',
  'selection_receipt_sha256': '7558838360d4f95c0ebc3b327bd20657688ec2ae18c9be11f75e020955dab8a9',
  'selection_run_id': 'run-3057585b1835e7390f5a0e1a',
  'source_evidence_sha256': '1fd7bc5522610e2827694abc985e1227097d9b45ed38e07296e27948756c33b4',
  'source_page_set_sha256': '3783f559f01dab5ccc2c6a88d7e5c3b00ae1d831720749f2a28c64ebac6d6fb9',
  'source_rows': 98,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-9dc64d64d57149ff7e12fe8e',
  'backfill_run_id': 'f86a03d722144055803d8530c764ed6a',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '65795f750167383b57de1fcd6033f97a437b776145c2169586504133d87b37ea',
  'candidate_receipt_sha256': 'c5e8987568c2a237e96a2fe7026bfd2dae8b20cd184c38531b76c11baa7492cc',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260914',
  'missing_codes': ('HK.01196', 'HK.02670'),
  'missing_evidence_markers': ('historical_capture_missing_HK.01196=TARGET_STAGE_MINUTE_ROWS_MISSING',
                               'historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'),
  'missing_reason_by_code': {'HK.01196': 'TARGET_STAGE_MINUTE_ROWS_MISSING',
                             'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 2,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:6facff3d7cd3bd06a17cba911311d833a7e6c85979acf1841c03dd8b38087534',
  'observed_rows': 98,
  'raw_artifact_sha256': '2f48dec592cf826e974fcc89f0b69c16ef8525748c333e4695b421e28214721d',
  'requested_rows': 100,
  'runner_receipt_sha256': '35379d54dcc16bb4121fb1757b096d1bef5357b870b5df8b93e95ebd0c443b29',
  'selected_rows': 10,
  'selection_artifact_sha256': '539072ba5e464b184464a854a459a50ff14ef2c1e155ab2eb2ed8426e548d99e',
  'selection_manifest_sha256': 'f10f29acc4c73c3a5ab88b780017f78a9645d67a86c5cef23146ea5f884ff497',
  'selection_receipt_sha256': '369f5afa30583f274eb14f5a72fa456f0bba2d8ed4bc9ac3f0c4c5f58254d771',
  'selection_run_id': 'run-9dc64d64d57149ff7e12fe8e',
  'source_evidence_sha256': 'cac456dbeca46fca157551803a112564cefc50c6bca500cdf4acdc8b404a0308',
  'source_page_set_sha256': '3783f559f01dab5ccc2c6a88d7e5c3b00ae1d831720749f2a28c64ebac6d6fb9',
  'source_rows': 98,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-885ba2189fcd5db08c9b1322',
  'backfill_run_id': 'be324b1ed29d4f1ca6a7fdd893808dd2',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '36c0fd5a08c0f626f80e05da2ef0557f358f1151e7c630c9801a1cac38c0f85c',
  'candidate_receipt_sha256': '4d8f1fc7772310b70f10a155afa607bab709e0b2b7341d0413f52674d77b429f',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260914',
  'missing_codes': ('HK.01196', 'HK.02670'),
  'missing_evidence_markers': ('historical_capture_missing_HK.01196=TARGET_STAGE_MINUTE_ROWS_MISSING',
                               'historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'),
  'missing_reason_by_code': {'HK.01196': 'TARGET_STAGE_MINUTE_ROWS_MISSING',
                             'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 2,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:9a677dfec764dd318425bdc0d278c5158885fe8b7a8713e5589b52274d219de9',
  'observed_rows': 98,
  'raw_artifact_sha256': 'ec2292f5e389577f328b06f36519a7119555e91b1ba275a4b6a95a0ff9bf75a0',
  'requested_rows': 100,
  'runner_receipt_sha256': 'f0991f1aa3d6df826f639c55c72371658f4d9a2cc038b57c026527b57f5315e9',
  'selected_rows': 10,
  'selection_artifact_sha256': '0d5222a5709b95585f4c79b12ee965667f9c20ff0fec923703932d92d7fc407e',
  'selection_manifest_sha256': '88927cb37f7f324a6fbaff0b72205fc7ad4e1c1bdc8c8c7975dad1a74737f963',
  'selection_receipt_sha256': 'dfe840020b85f8b9feb636de79346c19fa6cb6f13387cdad525aecf6b556ad90',
  'selection_run_id': 'run-885ba2189fcd5db08c9b1322',
  'source_evidence_sha256': '49bf6fff4fc015640958f3a6b8545c65d120089b0d617179a8a8fc43a72c3d6a',
  'source_page_set_sha256': '3783f559f01dab5ccc2c6a88d7e5c3b00ae1d831720749f2a28c64ebac6d6fb9',
  'source_rows': 98,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-984fc4f4acfd19c81081cc0f',
  'backfill_run_id': '9b9fba7fc4c94bd898e469bd0e8dadd7',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'eccfc232f40330f273c5e24f7a272c53021b26b633ea3bdbfed85a3b5186b432',
  'candidate_receipt_sha256': '90ce014e7a59f426a4603a1976402abe15a1d1e080e78f46730a5dcb4fae6ede',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260914',
  'missing_codes': ('HK.01196', 'HK.02670'),
  'missing_evidence_markers': ('historical_capture_missing_HK.01196=TARGET_STAGE_MINUTE_ROWS_MISSING',
                               'historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'),
  'missing_reason_by_code': {'HK.01196': 'TARGET_STAGE_MINUTE_ROWS_MISSING',
                             'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 2,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:5fa87623ea1ca460fd58796c030093bb12cffdb8ca93b81f8fb9fa97caed74cd',
  'observed_rows': 98,
  'raw_artifact_sha256': '23e4f34467d522cbb6251761a027b1020b7209e64250547d4480b1c59dddc5ed',
  'requested_rows': 100,
  'runner_receipt_sha256': '8ad660e061b844f08636be226aa013b6abd435dca7e213d493406d2ab152139d',
  'selected_rows': 10,
  'selection_artifact_sha256': '6d49aeb536b30d7a643623551e8171ea44de5f53aa7169d0e7b149a22dac022c',
  'selection_manifest_sha256': '94f3d157e556a0f2425232926ca587595d8e27afb1bcb54a875ddadfeebbbfcd',
  'selection_receipt_sha256': '5de07b1eeed3a895f3f6998f83bd82b88186a26ba03f0a0483c7b75a30e7460d',
  'selection_run_id': 'run-984fc4f4acfd19c81081cc0f',
  'source_evidence_sha256': '545839c243c567925067e0c7d7e0edb1def52a5ca33188ca87c07cf377f0d85d',
  'source_page_set_sha256': '3783f559f01dab5ccc2c6a88d7e5c3b00ae1d831720749f2a28c64ebac6d6fb9',
  'source_rows': 98,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-b38bc954cf8b47b594485b4a',
  'backfill_run_id': 'ab83198f8c12420a85f05a8569b9ad94',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '991fe378a465b55b68b7a9ea0a9f69e44de89c9f85ac2b4ca879582bbdde737b',
  'candidate_receipt_sha256': '4184b8adb98d882ff92976d779c6e126d818f064210056e3bff121f1d71165d7',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260914',
  'missing_codes': ('HK.01196', 'HK.02670'),
  'missing_evidence_markers': ('historical_capture_missing_HK.01196=TARGET_STAGE_MINUTE_ROWS_MISSING',
                               'historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'),
  'missing_reason_by_code': {'HK.01196': 'TARGET_STAGE_MINUTE_ROWS_MISSING',
                             'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 2,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:edc53a7b0ca677ab48c875998bcb2a86ed5c443f9b39984050b0dfb10fac55c7',
  'observed_rows': 98,
  'raw_artifact_sha256': 'ee82c819fd446454071ff766454dae67986efbecdac044c34270ab897ff0c21c',
  'requested_rows': 100,
  'runner_receipt_sha256': 'a5bfd4389bc3ad5a8bb40e46c9c6dcbc734b8a15d6a64cf66ad7636ecb60f582',
  'selected_rows': 10,
  'selection_artifact_sha256': 'b6710094e809961d94153954bdc474a709f6837c258651d2a908e10dd2b4737f',
  'selection_manifest_sha256': 'ced9b42daf03ae7d758b9330bff5c189e99d55d621de8399828ebcdd2a7f550a',
  'selection_receipt_sha256': 'ea7715a2a2e9595b93979714dcfe3e6ffd4d0478026ea7cba489c979b836632d',
  'selection_run_id': 'run-b38bc954cf8b47b594485b4a',
  'source_evidence_sha256': '5b9e424fcc8a942bdfccaa3a9e6f2e0dbeae677e9608a63eb1fdd45bcfa38ea8',
  'source_page_set_sha256': '3783f559f01dab5ccc2c6a88d7e5c3b00ae1d831720749f2a28c64ebac6d6fb9',
  'source_rows': 98,
  'stage_id': 'STAGE_1545_1555'},
 {'artifact_id': 'selection-d9fdf4a2586bca72a538af60',
  'backfill_run_id': '9232a5a50ef24af38e7f59587ed22c02',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'c8e31c2577a01d7a7e6ef75d9b0f679ba73e51a4c2d71b544ab756d95527b632',
  'candidate_receipt_sha256': 'c837fa69cb3647421b95643daa83da9cc94cfe1012c9040aa0f592fa145113e3',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260915',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:8e178f89ea3d982eacb87abce1cf4ed45e7a0cd422043fcc224266c91db539f2',
  'observed_rows': 99,
  'raw_artifact_sha256': 'e5963b129a404a3add1bc801eccbf7bb1d404af3facd1205c183c7331a0008c7',
  'requested_rows': 100,
  'runner_receipt_sha256': '8d3dc988fdf2e24b125f8ada3a552da752bb066a49768f8ec2e8ac865f61ba80',
  'selected_rows': 10,
  'selection_artifact_sha256': 'f8f3ac55e74c39c924d08c21de38f134749bd2abd8aa04bd20db4690475dd385',
  'selection_manifest_sha256': '60ad19484633bd0ac3a809fe74db6ac22826469ab6fe49e3dc655010836fa7f3',
  'selection_receipt_sha256': 'd25aad39b39b3b1192b3412afa84920f2f8f5c6f87fac7d7dc2203043dccf0f8',
  'selection_run_id': 'run-d9fdf4a2586bca72a538af60',
  'source_evidence_sha256': 'd80151a732e3cf1b990555c8a31958c3f34d8d1ef18c60555361de68c7d1d753',
  'source_page_set_sha256': '566378ebe0f8177685eb9bdc388979448e2371d582d7242451997339041bbd41',
  'source_rows': 99,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-4ed954afdb79ca60c64dfb36',
  'backfill_run_id': '672d138bb8ab4606bb31b90a548ec69c',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '05209b32915ed59485ce4f4ad92b675b5eade73b894cb784ce0262e267407eb8',
  'candidate_receipt_sha256': 'e77dd3060f9e78779cbc5a3921da9eee5b23b1868ea3ceeac81aabe352117520',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260915',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:94a09b4983285dd29fbeb4c03aac120b4fe53b4e1f84d609dec8063e4aff3797',
  'observed_rows': 99,
  'raw_artifact_sha256': '71b0118aab58faa5841ddb69f790856781165bedd72ea733187ec3714ace12e5',
  'requested_rows': 100,
  'runner_receipt_sha256': '0838e1512c9a93b1402d543e6835bbec7f05f65318a828fa55278313d75a83b6',
  'selected_rows': 10,
  'selection_artifact_sha256': '90dbff5a318e5ffc5afe7af945655e310bdf8ecfaba977dcf85bc45c331b7d26',
  'selection_manifest_sha256': '448dc963825064fef2fadb3f28a55c2e9b7743ecb0074073bca0edb3489ab8a5',
  'selection_receipt_sha256': '56898263d1dd0035536d399ff16684a870eff8a81c145c03942f842994c704bf',
  'selection_run_id': 'run-4ed954afdb79ca60c64dfb36',
  'source_evidence_sha256': 'd3fcf3ba24bcf3235cdca834e066c899d4e947e9353cb57324e1a2f36ad2dfac',
  'source_page_set_sha256': '566378ebe0f8177685eb9bdc388979448e2371d582d7242451997339041bbd41',
  'source_rows': 99,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-4160e18c302f88b003f45135',
  'backfill_run_id': 'b081ecdbe93c44a687f8872c6de14d8e',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '4ab3208c93759997078e88a589b6e1bc9c575c884e7ca0f7f75998326aa06b9f',
  'candidate_receipt_sha256': 'f1ab4ee1a545103c529e279e3a906b76354de5812cfa284b6f1450200337ca64',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260915',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:4fe2940be4ab6cba3cb3b6e0dcd140788e818c7ef2fc3b18b08d77faca05187a',
  'observed_rows': 99,
  'raw_artifact_sha256': '0a2d63d5a9ed8afe0f07126d41042996de3e42d6da67e3e8bfbfafe3060919bf',
  'requested_rows': 100,
  'runner_receipt_sha256': '89554895d4df0c4bacddd43c6edf6b08a6635e810991d43cfd40ec2a4f444338',
  'selected_rows': 10,
  'selection_artifact_sha256': 'e079485984ce308bf97f0517c17d6b6605c6b16577f9ba1420649e99524463be',
  'selection_manifest_sha256': 'fda3bd2f4400cb377828e5c8de214ed102fea2231cfe773c74747010642d8303',
  'selection_receipt_sha256': '783aae584ffbb5cc5e8f0eda4a7fba008b31ae52df7919afecf15fdc872fd0d9',
  'selection_run_id': 'run-4160e18c302f88b003f45135',
  'source_evidence_sha256': '3861479e37f99ef19b4ab1f26bbb5115d0270c4992f16196a937843c552935bf',
  'source_page_set_sha256': '566378ebe0f8177685eb9bdc388979448e2371d582d7242451997339041bbd41',
  'source_rows': 99,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-97fd9df57a5dcf48347b3add',
  'backfill_run_id': 'd3363a04487849d4b0a303c8f9e7062b',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '0f1a20a9cdfdaec38c9236d74e8dcccc4dffaa19b1049b57448ca1d528db83a5',
  'candidate_receipt_sha256': '9262c06e10be0f17913dfeeda20bfe7b2a096f4df1eae0592ba08259e91025ac',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260915',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:2de67ea8a4cc06c19ff64f4c4f24e3ceb851a561696364b3b793da2999ec14f2',
  'observed_rows': 99,
  'raw_artifact_sha256': '95800c9cef25359137039951b0718cb1973c9d9435390312fb9ed3b3e42bcaef',
  'requested_rows': 100,
  'runner_receipt_sha256': '1cc78f64f0dd4c1d9dfbd711971c9ad074669d177a7f1857b2dd54568846c016',
  'selected_rows': 10,
  'selection_artifact_sha256': 'a30641a9bf73683d9ad2424df1de70fc4d27a3be0a9a842b4e57d820f487ed8b',
  'selection_manifest_sha256': 'f17ba15a7ac9470126021b877cabb0ebd80be01aa44ef04d93dc13010ff20c25',
  'selection_receipt_sha256': '6e17211a64b6b6d3b90d38135608933ebd365571927aa71038f0e68da71fffa1',
  'selection_run_id': 'run-97fd9df57a5dcf48347b3add',
  'source_evidence_sha256': '02e59998c499d506fabac75ca082ee3635a9d2dfb8ad74ff1a913897b1c2ccc2',
  'source_page_set_sha256': '566378ebe0f8177685eb9bdc388979448e2371d582d7242451997339041bbd41',
  'source_rows': 99,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-3658c89eae57026e4480ffa9',
  'backfill_run_id': 'bd2eb6ed38ea41e7adf28776655669ce',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'ae26a9530b2e0b19b2e9dff541955c6ac690ac42703a08f62ff331607cc7e1a7',
  'candidate_receipt_sha256': 'ade4791c3d9eaf649b91d77ac8a79f053912ca9a44747af444542baee24bf7ba',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260915',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:66588a4aabd225f744d3642cbc7a1bc6cee1309f14408fa0b6e03e73c2825a2c',
  'observed_rows': 99,
  'raw_artifact_sha256': '4cbd6ac3b84f76d50ec8bc4d82b79819ab2893ab56fd258ae2965e8e1eea49e5',
  'requested_rows': 100,
  'runner_receipt_sha256': '7f887d9d0e0681b59fc012826698b44c803175e5720ab01755528d5ecad01dc2',
  'selected_rows': 10,
  'selection_artifact_sha256': '42eeb9626c21802dc67c89f136587c819f82439b34f7a5dbc6859b1ccb4613b4',
  'selection_manifest_sha256': '6a5b67f178eace4ad967023a63f0499ba9da9b53989585991210f1e090153c29',
  'selection_receipt_sha256': 'b5a1d62c699ee899fe3d3e5e7cdbf5750ff2d39851da15f99d1dc7fd0a90f4f7',
  'selection_run_id': 'run-3658c89eae57026e4480ffa9',
  'source_evidence_sha256': 'd5d4b400f8eaddd1e8dd82c047f7b6fe90b94b738310be1a4ad11913508d4430',
  'source_page_set_sha256': '566378ebe0f8177685eb9bdc388979448e2371d582d7242451997339041bbd41',
  'source_rows': 99,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-8eb1d559c0e4b71e8e14abbb',
  'backfill_run_id': 'ea9aa147e21e4adcbba28d6f39c5a838',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '1faae465820a2cce51f2dbaa2313fd51e94b11ec30c205f97bc7e96daedf6f56',
  'candidate_receipt_sha256': 'e057b95c8ff312e5c04c60e8674fcefff52bdb9cd0c20d65f3b5bff13fd7fd20',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260915',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:a7b593b48db232e2bbfe3cbed7bdfd2e1a86df280877a18acc36fb29e6c4263f',
  'observed_rows': 99,
  'raw_artifact_sha256': 'da1e00c91e00cd9e245c3126a796a6ab27506d51d82b53204d88e0371b31963b',
  'requested_rows': 100,
  'runner_receipt_sha256': 'dfef86916a29142600b6227cdff5b0d197a10fd33cae4cf39a1bd1327177a3a9',
  'selected_rows': 10,
  'selection_artifact_sha256': '5b16dcf10b542e3462c66018fa107761a69bf245b328c6679d2e4c189d517547',
  'selection_manifest_sha256': 'd98be7467cfa066b07fdb4ca8d052b500e89539746a5cc97004b587f9f04ff6f',
  'selection_receipt_sha256': '1e220325ea6b9be61bc0f9b53b329326a9ef4a829814394933a3d0a07d1d88a6',
  'selection_run_id': 'run-8eb1d559c0e4b71e8e14abbb',
  'source_evidence_sha256': '1ad0055a40143dbf78f38b935b9c0816197816e666ac2a4c994a81239d4825bf',
  'source_page_set_sha256': '566378ebe0f8177685eb9bdc388979448e2371d582d7242451997339041bbd41',
  'source_rows': 99,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-3308bf527e116d3dfd8e514c',
  'backfill_run_id': '13e47dbce6ad4bad8ca9d80fc1b0129e',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'fb02308c5ef78ab177b9fd24c7b6d0928dbace07769ec87cfa372fb809732f3b',
  'candidate_receipt_sha256': '0812e292d9b8fe30b01f63e1f7f4e451909434aa44d9120c702d6a6257b57e96',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260916',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:4c3356bcdd85c468a3c6897558db57915367c3e753966d0c5fe61c7840c623fd',
  'observed_rows': 99,
  'raw_artifact_sha256': '5f5f05f96715cbccb76a2848f80fc51b0c2a88e21a589b69d394421e384d5e5b',
  'requested_rows': 100,
  'runner_receipt_sha256': '639454cb664da986cddb5458e1eb036f0dc989362c1259512d06055dcccc47e2',
  'selected_rows': 10,
  'selection_artifact_sha256': 'db95971b95b0f70d55487009dbd3b92a8920e2bcc0df225cc696cf9a1b0e2f44',
  'selection_manifest_sha256': '5155d6ab76f55641cd7d272569c80d8d8da477bb32b5935d17a04804bfb11e58',
  'selection_receipt_sha256': 'ab943e1c50f7843ff1fde3eda36eebd6b3340560eef41ec4d9edfed7474f2b2b',
  'selection_run_id': 'run-3308bf527e116d3dfd8e514c',
  'source_evidence_sha256': '44bd39218da16afb7975acaa22151f0038fc5d9a2698a4d900151db5fddb83bd',
  'source_page_set_sha256': 'b938b86ff5712a9cba1a3825a1bfdbf3ef88965982f6cb73eb2a0611b71ab2bf',
  'source_rows': 99,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-7ce97b70f678096c204b0bd3',
  'backfill_run_id': 'a31d40234d4f4159a0dd426fd136117f',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '718beed7198788e837d9343cf48cc0daf6380a3c4d65a10b969aad77532792b9',
  'candidate_receipt_sha256': '4ec0ee47c4e12f2c75da4ef9b1fec2ed19cdb16338ec4ae71162bfca9915c4f2',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260916',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:300b4827346176f9657cd86b76d8090d9ce3210cb2bbf6e1913a70364a3fb40e',
  'observed_rows': 99,
  'raw_artifact_sha256': '3bbf570dd589c1d0e3e5336e0d9d50ab4691f776b1b05c8be51a9aaefcd8abf0',
  'requested_rows': 100,
  'runner_receipt_sha256': '4c9a9774294af57ed94daa06f2240758e270563337cccae348a37588079dd55f',
  'selected_rows': 10,
  'selection_artifact_sha256': '0c83b31a81f001a5f44f4800532442e4f246a8e580204991aa5fd6a750fa85a5',
  'selection_manifest_sha256': '7cba128936014f5b39b0ade87fe9e22dd5ad4d43f1895f854613a5c816f60583',
  'selection_receipt_sha256': 'd97f6ccde620c8bc7d9c29393cfcd2ab49fca359d6a33661e51c66d241b49544',
  'selection_run_id': 'run-7ce97b70f678096c204b0bd3',
  'source_evidence_sha256': '3f9b5285b16c91f233a9169e26943c2afb7aa7bcd3f577c251765eee6a3e754d',
  'source_page_set_sha256': 'b938b86ff5712a9cba1a3825a1bfdbf3ef88965982f6cb73eb2a0611b71ab2bf',
  'source_rows': 99,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-cd15ed52cf26f9f565bd9d2e',
  'backfill_run_id': '7cf166da64d1419f88b9f31a5dadc104',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'd0ea9ba075645a3f45e29d1a63dde39efd259ec5229e7db5f1d4b5dd5b3fdb4a',
  'candidate_receipt_sha256': '3e55d61ecd351c79a0b7b37cee9e70c6f2d8be0245e3087bf9adf71cf8bc7b2a',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260916',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:c8dba3112708641dcdca853d1c8aa25cd771d0715000ddf74c667f66968a70ff',
  'observed_rows': 99,
  'raw_artifact_sha256': '05d9ea6d28400dbeb8dbac8d426fa033377ebb000760f23efc7169dba3b54a13',
  'requested_rows': 100,
  'runner_receipt_sha256': 'e35247e73d5c85b5475a2dab9317acfcae8283a711bfcb7daa783acc3b1e6fe9',
  'selected_rows': 10,
  'selection_artifact_sha256': '84a93fff5ed70657976ac2c9583e845d1e9e5b4267500d5b1efc8b533bb8ef98',
  'selection_manifest_sha256': '4637dc76641545be4ba216855b8262faf4ef43b9ba236b2adcb70e8fca840739',
  'selection_receipt_sha256': 'fb0d3f44f324682d4faadac12135c47735b6784ce9a0070f135dfd71d162e3ee',
  'selection_run_id': 'run-cd15ed52cf26f9f565bd9d2e',
  'source_evidence_sha256': '8dab96974dd9a59f6548d06c5538b82e02da36414b69ab030c6b3dfe2d74ca1c',
  'source_page_set_sha256': 'b938b86ff5712a9cba1a3825a1bfdbf3ef88965982f6cb73eb2a0611b71ab2bf',
  'source_rows': 99,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-45966d7f467e4852d4ac0aca',
  'backfill_run_id': 'd7205f5091a84cf6bc3118381d668508',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '22466621d489f69099b34dcd6f9b7d0a3919cad93fcdf503045d6a80347105c3',
  'candidate_receipt_sha256': 'dfda599cc58ff39d25358a57d4762d8fff1bcb96f50a6ccc5b7c3830b9c51327',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260916',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:eb2a0afba40df1a9b33d327989edd4b0bfd7b25a1a05b5e8b7842fed380e665e',
  'observed_rows': 99,
  'raw_artifact_sha256': '391b3841652ce1f3a1ae896103e3cf0522a7a5e4fcfc955ec4209417b8b1604b',
  'requested_rows': 100,
  'runner_receipt_sha256': 'fa5e1bb59531b153f4c21679ca0a8a7ea942c8293a6903be2eada4f3d614b207',
  'selected_rows': 10,
  'selection_artifact_sha256': 'f17f5182d504c9cec605eb5513875cedc3c84787ea64c0aad6518a7510c82d4b',
  'selection_manifest_sha256': '119c19eb5819b3cf98e90baa6da16052c2531211c415f7bd0073898a463aa4f3',
  'selection_receipt_sha256': '885a385824df28b668afe98dac013a326d33427492e8501f910c46c523d83ec8',
  'selection_run_id': 'run-45966d7f467e4852d4ac0aca',
  'source_evidence_sha256': 'a55a2dcb857d30f92e914409125ca31ac83a18714c511e21252e763c528e3b8f',
  'source_page_set_sha256': 'b938b86ff5712a9cba1a3825a1bfdbf3ef88965982f6cb73eb2a0611b71ab2bf',
  'source_rows': 99,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-2545bacc3e216c1a92c0752d',
  'backfill_run_id': 'dbdf5bfe832a40e5bd93c13cd8020274',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '098512687b94a0d869e9883b67bd0524f339fe0384f55e58a4baadf1857e5fc4',
  'candidate_receipt_sha256': '17491a78f316d69fcfdd6d0f278734e55d1448ef3f64bd69144fe9945892abd5',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260916',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:ee0eef4f94a040889c141a7db1024073791b2d9e0561a08e017314c4eae7eb0c',
  'observed_rows': 99,
  'raw_artifact_sha256': 'd1eef86646d966cac8cfa59ec3c9d30ba2ffb5090ca3e52b28311fadbaa597e8',
  'requested_rows': 100,
  'runner_receipt_sha256': 'd85d176229351d26dc45876ac5ec280f29851e8b924ec6d8a5452a339b4c66c1',
  'selected_rows': 10,
  'selection_artifact_sha256': '50fe2becb5a4da225eecd6000142670253b238762f22540beb5069dc7fb75fdf',
  'selection_manifest_sha256': 'a5b5dacc3c7a0fea610fcff47dbcc22907915d7375dec983081d27f40ffc07ec',
  'selection_receipt_sha256': 'f59f1056af91fd402274abd4ea20d2283919726bd2b54f55511c3597b1cc56ea',
  'selection_run_id': 'run-2545bacc3e216c1a92c0752d',
  'source_evidence_sha256': 'f46bdb0eb3318273be6f2425e05cf55ba2a837dcce2766370bef78da277f9b7a',
  'source_page_set_sha256': 'b938b86ff5712a9cba1a3825a1bfdbf3ef88965982f6cb73eb2a0611b71ab2bf',
  'source_rows': 99,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-baa203a83f032a7d52cef9da',
  'backfill_run_id': '2132d0ee4bd843ff86f320b10222a249',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '3f528790ef815400c7195556500a1e91b6e55e939bd7ab2ba535b81b8bbd9a36',
  'candidate_receipt_sha256': '452d46ef3dd333ff1c9d8cd357d9c5f5294ae0785b72be9b3b1966070935c6e0',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260916',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:40a6fd1a44ab8130673c6064cb90b92e714a289a421f25c4b9728cf31724ac3e',
  'observed_rows': 99,
  'raw_artifact_sha256': 'f52bac4e4093ebd9224cd83defc9b60063a8a6365a6026a9fc75e2cee5fbc184',
  'requested_rows': 100,
  'runner_receipt_sha256': '7073170c6c7f1feb91a77bfb1993b34867d2fe47967910ae03840be899d1fac9',
  'selected_rows': 10,
  'selection_artifact_sha256': '4ec7ac8c72d4f52149bc9cad6ca56e04566576819809222b09a4920e8daec4b3',
  'selection_manifest_sha256': '990755462f7fddeec976a846bbff0b22ae62df910ae954282e5edd18fc9a5e97',
  'selection_receipt_sha256': 'a229fac9ff6dd4149d932cfa5ff8e27afc922f26aa47b42147bad403512d59d0',
  'selection_run_id': 'run-baa203a83f032a7d52cef9da',
  'source_evidence_sha256': 'bc4d58530273819a175474ef06e3100916eca7b8ffc41c2fb6a177174251e6c5',
  'source_page_set_sha256': 'b938b86ff5712a9cba1a3825a1bfdbf3ef88965982f6cb73eb2a0611b71ab2bf',
  'source_rows': 99,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-1212d7bdd75a7c75ce57ced4',
  'backfill_run_id': '574c6acccd3c4463a95f729d29568056',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'f7d20ea5f247606f8b079cfef2f5c4356d7386569a0abd5ac1a05f342ddac296',
  'candidate_receipt_sha256': 'ff1ee92e7ab7317490f28b5d2194d69aebe4695fbd08dee2dc0839b169ad91b1',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260916',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:d7ad57f57eb68d70445124e0e772d0f5d5cf4cbde7cc0a43f4fb82057681d407',
  'observed_rows': 99,
  'raw_artifact_sha256': '72cf61881b8ff1f44b98250b77730eaee05a0ac66df7207c2b5f194119b3d9e1',
  'requested_rows': 100,
  'runner_receipt_sha256': '92869704e1e569dc50420fced8fbf851c520c38f88ea75ccc9b726ced7e10966',
  'selected_rows': 10,
  'selection_artifact_sha256': 'e0a2cd28550a6ba9a532bdc1fe61d6bb2bd2e3bd3d8ac15a845081278373fd5a',
  'selection_manifest_sha256': 'fade916d87035baf89e00ac408ec92e62f6cea06bcadb5ee9a57aae5df3acfb7',
  'selection_receipt_sha256': '683d3b712fd27aeda50ef2c39651a695830812b02ddb2f08557f7b4186b1f6a3',
  'selection_run_id': 'run-1212d7bdd75a7c75ce57ced4',
  'source_evidence_sha256': '01f54aa14b72aa1c165893fe665ce43959646b9b56ffcd1b54a464abb0f2a278',
  'source_page_set_sha256': 'b938b86ff5712a9cba1a3825a1bfdbf3ef88965982f6cb73eb2a0611b71ab2bf',
  'source_rows': 99,
  'stage_id': 'STAGE_1545_1555'},
 {'artifact_id': 'selection-93f3e494054494a37a57ee71',
  'backfill_run_id': '345c5f62a4a84b1da86204eb59b4888e',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '8b8d69a80a6d46906ff710375ff0de572d264380edd4dc754a99da7f46701583',
  'candidate_receipt_sha256': '1b29df97202b5af39ad8d53bc6845a6f6fdb3eb0866bdd5ea6075234f45e2e18',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260917',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:872aa12ec451e5485eccd91f6f9ad1b8823e62f7976ceec9bc3479225f1879c1',
  'observed_rows': 99,
  'raw_artifact_sha256': 'd1a982e2a816d49e686e93397ea5aea9c014634280d2f2af79a78a75d90084c2',
  'requested_rows': 100,
  'runner_receipt_sha256': '2e881b764eaa5a185f677cc2281cb3a39632292f582d60372304aef4a3292456',
  'selected_rows': 10,
  'selection_artifact_sha256': 'aac0949aa53265eec5fe0e8071f5024e3af42e010bac241a7caf702262f9416d',
  'selection_manifest_sha256': '575717d64834c11da2c84d088a7ef215e28b7239e85ec7bff8bb059db659d7ee',
  'selection_receipt_sha256': 'f8f2a0bf99593ec45cbe3c929b4086fd45125e0a4d32d577c740b4d5aa7c883d',
  'selection_run_id': 'run-93f3e494054494a37a57ee71',
  'source_evidence_sha256': 'beaaa9b801387223e8aca9d48fba6af15930247a3d0fd74f8ba3ea4d59414dee',
  'source_page_set_sha256': '046604a7738b7eb161031a79cf4aa08ced3ad19f98521f5a9cd88d5926ee4194',
  'source_rows': 99,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-39b75c772961aaca3d81aed1',
  'backfill_run_id': '0352e2d67f4841219f39de2791ccc87d',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '416d6c9139839003e6bff1bce752581d1e79cff83b824c4ae0fabfbfbc1cf5dc',
  'candidate_receipt_sha256': '752650738fba3d6aae329945977961ad2d5f358a57909017e228bfc72adf22bd',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260917',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:a8f94c21fc277f946b857ff6790c757c165e46b1182144c66f061c52ac5cf7ae',
  'observed_rows': 99,
  'raw_artifact_sha256': 'ea610c05d00d6d131721596e96a69b53807356d035397d565fdf01d2bd2e028c',
  'requested_rows': 100,
  'runner_receipt_sha256': '600ec3fe0b333328ba489421002a50cdb7835ca117c10fa06bf5e8557e1c18a8',
  'selected_rows': 10,
  'selection_artifact_sha256': '0ee6586180fe3d9495a720d89ebc7f7e85cb840e5ca184be5d7ee025216bf934',
  'selection_manifest_sha256': '694f4ae32025243a9ef7852add0a6311ad76add4d9be5a39c2cad0275d3776b4',
  'selection_receipt_sha256': 'f899651d62f64a43de2375d5f0ef8ff5d437d211cc0269193a8e6690225fdac7',
  'selection_run_id': 'run-39b75c772961aaca3d81aed1',
  'source_evidence_sha256': '4e616432701b3ea2f2bfbeb1cf2464f63e23fc244846e59199c2f40b276feca5',
  'source_page_set_sha256': '046604a7738b7eb161031a79cf4aa08ced3ad19f98521f5a9cd88d5926ee4194',
  'source_rows': 99,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-d6674eea1299248054b253d0',
  'backfill_run_id': 'aa88e568c7104d3bbce9e157ba012764',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '5469eb70a54d7ed84c278597cb95d83bf355edfd8f51e152727afea78ecf45e5',
  'candidate_receipt_sha256': '2e260bb03adc1172cc7c77ab1bd9bf49458931517d54afce3a71885560931a9a',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260917',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:ca16be12097890870cbc3c81bfbf95cadb20c50dc8157a5f286f29aee004a124',
  'observed_rows': 99,
  'raw_artifact_sha256': 'b5fcf299606a67cac76a5fe068d0d45773eaf729eef67110097095b3823e0dc6',
  'requested_rows': 100,
  'runner_receipt_sha256': 'fa438fa35a5f2c05cf9c8b5d99da522d78990b26911df183b08ce5091766049c',
  'selected_rows': 10,
  'selection_artifact_sha256': 'dabb98917c822bac6f0c83b4ba163dcf774a15b07905d2c1564d1f8b9f3bd28d',
  'selection_manifest_sha256': '7fbb203ef1470fcda1a7e4183d4543bc8c8c5460a766d179f16676e452949ec6',
  'selection_receipt_sha256': '4560a5cf95ad95513349d648a4cff5beea1301014c4f7c3441af174e78782cec',
  'selection_run_id': 'run-d6674eea1299248054b253d0',
  'source_evidence_sha256': '440bec8407891a3db2f0b198f9cb084a57ba9bd503be7a410c988b7cfe6c7bc6',
  'source_page_set_sha256': '046604a7738b7eb161031a79cf4aa08ced3ad19f98521f5a9cd88d5926ee4194',
  'source_rows': 99,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-67d83183a06123f0ae4b7808',
  'backfill_run_id': 'c39b60010cb44448be0956fd04c33443',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '105ebf7c98c4c242fd15f862cbe1a35d19bbc8a1e3d33462b0b1083ea2f9a96e',
  'candidate_receipt_sha256': '8eed01badccfd04f5165e9b256bd737081ace9715fbe56585a29c2660a837f1f',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260917',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:31c0fb75e03753ab3b0a5aa9555662d1a412c872001137ab5f060e11910de342',
  'observed_rows': 99,
  'raw_artifact_sha256': '955be48410789034a287dd81413fda120f67d1fbe43e158a095a4408e396b88c',
  'requested_rows': 100,
  'runner_receipt_sha256': 'f8fc7553dd284d09778b39e3fcf70ee5fe006fc300ea45f7e9bee0e09237a480',
  'selected_rows': 10,
  'selection_artifact_sha256': 'd5941ea13f39810ddbc252b79aea0e9ecfc961e3e0096d962f26cb9d4ac84d97',
  'selection_manifest_sha256': '3e1d03fd9add1dc814fd4bd45544d89ab1a3f31159f4958afab6bb4b38e55051',
  'selection_receipt_sha256': '2861e95154fcb1d686a481a83a984a1b73e5cb01917d01a21d5a038d5b14ded3',
  'selection_run_id': 'run-67d83183a06123f0ae4b7808',
  'source_evidence_sha256': '6f0f2d40ac05b8a622943e4945330ce1e8621f0f3cf2ad936a78197315fe9eef',
  'source_page_set_sha256': '046604a7738b7eb161031a79cf4aa08ced3ad19f98521f5a9cd88d5926ee4194',
  'source_rows': 99,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-02c3e626e28678c945d53c3b',
  'backfill_run_id': '9b22a4dbcf484c29b06b9b0cfbbec0a4',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '88601390d4c18c018885e14edd5dc4608bbe2b9413e9e1dd971566ecfa34c5ec',
  'candidate_receipt_sha256': '69612c56c3862bdea7e327450a62a7e53fc1be315ec543e37900fb218dc53649',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260917',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:65effce614c667f1d142309dfc65e1bb7b44f00ddc74389ebc8c80368d797ad3',
  'observed_rows': 99,
  'raw_artifact_sha256': '6797b3dffc012e945b592023ba4d619ab61a70d7b24ec016f308ab6eef9303e4',
  'requested_rows': 100,
  'runner_receipt_sha256': 'db7d164eebaa9b1f7b74c51cb84110959cde3d1878fd62227fc94dcabf51b774',
  'selected_rows': 10,
  'selection_artifact_sha256': 'a36841c0915d9af6c4eaa3ee717592172b9270cd18b5074df671e12d34ed4b62',
  'selection_manifest_sha256': '9bc924a569c98a3622a5c71b912450fc1600862113e578b9fd7ca057ba337ee2',
  'selection_receipt_sha256': 'e385cfaad9228e327a7295d4efe469793c31a6ae56ee5cb5bf55d01bae503a54',
  'selection_run_id': 'run-02c3e626e28678c945d53c3b',
  'source_evidence_sha256': '18d1792bb7fe9ea352e70a136eb82b8eef3ea33ce67f081e10ace81dcc4abec7',
  'source_page_set_sha256': '046604a7738b7eb161031a79cf4aa08ced3ad19f98521f5a9cd88d5926ee4194',
  'source_rows': 99,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-67f936da6247b66695f6e591',
  'backfill_run_id': '25f6990ead484ac99b9613b838d38de3',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'fa44135219a89968fbea7e1d6bef85eeace2a627b36783929666d0f12af59458',
  'candidate_receipt_sha256': '4f301b80c646cf7963fec3f9cda2df6055919ef1aff8a6d6c67eef79bbd6ca29',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260917',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:175aabf946ffe601bdf2fc63ca92f2e6be6fcd5f456ac0314df7cc6cd7de00d3',
  'observed_rows': 99,
  'raw_artifact_sha256': 'c20acca5f036144b6485de59bddbea88def5ae61bc82af628fbd530409f8e162',
  'requested_rows': 100,
  'runner_receipt_sha256': 'e893734694c22177e1344794bdc2e863bb42b2b8d088fb0f2d8d60d97c93f80d',
  'selected_rows': 10,
  'selection_artifact_sha256': '956bba81507db94427d08a908596701531213d6d9939160b41d17f813f1d9898',
  'selection_manifest_sha256': '29327dc3e80b691e54a93f2c3b59a5c96b6223d530c079300555643a6a4a4ead',
  'selection_receipt_sha256': 'c78d3f3a60af563db2fbfe2541de86d4d1b8d27f8c904abff35699d01aeec0fb',
  'selection_run_id': 'run-67f936da6247b66695f6e591',
  'source_evidence_sha256': 'c7238e64078f44f24754f505c7dfe14754150a1fb4ca90f93c7a9aa74cdb1b38',
  'source_page_set_sha256': '046604a7738b7eb161031a79cf4aa08ced3ad19f98521f5a9cd88d5926ee4194',
  'source_rows': 99,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-6e80d577f023181f97d59987',
  'backfill_run_id': '09f5d440a0704370a7305dde6cb703f4',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'cb0026324631cf03df3a308b44607383da18de0c790be33d04e88209fb76e17a',
  'candidate_receipt_sha256': 'dbab11571a132574ac3cd0cd94a5bdb5e491a36a58905075b9102cd48093fafb',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260917',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:15767d080cd8db1e79a310f753e0a807b6ec9f6a98a2a396d4d8d5e0dc7457c0',
  'observed_rows': 99,
  'raw_artifact_sha256': 'd93f51a10833f4148556183d9048af327f101713af43091e2873395accc3435f',
  'requested_rows': 100,
  'runner_receipt_sha256': '48b0e11789b6036b480ab5a9ebec2322d6f4142759638d903ae13c21f6627144',
  'selected_rows': 10,
  'selection_artifact_sha256': '29f0b2cb67dccc7c96e65a1d497d08891a00a27001037e1b46d34cf5a53b4b56',
  'selection_manifest_sha256': 'a03bfc0ac48099eec089008c3b755d0004f3a307e38cc9bac32d461853668316',
  'selection_receipt_sha256': '26025553f70985eb83d456cebf0f1c680a75974de7f4af5b0ad68dd7f63c6250',
  'selection_run_id': 'run-6e80d577f023181f97d59987',
  'source_evidence_sha256': '423522f4e6f63cdc018f346fcf4b632c06fcf3d3f1d1b0edb79eb0fbe8dae576',
  'source_page_set_sha256': '046604a7738b7eb161031a79cf4aa08ced3ad19f98521f5a9cd88d5926ee4194',
  'source_rows': 99,
  'stage_id': 'STAGE_1545_1555'},
 {'artifact_id': 'selection-f42724a20421c2fc48e08363',
  'backfill_run_id': '7488875cfac14ab68d11d1c6c31b180a',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '1c98265b37aa3215b5f46a6cac120f1822346ca5fb1ef7243917a9f1c046bf13',
  'candidate_receipt_sha256': '2df01709b5ba528db3a5f497828b89ff2dbe56177f89e3560fba5ab0640cabe2',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260918',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:81fa811a5e10c2b0c23bd228feb1a8a00e751bc4f290f0d65184beed41628259',
  'observed_rows': 99,
  'raw_artifact_sha256': '87f439858ce03c88608ab3990bb3ad33808cd75a11e3f04745401f8a3b996803',
  'requested_rows': 100,
  'runner_receipt_sha256': '25771713c0b56dd4a3129c79a0c2ca4e7d49b4628e1976c5bdc58303fafd4e9b',
  'selected_rows': 10,
  'selection_artifact_sha256': '05429ef006a9c5de2515deb4f070ac6b17cbbeaf45c2ee7577dfc3af0e811029',
  'selection_manifest_sha256': '4fb406990291dd5e730499630927409fafd0e3934c19124607656245cbfb655a',
  'selection_receipt_sha256': 'b3e4581972366a11a5c8b6f83359660eaa63c6ca8b4b1b2390aaf656143d728e',
  'selection_run_id': 'run-f42724a20421c2fc48e08363',
  'source_evidence_sha256': '891a80bd6f9869840148e1c0f9953593f41bc525093f919ee7261c57b9475e02',
  'source_page_set_sha256': 'd677e29ed0ec04e099f7d13a5c88f1d55b8d89494abc3ca3fa4f75a42ba04f8b',
  'source_rows': 99,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-a78ea41f7b96696dec2b7b7b',
  'backfill_run_id': '6b7f9616969146ed909fa0a0f89506dd',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '721eeafdea98043f821e0afae4035232d1fe110331bca08a367455122d2abecb',
  'candidate_receipt_sha256': '712ed94fc9fafcd45c6e2e8328f47dd98c666d6719760abcdc7ab931bb056f59',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260918',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:294ff0aa03fcdd7a92bc02e24aaf002ec8dbf31b6f443c4991dce61a5ff2295e',
  'observed_rows': 99,
  'raw_artifact_sha256': '791f3b91330d27cab46cefa815b10f35daa2730018f12dbbce0d9d90775ac7d9',
  'requested_rows': 100,
  'runner_receipt_sha256': '9a3c27bbc97bfa493f05f029cefff3a2c85df9cc8cd6d2d4dab1330e1212bf37',
  'selected_rows': 10,
  'selection_artifact_sha256': '3286235f47d1e93ce69e3b89fc34c348508131bed9301dcd2b391e33eb250d64',
  'selection_manifest_sha256': '6c0f3031cd54f1b98ef95d2a32239994b5fdf5f99b0531ef9e6bda013dee9504',
  'selection_receipt_sha256': '3e441291fab9e7103be48970ea3bf97194ee20bf092ee31d17b1f545482ad5ce',
  'selection_run_id': 'run-a78ea41f7b96696dec2b7b7b',
  'source_evidence_sha256': '62eb4b974fb0d48e8f718ff13aa2533cf35375750ca8262af0bb552a3fd443ac',
  'source_page_set_sha256': 'd677e29ed0ec04e099f7d13a5c88f1d55b8d89494abc3ca3fa4f75a42ba04f8b',
  'source_rows': 99,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-55d4feb1cd038f3d35f383ef',
  'backfill_run_id': '5c694d4b361d450cbf45e875525564c7',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '03d08f664f63ec24eab0f39057132ddf9ab051da9484949f1e9a33be1fb6f9e1',
  'candidate_receipt_sha256': 'ce91378fd44a249d1ecd25e8c855c2289179194135a214688485dfc0bb2da9eb',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260918',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:844616f5b21681548afd4b8f0608ea0bc167857a4d6451f0e98b41de76c7a2b8',
  'observed_rows': 99,
  'raw_artifact_sha256': '3abd0711b5b260371d7ac2f11af036bc9f6e859bfcb1c0d2d8ea72a988c49791',
  'requested_rows': 100,
  'runner_receipt_sha256': '5f1117258eb6831cefa46e6c6a081e9e99bad60453cf68632faf3bac8fa088c0',
  'selected_rows': 10,
  'selection_artifact_sha256': '002aadfe1e93911855298115586560ce261fe2a89f0f99ca4290320716b379fa',
  'selection_manifest_sha256': '28027fa4224a1477291b937e29cdad02c74c5fae4a203b7cb2882298dbfd3e48',
  'selection_receipt_sha256': '8168c6a0fa3923b18de0cf52c0883ccdf3d1f8ab57fd1a26e7e8f99205cdf78a',
  'selection_run_id': 'run-55d4feb1cd038f3d35f383ef',
  'source_evidence_sha256': '1e504d87ac46f6dcf5a6b97741f023c0868fac5e200924f4e725f3691722071c',
  'source_page_set_sha256': 'd677e29ed0ec04e099f7d13a5c88f1d55b8d89494abc3ca3fa4f75a42ba04f8b',
  'source_rows': 99,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-7662add69eeb9cb411aa9296',
  'backfill_run_id': '8ab35842e42e4543b697cab570d3ca44',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '53463165b62708f9af6b561d4a1c96cebeb7a6f895aba36a0c88ea03b01638e7',
  'candidate_receipt_sha256': '20d2a69eb53883c554bae002f2dbf86408c2e783e95b184110a447be5946d042',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260918',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:338521c41a6c049270ede59cdb1749e131d31d04bf18c4257cc835494c7d79e6',
  'observed_rows': 99,
  'raw_artifact_sha256': 'c02e88e3bd1ac211690d83fa8c6748e73826e660af9f390fd880b14234bdcce1',
  'requested_rows': 100,
  'runner_receipt_sha256': '13ac3f8bda9316549596d74fda76924f7751f6ff9fbd0c43dc48a2642cd12025',
  'selected_rows': 10,
  'selection_artifact_sha256': '3074048e8ea2d107d75a74c42f49923625c24d725cf27f512dd15c642f19f2c1',
  'selection_manifest_sha256': 'ae1a18c5dfcbf778ef93a8ab843ec049b085899296cb33b32ed40b9c24f06b78',
  'selection_receipt_sha256': '90ec89992b6e2a69563d6b6af9993e5f553bedecdf9ca4bd37f4cbb15ac8256f',
  'selection_run_id': 'run-7662add69eeb9cb411aa9296',
  'source_evidence_sha256': '3c6073c45188eaf17c0fe63e374c04fe0235ea94c3abe67743d8cca525b85cb9',
  'source_page_set_sha256': 'd677e29ed0ec04e099f7d13a5c88f1d55b8d89494abc3ca3fa4f75a42ba04f8b',
  'source_rows': 99,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-1d77603671f48b9700dbc2eb',
  'backfill_run_id': '6042e38d20884297b0f684b58b062bd6',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '0f8d73ba4a8cab7d5e884d45a1468dbe32397d3d898057f00937475d40f693e2',
  'candidate_receipt_sha256': '9e3b680b0122684d345a1b77f8a792a4d14495f865a39fdb77a7692b7e4e7cb1',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260918',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:f31ad10cb7dda658b63a21ca3dec864bc4fdb30334e17d2def5b3f3b3ae9e7c8',
  'observed_rows': 99,
  'raw_artifact_sha256': 'bceda569eac71d68e5fcaa6d85f6d0ee074d663bdd8e68838fdc150654809b50',
  'requested_rows': 100,
  'runner_receipt_sha256': '0037c01fb996cf3ce4c2528e001f63787a0bc562d68c8fafa741b30758d83c86',
  'selected_rows': 10,
  'selection_artifact_sha256': '560bf2d7afa92644f1323c1d1e135f54f45bc2f47e822302dfe5e8a242de9419',
  'selection_manifest_sha256': '72f2fdef540e9b511399d79f0b27bb83cecb35b9266cfffba79594e3137d6fa2',
  'selection_receipt_sha256': '31fe696f623750c2837f47616b635be6b93b3bd357390c29d587482890d67832',
  'selection_run_id': 'run-1d77603671f48b9700dbc2eb',
  'source_evidence_sha256': 'e17d736f14820e084771dd4a4baca998354f7fc8c766fdc174df0f61a7a45814',
  'source_page_set_sha256': 'd677e29ed0ec04e099f7d13a5c88f1d55b8d89494abc3ca3fa4f75a42ba04f8b',
  'source_rows': 99,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-0266f710dbf5357c0aeae079',
  'backfill_run_id': 'ffe254160c1e4793b823083723c6ecc6',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '570528870463a18ff1896c3275613a4ac391b2731f19c540ed003a47fc8930df',
  'candidate_receipt_sha256': '0f09a06b97e5c992d1014be7e1d86a17eb52339f43a6729fd75abe1053adaad2',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260918',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:07595780ed9b3ab474d4c71fbb239b6a66ec49a5d2789e73c1453f9133a8208b',
  'observed_rows': 99,
  'raw_artifact_sha256': '0b0dd0488eb3b59510b3f52507b6a34bd8c4b75861dfae5ea97bd26d9a741df5',
  'requested_rows': 100,
  'runner_receipt_sha256': 'ed93a13c7c77e4ad1e932095426479a4eeef54d941d517ebad9f2409fbdee69f',
  'selected_rows': 10,
  'selection_artifact_sha256': '52247036ced29da241087af7da884155b734164ad4023e80dd39e2c57c6b5ecc',
  'selection_manifest_sha256': 'f35447ac37ccacace57efe33838677e48d2b34b312f3786d73d697cc37968186',
  'selection_receipt_sha256': '14abec54a9e58587842b21af2f8f1476cb811ac1fbcc9e377ae9115493790f19',
  'selection_run_id': 'run-0266f710dbf5357c0aeae079',
  'source_evidence_sha256': '366c81ac816d8d1e2162e10193173126c1d12fb77670ecaa0ebc438982723e5d',
  'source_page_set_sha256': 'd677e29ed0ec04e099f7d13a5c88f1d55b8d89494abc3ca3fa4f75a42ba04f8b',
  'source_rows': 99,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-8870dda91f9fddb0032d1d89',
  'backfill_run_id': '4fd4f0c226bf49b799d629b20fa26edc',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '3e2ac594c30dec1dcec5ead9843ba4c1c29fc567fb47df8647bc06a2681e18c4',
  'candidate_receipt_sha256': '3e0a6d6fbf1353d7314209a5834e65bc160ff9c298758d39659c011aef802f92',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260918',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:bf9a2dfc42314f2e14c90e94ae6fc02d0cab867d5d224937643f4c2bd4094751',
  'observed_rows': 99,
  'raw_artifact_sha256': '08b165ca8051036782380eb5d647ee9c07eec234a4c3c1a83a104f168e3ad25b',
  'requested_rows': 100,
  'runner_receipt_sha256': '857db202dbbd4e78be4a98614b900d38e4fe25bef856a7e78773ff7233813868',
  'selected_rows': 10,
  'selection_artifact_sha256': '6fc0763bd03d214aa929360ded6687a079e828bcfe275b7333630ec5417e2f55',
  'selection_manifest_sha256': '33053f9440d0ea18d17e096d3e2e1d6779bbc52e373914c89b9109f68b9d9ed9',
  'selection_receipt_sha256': '471af3dce7231f9954db6f01a24c0fad75527f0f0144780b343e8f1e57fcc3e1',
  'selection_run_id': 'run-8870dda91f9fddb0032d1d89',
  'source_evidence_sha256': 'c0f8810efd420fe72ee9cadd0ac8717df2cc4a1df045a3b3806a20ab00c575e6',
  'source_page_set_sha256': 'd677e29ed0ec04e099f7d13a5c88f1d55b8d89494abc3ca3fa4f75a42ba04f8b',
  'source_rows': 99,
  'stage_id': 'STAGE_1545_1555'},
 {'artifact_id': 'selection-495bfac69877aee214eb397a',
  'backfill_run_id': '4135ad846ccf4baea98032caa3feb396',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '99e69199e08d209ed7789c4dd954f50ca8b3dda12e5a40b71a54e1f03ac5329a',
  'candidate_receipt_sha256': 'be0c7ea635c98718986abb86353f68e06e75f77ff2c4897ceb177cc43a352b96',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260922',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:6ec6c57bc949a64669a68e4e19ab53c11178e33c535f6d7d30c2a86fa43e62bd',
  'observed_rows': 99,
  'raw_artifact_sha256': '0dcb6d1e399ac18d4a463bb6c767c91045b760d7ef602e1b4907e68ed283a8e2',
  'requested_rows': 100,
  'runner_receipt_sha256': 'a14bf69ccbb6ab39f12b52a5cd257db55eeaa6688fbd57a48afc5a6b05d93c73',
  'selected_rows': 10,
  'selection_artifact_sha256': '166971a302e64abd78b41af54891845715592bc903168f5b0c8f3d83c0a9401b',
  'selection_manifest_sha256': '3f071c3ffc1e65f3704a29d5cf9a90639e66013f4b61896098fdf95696e4865f',
  'selection_receipt_sha256': '9447cf3a74cc176c297f4fb9c6d1ed489d7637d600001756cfd9125b4c7bbbc2',
  'selection_run_id': 'run-495bfac69877aee214eb397a',
  'source_evidence_sha256': '15a50c79e9dca4499ef51f98f9d0bf3a436344b5b295015f4c6e8956ded1739f',
  'source_page_set_sha256': '33844bbac3d07b63611993a63d50f5a223041533e15605844a06c4a12bc57514',
  'source_rows': 99,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-81c8c913614607152cb302f2',
  'backfill_run_id': '793fe5e312354fd981a281f6ae371050',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '57f783d369c8afbc65a51deaf99762e4a68b74684f52ae18c4406be37f96df24',
  'candidate_receipt_sha256': 'b818e91d588c99382ffdc093be86a98b28c13844999c159c4b2e73b1a4bc9d71',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260922',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:a92a1cf63c0914b04a5d3475c0ddd3c41b0648e03f01bcee357b2c8f23743c42',
  'observed_rows': 99,
  'raw_artifact_sha256': 'c820743ee7abe90fd1cbd7edd085021c8f018f9bad2a071ff07f395ce51f3ce8',
  'requested_rows': 100,
  'runner_receipt_sha256': 'ea943eb245e2a5fa542869c20c1704832f85418011cca8a73f1be50cafa3b19f',
  'selected_rows': 10,
  'selection_artifact_sha256': '92de11b57e6ee59d6740c3d99f63ed1f83ab3da09fdb6562befed584aa74dc83',
  'selection_manifest_sha256': '6ba64f12ca73d69519c5fecf2bad93d8c16852d97c2e33fdc74099ba587557d7',
  'selection_receipt_sha256': 'd47e99b1b6c02e9642bb0e6ded8ba2a6c5068d3d2c167abf0bf6b757fc87561b',
  'selection_run_id': 'run-81c8c913614607152cb302f2',
  'source_evidence_sha256': 'b17b0cda201e0f5bc821f87b825d9abe41183469856398f9e778d244c250c493',
  'source_page_set_sha256': '33844bbac3d07b63611993a63d50f5a223041533e15605844a06c4a12bc57514',
  'source_rows': 99,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-ecf95f06d31f9594e481dc08',
  'backfill_run_id': '0061b749424d4552aa1d636d851a7cdd',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'f10b20c89ee8435ba17f0910e09258a51b397c39d1a5fe7ea2d364010fd7ffb7',
  'candidate_receipt_sha256': 'cdd02056dbfe908a5c85cbb234fb0173a9cd3eb47995823db0c2dd856b2b91f9',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260922',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:3ade93953403208bf0c68b5eddaf5c9b523d9542575a5a133e51c6db7bf81b20',
  'observed_rows': 99,
  'raw_artifact_sha256': 'a2e265e5dc1de8259634b64e9e8593b3b9698cd2fcd51548febce4bedfc1f4ae',
  'requested_rows': 100,
  'runner_receipt_sha256': 'adf108cac77ae0d8e1ebc2638a26fdf8dcbc9fa31af7d09df735d1248f5f925e',
  'selected_rows': 10,
  'selection_artifact_sha256': '3b8328775e05b25666d86806dc234d1258a6e1927e3239e5f878aeb3367d792e',
  'selection_manifest_sha256': 'bbfa3296f13a1ebd22f4a0ecdf8fc4721fe1c32679aeb5e8180ec183521bb4cb',
  'selection_receipt_sha256': 'ea37de3bb06e2a55c5b4979d652506f8935e70a3ef8fb897cdd6f218dadf348f',
  'selection_run_id': 'run-ecf95f06d31f9594e481dc08',
  'source_evidence_sha256': '3a806d62d4ef0601a95b8dc14ad2ba9cff8a7f0cda5d45198c0e40c28ea05c99',
  'source_page_set_sha256': '33844bbac3d07b63611993a63d50f5a223041533e15605844a06c4a12bc57514',
  'source_rows': 99,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-8d27ad9906a504bbb3178bec',
  'backfill_run_id': '1d0cde755fbd4efdbf40c733086cba17',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '7f19f52000ee1cd8dce49f58a66e018eb07cd53bb971490a465062aaf6689574',
  'candidate_receipt_sha256': 'e638f41527ec1594174bd8e2c555cad41bd2a75bf2a8dc6df3eb908fd8b225bd',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260923',
  'missing_codes': ('HK.02670',),
  'missing_evidence_markers': ('historical_capture_missing_HK.02670=TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING',),
  'missing_reason_by_code': {'HK.02670': 'TDX_EMPTY_PAGE_OFFSET0_OBSERVATION_MISSING'},
  'missing_rows': 1,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:9909d4eaa62696a81a03d4ffade3c51219013298a951c9ed494bc8476ce34c03',
  'observed_rows': 99,
  'raw_artifact_sha256': 'cc3994adaa1d4ce844e831ac6b9e378a7068f437bc670ba4c9a25d927e019c15',
  'requested_rows': 100,
  'runner_receipt_sha256': '196d4f4329c8edc314201f0ef001e830902207d21b5d85c9069c0b671f863cf4',
  'selected_rows': 10,
  'selection_artifact_sha256': 'cc1a99be0700a210adeaa15baf476db52cf9898a1e66f079f4fd4689167ef132',
  'selection_manifest_sha256': '72225544c487e47bdad800b985eb222cff97b7bf911b956dd1796bfe506f2c54',
  'selection_receipt_sha256': '84e55c48d551088081650bd1a3f2601e3a231dc3d09536662aa6e6e865416d45',
  'selection_run_id': 'run-8d27ad9906a504bbb3178bec',
  'source_evidence_sha256': 'd581a9dd5d540b1b9c483ea76d5b2e208438e378c28935308073a0d74b47cbcd',
  'source_page_set_sha256': '5ac7ff702ef278fe29459def86d878ffc93465fbe0b6c49493852fddefebc43b',
  'source_rows': 99,
  'stage_id': 'STAGE_1545_1555'},
 {'artifact_id': 'selection-f77251f89c1f092aa26ef815',
  'backfill_run_id': '2d99d9803702434e9b899b496eb15129',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '7464163c24b1513455d492db4d4a6128ae8b80caa290949f6d4f317a4188798c',
  'candidate_receipt_sha256': '3a4855fffc46121473879416893c9a4fd375e538c4059b397b11fb8dc70b4d38',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260929',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:3f420c07a89f7a9ba69ac1986f74a5bf277d124cdaa118aaad92cd5ae05f767f',
  'observed_rows': 100,
  'raw_artifact_sha256': '447b8b94ef64a58f6b5a7c845160627e4aa11392e82346b92c32c0603c72d0b7',
  'requested_rows': 100,
  'runner_receipt_sha256': '339c57ed582ee16f51756b95fbc88bfffb7c7bc07f829ca7baa6f5edd088c1f9',
  'selected_rows': 10,
  'selection_artifact_sha256': '97ea8668ba4bce4ea8de53373e4d7e9b80af64ced8a4383a10f83212725c7ad7',
  'selection_manifest_sha256': 'bf60d5161ba115ec2c6280d307309422ce881bbd1489f6df08322382bf38f351',
  'selection_receipt_sha256': 'd591436d080118884326a74cee20233af64a6799fda87b20131edc2952d14343',
  'selection_run_id': 'run-f77251f89c1f092aa26ef815',
  'source_evidence_sha256': '0e43c440ef70de7d4190badcb18c637e80347a3805887e4ddba977f884ca5252',
  'source_page_set_sha256': '4a5bf889a7c67a2a225304d715a2616057e80473fe877863e911b35657a908fb',
  'source_rows': 100,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-d161329311798f922c506d9e',
  'backfill_run_id': 'de2ff6a6d465432b99bacecf3f004542',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '74ad7212aaff7b26cf0bd537dad5cf895bf07e8edc1f8aef450a7452168c4316',
  'candidate_receipt_sha256': '849ce138055fab104687a93593fa2def24c3b087104c2f70fa022f6b6eb6f3aa',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260929',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:9380f7ed69752159111a8edef8aaad0961b34253d1cb2f235b85cdc130cf1d5e',
  'observed_rows': 100,
  'raw_artifact_sha256': '74ad4eb9bad7ddb89d7f261f7a7cccee58dc283c060594379abd80a2c719f85f',
  'requested_rows': 100,
  'runner_receipt_sha256': 'da1c6e1b64c579767c9bb12a3f1995cc4665ecd050ed01bc5735a7bbcd8cb53f',
  'selected_rows': 10,
  'selection_artifact_sha256': 'f242830652f49c575461fb3d2bea247a294e4980b34fa1824646b0e3e9242330',
  'selection_manifest_sha256': '80f9e9aae9765775560dd986b6ad697764c75325f48bc4d4f917b7abbad73cda',
  'selection_receipt_sha256': '6e55337f6964c74bba02f6b7ef66d7a38220f5f777a961b3696349e8c8157409',
  'selection_run_id': 'run-d161329311798f922c506d9e',
  'source_evidence_sha256': 'ec571dcfea6b4078b84b50928239a480a9d80b58a1030393bb3d972d431164eb',
  'source_page_set_sha256': '4a5bf889a7c67a2a225304d715a2616057e80473fe877863e911b35657a908fb',
  'source_rows': 100,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-62693b22a74187b1c4f434dc',
  'backfill_run_id': 'd2aa066d709e4a398804d9e3df5ba83c',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '5ab26f86af3dc27be8e36c18b007f6077c004c82f09f7b54049f68074b392ac8',
  'candidate_receipt_sha256': 'b260fe33dc6d03e79241932c98d03c8813bc1e1487843114fd0a9ff77ce60762',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260929',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:b9c05dc5b6659aa762826488a0af4652057d4cc92611a464b15bdef0fa6b0f02',
  'observed_rows': 100,
  'raw_artifact_sha256': '0088ad8a89a1253682f7a134c44f9f70eb20e9a2a21eedd1910f9d9cdfcfd8e9',
  'requested_rows': 100,
  'runner_receipt_sha256': '0ff56fb283f111ab57600f16c5370363c328ca24a0d1e37856abafbf43db56af',
  'selected_rows': 10,
  'selection_artifact_sha256': '1eca4fd48f8a723ced054753ba57044d731c38e3f2283fe3d375ad51a6ac9ce0',
  'selection_manifest_sha256': '1db73a25012212e3224995f496903af7892714e99d52183737973971caa1bcfa',
  'selection_receipt_sha256': '22521069173caf73b48c8faf74aedc787b23675f2c2c12c170cdd9f1c9abee22',
  'selection_run_id': 'run-62693b22a74187b1c4f434dc',
  'source_evidence_sha256': '01772abfa64b5a81d434438b3a79db1f56cd40a5858f6f2fbea31c86662f4674',
  'source_page_set_sha256': '4a5bf889a7c67a2a225304d715a2616057e80473fe877863e911b35657a908fb',
  'source_rows': 100,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-f19f555f8922b9e5bd23e754',
  'backfill_run_id': 'f2b9c32a05274e2c9d29f9b6f2caaf9a',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '96a3293d0edca571b38a1b42f31157418e3eb76b108f7f5c3b7cdbd77cc4ae7b',
  'candidate_receipt_sha256': '8f498211088c74e392775869f393e150c14d2f1c537df7d769456d6bbb19bdab',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260929',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:6bacd58f8328fad960e4d9941808cb73a86aeab5a907bd9eef95f95c42a9e96d',
  'observed_rows': 100,
  'raw_artifact_sha256': '842f8358509db5f4f1474ac783d0fde696ae2d6a6256e360def6d517c4fac0d1',
  'requested_rows': 100,
  'runner_receipt_sha256': '78804c68d11a7ac3b1df5f369dd4f93a48a028f863edac881e1276e4b7233906',
  'selected_rows': 10,
  'selection_artifact_sha256': 'a64c8ca2c3530a4bbcaa06f973a3163f89f6989a27a89f035dddbc5f5dba306d',
  'selection_manifest_sha256': '92ed52610f2c00db42b6984591d7564a9e5527f4f9bb23b5b7131eb7a66c7354',
  'selection_receipt_sha256': 'e99bddcd5abe77399983f64b93f9e4b512435963ea99168cddd1c17213dcff8b',
  'selection_run_id': 'run-f19f555f8922b9e5bd23e754',
  'source_evidence_sha256': 'cb19ea749ef38d6619a4c164462f6e178a0e00a467b7ba85a47e5d09438c1881',
  'source_page_set_sha256': '4a5bf889a7c67a2a225304d715a2616057e80473fe877863e911b35657a908fb',
  'source_rows': 100,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-dd83ea424378b09453ac5358',
  'backfill_run_id': 'f113f3adceb64b7e841d473a1871f564',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '5e173bb9e84a8839c0ad09de9161992b65540d9c44adf5cae23ae98b590d1d04',
  'candidate_receipt_sha256': 'c176d30c7a639862094a4ffa2ec83a6aef5dfa08085cf6e993be289783ebb587',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260929',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:ad3a628900fb182fe5a588b49ac520b6acf1284675199a2262e7eb19093a7e1e',
  'observed_rows': 100,
  'raw_artifact_sha256': '10bc86d1b1abf27cf119f70467f3f545c91af6a3bd5bf216057498a8339bcc73',
  'requested_rows': 100,
  'runner_receipt_sha256': '8e3b707f8ba71b3c29d62888aa7aabac7f592ad15954ee70793f51dfadae6799',
  'selected_rows': 10,
  'selection_artifact_sha256': '702812870212702fa7e3d6385818b68da41b3dcaff9cf8d349edec3d739655e8',
  'selection_manifest_sha256': '65125ee992cb9569ff24320db1c415c68f2a0ca2892fbe4b7f1a5e7d29b149a0',
  'selection_receipt_sha256': '0cead03c50889bb9b9e2beea410d19ee7232ef9461dadf722b0fc828c4ae94f6',
  'selection_run_id': 'run-dd83ea424378b09453ac5358',
  'source_evidence_sha256': 'b35502372d14c9a4600c9b0a837377240622d1037ae4c6546997864deeee2e44',
  'source_page_set_sha256': '4a5bf889a7c67a2a225304d715a2616057e80473fe877863e911b35657a908fb',
  'source_rows': 100,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-9f6442af35132a77bac9d0f4',
  'backfill_run_id': '386b053f54a54dc79f3745f2a9477df8',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '0700c25e117bd933475ca5730c6055c22094379c9b53e0ba1034e35e31da31a9',
  'candidate_receipt_sha256': 'e27843ea7a8a3c51b6d61a2570d4f4ecfb3e835335c56f4d6760c597cf17b0db',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260929',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:74f24d0b31c93f6b6654ba3c4eae175761d039dd6c230b19ae81e646713ea9f0',
  'observed_rows': 100,
  'raw_artifact_sha256': '17c1b25a973116a17ff381c909b579ab3f588bbb418649e6719d993a26963af8',
  'requested_rows': 100,
  'runner_receipt_sha256': '8e43e16bb94200a24b416bddf8c3489c7101152a1f56cbf75cfc3efa21d2a33e',
  'selected_rows': 10,
  'selection_artifact_sha256': '6b2782450a2fc7868210623356ced7411765e9c7b75c48b4c378b8256de7132b',
  'selection_manifest_sha256': 'ddfde0ea294b43444e699f1b743abdef74960fa6dbaf26148088d559b89c9702',
  'selection_receipt_sha256': '642395bc444bbb13ca7fbd793e6a043851bb1930117c634641b6b1204b5efc76',
  'selection_run_id': 'run-9f6442af35132a77bac9d0f4',
  'source_evidence_sha256': '1cad570279b9462e8659b14114c8713a8bb8b506a55db5058753ecc6fbfb9f90',
  'source_page_set_sha256': '4a5bf889a7c67a2a225304d715a2616057e80473fe877863e911b35657a908fb',
  'source_rows': 100,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-c69969c788aaa361486d0d27',
  'backfill_run_id': '26c150769cbe4476aaae2560069cf5b2',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'e62e704d665fbd66e212dee8c8a211cf5a8cd9382f46ab8d4bc059fce97dc723',
  'candidate_receipt_sha256': 'e21a330add0a9c6220221381bfafb8d4f824c6d1740b5816ec78316aab3346c4',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20260929',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:ce20ae9ceada1fdb87767f1d32771937271f99341683cb3f54713181699c0d0c',
  'observed_rows': 100,
  'raw_artifact_sha256': 'd94b83478c6006bbbdd98f441d95014093a0850b89b9d77157a09b824a4eb084',
  'requested_rows': 100,
  'runner_receipt_sha256': '8adbb4798b115807fd2482fd8f05d422cd8674d0c43e7290efad0bf3abd21dfd',
  'selected_rows': 10,
  'selection_artifact_sha256': '386eab8e7968d1f9c3db1f3661cd117a00409adebe5e0919937b1231b7ad9a5c',
  'selection_manifest_sha256': 'e5271e34d3450ff82ae84ce9c4af0237f2a8e361ea48493d65cd9a321038c66e',
  'selection_receipt_sha256': '798e52d98cb1f19971531743ba701d9f93833fbef735e1eee25b54bbd9d3c9a3',
  'selection_run_id': 'run-c69969c788aaa361486d0d27',
  'source_evidence_sha256': '34ebaa8cbdf1705c9b20209ab7a84fe6c96b150f0b4d27828d11c921427ad20a',
  'source_page_set_sha256': '4a5bf889a7c67a2a225304d715a2616057e80473fe877863e911b35657a908fb',
  'source_rows': 100,
  'stage_id': 'STAGE_1545_1555'},
 {'artifact_id': 'selection-4b3274c7dc78a9abec4cb864',
  'backfill_run_id': 'cfb6c501b1e94a3c9713ae50b359b358',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '967dde10097d5c6dc7c91150f8425ca7212000219a214be6834a693d3cbd82b5',
  'candidate_receipt_sha256': 'ce3178e8730f12aeca5e6349ddf0274062c46d16bba25c3139a8d5551ad05cfb',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20261002',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:dc60ce53c9efb63b064955680f659aa4a9b90052f8938f9ef9222fc724e7b5e1',
  'observed_rows': 100,
  'raw_artifact_sha256': 'd2dc537e4a223a061d5389bfca0e5b36a0e2719f8306d23f2624597e0a809195',
  'requested_rows': 100,
  'runner_receipt_sha256': '71a0b5fa219bc5a13e79adc22e3d7c633fc39d6900eb841f81bb4ca0141f434d',
  'selected_rows': 10,
  'selection_artifact_sha256': '91044278007fe878eeded311c84122618b77d26b5232e3c0432896cc9a067415',
  'selection_manifest_sha256': '4d9e7933b1178465e471be3404c5659f7c2c4208297ccb8f88734d879f1dddb0',
  'selection_receipt_sha256': 'b4c846891bd2a4a1be8455718b47c0695b0b8e6f56061ee293241c567ddf0561',
  'selection_run_id': 'run-4b3274c7dc78a9abec4cb864',
  'source_evidence_sha256': '001c6f2f54286089eceb42ba2494c41c37f1b98a7f854525b3738e5b3c61866b',
  'source_page_set_sha256': '568f22680dd12caa2cae365dee9b55afef1b5f4107b6bd2c2914cf9fabe47b7f',
  'source_rows': 100,
  'stage_id': 'STAGE_0930_0935'},
 {'artifact_id': 'selection-1e3ad9d6cf084aeb82caee76',
  'backfill_run_id': '6b6fe78785764c1cb87a5db140e7bc3e',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '2c1f8a747dd52597da42555c8d9b25d4e5f3fee622e7895e4b8067b698811d48',
  'candidate_receipt_sha256': 'f1dbe2db500d10c6c749e147054f55a1cd1a472b1b5c74d0fa790bd60266d3be',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20261002',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:73852d02a7bd6247b804701bc49cf45fa66dcdeda81e9a045eae9c1f3bad308a',
  'observed_rows': 100,
  'raw_artifact_sha256': '362f8d9d7eaf28f7170495adf9b49952abf3cf1f4de0156644804782f62d9b8e',
  'requested_rows': 100,
  'runner_receipt_sha256': '64907930e12a128422e09bb1e0b686c8c6f67313a2ad3a3d9491374c7c958758',
  'selected_rows': 10,
  'selection_artifact_sha256': 'b5256652c2be725a1faf17d99afefe8bdd7e10a9d9804fbca9d45a7fc05cffa6',
  'selection_manifest_sha256': '42225eef0788549bd5ff548cb95d8b935c6ed91606eed9d0d4560f8eea5310dd',
  'selection_receipt_sha256': '6d8d8739d24ab9f6fafe5ae121aef044217d66156e3caaf2b50c6336374ad728',
  'selection_run_id': 'run-1e3ad9d6cf084aeb82caee76',
  'source_evidence_sha256': 'a28f5e95b1f48abb2b306cf217af37c221a15d38cc90c038960fb10e9ce6b6a3',
  'source_page_set_sha256': '568f22680dd12caa2cae365dee9b55afef1b5f4107b6bd2c2914cf9fabe47b7f',
  'source_rows': 100,
  'stage_id': 'STAGE_0935_0940'},
 {'artifact_id': 'selection-9adce62080eaade1145b5d99',
  'backfill_run_id': 'a0749c57ac2a43c2ba3460af743b6c0b',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '21bbf3edfdfed786047b3c9eb82817c6deed8ad62ac455f247068d46a82cdbc7',
  'candidate_receipt_sha256': '01fef47f283773aab2d8f589f118e341653a5da45ebf8cd4035486fa802a8640',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20261002',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:527fc6b187ca0aaee64a4df5e358d7beb8b0241931967d9af7d3157badbc338c',
  'observed_rows': 100,
  'raw_artifact_sha256': '27d6acb3d32a62a0b1ba9506bc0ab2b3de48976e0c9d43846e75de7b60bd48bc',
  'requested_rows': 100,
  'runner_receipt_sha256': 'bdc8832d86ad0bec652fd01d8ea1ba89611ca13d04642d9a19f8c097e88b5dae',
  'selected_rows': 10,
  'selection_artifact_sha256': 'dfbae60a040df54c859184397c4878e1628cb14c8d7b9b9eff629029e96c35bf',
  'selection_manifest_sha256': '5cbf7d007777ac5f949e89cd9cadd43e9451b8bb3ff39bb4d8f275e90e33d7dd',
  'selection_receipt_sha256': '3686d35dab1964f61b49a981894a1a9222579e896dd7a3ea87266b480b56e945',
  'selection_run_id': 'run-9adce62080eaade1145b5d99',
  'source_evidence_sha256': '73070bbca99ff2386c5fc3dc8fd09249aa9807018ad25ed9f9a3532c05ab367d',
  'source_page_set_sha256': '568f22680dd12caa2cae365dee9b55afef1b5f4107b6bd2c2914cf9fabe47b7f',
  'source_rows': 100,
  'stage_id': 'STAGE_0940_0945'},
 {'artifact_id': 'selection-92db749725e293be31f015e3',
  'backfill_run_id': '3ec2b8cf2f834533af3647036e66eeaf',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '16a671a259db85130c4101e735b63f38b5323c56297dbbd1f76f220769c0df9d',
  'candidate_receipt_sha256': '7e3748eb5cdf9f60cdc56c53b3d7e745ac0dab46e80a536f2dce6e531def623e',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20261002',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:b42c7200744d3303274f42205ec42c72c6c584998ca823cb9431cc6038bb0e84',
  'observed_rows': 100,
  'raw_artifact_sha256': '33b9ae14a2834f7d5f2a0aadc49a7780176a0e637e0b6cf95698d927b59d91c9',
  'requested_rows': 100,
  'runner_receipt_sha256': 'a8086206cb39c07b3da125111f58abebbec7c09c5bd89cddad37ad71e9704a01',
  'selected_rows': 10,
  'selection_artifact_sha256': '40392cff5cb99d9885515b328fa02baf404a48fe303a003ab378d75caf5f75f1',
  'selection_manifest_sha256': '7495d5c6398e59f4990d5e03b251d1fe7457660169b031cee8278585be2e3341',
  'selection_receipt_sha256': '1891fcf333b462c6f733cb35b2b34a8c240a0d670dc5377d376999f1a2c027aa',
  'selection_run_id': 'run-92db749725e293be31f015e3',
  'source_evidence_sha256': 'c05664b38b73dddd3b74d151c986a631565b074cc1830763edc0f89cf2cdf4c9',
  'source_page_set_sha256': '568f22680dd12caa2cae365dee9b55afef1b5f4107b6bd2c2914cf9fabe47b7f',
  'source_rows': 100,
  'stage_id': 'STAGE_0945_1030'},
 {'artifact_id': 'selection-240076f4908d3f66b1aa0c38',
  'backfill_run_id': '79ccf89f0bee4cb88b4ca4de984e3685',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'c6902aabf31f93651ba52158c9910e61fc90caa8743e326acdc150364fe78599',
  'candidate_receipt_sha256': '81afa839f83690141287d314c18f5dfc7e78152cc9d059e4bade84d861b135cf',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20261002',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:00fc582916f7fbeb4eb659d87c85112e88fbfcc3d01d54cc115578f573d8e8cd',
  'observed_rows': 100,
  'raw_artifact_sha256': '07e464135a0b126513992e3afaa24a25aacd628aa79424e0e92084e72f19ed63',
  'requested_rows': 100,
  'runner_receipt_sha256': '5af00503c08bc50a85e1342e257e17603be3cfb886ea8c7be17130b3cfe08f3f',
  'selected_rows': 10,
  'selection_artifact_sha256': 'a70906b59475fc205b95fe405c01f74bdf64e813c5f8ec0333ad42efce375426',
  'selection_manifest_sha256': '5bb299bf5aec7762ec18ed2cd1871498814ea2e5de9461b1f49d834c26d34efd',
  'selection_receipt_sha256': '35fb29101b1eac1fa37c95674593e8789ddac8d61c1709f4d97802c601c5da47',
  'selection_run_id': 'run-240076f4908d3f66b1aa0c38',
  'source_evidence_sha256': '89b4abff38e7c8772bf51b4dc4f6bc36775288732add569944c1998765627ef8',
  'source_page_set_sha256': '568f22680dd12caa2cae365dee9b55afef1b5f4107b6bd2c2914cf9fabe47b7f',
  'source_rows': 100,
  'stage_id': 'STAGE_1300_1315'},
 {'artifact_id': 'selection-d181474a3598cb08a6d4ca4f',
  'backfill_run_id': '10a63f25ac0b400cbf3a6d299ebff6df',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': 'b2e2fbefaa1eb176e92a8ee6bba4f6f7d8146db61892bc6a3872d37fc5287a69',
  'candidate_receipt_sha256': '26a69cb64cbf1849887513355bf4b2e0b29de79a907cc03efccab0ad3b98feb8',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20261002',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:2fdba26e27e564e68b012b564db75627f7b2c09aaaf17f4f9447b0d89a7fcb82',
  'observed_rows': 100,
  'raw_artifact_sha256': '678de4ac0042dbfe4400ac7b2c0119fe56869ae82021bf89cf0a545ad933dd89',
  'requested_rows': 100,
  'runner_receipt_sha256': '2a60eadcd79af613085a6623f037628cb2d90f3575c9f89b02d8e18c2995805f',
  'selected_rows': 10,
  'selection_artifact_sha256': '906726eaf2943483c1ab3a3f8cf4ba0fa41e270115fd4e53859696dabcf934cb',
  'selection_manifest_sha256': 'f69c43253fce92f09bbc09c0d0071fc91b8be13709dafb1c78d8710bb3fc5126',
  'selection_receipt_sha256': '0f0da76604b8378beb01b62d15a32f2bb44f4e0676278be98b3f76bab6830b0d',
  'selection_run_id': 'run-d181474a3598cb08a6d4ca4f',
  'source_evidence_sha256': '565478971f091c925460d15d3c4dfbfb795bc1c9f670a989026eba1f27562703',
  'source_page_set_sha256': '568f22680dd12caa2cae365dee9b55afef1b5f4107b6bd2c2914cf9fabe47b7f',
  'source_rows': 100,
  'stage_id': 'STAGE_1445_1500'},
 {'artifact_id': 'selection-6a6b1f1dab5184c0eeee0725',
  'backfill_run_id': 'a5dc0d3acd9b42a29dc98edaff9ea293',
  'candidate_batch_receipt_sha256': 'a3b16606dcd6b3bdcce367b96bb8e560561fc5584fb061be1a2e1d846fb0dada',
  'candidate_manifest_sha256': '7b5eaeef490abc540fbd37688a0439da65ce538ec34473cd9928a9d30c72a7cc',
  'candidate_receipt_sha256': '48e9f2bdb728d129cf3a183b2151a65edc6bb16eb0491dfa0283bf21ae7d5174',
  'cannot_confirm_count': 3,
  'capture_batch_receipt_sha256': '726531a5a49c7aef0594d06f28e912d77f0aed2be86d0e2e2df6667f3bf04597',
  'date': '20261002',
  'missing_codes': (),
  'missing_evidence_markers': (),
  'missing_reason_by_code': {},
  'missing_rows': 0,
  'observation_mode_marker': 'STAGE_CENTER_AFTERFACT_OBSERVATION_R1:de47780010673450a4b059fbb08103f7daaf5e3b5fa75b511be77702bca9551f',
  'observed_rows': 100,
  'raw_artifact_sha256': 'ff0a4606e5798f6f03f48b12dc8767f23d7c5b7b123fd212fef795d48023286d',
  'requested_rows': 100,
  'runner_receipt_sha256': '764c2b39429b55f1b9affac04449f36290a42988e0c6d9684acaee6ad12b2463',
  'selected_rows': 10,
  'selection_artifact_sha256': '8734654a6a07dfc3e4e8c926134b23215189f47cca8a527f531e48b695ef7ce4',
  'selection_manifest_sha256': '2a7919e0743ea55ea2ed23d3516c63abb370f3afec6ac3c5f74d254d3f88e091',
  'selection_receipt_sha256': '2f0b27d74d138ec180d4af2d8c7e700a80e5f44d0577924803ce17a41d1a27e6',
  'selection_run_id': 'run-6a6b1f1dab5184c0eeee0725',
  'source_evidence_sha256': '019bdf66bb193c834020bf8061ed669cf5e1bd559e2c1d42169f8a4e328274f7',
  'source_page_set_sha256': '568f22680dd12caa2cae365dee9b55afef1b5f4107b6bd2c2914cf9fabe47b7f',
  'source_rows': 100,
  'stage_id': 'STAGE_1545_1555'})

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

    ``V35_DATA_ROOT`` points at the shared host data tree and is also passed as
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
        if explicit_data_root.resolve() == (_V35_STATE_ROOT / "data").resolve():
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


def _load_manager_research_components() -> tuple[type[Any], type[Any], type[Any], type[Any]]:
    """Load only the independent manager package from its own directory.

    The live host may receive ``v4/manager_research`` without the historical
    V4 Gate 0 package.  Importing ``v4.manager_research`` in that layout would
    execute a parent ``v4/__init__.py`` and pull unrelated gate modules into
    the host.  A private package alias keeps relative imports inside the
    manager package intact while making its minimal closure explicit.
    """

    loaded = sys.modules.get(_MANAGER_RESEARCH_RUNTIME_PACKAGE)
    if loaded is not None:
        return (
            loaded.ManagerResearchJobService,
            loaded.ManagerResearchStore,
            loaded.HkexOfficialProvider,
            loaded.MaterialStore,
        )
    package_dir = Path(__file__).resolve().parents[3] / "v4" / "manager_research"
    init_path = package_dir / "__init__.py"
    if not init_path.is_file():
        raise RuntimeError(f"independent manager research package is missing: {init_path}")
    spec = importlib.util.spec_from_file_location(
        _MANAGER_RESEARCH_RUNTIME_PACKAGE,
        init_path,
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot create independent manager research package spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MANAGER_RESEARCH_RUNTIME_PACKAGE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_MANAGER_RESEARCH_RUNTIME_PACKAGE, None)
        raise
    return (
        module.ManagerResearchJobService,
        module.ManagerResearchStore,
        module.HkexOfficialProvider,
        module.MaterialStore,
    )


def _strict_date(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise HTTPException(status_code=422, detail="date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="date must be a real calendar date") from error
    return value


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_exact_configured_hk_pool(payload: Mapping[str, Any], target_date: str) -> bool:
    """Accept only a complete, exact-date HK 0.2 pool from the configured root."""
    signal_date = payload.get("signal_date")
    provenance = payload.get("historical_provenance")
    rows = payload.get("rows")
    eligibility_date = (
        provenance.get("eligibility_source_date")
        if isinstance(provenance, Mapping)
        else None
    )
    if (
        payload.get("schema_version") != "v3_5.preselection_pool.v1"
        or payload.get("pool_id") != "hkconnect_d1_top100"
        or payload.get("market") != "HK"
        or payload.get("status") != "STRICT_0_2_READY"
        or payload.get("producer_id") != "v3_shared_hk_0_2_consumer_v1"
        or payload.get("source_role") != "SHARED_VERIFIED_HK_0_2"
        or payload.get("trade_date") != target_date
        or payload.get("target_date") != target_date
        or not isinstance(signal_date, str)
        or len(signal_date) != 8
        or not signal_date.isdigit()
        or signal_date >= target_date
        or not _is_sha256(payload.get("source_sha256"))
        or not str(payload.get("source_run_id") or "").strip()
        or not _is_sha256(payload.get("source_manifest_sha256"))
        or not _is_sha256(payload.get("source_receipt_sha256"))
        or payload.get("stage_selection_eligible") is not True
        or not isinstance(provenance, Mapping)
        or provenance.get("schema_version") != "v4.hk_d1_split_date_provenance.v1"
        or provenance.get("price_signal_date") != signal_date
        or not isinstance(eligibility_date, str)
        or len(eligibility_date) != 8
        or not eligibility_date.isdigit()
        or eligibility_date > signal_date
        or not str(provenance.get("eligibility_source_run_id") or "").strip()
        or not _is_sha256(provenance.get("eligibility_source_artifact_sha256"))
        or not str(provenance.get("eligibility_source_captured_at") or "").strip()
        or provenance.get("d1_source_run_id") != payload.get("source_run_id")
        or provenance.get("d1_source_artifact_sha256") != payload.get("source_sha256")
        or provenance.get("d1_source_manifest_sha256") != payload.get("source_manifest_sha256")
        or provenance.get("d1_source_receipt_sha256") != payload.get("source_receipt_sha256")
        or not isinstance(rows, list)
        or len(rows) != 100
        or any(payload.get(flag) is not False for flag in TRADING_SAFETY_FLAGS)
    ):
        return False
    symbols: set[str] = set()
    ranks: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            return False
        symbol = str(row.get("symbol") or row.get("code") or "").strip().upper()
        rank = row.get("pool_rank")
        if (
            len(symbol) != 8
            or not symbol.startswith("HK.")
            or not symbol[3:].isdigit()
            or row.get("pool_id") != "hkconnect_d1_top100"
            or row.get("market") != "HK"
            or row.get("trade_date") != target_date
            or row.get("target_date") != target_date
            or row.get("signal_date") != signal_date
            or isinstance(rank, bool)
            or not isinstance(rank, int)
            or rank not in range(1, 101)
            or any(row.get(flag) is not False for flag in TRADING_SAFETY_FLAGS)
            or str(row.get("recommendation_status") or "").upper() not in {"WATCH_ONLY", "WATCH_ONLY_BACKTEST_GATED"}
        ):
            return False
        symbols.add(symbol)
        ranks.add(rank)
    return len(symbols) == 100 and len(ranks) == 100


def _preselection_response_from_pools(
    pools: list[dict[str, Any]], *, trade_date: str, limit: int, offset: int
) -> dict[str, Any]:
    """Render merged exact-date pool reads with the existing API page contract."""
    pools = preselection_domain._replace_review_core_fupan_pool(pools, trade_date)
    pools = preselection_domain._replace_review_core_stage7_pool(pools, trade_date)
    pools = preselection_domain._complete_independent_pool_set(pools, trade_date)
    payload = preselection_domain._project_independent_pools(pools, trade_date)
    rows = payload["rows"]
    status = "READY_WITH_ROWS" if payload.get("producer_status") == "CANONICAL_COMPLETE" else "PARTIAL_WITH_ROWS"
    if not rows:
        raise ValueError("exact-date pool projection has no rows")
    response = {
        key: payload.get(key, [] if key.endswith("rows") or key == "pools" or key == "cannot_confirm" else {})
        for key in ("pools", "unified_rows", "a_source_only_rows", "a_all_pool_rows", "startup_ensure", "strict_0_2_status", "evidence_paths", "cannot_confirm")
    }
    response.update({
        "ok": True,
        "data_status": status,
        "blocking_reasons": list(payload.get("blocking_reasons", [])),
        "schema_version": "v3_preselection_pools.v1",
        "trade_date": trade_date,
        "module_id": "unified_preselection_pools",
        "write_policy": "read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        "pool_count": len(payload.get("pools", [])),
        "row_count": len(rows),
        "unified_row_count": len(payload.get("unified_rows", rows)),
        "a_source_only_row_count": len(payload.get("a_source_only_rows", [])),
        "a_all_pool_row_count": len(payload.get("a_all_pool_rows", rows)),
        "rows": [],
        "daily_readiness_status": payload.get("daily_readiness_status", status),
        "mandatory_pool_ids": list(payload.get("mandatory_pool_ids", ())),
        "optional_pool_ids": list(payload.get("optional_pool_ids", OPTIONAL_DAILY_POOL_IDS)),
    })
    response["market_totals"] = payload.get("market_totals", preselection_domain._market_totals(rows))
    response["hk_pool_version"] = payload.get("hk_pool_version")
    response["hk_pool_role"] = payload.get("hk_pool_role")
    response["input_fingerprint"] = preselection_domain._input_fingerprint(payload.get("pools", []), trade_date)
    response["source_digests"] = {
        str(pool.get("pool_id") or ""): str(pool.get("source_sha256") or "")
        for pool in payload.get("pools", [])
        if str(pool.get("pool_id") or "")
    }
    full_arrays = {
        "unified_rows": list(response["unified_rows"]),
        "a_source_only_rows": list(response["a_source_only_rows"]),
        "a_all_pool_rows": list(response["a_all_pool_rows"]),
    }
    array_pagination = {
        name: preselection_domain._page_metadata(array_rows, limit=limit, offset=offset)
        for name, array_rows in full_arrays.items()
    }
    response["unified_rows"] = preselection_domain._page_per_market(full_arrays["unified_rows"], limit, offset)
    response["a_source_only_rows"] = preselection_domain._page_per_market(full_arrays["a_source_only_rows"], limit, offset)
    response["a_all_pool_rows"] = preselection_domain._page_per_market(full_arrays["a_all_pool_rows"], limit, offset)
    paged_pools: list[dict[str, Any]] = []
    pool_pagination: dict[str, dict[str, Any]] = {}
    for pool in response["pools"]:
        full_pool_rows = list(pool.get("rows", []))
        metadata = preselection_domain._page_metadata(
            full_pool_rows, limit=limit, offset=offset, status=str(pool.get("status") or "")
        )
        pool_id = str(pool.get("pool_id") or "")
        pool_pagination[pool_id] = metadata
        paged_pools.append({
            **pool,
            "pool_size": len(full_pool_rows),
            "returned_rows": metadata["returned_rows"],
            "rows": preselection_domain._page_per_market(full_pool_rows, limit, offset),
            "page_offset": offset,
            "page_limit": limit,
            "has_more": metadata["has_more"],
            "complete": metadata["complete"],
        })
    response["pools"] = paged_pools
    response["rows"] = [row for pool in paged_pools for row in pool.get("rows", [])]
    has_more = any(metadata["has_more"] for metadata in (*array_pagination.values(), *pool_pagination.values()))
    response["pagination"] = {
        "offset": offset,
        "limit": limit,
        "next_offset": offset + limit if has_more else None,
        "has_more": has_more,
        "complete": not has_more and status == "READY_WITH_ROWS" and all(
            metadata["complete"]
            for pool_id, metadata in pool_pagination.items()
            if pool_id not in OPTIONAL_DAILY_POOL_IDS
        ),
        "arrays": array_pagination,
        "pools": pool_pagination,
    }
    response["a_all_pool_complete"] = array_pagination["a_all_pool_rows"]["complete"]
    response["unified_rows_complete"] = array_pagination["unified_rows"]["complete"]
    response["a_source_only_rows_complete"] = array_pagination["a_source_only_rows"]["complete"]
    response["optional_pool_status"] = payload.get("optional_pool_status", "CANNOT_CONFIRM")
    response["daily_readiness_status"] = payload.get("daily_readiness_status", status)
    response["mandatory_pool_ids"] = list(payload.get("mandatory_pool_ids", ()))
    response["optional_pool_ids"] = list(payload.get("optional_pool_ids", OPTIONAL_DAILY_POOL_IDS))
    return response


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
) -> FastAPI:
    app = FastAPI(title="V3.5", version="0.1.0")
    store = NativeDataStore(data_root or Path.cwd() / ".runtime" / "data")
    review_store = ReviewStore(store.root)
    configured_research_root = research_data_root or os.environ.get("V35_RESEARCH_DATA_ROOT")
    resolved_research_root = Path(configured_research_root).expanduser() if configured_research_root else store.root
    configured_pool_source = (
        preselection_source_root or os.environ.get("V35_PRESELECTION_SOURCE_ROOT")
    )
    resolved_pool_source = (
        Path(configured_pool_source).expanduser()
        if configured_pool_source
        else store.root
    )
    configured_morning_news_root = (
        morning_news_data_root or os.environ.get("V35_MORNING_NEWS_DATA_ROOT")
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

    def _hk_display_mode(
        market_payload: Mapping[str, Any],
        rows: list[dict],
        execution_market: Mapping[str, Any] | None,
    ) -> tuple[str, list[str]]:
        """Only call HK rows formal after selection and execution binding agree."""
        status = str(market_payload.get("status") or "CANNOT_CONFIRM")
        selection_status = str(market_payload.get("selection_status") or status)
        reasons = [str(item) for item in market_payload.get("cannot_confirm") or []]
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
            return ("OBSERVATION_UNVERIFIED" if rows else "CANNOT_CONFIRM"), reasons

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
        canonical_markets = payload.get("markets", {})
        frontend_markets: dict[str, dict] = {}
        unified_rows: list[dict] = []
        aliases = {"A_SHARE": "A", "HK_CONNECT": "HK"}
        execution_markets = (
            (payload.get("execution_evidence") or {}).get("markets") or {}
        )
        backfill_provenance_fields = frozenset(
            {
                "selection_mode",
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
            if canonical_market == "HK_CONNECT" and ordinary_hk_display:
                display_mode, display_reasons = _hk_display_mode(
                    market_payload, rows, execution_markets.get(canonical_market)
                )
                frontend_markets[alias]["display_mode"] = display_mode
                frontend_markets[alias]["display_reasons"] = display_reasons
                frontend_markets[alias]["observation_count"] = len(rows)
                if display_mode in {"CANNOT_CONFIRM", "OBSERVATION_UNVERIFIED"}:
                    frontend_markets[alias]["candidate_count"] = None
                    frontend_markets[alias]["status"] = (
                        "PARTIAL_WITH_ROWS" if display_mode == "OBSERVATION_UNVERIFIED" else "CANNOT_CONFIRM"
                    )
                    frontend_markets[alias]["selected_rows"] = None
            for row in rows:
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
            None if hk_display_mode in {"CANNOT_CONFIRM", "OBSERVATION_UNVERIFIED"}
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
        return {
            **payload,
            "status": stage_status,
            "selection_markets": canonical_markets,
            "markets": frontend_markets,
            "market_summaries": frontend_markets,
            "unified_rows": unified_rows,
            "cannot_confirm": cannot_confirm,
            "stage": {
                "stage_id": stage_id,
                "label": stage_definition.get("label", stage_id),
                "window": stage_definition.get("window", ""),
                "status": stage_status,
                "display_status": stage_status,
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
        exact = stage_workbench(
            date=trade_date,
            stage=stage_id,
            limit=limit,
            market="HK_CONNECT",
            backfill_run_id=binding["backfill_run_id"],
        )
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

    @app.get("/api/v3/meta/stages")
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

    @app.get("/api/v3/preselection-pools")
    def preselection_pools(
        date: str | None = None,
        limit: int = Query(default=200, ge=1, le=300),
        offset: int = Query(default=0, ge=0),
        page: int | None = Query(default=None, ge=1),
    ) -> dict:
        requested = _strict_date(date) if date is not None else None
        catalog = _catalog()
        selected = requested or catalog["default_date"] or catalog["system_date"]
        page_offset = (page - 1) * limit if page is not None else offset
        response = preselection(store, selected, limit, offset=page_offset)
        if configured_pool_source:
            configured_root = resolved_pool_source.expanduser().resolve()
            local_root = store.root.expanduser().resolve()
            if configured_root != local_root:
                try:
                    local_pools = PreselectionPoolStore(store.root).read_all(selected)
                except FileNotFoundError:
                    local_pools = []
                except (OSError, ValueError, TypeError, KeyError):
                    local_pools = None
                if local_pools is not None:
                    local_hk_pool = next(
                        (pool for pool in local_pools if pool.get("pool_id") == "hkconnect_d1_top100"),
                        None,
                    )
                    local_hk_missing = local_hk_pool is None or (
                        local_hk_pool.get("status") == "CANNOT_CONFIRM"
                        and not local_hk_pool.get("rows")
                        and local_hk_pool.get("source_role") == "EXPECTED_MISSING"
                        and local_hk_pool.get("source_path") == ""
                    )
                    local_hk_ready = bool(local_hk_pool and local_hk_pool.get("rows")) and (
                        str(local_hk_pool.get("status") or "").upper().endswith("_READY")
                        or str(local_hk_pool.get("status") or "").upper() in {"READY", "MATERIALIZED", "AVAILABLE"}
                    )
                    if local_hk_missing and not local_hk_ready:
                        source_pending = False
                        source_unconfirmed: str | None = None
                        try:
                            from infrastructure.interprocess_lock import owned_interprocess_lock

                            source_store = PreselectionPoolStore(resolved_pool_source)
                            with owned_interprocess_lock(
                                source_store.root / ".import.lock",
                                timeout_seconds=10,
                                timeout_message="data-root import lock timeout",
                            ) as source_lock:
                                pending_relative_for = getattr(
                                    source_store, "_pending_relative", None
                                )
                                pending_relative = (
                                    pending_relative_for(
                                        trade_date=selected,
                                        pool_id="hkconnect_d1_top100",
                                    )
                                    if callable(pending_relative_for)
                                    else (
                                        "preselection_pending_commits/"
                                        f"{selected}/hkconnect_d1_top100.json"
                                    )
                                )
                                try:
                                    source_store._io.read_bytes(pending_relative)
                                except FileNotFoundError:
                                    snapshot_reader = source_store.read_pool_snapshot
                                    if "lock_lease" in inspect.signature(
                                        snapshot_reader
                                    ).parameters:
                                        source_snapshot = snapshot_reader(
                                            selected,
                                            "hkconnect_d1_top100",
                                            lock_lease=source_lock,
                                        )
                                    else:
                                        # R9's descriptor-anchored snapshot reader
                                        # is already read-only and does not accept a
                                        # lease keyword.  The caller still holds the
                                        # same root import lock around pending check
                                        # and trio read.
                                        source_snapshot = snapshot_reader(
                                            selected, "hkconnect_d1_top100"
                                        )
                                else:
                                    source_pending = True
                                    source_snapshot = None
                        except FileNotFoundError:
                            source_snapshot = None
                        except OSError:
                            source_snapshot = None
                            source_unconfirmed = "source_read_unavailable"
                        except (ValueError, TypeError, KeyError):
                            source_snapshot = None
                            source_unconfirmed = "source_integrity_unconfirmed"
                        if source_pending or source_unconfirmed is not None:
                            response["configured_hk_pool_fallback"] = {
                                "applied": False,
                                "status": "CANNOT_CONFIRM",
                                "reason": (
                                    "source_pending_commit"
                                    if source_pending
                                    else source_unconfirmed
                                ),
                                "read_policy": "read_only_exact_date",
                                "target_date": selected,
                                "production_allowed": False,
                                "buy_gate_updated": False,
                                "orders_sent": False,
                            }
                        source_pool = source_snapshot.get("artifact") if isinstance(source_snapshot, Mapping) else None
                        if isinstance(source_pool, Mapping) and _is_exact_configured_hk_pool(source_pool, selected):
                            merged_pools = [
                                pool for pool in local_pools
                                if pool.get("pool_id") != "hkconnect_d1_top100"
                            ]
                            merged_pools.append(dict(source_pool))
                            response = _preselection_response_from_pools(
                                merged_pools,
                                trade_date=selected,
                                limit=limit,
                                offset=page_offset,
                            )
                            response["configured_hk_pool_fallback"] = {
                                "applied": True,
                                "read_policy": "read_only_exact_date",
                                "target_date": selected,
                                "pool_artifact_sha256": source_snapshot.get("artifact_raw_sha256"),
                                "pool_manifest_sha256": source_snapshot.get("manifest_raw_sha256"),
                                "pool_receipt_sha256": source_snapshot.get("receipt_raw_sha256"),
                                "producer_run_id": source_pool.get("source_run_id"),
                                "producer_artifact_sha256": source_pool.get("source_sha256"),
                                "producer_manifest_sha256": source_pool.get("source_manifest_sha256"),
                                "producer_receipt_sha256": source_pool.get("source_receipt_sha256"),
                            }
        response["requested_date"] = requested
        response["selected_date"] = selected
        response["page"] = page if page is not None else (page_offset // limit) + 1
        return response

    @app.get("/api/v3/workbench/stage")
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
            rows = market_payload.get("rows") or []
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
                        or market_payload.get("requested_rows") != binding["requested_rows"]
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
            if binding.get("requested_rows") is not None:
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
            payload = shared_selection_consumer.get(
                selected, stage, allow_backfill=True
            )
            payload = _quarantine_known_hk_auction_pool_mismatch(
                payload, selected, stage
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
                    exact_hk = stage_workbench(
                        date=selected,
                        stage=stage,
                        limit=limit,
                        market="HK_CONNECT",
                        backfill_run_id=day24_run_id,
                    )
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

    @app.post("/api/v3/workbench/stage/ensure")
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

    @app.get("/api/v3/stage-center/selection")
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

    @app.get("/api/v3/manager/stage-selection")
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

    @app.post("/api/v3/stage-center/selection/ensure")
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
    app.include_router(create_review_router(
        store.root,
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
        )
    )

    # Research is an owned V3.5 read-only slice.  Register the compatibility
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

    # V4 manager research is a separate date/input keyed job lane.  This
    # adapter only reads the already materialized HK_CONNECT stage response;
    # it never instantiates a V3 producer or accepts browser supplied rows.
    if manager_research_observation_reader is None:
        class _SharedManagerObservationReader:
            def read(self, target_trade_date: str) -> Mapping[str, Any]:
                if shared_selection_consumer is None:
                    return shared_selection_unconfigured(target_trade_date, "STAGE_0935_0940")
                return project_shared_selection(
                    shared_selection_consumer.get(
                        target_trade_date,
                        "STAGE_0935_0940",
                        markets=("HK_CONNECT",),
                    ),
                    limit=50,
                )

        manager_research_observation_reader = _SharedManagerObservationReader()
    resolved_manager_research_state_root = _resolve_manager_research_state_root(
        manager_research_state_root,
        data_root,
    )
    (
        manager_research_job_service,
        manager_research_store,
        hkex_official_provider,
        manager_material_store_class,
    ) = _load_manager_research_components()
    # One shared material store backs every manager research fetch lane: the
    # same URL is retrieved once and reused across official PDFs, media events,
    # and the public reader (cached parses included) until its TTL expires.
    manager_material_store = manager_material_store_class(
        Path(resolved_manager_research_state_root) / "materials"
    )
    if manager_research_source_provider is not None:
        manager_research_provider = manager_research_source_provider
    else:
        manager_research_provider = hkex_official_provider(material_store=manager_material_store)
    manager_bridge = importlib.import_module(
        f"{_MANAGER_RESEARCH_RUNTIME_PACKAGE}.us_market_bridge"
    )
    manager_us_market_reader = manager_bridge.ResearchPeripheralUsMarketReader(store.root)
    manager_research_service = manager_research_job_service(
        manager_research_store(resolved_manager_research_state_root),
        manager_research_observation_reader,
        manager_research_provider,
        existing_research_source=research_source,
        close_observation_reader=ManagerWorkbenchResearchReader(resolved_manager_research_state_root),
        workspace_ledger_root=Path(ledger_root) if ledger_root is not None else None,
        workspace_security_master_root=(Path(os.environ["V4_MANAGER_SECURITY_MASTER_ROOT"])
            if os.environ.get("V4_MANAGER_SECURITY_MASTER_ROOT") else
            (Path(shared_data_root) if shared_data_root is not None else None)),
        workspace_screen_authority_root=(Path(os.environ["V4_MANAGER_SCREEN_AUTHORITY_ROOT"])
            if os.environ.get("V4_MANAGER_SCREEN_AUTHORITY_ROOT") else
            (Path(os.environ["V4_MANAGER_SECURITY_MASTER_ROOT"])
             if os.environ.get("V4_MANAGER_SECURITY_MASTER_ROOT") else
             (Path(shared_data_root) if shared_data_root is not None else None))),
        material_store=manager_material_store,
        catalyst_data_root=(Path(os.environ["V4_MANAGER_NEWS_DATA_ROOT"])
                            if os.environ.get("V4_MANAGER_NEWS_DATA_ROOT") else store.root),
        catalyst_news_owner_root=(Path(os.environ["V4_MANAGER_NEWS_OWNER_ROOT"])
                                  if os.environ.get("V4_MANAGER_NEWS_OWNER_ROOT") else None),
        workspace_us_market_reader=manager_us_market_reader,
    )
    app.state.manager_research_service = manager_research_service
    app.include_router(create_manager_research_router(manager_research_service))
    app.include_router(create_manager_workbench_router(resolved_manager_research_state_root))

    preview_root = Path(__file__).resolve().parents[2] / "web" / "preview"
    if preview_root.is_dir():
        app.mount("/preview", StaticFiles(directory=preview_root, html=True), name="preview")

    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if dist.is_dir():
        app.mount("/", _RevalidatingStaticFiles(directory=dist, html=True), name="web")

    return app
