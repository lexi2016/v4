"""Frozen source identities and 87D availability for the post-10/15 experiment."""
from pathlib import Path
import hashlib,json,sys
import numpy as np

ROOT=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_post1015_oos_20261105')
PREV=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105')
PANEL=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/selector_ready_panels/data_layer_daily_formula_increment_update_v1/selector_ready_current_to_20261105_qfq_63986092da44625a/selector_ready_current_to_20261105.parquet')
PANEL_SHA='0765424ddb7630fd5869ea344ad0621922145dc0f3db9fe7c1bb90f4a8826ba2'
GEN='63986092da44625a69d34f5f98a300c8ba685ea023dbaa007639207caa3ea109'
MANIFEST=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/a_formula_runs/qfq_63986092da44625a69d3/candidate_receipt.json')
MANIFEST_SHA='a683e977b1e24fa12a1f272e403425e5d80d1878418932d3000261bcf3926761'
PARENT=PREV/'local_increment_v1/model_t5_local_increment.pkl';PARENT_SHA='ba3553516af05dec467299579dccc7d8c418882dbd4cc89433b4722c2df9dd43'
PROFILE=PREV/'cpu_original/models/V193_ALL_A_V3_1/per_stock_adaptive_posteriors_12d_5576.parquet';PROFILE_SHA='dfa69f36888f8f2f451e7f33e096c1677556521c20c155536c86592e127154cb'
ORDER=PREV/'cpu_original/models/V193_ALL_A_V3_1/feature_order_v3_1.json';ORDER_SHA='6d4e8f60a7854f1895976e1d462975d4645fc0dc01d2b92661d8111b28172325'
CALENDAR=Path(__file__).resolve().parents[2]/'contracts/market_calendar_2026.json';CALENDAR_SHA='9e2638b69e25495478cecb6ed551713178fcb989a63ebb4ecfd59689615f0acb'
CANON=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-daily-chain-20261031-r6-main/app/components/a_formula/build_canonical_formula_research_panel.py');CANON_SHA='074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258'
EXCLUDED={'000831.SZ','000972.SZ','002129.SZ','002623.SZ','002827.SZ','300237.SZ','605258.SH','688121.SH'}
TRAIN=20261016;TRAIN_END=20261026;TEST=(20261027,20261028);ASOF=20261105;X_END=20261028;PREFIX=20240101
FEATURES=json.loads(ORDER.read_text())
STRUCT=['kb_personal_vol_quantile_z','J','kb_personal_j_quantile_z','kb_white_yellow_bowl_score','digested_big_green_rebuild_flag','undigested_big_green_veto_flag','day1_high_j_pullback_flag','jcb_accumulation_intensity','tactic_pb1_shallow_white_score','tactic_pb2_yellow_bowl_b1_score','tactic_pb3_keyk_low_spring_score','tactic_b2_yang_confirm_score','mkt_ew_ret_5d','p53_jcb_rs_5d_excess']
PROFILE_MAP={'pers_eb_keyk_ret5_edge':'alpha_i','pers_eb_touch_white_win_edge':'beta_pb1','pers_eb_touch_yellow_win_edge':'beta_pb2','pers_eb_touch_keyk_bot_win_edge':'beta_pb3','pers_eb_b1_win_edge':'beta_j_wash','pers_eb_b2_win_edge':'beta_b2','pers_eb_buildup_win_edge':'beta_jcb','pers_eb_big_green_fail_diff':'gamma_fail','pers_eb_strong_weak_regime_spread':'beta_yellow'}
COLUMNS=['ts_code','trade_date','market_type','open','high','low','close','volume','amount','amount_ratio_20','zge_white_line','zge_yellow_line','BBI','J','ma20']

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def bindings():
    for path,digest in [(MANIFEST,MANIFEST_SHA),(PARENT,PARENT_SHA),(PROFILE,PROFILE_SHA),(ORDER,ORDER_SHA),(CALENDAR,CALENDAR_SHA),(CANON,CANON_SHA)]:
        if sha(path)!=digest:raise ValueError('SOURCE_HASH_DRIFT:'+str(path))
    m=json.loads(MANIFEST.read_text())
    if m['generation_id']!=GEN or m['candidate_sha256']['selector']!=PANEL_SHA or m['asof_date']!=ASOF or str(PANEL)!=m['candidates']['selector']:raise ValueError('PANEL_GENERATION_BINDING_MISMATCH')

def feature_map():
    actual={'pct_chg':'PREFIX_V192_CLOSE_OVER_PREVIOUS_CLOSE','amplitude_pct':'PREFIX_V192_RANGE_OVER_PREVIOUS_CLOSE',
      'amount_ratio_20':'PANEL_CANONICAL_V192_MATCH','J':'PANEL_CANONICAL_V192_MATCH_P52_WARMUP_LIMITATION',
      'is_gem_star':'P58_BOARD_FROM_CODE','is_bse':'P58_BOARD_FROM_CODE','dist_yellow_pct':'V192_CLOSE_OVER_PANEL_YELLOW',
      'dist_white_pct':'P52_CLOSE_OVER_WHITE_MAPPED_PROXY','dist_bbi_pct':'CLOSE_OVER_PANEL_BBI_MAPPED_PROXY',
      'pers_vol_norm_5d':'P58_FROM_AMOUNT_RATIO','pers_dist_w_norm_60d':'P58_FROM_WHITE_PROXY_AND_AMPLITUDE',
      'pers_dist_y_norm_120d':'P58_FROM_YELLOW_AND_AMPLITUDE','pers_amp_norm_20d':'P58_FROM_AMPLITUDE',
      'pers_ret_z_20d':'P58_FROM_PCT_AND_AMPLITUDE','day1_high_j_pullback_flag':'P58_PREFIX_PCT_AND_J',
      'undigested_big_green_veto_flag':'P58_THREE_VALUED_CONDITIONAL_TRUE_ONLY',
      'pers_pb_depth_style_index':'P59_P52_ANCHOR_AND_PIT2024_HABIT_MAPPED_PROXY'}
    actual.update({x:'P59_FROZEN_W2_LABEL_CUTOFF_20241231_ASOF_INPUT_20261015_FIRST_AVAILABLE_UNKNOWN' for x in PROFILE_MAP})
    out=[]
    for i,c in enumerate(FEATURES):
        if c in actual:status=actual[c]
        elif c.startswith('p54_repr_'):status='UNKNOWN_TEACHER_UNAVAILABLE'
        elif c.startswith('p53_') or c.startswith(('jcb_','tactic_','rev_r')):status='UNKNOWN_NAMED_V31_PRODUCER_NOT_DELIVERED'
        elif c.startswith('behav_'):status='UNKNOWN_PROFILE_FIRST_AVAILABLE_UNPROVEN'
        else:status='UNKNOWN_C_EVENT_SOURCE_NOT_BOUND'
        out.append({'index':i,'feature':c,'mapping':status,'unavailable':'NaN; fixed parent imputer only for backbone','pit':'CANNOT_CONFIRM'})
    return out
