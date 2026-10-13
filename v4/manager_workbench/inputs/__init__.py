"""Authority adapters are injected; B owns public InputBatch and persistence."""
from .authority import load_inputs as _load_inputs


def load_inputs(context, adapters):
    values = _load_inputs(context, adapters)
    try:
        from v4.manager_workbench.contracts import InputBatch
    except ModuleNotFoundError as exc:
        if exc.name not in ("v4.manager_workbench.contracts", "v4.manager_workbench"):
            raise
        return values
    return {lane: InputBatch.model_validate(value) for lane,value in values.items()}

__all__ = ["load_inputs"]
