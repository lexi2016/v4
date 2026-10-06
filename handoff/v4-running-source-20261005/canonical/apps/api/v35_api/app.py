from datetime import datetime
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
from domains.preselection import date_catalog, preselection
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

    def _read_r8_exact_target_hk_override(
        payload: dict, trade_date: str, stage_id: str, limit: int
    ) -> dict | None:
        binding = _HK_R8_BINDING_BY_DATE_STAGE.get((trade_date, stage_id))
        if binding is None:
            return None
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
            hk_market["superseded_source"] = {
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
                            "source": "APPROVED_EXACT_TARGET_D1_AFTERFACT_CANDIDATE_R8",
                            "backfill_run_id": binding["backfill_run_id"],
                            "run_id": hk_market.get("run_id"),
                            "requested_rows": hk_market.get("requested_rows"),
                            "source_rows": hk_market.get("source_rows"),
                            "selected_rows": hk_market.get("selected_rows"),
                            "raw_artifact_sha256": hk_market.get("raw_artifact_sha256"),
                            "selection_manifest_sha256": hk_market.get("selection_manifest_sha256"),
                            "runner_receipt_sha256": hk_market.get("runner_receipt_sha256"),
                            "target_pool_sha256": _HK_R8_POOL_EVIDENCE[trade_date]["pool_sha256"],
                        }
                    },
                    "single_bundle_artifact_id": None,
                },
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
                or any(marker not in source_evidence for marker in binding["required_evidence"])
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
