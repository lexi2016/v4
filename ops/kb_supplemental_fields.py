"""Missing dictionary outputs derived from an existing accepted stock prefix.

This is a projection within the existing KB authority: no market acquisition,
signal overwrite, trading action or full-market producer is performed here.
Source identities and differences from upstream defaults are in the contract.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from ops.kb_yidong_authority import project_yidong_history


DICTIONARY_FIELDS = (
    'kb_rsi6','kb_rsi12','kb_rsi24','kb_wr5','kb_wr10',
    'kb_boll_mid','kb_boll_upper','kb_boll_lower','kb_boll_width','kb_boll_position','kb_vol_ratio',
    'kb_yidong_type','kb_yidong_vol_ratio','kb_yidong_above_60d',
    'kb_brick_trend','kb_brick_count','kb_brick_action_desc','kb_b1_rally_pct','kb_b1_pass_30',
    'kb_double_gun_vol1','kb_double_gun_vol2','kb_double_gun_gap_days',
    'kb_bowl_upper','kb_bowl_lower','kb_key_k_list','kb_violence_k_type','kb_violence_k_body',
    'kb_signal','kb_prev_high','kb_prev_low','kb_high_52w','kb_high_52w_dist',
    'kb_net_lg_mf','kb_net_elg_mf','kb_dmi_plus','kb_dmi_minus','kb_adx',
)


def _numeric(frame, name, *, positive=False, nonnegative=False):
    value = pd.to_numeric(frame[name], errors='coerce').astype('float64')
    valid = np.isfinite(value)
    if positive: valid &= value > 0
    if nonnegative: valid &= value >= 0
    return value.where(valid)


def _flag(value):
    if value is None or pd.isna(value): return None
    if value not in (True,False): raise ValueError('KB_SUPPLEMENT_FLAG_INVALID')
    return bool(value)


def _finite(value):
    try: return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError): return False


def _round_or_none(value, digits=2):
    return round(float(value), digits) if _finite(value) else None


def _brick_description(color, count, flip):
    if color is None or count is None or flip is None: return None
    count = int(count)
    if flip: return f'红砖翻绿！立刻止损（连续红砖{count}块后翻绿）'
    if color == 'RED' and count >= 4:
        return '红砖已满4块，至少减仓一半' if count == 4 else f'红砖已延续{count}块，趋势延续中，但未减仓需警惕'
    if color == 'GREEN':
        return f'绿砖已连续{count}块，跌势可能接近尾声但仍禁止抄底' if count >= 4 else f'绿砖下跌中（{count}块），绝不抄底，先数4块'
    return f'红砖上涨中（{count}块），继续持有'


def _double_gun_observed(i, op, close, volume, pct):
    """Recover component values only for an already accepted true signal."""
    n=i+1; gun2=None
    for j in range(n-2,max(0,n-15),-1):
        if (j>0 and all(_finite(v) for v in (op[j],close[j],volume[j],volume[j-1],pct[j]))
                and volume[j-1]>0 and pct[j]>=3 and close[j]>op[j] and volume[j]/volume[j-1]>=1.8):
            gun2=j;break
    if gun2 is None:return None
    gun1=None
    for j in range(gun2-3,max(0,gun2-12),-1):
        if (j>0 and all(_finite(v) for v in (op[j],close[j],volume[j],volume[j-1],pct[j]))
                and volume[j-1]>0 and pct[j]>=3 and close[j]>op[j] and volume[j]/volume[j-1]>=1.8):
            gun1=j;break
    if gun1 is None:return None
    return round(volume[gun1]/volume[gun1-1],1),round(volume[gun2]/volume[gun2-1],1),gun2-gun1


def _key_event(i, dates, op, high, low, close, vol, pct):
    """Project the pinned key-candle helper's latest-day component."""
    if i<9:return None
    arrays=(op,high,low,close,vol,pct)
    start=max(0,i-20)
    if not all(_finite(a[j]) for a in arrays for j in range(start,i+1)) or close[i-1]<=0:
        return None
    body=abs(close[i]-op[i])/close[i-1]*100
    avg=sum(vol[i-5:i])/5
    if avg<=0:return None
    ratio=vol[i]/avg
    h=max(high[start:i]);l=min(low[start:i])
    if h<=0 or l<=0:return None
    dh=(high[i]-h)/h;dl=(l-low[i])/l
    at_key=(-.02<=dh<=.15) or (-.02<=dl<=.15)
    if body>=3 and ratio >= (1.1 if body>=7 else 1.3) and at_key:
        return dict(date=int(dates[i]),close=float(close[i]),pct=float(pct[i]),
                    type='反转' if close[i]>op[i] else '衰竭',body_pct=round(body,1),vol_ratio=round(ratio,1))
    return False


def _signal(i, frame, op, close, vol, pct):
    """Source-priority enum using accepted components; uncertain inputs stay null."""
    if i<29:return None
    row=frame.iloc[i]
    for name in ('kb_macd_veto','kb_macd_gold_fake','kb_fangliang_yinxian',
                 'kb_macd_top_divergence','kb_macd_bottom_divergence','kb_macd_dead_fake',
                 'kb_suoliang','kb_beidou'):
        if _flag(row[name]) is None:return None
    j=row['kb_b1_j'];bbi=row['kb_hold_bbi']
    if not all(_finite(x) for x in (j,bbi,pct[i],close[i])):return None
    if row['kb_macd_veto']:return 'WATCH'
    if row['kb_macd_gold_fake']:return 'S1'
    if row['kb_fangliang_yinxian'] and pct[i]<-3:return 'S1'
    if row['kb_macd_top_divergence']:return 'S2'
    if row['kb_macd_bottom_divergence']:return 'B1'
    if row['kb_macd_dead_fake']:return 'B2'
    if j < -10 and row['kb_suoliang']:return 'B1'
    if -10<j<55 and pct[i]>4 and row['kb_beidou']:
        previous=frame['kb_b1_j'].iloc[max(0,i-9):i-1].tolist()
        if any(_finite(v) and v < -10 for v in previous):return 'B2'
        if not all(_finite(v) for v in previous):return None
    if j < -5 and row['kb_suoliang']:
        if not all(_finite(v) for v in (op[i-2],close[i-2],vol[i-2],vol[i-3])):return None
        if close[i-2]<op[i-2] and vol[i-2]>vol[i-3]*1.5:return 'SB1'
    if close[i]>bbi and j>0 and pct[i]>0:return 'HOLD'
    return 'WATCH'


def project_dictionary_fields(frame):
    """Append only the 37 missing dictionary outputs to a full ordered prefix."""
    required={'trade_date','ts_code','open','high','low','close','volume','pct_chg','ma60',
              'zge_white_line','zge_yellow_line','kb_yidong','kb_brick_value','kb_brick_consecutive',
              'kb_brick_flip_green','kb_double_gun','kb_violence_k','kb_b1_j','kb_hold_bbi',
              'kb_macd_veto','kb_macd_gold_fake','kb_fangliang_yinxian','kb_macd_top_divergence',
              'kb_macd_bottom_divergence','kb_macd_dead_fake','kb_suoliang','kb_beidou'}
    if not required.issubset(frame.columns):raise ValueError('KB_SUPPLEMENT_INPUT_MISSING:'+','.join(sorted(required-set(frame.columns))))
    data=frame.reset_index(drop=True)
    dates=data.trade_date.astype(int).tolist()
    if len(set(data.ts_code))!=1 or dates!=sorted(dates) or len(set(dates))!=len(dates):raise ValueError('KB_SUPPLEMENT_IDENTITY_INVALID')
    n=len(data); out=pd.DataFrame(index=data.index)
    # Forward-adjusted historical prices can be negative after cash dividends.
    # Difference/shape indicators must preserve those real source observations;
    # divisions which specifically require a positive base check it separately.
    op=_numeric(data,'open');hi=_numeric(data,'high')
    lo=_numeric(data,'low');close=_numeric(data,'close')
    vol=_numeric(data,'volume',nonnegative=True);pct=_numeric(data,'pct_chg')
    opv,hiv,lov,cv,vv,pv=(x.to_numpy() for x in (op,hi,lo,close,vol,pct))
    close_ok=close.notna().cummin();change=close.diff()
    for period in (6,12,24):
        up=change.clip(lower=0).ewm(alpha=1/period,adjust=False).mean()
        down=(-change.clip(upper=0)).ewm(alpha=1/period,adjust=False).mean()
        denominator=up+down
        value=(100*up/denominator).where((denominator>0)&close_ok)
        value.iloc[:period]=np.nan
        out[f'kb_rsi{period}']=value.round(2)
    for period in (5,10):
        hh=hi.rolling(period,min_periods=period).max();ll=lo.rolling(period,min_periods=period).min()
        out[f'kb_wr{period}']=(-100*(hh-close)/(hh-ll)).where(hh>ll).round(2)
    mid=close.rolling(20,min_periods=20).mean();sd=close.rolling(20,min_periods=20).std(ddof=0)
    upper=mid+2*sd;lower=mid-2*sd
    out['kb_boll_mid']=mid.round(2);out['kb_boll_upper']=upper.round(2);out['kb_boll_lower']=lower.round(2)
    out['kb_boll_width']=((upper-lower)/mid*100).where(mid>0).round(2)
    out['kb_boll_position']=((close-lower)/(upper-lower)*100).where(upper>lower).round(1)
    average=vol.shift(1).rolling(5,min_periods=5).mean();ratio=(vol/average).where(average>0)
    out['kb_vol_ratio']=ratio.round(2)
    details=project_yidong_history(data[['trade_date','open','close','volume','pct_chg','ma60','zge_yellow_line']].to_dict('records'))
    types=[];anomaly_ratio=[]
    for i,(d,raw) in enumerate(zip(details,data.kb_yidong)):
        flag=_flag(raw)
        if flag is not None and d['kb_yidong_is'] is not None and flag != d['kb_yidong_is']:
            raise ValueError('KB_YIDONG_EXISTING_FLAG_MISMATCH:'+str(dates[i]))
        types.append(d['kb_yidong_type'] if flag is True else None)
        anomaly_ratio.append(_round_or_none(ratio.iloc[i]) if flag is not None and ratio.iloc[i]>=2 and _finite(pv[i]) and pv[i]>0 else None)
    out['kb_yidong_type']=types;out['kb_yidong_vol_ratio']=anomaly_ratio
    ma60=_numeric(data,'ma60',positive=True)
    out['kb_yidong_above_60d']=[None if i<59 or not _finite(cv[i]) or not _finite(ma60.iloc[i]) else cv[i]>=.95*ma60.iloc[i] for i in range(n)]
    bricks=pd.to_numeric(data.kb_brick_value,errors='coerce')
    colors=[None if i<13 or not _finite(bricks.iloc[i]) or not _finite(bricks.iloc[i-1]) else
            'RED' if bricks.iloc[i]>=bricks.iloc[i-1] else 'GREEN' for i in range(n)]
    counts=[int(x) if _finite(x) else None for x in data.kb_brick_consecutive]
    out['kb_brick_trend']=colors;out['kb_brick_count']=counts
    out['kb_brick_action_desc']=[_brick_description(colors[i],counts[i],_flag(data.kb_brick_flip_green.iloc[i])) for i in range(n)]
    rally=[];pass30=[]
    for i in range(n):
        start=max(0,i-29)
        if i<9 or not all(_finite(lov[j]) and _finite(cv[j]) for j in range(start,i+1)):
            rally.append(None);pass30.append(None);continue
        first=min(range(start,i+1),key=lambda j:lov[j])
        if cv[first]<=0:rally.append(None);pass30.append(None);continue
        r=(cv[i]-cv[first])/cv[first]*100
        rally.append(round(r,2));pass30.append(25<=r<=40)
    out['kb_b1_rally_pct']=rally;out['kb_b1_pass_30']=pass30
    guns=[_double_gun_observed(i,opv,cv,vv,pv) if _flag(data.kb_double_gun.iloc[i]) is True else None for i in range(n)]
    for idx,name in enumerate(('kb_double_gun_vol1','kb_double_gun_vol2','kb_double_gun_gap_days')):
        out[name]=[g[idx] if g else None for g in guns]
    white=_numeric(data,'zge_white_line',positive=True);yellow=_numeric(data,'zge_yellow_line',positive=True)
    prefix_close=close.notna().cummin();warm=pd.Series(np.arange(n)>=119,index=data.index)&prefix_close
    out['kb_bowl_upper']=white.where(warm).round(2);out['kb_bowl_lower']=yellow.where(warm).round(2)
    key_events=[_key_event(i,dates,opv,hiv,lov,cv,vv,pv) for i in range(n)]
    key_lists=[];types=[];bodies=[]
    for i in range(n):
        recent=key_events[max(0,i-59):i+1]
        if i<9 or any(x is None for x in recent):key_lists.append(None)
        else:key_lists.append([dict(x,is_latest=x['date']==dates[i]) for x in recent if isinstance(x,dict)])
        if _flag(data.kb_violence_k.iloc[i]) is True:
            r=ratio.iloc[i];body=abs(cv[i]-opv[i])/cv[i-1]*100 if i and _finite(cv[i-1]) and cv[i-1]>0 else None
            types.append('大暴力' if _finite(r) and r>=3 else '小暴力' if _finite(r) else None)
            bodies.append(_round_or_none(body,1))
        else:types.append(None);bodies.append(None)
    out['kb_key_k_list']=key_lists;out['kb_violence_k_type']=types;out['kb_violence_k_body']=bodies
    out['kb_signal']=[_signal(i,data,opv,cv,vv,pv) for i in range(n)]
    out['kb_prev_high']=hi.shift(1);out['kb_prev_low']=lo.shift(1)
    peak=hi.rolling(240,min_periods=240).max();out['kb_high_52w']=peak
    out['kb_high_52w_dist']=((peak-close)/close*100).where(close>0)
    out['kb_net_lg_mf']=None;out['kb_net_elg_mf']=None
    hd=hi.diff();ld=-lo.diff()
    dmplus=hd.where((hd>ld)&(hd>0),0.).where(hd.notna()&ld.notna())
    dmminus=ld.where((ld>hd)&(ld>0),0.).where(hd.notna()&ld.notna())
    tr=pd.concat([hi-lo,(hi-close.shift()).abs(),(lo-close.shift()).abs()],axis=1).max(axis=1,skipna=False)
    p=dmplus.rolling(14,min_periods=14).mean();m=dmminus.rolling(14,min_periods=14).mean()
    trmean=tr.rolling(14,min_periods=14).mean()
    out['kb_dmi_plus']=(p/trmean*100).where(trmean>0).round(2)
    out['kb_dmi_minus']=(m/trmean*100).where(trmean>0).round(2)
    dx=(abs(p-m)/(p+m)*100).where(p+m>0)
    out['kb_adx']=dx.rolling(14,min_periods=1).mean().where(trmean>0).round(2)
    return out.loc[:,DICTIONARY_FIELDS]
