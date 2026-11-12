"""Only hidden native states are initialized; original Par component states reused."""
import copy,hashlib
from pathlib import Path
from native_state import NATIVE_CORE_SHA,new_state,append,digest
from environment import observed_environment


def initialize_from_original(kernel,document):
    rows=document['rows'];context=document['context'];bundle=document['bundle'];component=bundle['component109'];state51=bundle['state51'];symbol=context['symbol']
    if not rows or not (bundle['symbol']==component['symbol']==state51['symbol']==symbol):raise ValueError('REUSE_ORIGINAL_SYMBOL')
    if not (len(rows)==component['count']==state51['count'] and rows[-1]['event_date']==bundle['asof']==component['last_date']==str(state51['last_date'])==context['asof']):raise ValueError('REUSE_ORIGINAL_COUNT_ASOF')
    if component['schema']!='ORIGINAL109_LATEST_COMPONENT_STATE_V1' or component['original_pins']!=kernel.pins:raise ValueError('REUSE_ORIGINAL_CODE_PINS')
    for key in ('foundation','n_score'):
        if component[key]['count']!=len(rows) or component[key]['last_date']!=context['asof']:raise ValueError('REUSE_COMPONENT_BOUNDARY:'+key)
    # The Loader authenticated the complete recursive source references and
    # original self-hashes. Preserve the actual state51 strings verbatim.
    source_binding=copy.deepcopy(document['source_binding']);num=kernel.steps['numeric'](rows)
    binding={**source_binding,'native_core_sha256':NATIVE_CORE_SHA,'initialized_numeric_prefix_sha256':digest(num)}
    native=new_state(symbol,binding)
    for row in num:append(native,row,initialization=True)
    return dict(schema='par.all109.native_recovery.candidate.v1',product_kind='NEW_RECOVERY_PRODUCT_NOT_HISTORIC_ORIGINAL',symbol=symbol,count=len(rows),asof=context['asof'],context=copy.deepcopy(context),source_binding=source_binding,environment_binding=observed_environment(),code_binding=copy.deepcopy(kernel.code_binding),initialization_driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),original_rows=copy.deepcopy(rows),native_state=native,component109=copy.deepcopy(component),original_state51=copy.deepcopy(state51),latest109=None,detector_dependency_closed=False,all109_compatibility_certified=False,
      counters=dict(original_full_prefix_initializations=0,native_full_prefix_initializations=0,native_hidden_state_initialization_rows=len(rows),original51_recomputations=0,original_foundation_history_recomputations=0,original_n_score_history_recomputations=0,daily_rows=0,historical_primitive_rows_recomputed_daily=0),RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
