"""infrastructure.scheduling.executor_registry: daily_reader (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _FixedExecutorRegistry__daily_materialize_body(_v4_scope, /, self, request):
    """Run the single 21:40 owner with explicit business/target dates."""
    module = "ops.daily_materialize"
    arguments = [
        "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
        "--business-date", request.business_date,
        "--target-date", request.target_date,
    ]
    if self.shared_data_root is not None:
        arguments.extend(["--shared-data-root", _v4_global(_v4_scope, 'str')(self.shared_data_root)])
    if self.selector_data_root is not None:
        arguments.extend(["--selector-data-root", _v4_global(_v4_scope, 'str')(self.selector_data_root)])
    if self.stage_selection_root is not None:
        arguments.extend(["--stage-selection-root", _v4_global(_v4_scope, 'str')(self.stage_selection_root)])
    generation_pointer = _v4_global(_v4_scope, 'str')(
        _v4_global(_v4_scope, 'os').environ.get("V35_RESEARCH_PANEL_A_FORMULA_GENERATION_POINTER") or ""
    ).strip()
    if generation_pointer:
        arguments.extend(["--formula-generation-pointer", generation_pointer])
    result = self._run(module, arguments)
    result["modules"] = [module]
    return result
