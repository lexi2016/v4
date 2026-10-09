# Dependency closure evidence

The excerpts below are exact current source bytes copied into this local packet. Current file hashes are listed in SOURCE_IDENTITY_GAPS.json. Historical dependency SHA values remain CANNOT_CONFIRM where the prepared binding does not bind them.

## R2 contract dependency closure: /Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R2_CODE_20261009/candidate/src/rff_saved_eval_contracts.py

Full R2 file SHA256: e41ab4b41c8386875b14515e34c7609e108db17b538ed43eebe7f76fc3394ba6. The required executable-helper names are fixed in this block:

~~~python
 586 |     required = {"metadata_files": {"candidate_binding", "candidate_spec", "prediction_seal",
 587 |             "experiment_contract", "candidate_start", "candidate_terminal", "native_reference",
 588 |             "native_runtime_contract", "append_policy"},
 589 |         "executable_helpers": {"accepted_worker", "score_aware_metrics", "frozen_metrics",
 590 |             "frozen_settings", "frozen_package_init", "native_runtime", "resource_tree"},
 591 |         "official_helpers": {"execution_guard", "registry_adapter", "builder", "validator"}}
 592 |     for category, names in required.items():
 593 |         if set(binding.get(category, {})) != names:
 594 |             raise SavedEvaluationError(f"BOUND_DEPENDENCY_CLOSURE_MISMATCH:{category}")
 595 |     verify_sources(binding)
~~~

## R2 worker import allowlist and evaluator load: /Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R2_CODE_20261009/candidate/src/rff_saved_eval_worker.py

Full R2 file SHA256: c015246b4b3a21bcb69a1745e41516a9c19f694bf923dfb39553a920a96dfdd8. The worker rejects package modules whose origin is not present in its bound helper allowlist, then loads the evaluator at the cited call site.

~~~python
  75 |     common.load_bound_module(helpers["frozen_package_init"], "spike5", package=True)
  76 |     common.load_bound_module(helpers["frozen_settings"], "spike5.settings")
  77 |     metrics = common.load_bound_module(helpers["frozen_metrics"], "spike5.metrics")
  78 |     if score_aware.frozen_metrics() is not metrics:
  79 |         raise common.SavedEvaluationError("FROZEN_EVALUATOR_IMPORT_IDENTITY_MISMATCH")
  80 |     allowed = {Path(v["path"]).resolve() for v in helpers.values()}
  81 |     for name, module in list(sys.modules.items()):
  82 |         if name == "spike5" or name.startswith("spike5."):
  83 |             origin = Path(str(getattr(module, "__file__", ""))).resolve()
  84 |             if origin not in allowed:
  85 |                 raise common.SavedEvaluationError(f"UNBOUND_FROZEN_PACKAGE_DEPENDENCY:{name}:{origin}")

 164 |             raise common.SavedEvaluationError("SAVED_EVALUATION_INPUT_SET_MISMATCH")
 165 |         status["native_runtime_check_attempts"] = 1
 166 |         status["native_runtime_observation"] = _validate_child_runtime(common, binding, payload)
 167 |         status["native_runtime_checks_completed"] = 1
 168 |         frames, score_aware, accepted = _load_evaluators(common, binding)
 169 |         metadata = {name: common.json_object(common.checked_read(record, name=name), name=name)
 170 |                     for name, record in binding["metadata_files"].items()
~~~

## Durable start precedes monitored worker: /Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R2_CODE_20261009/candidate/src/run_rff_saved_evaluation.py

Full R2 file SHA256: 115f84e85777a3f002e01c441f62f0fe179adbac72e3c2ecdfaa91adbc5802ba. This shows why the missing dependency closure must be validated before RUN_STARTED.

~~~python
 330 |         claim = guard.claim_no_fit(execution_id=binding["execution_id"], arm=ARM,
 331 |             contract_sha256=binding["run_spec_sha256"], input_binding_sha256=input_binding_sha256)
 332 |     except BaseException as exc:
 333 |         start_error = _error(exc, "OFFICIAL_RUN_STARTED_APPEND")
 334 |         try:
 335 |             start_raw, own = _readback(common, adapter, binding, input_binding_sha256)
 336 |         except BaseException as readback_exc:
 337 |             common.write_json_exclusive(output / "EVALUATION_PRESTART_FAILURE.json", {
 338 |                 **identity, "status": "START_NOT_CONFIRMED_NO_WORKER_LAUNCHED", "error": start_error,
 339 |                 "readback_error": _error(readback_exc, "RUN_STARTED_SINGLE_READBACK"),
 340 |                 "automatic_retry": False, "safety": common.SAFETY})
 341 |             raise exc
 342 |         claim = guard_module.ExecutionClaim(experiment_id=binding["route_id"], execution_id=binding["execution_id"],
 343 |             arm=ARM, contract_sha256=binding["run_spec_sha256"], input_binding_sha256=input_binding_sha256,
 344 |             execution_kind="NO_FIT_ENGINEERING_CANARY", real_fit_budget_debit=0)
 345 |     try:
 346 |         if start_error is None:
 347 |             start_raw, own = _readback(common, adapter, binding, input_binding_sha256)
 348 |         start_sha = common.write_json_exclusive(Path(binding["start_receipt_path"]), {
 349 |             "schema": "F5_RFF_SAVED_EVAL_START_RECEIPT_V1", **identity,
 350 |             "status": "RUN_STARTED_DURABLE", "start_event_sha256": own[0]["event_sha256"],
 351 |             "official_registry_sha256_after_start": common.sha256_bytes(start_raw),
 352 |             "real_fit_budget_debit": 0, "planned_real_fit_count": 0, **common.ZERO_COUNTS,
 353 |             "historical_candidate_debits": {"fit": 1, "predict": 1, "truth_decode": 1},
 354 |             "start_append_raised_after_durable": start_error is not None,
 355 |             "safety": common.SAFETY, "automatic_retry": False})
 356 |         if start_error is not None:
 357 |             error = start_error
 358 |         else:
 359 |             drift = adapter._verify_contract_snapshots()
 360 |             if drift["files"]:
 361 |                 raise RuntimeError("BOUND_DEPENDENCY_OR_RELEASE_CHANGED_AFTER_START")
 362 |             payload = {**binding, "input_binding_sha256": input_binding_sha256,
 363 |                        "start_receipt_sha256": start_sha, "native_spec": native_spec}
 364 |             monitor_entered = True
 365 |             monitor_result = monitor(None, payload, native_spec=native_spec,
 366 |                 native_runtime_helper_path=Path(binding["executable_helpers"]["native_runtime"]["path"]),
 367 |                 wall_seconds_max=resources["wall_seconds_max"],
 368 |                 rss_bytes_max=resources["aggregate_process_tree_rss_bytes_max"], threads=resources["cpu_threads"],
 369 |                 sample_seconds=resources["sample_seconds"], resource_trace_path=trace,
~~~

## Frozen evaluator imports

The prepared helper is metrics.py and the same-package settings file has a current bound SHA. settings.py imports common.py and features.py, then reads two JSON contracts. The package tree establishes the direct path through common.py (ROOT is the parent of spike5).

~~~python
   1 | """Fixed-domain predictive metrics, not a P&L/backtest engine.
   2 | Unknown bounds are identification bounds, NOT confidence intervals.
   3 | AP is reported on known scored labels only; its denominator is explicit.
   4 | """
   5 | from __future__ import annotations
   6 | import math
   7 | import numpy as np
   8 | import pandas as pd
   9 | from sklearn.metrics import average_precision_score
  10 | from .settings import CONTRACT
  11 | 
  12 | 
  13 | def select_top3(frame):
  14 |     q=frame.loc[frame.scoreable.astype(bool)&np.isfinite(frame.probability)].copy()

   1 | from .common import ROOT,read_json
   2 | from .features import PATH_FEATURES
   3 | BASE_FEATURES=read_json(ROOT/'config/base_features.json')
   4 | FEATURES=BASE_FEATURES+PATH_FEATURES
   5 | CONTRACT=read_json(ROOT/'config/contract.json')
   6 | PARAMS=CONTRACT['learner']['params']
   7 | ROUNDS=CONTRACT['learner']['rounds']

   1 | from __future__ import annotations
   2 | import hashlib,json,os,tempfile
   3 | from pathlib import Path
   4 | import numpy as np
   5 | 
   6 | ROOT=Path(__file__).resolve().parents[1]
   7 | 
   8 | def sha(path):
   9 |     h=hashlib.sha256()
  10 |     with open(path,'rb') as f:
  11 |         for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
  12 |     return h.hexdigest()
  13 | 
  14 | def clean(x):
  15 |     if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
  16 |     if isinstance(x,(list,tuple)):return [clean(v) for v in x]
  17 |     if isinstance(x,np.ndarray):return clean(x.tolist())
  18 |     if isinstance(x,(np.integer,)):return int(x)
~~~

The direct dependencies are preserved as exact current byte snapshots in frozen_package_current_snapshot/. They are evidence for dependency closure repair, not proof that current bytes match any historical frozen version.
