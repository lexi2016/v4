"""Incrementally repair the existing KB rebuild field from the fixed source.

Source: complex_patterns.py SHA-256
304544550c0a6cd34231a3f883c6c44a5ff881bc19c65f80cb2a5d7d9aec698d.
This is a research observation; incomplete history and invalid inputs stay null.
"""
from __future__ import annotations

import math
import pandas as pd


SOURCE_SHA256='304544550c0a6cd34231a3f883c6c44a5ff881bc19c65f80cb2a5d7d9aec698d'


def _finite(value):
    try:return math.isfinite(float(value))
    except (TypeError,ValueError,OverflowError):return False


def project_rebuild(frame):
    """Evaluate only the fixed rebuild rule over the complete ordered prefix."""
    required={'trade_date','close','volume','pct_chg'}
    if not required.issubset(frame.columns):raise ValueError('KB_REBUILD_INPUT_MISSING')
    dates=[int(x) for x in frame['trade_date']]
    if dates!=sorted(dates) or len(set(dates))!=len(dates):raise ValueError('KB_REBUILD_DATES_INVALID')
    close=pd.to_numeric(frame['close'],errors='coerce').reset_index(drop=True)
    vol=pd.to_numeric(frame['volume'],errors='coerce').reset_index(drop=True)
    pct=pd.to_numeric(frame['pct_chg'],errors='coerce').reset_index(drop=True)
    yellow=sum(close.rolling(n,min_periods=n).mean() for n in (14,28,57,114))/4
    output=[]
    for i in range(len(frame)):
        if i<123 or not all(_finite(x) for x in (close[i],yellow[i],yellow[i-4],yellow[i-9])) or yellow[i]<=0:
            output.append(None);continue
        start=i-14
        if any(not _finite(vol[j]) or vol[j]<0 or not _finite(pct[j]) for j in range(start,i+1)):
            output.append(None);continue
        surge=None
        # The fixed source starts at the second item in the last 15 bars and
        # divides by five even where that local prefix contains fewer bars.
        for j in range(start+1,i+1):
            mean=sum(vol[k] for k in range(max(start,j-5),j))/5
            if pct[j]>5 and vol[j]>mean*1.5:
                surge=vol[j];break
        if surge is None:
            output.append(False);continue
        output.append(bool(vol[i]<surge*.6 and abs(close[i]-yellow[i])/yellow[i]<.02 and yellow[i-4]>yellow[i-9]))
    return output
