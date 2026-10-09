# Source and review evidence attachment

This bundle contains mechanism source plus the PR5 accepted RFF truth-join worker, its scoped test, and the independent Mac review receipt. It excludes candidate score files, Top3 rows, model files, labels, truth rows, datasets, and registries.

The RFF worker at rff/pre_pr5_historical/src/rff_worker.py is the historical pre-PR5 copy (SHA256 cecff1218a60c3c67405168b742f40ba76286efbd2435d8f31703375c640619d). The accepted PR5 worker is separately stored at rff/pr5_accepted/src/rff_worker.py (SHA256 3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c). Do not conflate or substitute these copies.

PR5 evidence covers 29 synthetic truth-join cases only. Full worker/L04 behavior and the exact historical real failure keys remain unconfirmed. A future saved-evaluation binding must bind/reuse the accepted worker helper SHA. The XENDCG saved-evaluation sources are mechanism references; their current on-disk hashes may differ from the frozen XENDCG R2 input binding.
