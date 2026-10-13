"""Authoritative inputs are injected; never pulled from a frontend or local path."""
from .authority import load_inputs
__all__ = ["load_inputs"]
