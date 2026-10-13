"""Read-only exact-date owner adapters."""
from .native import NativeAdapters
from .loader import load_inputs

__all__ = ["NativeAdapters", "load_inputs"]
