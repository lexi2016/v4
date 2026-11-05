"""Pinned CPU classes and restricted pickle restoration for the Phase5.9 package."""
from __future__ import annotations
import __future__, ast, ctypes, hashlib, importlib.util, io, pickle, sys, types
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import linalg,optimize,special

OUT=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105')
CPU=OUT/'cpu_original'; MODEL=CPU/'models/V193_ALL_A_V3_1'
SOURCES={'P5_8_MODEL_ENGINE':('P5_8_MODEL_ENGINE.py','42e9588683288a6908dac5aac396b400cb27cc61cddf7443a24b488f9996a1f8'),
 'P5_9_TRANSFER_ADAPTIVE_ENGINE':('P5_9_TRANSFER_ADAPTIVE_ENGINE.py','0999f035fd34653fdb365cd22563178c004561052b3cf7cc740105e17390f6de')}
CLASSES={'P5_8_MODEL_ENGINE':['VectorizedPreprocessor','NumpyRidgeElasticNet','RandomFourierKernelRidge','NumpyHistGBDT','PAVAIsotonicCalibrator','PlattCalibrator','StandardBackboneModel'],
 'P5_9_TRANSFER_ADAPTIVE_ENGINE':['EmpiricalBayesAdaptiveMixedModelV31']}
MODEL_SHA={'model_t1_v3_1_all_a.pkl':'f7b0a66814a0b5eb3bc53c466990390f6307c58fb5fa92142d8591ff103a4275',
 'model_t2_v3_1_all_a.pkl':'9e11c7b2003ca756c597aef30bc04bd41f08928df278969ec501ea20c57c318f',
 'model_t5_v3_1_all_a.pkl':'522cdb4f704c227fa61c8cc702a46f57fe3b2249a8ae78b386ebf258e20f2548',
 'model_fail_risk_v3_1_all_a.pkl':'885a46ca3c9a116d436505005759df6faa7a12ba6e49a42d42ad3ea4d37ae8d1',
 'calibrators_pava_platt_v3_1.pkl':'4847dde9a0dfcf9a921b193048c4fbf7e2980aeea087aeb6b2f09100a9ca89cb'}

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def source(name):
    file,expected=SOURCES[name];path=CPU/'src'/file
    if sha(path)!=expected:raise ValueError('PINNED_ENGINE_SOURCE_CHANGED:'+str(path))
    return path

def audited_classes(name,scope):
    path=source(name);tree=ast.parse(path.read_text());allowed=CLASSES[name]
    selected=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in allowed]
    if {n.name for n in selected}!=set(allowed):raise ValueError('ENGINE_CLASS_SET_MISMATCH:'+name)
    for cls in selected:
        if cls.decorator_list or cls.bases or cls.keywords:raise ValueError('ENGINE_CLASS_HEADER_UNEXPECTED')
        for n in ast.walk(cls):
            if isinstance(n,(ast.Import,ast.ImportFrom,ast.Global,ast.Nonlocal)):raise ValueError('ENGINE_CLASS_UNSAFE_NODE')
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
                if n.name in ('__setstate__','__reduce__','__reduce_ex__','__new__'):raise ValueError('ENGINE_UNSAFE_PICKLE_METHOD')
                if any(not isinstance(d,ast.Name) or d.id not in ('staticmethod','classmethod') for d in n.decorator_list):raise ValueError('ENGINE_DECORATOR_UNEXPECTED')
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('open','eval','exec','compile','__import__','input'):raise ValueError('ENGINE_UNSAFE_CALL')
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('CDLL','system','popen','Popen'):raise ValueError('ENGINE_UNSAFE_ATTRIBUTE_CALL')
    module=types.ModuleType(name);module.__dict__.update(scope);module.__dict__['_lib_gbdt']=None
    sys.modules[name]=module
    ast.fix_missing_locations(tree:=ast.Module(body=selected,type_ignores=[]))
    exec(compile(tree,str(path),'exec',flags=__future__.annotations.compiler_flag,dont_inherit=True),module.__dict__)
    return module

def install_compat():
    base={'np':np,'pd':pd,'linalg':linalg,'optimize':optimize,'special':special,'ctypes':ctypes}
    p58=audited_classes('P5_8_MODEL_ENGINE',base)
    scope={**base,'p58_eng':p58,**{x:getattr(p58,x) for x in CLASSES['P5_8_MODEL_ENGINE']}}
    p59=audited_classes('P5_9_TRANSFER_ADAPTIVE_ENGINE',scope)
    return p58,p59

def install_original_reference():
    # Independent, pinned upstream reference in a separate process. Never load
    # a platform-specific dynamic library from the cloud author's old path.
    if Path('/working_dir/c_fca2c6c6c6185857/work/fast_gbdt.so').exists():raise ValueError('UNEXPECTED_EXTERNAL_NATIVE_LIBRARY_PRESENT')
    source('P5_8_MODEL_ENGINE');path=source('P5_9_TRANSFER_ADAPTIVE_ENGINE')
    spec=importlib.util.spec_from_file_location('P5_9_TRANSFER_ADAPTIVE_ENGINE',path)
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    if mod.p58_eng._lib_gbdt is not None:raise ValueError('NATIVE_ACCELERATION_NOT_ALLOWED')
    return mod.p58_eng,mod

class RestrictedUnpickler(pickle.Unpickler):
    def find_class(self,module,name):
        if module in CLASSES and name in CLASSES[module]:return getattr(sys.modules[module],name)
        allowed={('numpy._core.multiarray','_reconstruct'):np._core.multiarray._reconstruct,('numpy','ndarray'):np.ndarray,('numpy','dtype'):np.dtype}
        if (module,name) in allowed:return allowed[(module,name)]
        raise pickle.UnpicklingError(f'PICKLE_GLOBAL_NOT_ALLOWED:{module}.{name}')
    def persistent_load(self,pid):raise pickle.UnpicklingError('PERSISTENT_PICKLE_REFERENCE_NOT_ALLOWED')

def load(path,expected_sha):
    path=Path(path);b=path.read_bytes()
    if hashlib.sha256(b).hexdigest()!=expected_sha:raise ValueError('MODEL_HASH_MISMATCH:'+str(path))
    return RestrictedUnpickler(io.BytesIO(b)).load()
