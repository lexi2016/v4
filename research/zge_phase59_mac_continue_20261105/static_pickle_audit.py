"""Statically enumerate protocol-4 globals; do not unpickle or execute archive code."""
import collections, hashlib,json,pickletools
from pathlib import Path

ROOT=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105')
MODEL=ROOT/'cpu_original/models/V193_ALL_A_V3_1'
ALLOWED={
 ('P5_9_TRANSFER_ADAPTIVE_ENGINE','EmpiricalBayesAdaptiveMixedModelV31'),
 *{('P5_8_MODEL_ENGINE',x) for x in ['VectorizedPreprocessor','NumpyRidgeElasticNet','RandomFourierKernelRidge','NumpyHistGBDT','StandardBackboneModel','PAVAIsotonicCalibrator','PlattCalibrator']},
 ('numpy._core.multiarray','_reconstruct'),('numpy','ndarray'),('numpy','dtype'),
}
receipt={}
for path in sorted(MODEL.glob('*.pkl')):
    raw=path.read_bytes();ops=list(pickletools.genops(raw));memo={};next_memo=0;globals_found=[];counts=collections.Counter();previous=None
    for index,(op,arg,pos) in enumerate(ops):
        counts[op.name]+=1
        if op.name=='MEMOIZE':
            if previous and previous[0].name in ('SHORT_BINUNICODE','BINUNICODE','UNICODE','BINUNICODE8'):memo[next_memo]=previous[1]
            elif previous and previous[0].name in ('BINGET','LONG_BINGET') and previous[1] in memo:memo[next_memo]=memo[previous[1]]
            next_memo+=1
        elif op.name=='STACK_GLOBAL':
            pushes=[]
            for prior,parg,_ in reversed(ops[max(0,index-8):index]):
                if prior.name in ('SHORT_BINUNICODE','BINUNICODE','UNICODE','BINUNICODE8'):pushes.append(parg)
                elif prior.name in ('BINGET','LONG_BINGET'):pushes.append(memo.get(parg))
                if len(pushes)==2:break
            if len(pushes)!=2 or None in pushes:raise ValueError(f'UNRESOLVED_STACK_GLOBAL:{path}:{pos}')
            pair=(pushes[1],pushes[0]);globals_found.append(pair)
            if pair not in ALLOWED:raise ValueError(f'PICKLE_GLOBAL_NOT_ALLOWED:{path}:{pair}')
        elif op.name in ('GLOBAL','EXT1','EXT2','EXT4','PERSID','BINPERSID'):
            raise ValueError(f'UNSUPPORTED_PICKLE_OPCODE:{path}:{op.name}:{pos}')
        previous=(op,arg)
    receipt[path.name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'protocol':ops[0][1],
      'globals':[{'module':a,'name':b} for a,b in globals_found],
      'opcode_counts':{k:counts[k] for k in ('STACK_GLOBAL','GLOBAL','EXT1','EXT2','EXT4','PERSID','BINPERSID','REDUCE','NEWOBJ','BUILD')},
      'status':'STATIC_ALLOWLIST_MATCH_NO_DESERIALIZATION'}
(ROOT/'STATIC_PICKLE_AUDIT.json').write_text(json.dumps({'files':receipt,'allowlist':[list(x) for x in sorted(ALLOWED)],'dynamic_restriction_required':True},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v['globals'] for k,v in receipt.items()},ensure_ascii=False))
