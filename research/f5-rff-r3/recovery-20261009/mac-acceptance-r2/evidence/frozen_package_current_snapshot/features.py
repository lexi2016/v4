"""Thirty continuous descriptors of an exact 60-row visible OHLC/activity prefix.
No event IDs, boolean P1-P4 labels, outcomes or whole-history normalizers.
Activity is the frozen raw amount series, not certified shares or money flow.
"""
from __future__ import annotations
import numpy as np

PATH_FEATURES=[
 'path_displacement_10','path_displacement_20','path_displacement_60',
 'path_close_range_10','path_close_range_20','path_close_range_60',
 'path_drawdown_20','path_drawdown_60','path_efficiency_20','path_efficiency_60',
 'path_compression_10v20','path_activity_10v20','path_peak_activity_share_30',
 'path_range_location_30','path_rebound_from_trough_60','path_below_peak_60',
 'path_max_return_60','path_min_return_60',
 'path_pulse_activity_ratio','path_pulse_age_60','path_pulse_return',
 'path_pulse_retention','path_pulse_cooling_5',
 'path_lower_reclaim_depth_mean_30','path_upper_rejection_depth_mean_30',
 'path_low_slope_20','path_volatility_10v20','path_down_up_activity_30',
 'path_lower_reclaim_fraction_30','path_upper_rejection_fraction_30']


def _ratio(a,b):
    a,b=np.broadcast_arrays(a,b);o=np.full(a.shape,np.nan,dtype=float)
    np.divide(a,b,out=o,where=np.isfinite(a)&np.isfinite(b)&(b!=0))
    return o


def continuous_path_many(windows):
    w=np.asarray(windows,dtype=np.float64)
    if w.ndim!=3 or w.shape[1:]!=(60,5):raise ValueError('expected (n,60,5) OHLC/activity')
    n=len(w);op,hi,lo,c,a=[w[:,:,i].copy() for i in range(5)]
    for x in (op,hi,lo,c):x[~np.isfinite(x)|(x<=0)]=np.nan
    a[~np.isfinite(a)|(a<0)]=np.nan
    out={}
    for k in (10,20,60):
        z=c[:,-k:]
        out[f'path_displacement_{k}']=_ratio(z[:,-1],z[:,0])-1
        out[f'path_close_range_{k}']=_ratio(z.max(1),z.min(1))-1
        good=np.isfinite(z).all(1)
        for nm in (f'path_displacement_{k}',f'path_close_range_{k}'):
            out[nm][~good]=np.nan
    for k in (20,60):
        z=c[:,-k:];chg=np.diff(np.log(z),axis=1)
        out[f'path_drawdown_{k}']=(_ratio(z,np.maximum.accumulate(z,axis=1))-1).min(1)
        distance=np.abs(chg).sum(1)
        eff=_ratio(np.abs(chg.sum(1)),distance)
        eff[(distance==0)&np.isfinite(z).all(1)]=0.
        out[f'path_efficiency_{k}']=eff
    recent=c[:,-10:];earlier=c[:,-30:-10]
    out['path_compression_10v20']=_ratio(_ratio(recent.max(1),recent.min(1))-1,
                                                   _ratio(earlier.max(1),earlier.min(1))-1)
    out['path_activity_10v20']=_ratio(np.median(a[:,-10:],axis=1),np.median(a[:,-30:-10],axis=1))
    out['path_peak_activity_share_30']=_ratio(a[:,-30:].max(1),a[:,-30:].sum(1))
    z=c[:,-30:];out['path_range_location_30']=_ratio(z[:,-1]-z.min(1),z.max(1)-z.min(1))
    out['path_rebound_from_trough_60']=_ratio(c[:,-1],c.min(1))-1
    out['path_below_peak_60']=_ratio(c[:,-1],c.max(1))-1
    ret=_ratio(c[:,1:],c[:,:-1])-1
    out['path_max_return_60']=ret.max(1);out['path_min_return_60']=ret.min(1)
    # One deterministic anchor: strongest activity-weighted positive impulse in [-40,-6].
    candidates=[];ratios=[];rets=[]
    for i in range(20,55):
        ar=_ratio(a[:,i],np.median(a[:,i-10:i],axis=1));rr=ret[:,i-1]
        strength=rr*np.log1p(ar)
        strength[~np.isfinite(strength)|(rr<=0)|(ar<=0)]=-np.inf
        candidates.append(strength);ratios.append(ar);rets.append(rr)
    strengths=np.column_stack(candidates);choice=np.argmax(strengths,axis=1)
    usable=np.isfinite(strengths.max(1));ix=choice+20;row=np.arange(n)
    ar=np.column_stack(ratios)[row,choice];rr=np.column_stack(rets)[row,choice]
    pc=c[row,ix];before=c[row,ix-1];pa=a[row,ix]
    vals=[ar,(59-ix)/60,rr,_ratio(c[:,-1]-before,pc-before),_ratio(np.median(a[:,-5:],axis=1),pa)]
    for nm,v in zip(PATH_FEATURES[18:23],vals):
        v=np.asarray(v,dtype=float);v[~usable]=np.nan;out[nm]=v
    good_candle=(np.isfinite(op)&np.isfinite(hi)&np.isfinite(lo)&np.isfinite(c)
                 &(hi>=np.maximum.reduce([op,c,lo]))&(lo<=np.minimum.reduce([op,c,hi])))
    recl=[];reject=[];rdepth=[];udepth=[]
    for i in range(30,60):
        prior=c[:,i-10:i];mn=prior.min(1);mx=prior.max(1)
        valid=good_candle[:,i]&np.isfinite(prior).all(1)
        hitlo=(lo[:,i]<mn)&(c[:,i]>=mn);hithi=(hi[:,i]>mx)&(c[:,i]<=mx)
        dl=np.where(hitlo,_ratio(mn-lo[:,i],mn),0.)
        du=np.where(hithi,_ratio(hi[:,i]-mx,mx),0.)
        rl=hitlo.astype(float);rh=hithi.astype(float)
        for v in (dl,du,rl,rh):v[~valid]=np.nan
        recl.append(rl);reject.append(rh);rdepth.append(dl);udepth.append(du)
    out['path_lower_reclaim_depth_mean_30']=np.column_stack(rdepth).mean(1)
    out['path_upper_rejection_depth_mean_30']=np.column_stack(udepth).mean(1)
    out['path_lower_reclaim_fraction_30']=np.column_stack(recl).mean(1)
    out['path_upper_rejection_fraction_30']=np.column_stack(reject).mean(1)
    lowlog=np.log(lo[:,-20:]);t=np.arange(20)-9.5
    out['path_low_slope_20']=(lowlog*t).sum(1)/(t*t).sum()
    logr=np.diff(np.log(c),axis=1)
    out['path_volatility_10v20']=_ratio(logr[:,-10:].std(1,ddof=1),logr[:,-30:-10].std(1,ddof=1))
    r=ret[:,-30:];aa=a[:,-30:]
    dn=_ratio(np.where(r<0,aa,0).sum(1),(r<0).sum(1))
    up=_ratio(np.where(r>0,aa,0).sum(1),(r>0).sum(1))
    v=_ratio(dn,up);v[~np.isfinite(aa).all(1)|~np.isfinite(r).all(1)]=np.nan
    out['path_down_up_activity_30']=v
    mat=np.column_stack([out[k] for k in PATH_FEATURES]);mat[~np.isfinite(mat)]=np.nan
    return mat.astype(np.float32)


def continuous_path(prefix):
    p=np.asarray(prefix)
    if p.shape!=(60,5):raise ValueError('exactly 60 rows are required')
    return dict(zip(PATH_FEATURES,map(float,continuous_path_many(p[None])[0])))


def path_matrix(raw):
    raw=np.asarray(raw,dtype=float)
    out=np.full((len(raw),len(PATH_FEATURES)),np.nan,np.float32)
    if len(raw)>=60:
        w=np.lib.stride_tricks.sliding_window_view(raw,60,axis=0).transpose(0,2,1)
        out[59:]=continuous_path_many(w)
    return out
