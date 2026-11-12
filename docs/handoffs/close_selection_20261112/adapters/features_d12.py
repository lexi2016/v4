"""D12 date adapter of unchanged D11 32-feature loop. No new signal logic.
Zero-range NA eligibility exactly reuses prior independently reviewed addendum.
"""
import hashlib,importlib.util,json,math
from pathlib import Path
import numpy as np
import pandas as pd
D='20261112'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def finite(x):
 try:return math.isfinite(float(x))
 except (TypeError,ValueError):return False
def module(ref,name):
 assert sha(ref['path'])==ref['sha256'],'FROZEN_FEATURE_SOURCE_DRIFT'
 spec=importlib.util.spec_from_file_location(name,ref['path']);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def build(frame,allkeys,source_files):
 a=module(source_files['old_17_feature_functions'],'d12_unchanged_old17');b=module(source_files['old_6_feature_functions'],'d12_unchanged_old6')
 old=json.loads(Path(source_files['old_model_freeze']['path']).read_text());names=old['feature_columns']['D']
 assert list(a.FEATURE_NAMES)+list(b.NEW_NAMES)==names[:23] and len(names)==32
 frame=frame.copy();frame['trade_date']=frame.trade_date.astype(str);frame=frame[frame.trade_date<=D]
 rows=[];grouped={str(code):g for code,g in frame.groupby('ts_code',sort=False)}
 for code in allkeys:
     g = grouped.get(code, frame.iloc[0:0]).sort_values('trade_date').reset_index(drop=True)
     sid = f'{code}|2026-11-12'
     out = {'sample_id': sid, 'security_code': code, 'trade_date': '2026-11-12', 'available_rows': len(g), 'feature_status': 'UNKNOWN', 'unknown_reasons': ''}
     vals = {n: np.nan for n in names}
     reason = []
     if g.empty or str(g.iloc[-1].trade_date) != D:
         reason.append('NO_EXACT_D12_ROW')
     else:
         d = g.iloc[-1]
         prev = g.iloc[-2] if len(g) >= 2 else None
         if len(g) < 61:
             reason.append('INSUFFICIENT_61_OBSERVED_BARS')
         else:
             win = g.iloc[-61:].copy()
             win['rel_bar'] = range(-60, 1)
             if win.volume.isna().any() or (pd.to_numeric(win.volume, errors='coerce') <= 0).any():
                 reason.append('ZERO_OR_UNKNOWN_VOLUME_IN_61BAR_WINDOW')
             try:
                 (v, r) = b.compute_struct_block(win)
                 vals.update(v)
                 reason.extend((f'STRUCT_{k}:{s}' for (k, s) in r.items()))
             except (ValueError, TypeError, KeyError) as exc:
                 reason.append('STRUCT_BLOCK:' + str(exc))
         indicator = {k: float(d[k]) if finite(d[k]) else np.nan for k in a.SOURCE_INDICATORS}
         try:
             vals.update(a.prefix_features(g, D, indicator))
         except (ValueError, TypeError, KeyError) as exc:
             reason.append('FROZEN17:' + str(exc))
         close = float(d.close) if finite(d.close) else np.nan
         required = ('macd_dif', 'macd_dea', 'macd_hist', 'brick_type_value', 'brick_length')
         for k in required:
             if not finite(d[k]):
                 reason.append('D_MISSING_' + k)
         if prev is None:
             reason.append('NO_PREVIOUS_BAR_FOR_INDICATORS')
         else:
             for k in ('macd_dif', 'macd_dea', 'macd_hist', 'brick_length'):
                 if not finite(prev[k]):
                     reason.append('PREVIOUS_MISSING_' + k)
         if finite(close) and close > 0 and all((finite(d[k]) for k in ('macd_dif', 'macd_dea', 'macd_hist'))):
             vals['macd_dif_over_close'] = float(d.macd_dif) / close
             vals['macd_dea_over_close'] = float(d.macd_dea) / close
             vals['macd_hist_over_close'] = float(d.macd_hist) / close
         if prev is not None and finite(close) and (close > 0) and all((finite(q) for q in (d.macd_dif, d.macd_dea, d.macd_hist, prev.macd_dif, prev.macd_dea, prev.macd_hist))):
             vals['macd_hist_delta_1_over_close'] = (float(d.macd_hist) - float(prev.macd_hist)) / close
             prior = float(prev.macd_dif) - float(prev.macd_dea)
             current = float(d.macd_dif) - float(d.macd_dea)
             vals['macd_cross_up'] = int(prior <= 0 and current > 0)
             vals['macd_cross_down'] = int(prior >= 0 and current < 0)
         if finite(d.brick_type_value):
             vals['canonical_brick_value'] = float(d.brick_type_value)
         if finite(d.brick_length):
             vals['canonical_brick_delta'] = float(d.brick_length)
         if prev is not None and finite(d.brick_length) and finite(prev.brick_length):
             vals['canonical_brick_turn_red'] = int(float(d.brick_length) > 0 and float(prev.brick_length) <= 0)
         for (ix, row) in [('D', d), ('PREV', prev)]:
             if row is not None and (row.formula_source != 'computed_main_chart_formula_20260515' or row.field_contract_version != 'authoritative_field_contract_v0_2_phase1'):
                 reason.append(ix + '_FORMULA_OR_FIELD_CONTRACT_MISMATCH')
     missing = [n for n in names if not finite(vals[n])]
     if missing:
         reason.append('MISSING_FEATURES:' + ','.join(missing))
     out.update(vals)
     out['unknown_reasons'] = '|'.join(reason)
     out['feature_status'] = 'ELIGIBLE_32' if not reason else 'UNKNOWN'
     rows.append(out)
 result=pd.DataFrame(rows);result['imputation_columns']=''
 allowed=['close_in_bar','upper_wick_in_bar','lower_wick_in_bar']
 for i,row in result.iterrows():
  if row.feature_status!='UNKNOWN':continue
  g=grouped.get(row.security_code)
  if g is None or g.empty:continue
  bar=g.sort_values('trade_date').iloc[-1];reason=str(row.unknown_reasons)
  if (str(bar.trade_date)==D and reason=='MISSING_FEATURES:'+','.join(allowed) and all(pd.isna(row[x]) for x in allowed)
      and all(np.isfinite(float(bar[x])) and float(bar[x])>0 for x in ('open','high','low','close','volume'))
      and float(bar.high)==float(bar.low) and float(bar.open)==float(bar.high)==float(bar.close)):
   result.at[i,'feature_status']='ELIGIBLE_ZERO_RANGE_IMPUTER';result.at[i,'imputation_columns']='|'.join(allowed)
 return result
