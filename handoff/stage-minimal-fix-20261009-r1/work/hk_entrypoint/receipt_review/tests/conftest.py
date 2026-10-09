"""Share only the independently constructed fixture with API protocol review."""
import importlib.util
from pathlib import Path
import sys

path = Path(__file__).resolve().parents[2] / "api_review/tests/conftest.py"
spec = importlib.util.spec_from_file_location("independent_stage_review_support", path)
support = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = support
spec.loader.exec_module(support)
runtime = support.runtime
DATE, STAGE = support.DATE, support.STAGE
json_bytes = support.json_bytes
