"""Single V4 review facade; explicit owned runtime, no legacy app loading."""

from .generation import (
    GENERATOR_SOURCE_ROOT_ENV,
    GenerationRefused,
    inspect_generator_source,
    prepare_payload,
    run_generation,
    write_exact_review,
)

__all__ = [
    "GENERATOR_SOURCE_ROOT_ENV",
    "GenerationRefused",
    "inspect_generator_source",
    "prepare_payload",
    "run_generation",
    "write_exact_review",
]


def __getattr__(name):
    """Lazy public assembly exports; package import performs no data/provider IO."""
    if name == "VibeRuntime":
        from .owned_runtime import VibeRuntime
        return VibeRuntime
    if name == "assemble_runtime":
        from .assembly import assemble_runtime
        return assemble_runtime
    raise AttributeError(name)
