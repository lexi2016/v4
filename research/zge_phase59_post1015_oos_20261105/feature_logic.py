"""P5.2 stock-isolated anchor/pullback states and bounded P5.9 input mapping.

Unknown C-event features stay NaN. No outcome data are read here. The
candidate is a documented mapped version, not complete original P5.9 parity.
"""
import numpy as np
import pandas as pd
import common as c


def create_stock(g,profile,history_complete=False):
    g=g.sort_values('trade_date',kind='stable').reset_index(drop=True).copy();n=len(g)
    if not n:return pd.DataFrame()
    if g.ts_code.nunique()!=1 or g.trade_date.duplicated().any():raise ValueError('STOCK_KEY_CONFLICT')
    for x in ['open','high','low','close','volume','amount','amount_ratio_20','zge_white_line','zge_yellow_line','BBI','J']:
        g[x]=pd.to_numeric(g[x],errors='coerce')
    o,h,l,cl,v=(g[x].astype(float) for x in ('open','high','low','close','volume'));white=g.zge_white_line;yellow=g.zge_yellow_line;bbi=g.BBI
    pvalid=(np.isfinite(o)&np.isfinite(h)&np.isfinite(l)&np.isfinite(cl)&(o>0)&(h>0)&(l>0)&(cl>0)&(h+1e-7>=l)&(h+1e-7>=cl)&(h+1e-7>=o)&(l<=cl+1e-7)&(l<=o+1e-7))
    vvalid=np.isfinite(v)&(v>0);pc=cl.where(pvalid).shift(1);cur=cl.where(pvalid);ret=cur/pc-1;amp=(h-l)/pc
    ran=(h-l).where((h-l)>0);body=(cl-o).abs()/ran;closepos=(cl-l)/ran;upper=(h-np.maximum(o,cl))/ran
    isyang=(cl>o)|((cl==o)&(ret>0));valid_bar=pvalid&vvalid&pc.notna();nser=pd.Series(np.arange(n),index=g.index)
    vv=v.where(vvalid);vr5=vv/vv.rolling(5,min_periods=5).mean();vr20=vv/vv.rolling(20,min_periods=20).mean();vrprev=vv/vv.shift(1)
    hh20=h.where(pvalid).shift(1).rolling(20,min_periods=15).max();ch15=cl.where(pvalid).shift(1).rolling(15,min_periods=10).max()
    hh60=h.where(pvalid).rolling(60,min_periods=20).max();ll60=l.where(pvalid).rolling(60,min_periods=20).min();position=(cl-ll60)/(hh60-ll60+1e-6)
    y5=is_yang=pd.Series(isyang.where(valid_bar),index=g.index);yangcount=y5.astype(float).rolling(5,min_periods=5).sum()
    yangv=vv.where(y5.eq(True),0).where(y5.notna());yinv=vv.where(y5.eq(False),0).where(y5.notna())
    rg=yangv.rolling(5,min_periods=5).sum()/(yinv.rolling(5,min_periods=5).sum()+1.)
    # P5.2's stock-local lagged personal reference, with its stated board prior.
    rs=vr5.shift(1);mean=rs.rolling(250,min_periods=60).mean();std=rs.rolling(250,min_periods=60).std();count=rs.rolling(250,min_periods=1).count()
    tc=str(g.ts_code.iloc[0]);is_bj=tc.endswith('.BJ');is_gem=tc.startswith(('300','301','688','689'));lim=.30 if is_bj else (.20 if is_gem else .10);board_prior=.78 if lim>=.19 else .72
    weight=np.minimum(nser,250)/250*.65;raw=(mean-.3853*std).clip(.50,.88).fillna(board_prior);q35=weight*raw+(1-weight)*board_prior
    # If the loaded prefix may have earlier source rows and is too short to
    # establish a full 250-reference window, do not assert a board fallback.
    q35=q35.where((nser>=255)|bool(history_complete))
    wready=(nser>=113)&white.notna()&yellow.notna()&(white>0)&(yellow>0);bready=(nser>=23)&bbi.notna()&(bbi>0)
    threshold_violent=.085 if lim>=.19 else .058;threshold_break=.045 if lim>=.19 else .032;threshold_act=.030 if lim>=.19 else .022
    base=valid_bar&(nser>=20)&body.notna()&closepos.notna()&vr5.notna()&vrprev.notna()&hh20.notna()&ch15.notna()&wready&position.notna()&vr20.notna()&yangcount.notna()&rg.notna()&upper.notna()
    vk=(ret>=threshold_violent)&(body>=.60)&((vr5>=1.45)|(vrprev>=1.55))&isyang
    bk=isyang&(ret>=threshold_break)&(body>=.50)&((vr5>=1.35)|(vrprev>=1.45))&(((cl>hh20)&(pc<=hh20))|((cl>ch15)&(pc<=ch15)&(cl>yellow)))
    keypos=(l<=white*1.035)|(l<=yellow*1.045)|(l<=g.ma20*1.035) if 'ma20' in g else (l<=white*1.035)|(l<=yellow*1.045)
    # The original key condition also uses MA20; this is a materialized panel field.
    if 'ma20' not in g:raise ValueError('MISSING_P52_MA20_SOURCE')
    act=isyang&(ret>=threshold_act)&(closepos>=.55)&keypos&((vrprev>=1.65)|(vr5>=1.45))&(cl>=white*.995)
    wave=(yangcount>=4)&vr20.between(1.15,3.8)&(rg>=1.6)&(cl>=yellow)&(white>=yellow*.98)&(position<=.78)
    climax=(position>.85)&(vr20>=2.6)&(upper>=.35)
    key=(vk|bk|act)&base;wave=wave&base
    # A continuous qualifying buildup is one structural episode: only its
    # first bar starts a wave anchor. A qualifying key K can start a new one.
    wave_start=wave & ~wave.shift(1,fill_value=False);anchor=key|wave_start
    rows=[];prior=None;anchor_uncertain=False
    for i in range(n):
        dt=int(g.trade_date.iloc[i]);active=None;status='NO_ANCHOR';kind='NONE';age=np.nan;dd=np.nan;gid=None;risk=False
        if prior is not None and i-prior['idx']<=15 and not anchor_uncertain:
            active=prior;age=i-prior['idx'];gid=f'{tc}:{prior["date"]}';dd=cl.iloc[i]/prior['high']-1 if pvalid.iloc[i] else np.nan
            required=bool(valid_bar.iloc[i] and wready.iloc[i] and bready.iloc[i] and np.isfinite(vr5.iloc[i]) and np.isfinite(q35.iloc[i]) and np.isfinite(position.iloc[i]))
            if required:
                vk_ratio=v.iloc[i]/prior['vol'];hold_low=cl.iloc[i]>=prior['low']*.992;hold_y=cl.iloc[i]>=yellow.iloc[i]*.985
                shrunk=(vk_ratio<=.68) or (vr5.iloc[i]<=q35.iloc[i]*1.05);distw=cl.iloc[i]/white.iloc[i]-1
                pa=hold_low and cl.iloc[i]>=white.iloc[i]*.995 and white.iloc[i]>yellow.iloc[i] and shrunk and dd>=-.065
                pb=hold_low and hold_y and not pa and shrunk and abs(distw)<=.038
                pcand=hold_low and (l.iloc[i]<white.iloc[i]*.990 or l.iloc[i]<=prior['low']*1.008) and cl.iloc[i]>=prior['low']*.998 and not pa and not pb
                pdn=(cl.iloc[i]<prior['low']*.985) or ((not bool(isyang.iloc[i])) and vr5.iloc[i]>=1.35 and cl.iloc[i]<white.iloc[i]*.985)
                pe=position.iloc[i]>.80 and dd<=-.09 and cl.iloc[i]<white.iloc[i]
                risk=bool(pdn or pe or climax.iloc[i]);kind='D' if pdn else ('E' if pe else ('HIGH_CLIMAX' if bool(climax.iloc[i]) else ('A' if pa else ('B' if pb else ('C' if pcand else 'NONE')))))
                status='RISK' if risk else ('TARGET' if (pa or pb or pcand) else 'NON_PULLBACK')
            else:status='UNKNOWN_CURRENT_OR_REFERENCE'
        elif anchor_uncertain:status='UNKNOWN_PRIOR_ANCHOR'
        if dt>=c.TRAIN:
            out={x:np.nan for x in c.FEATURES};out.update({'ts_code':tc,'signal_date':dt,'pool_status':status,'p52_type':kind,'risk':risk,'event_group':gid,
                'anchor_date':None if active is None else active['date'],'anchor_key':None if active is None else active['key'],
                'anchor_wave':None if active is None else active['wave'],'bars_since_anchor':age,'history_rows_loaded':i,'q35_count':int(count.iloc[i]) if pd.notna(count.iloc[i]) else 0,
                'history_prefix_complete':bool(history_complete),'anchor_state_asof':gid if active is not None else None})
            if valid_bar.iloc[i] and wready.iloc[i] and bready.iloc[i]:
                pct=float(ret.iloc[i]*100);ap=float(amp.iloc[i]*100);dw=float((cl.iloc[i]/white.iloc[i]-1)*100);dy=float((cl.iloc[i]/yellow.iloc[i]-1)*100);db=float((cl.iloc[i]/bbi.iloc[i]-1)*100)
                amt=float(g.amount_ratio_20.iloc[i]) if np.isfinite(g.amount_ratio_20.iloc[i]) else np.nan;j=float(g.J.iloc[i]) if np.isfinite(g.J.iloc[i]) else np.nan
                out.update({'pct_chg':pct,'amplitude_pct':ap,'amount_ratio_20':amt,'J':j,'is_gem_star':float(is_gem),'is_bse':float(is_bj),
                  'dist_white_pct':dw,'dist_bbi_pct':db,'dist_yellow_pct':dy,
                  'pers_vol_norm_5d':float(np.clip((amt-1)/.55,-3.5,3.5)) if np.isfinite(amt) else np.nan,
                  'pers_dist_w_norm_60d':float(np.clip(dw/(ap+1.2),-3.5,3.5)),'pers_dist_y_norm_120d':float(np.clip(dy/(ap*1.5+1.5),-3.5,3.5)),
                  'pers_amp_norm_20d':float(np.clip((ap-3.2)/2,-3,3.5)),'pers_ret_z_20d':float(np.clip(pct/(ap+1),-3.5,3.5)),
                  'day1_high_j_pullback_flag':float(pct<0 and j>50) if np.isfinite(j) else np.nan,
                  'undigested_big_green_veto_flag':1.0 if np.isfinite(amt) and pct<=-3 and amt>=1.25 else np.nan})
            if profile is not None:
                for target,source in c.PROFILE_MAP.items():
                    val=profile.get('w2_'+source,np.nan);out[target]=float(val) if pd.notna(val) and np.isfinite(val) else np.nan
                opt=profile.get('pit2024_opt_pb_depth_pct',np.nan)
                if np.isfinite(dd) and pd.notna(opt) and np.isfinite(opt):out['pers_pb_depth_style_index']=float(np.clip(1.5-abs(abs(dd*100)-float(opt))/3.5,-2,1.5))
            rows.append(out)
        # P5.2 most recent previous qualifying structural anchor; UNKNOWN is
        # propagated until a later known anchor resets it. No cross-stock ffill.
        if bool(base.iloc[i]):
            if bool(anchor.iloc[i]):
                prior={'idx':i,'date':dt,'high':float(h.iloc[i]),'low':float(l.iloc[i]),'vol':float(v.iloc[i]),'key':bool(key.iloc[i]),'wave':bool(wave_start.iloc[i])};anchor_uncertain=False
        else:anchor_uncertain=True
    return pd.DataFrame(rows)
