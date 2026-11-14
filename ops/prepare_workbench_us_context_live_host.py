"""Transplant the reviewed US card reader into the exact active workbench host."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from infrastructure.owned_io import SafeRoot


HOST_NAME = 'research_workbench_host.py'
ACTIVE_HOST_SHA256 = '596837e342a38563b514d7b1fa032249bf70d6c215db5904c1c6706714068b5b'
CANDIDATE_HOST_SHA256 = 'dd12a080969c1cf14e739cad1b58f3f641de77f4ef36ac87a45d3041e68d1ab4'
REVIEWED_HOST = Path(__file__).resolve().parents[1] / 'infrastructure' / HOST_NAME
REQUEST_IMPORT = 'from starlette.requests import Request\n'
US_IMPORT = 'from infrastructure.research_workbench_us_context import standalone_benchmarks, us_context_dates\n'
US_METHOD = '    def _standalone_us_context(self, observation):\n'
CONTEXT_METHOD = '    def source_context(self,source_date,revision=None):\n'
CONTEXT_FIELDS = "intraday_status='UNKNOWN',**FLAGS)"


def _replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError('WORKBENCH_US_LIVE_HOST_PATCH_SITE_CONFLICT')
    return source.replace(old, new, 1)


def transplant(active, reviewed):
    if sha256(active).hexdigest() != ACTIVE_HOST_SHA256:
        raise ValueError('WORKBENCH_US_LIVE_HOST_BASE_SHA_MISMATCH')
    if sha256(reviewed).hexdigest() != CANDIDATE_HOST_SHA256:
        raise ValueError('WORKBENCH_US_LIVE_HOST_REVIEWED_SHA_MISMATCH')
    source = active.decode()
    candidate = reviewed.decode()
    start = candidate.index(US_METHOD)
    stop = candidate.index(CONTEXT_METHOD, start)
    method = candidate[start:stop]
    if method.count('except SOURCE_ERRORS') != 2 or candidate.count(US_IMPORT) != 1:
        raise ValueError('WORKBENCH_US_LIVE_HOST_REVIEWED_TOPOLOGY_CONFLICT')
    method = method.replace('except SOURCE_ERRORS', 'except (ValueError, OSError, KeyError, TypeError)')
    source = _replace(source, REQUEST_IMPORT, REQUEST_IMPORT + US_IMPORT)
    source = _replace(source, CONTEXT_METHOD, method + CONTEXT_METHOD)
    start = source.index(CONTEXT_METHOD)
    stop = source.index('    def _owner_execution(', start)
    context = source[start:stop]
    if context.count(CONTEXT_FIELDS) != 2:
        raise ValueError('WORKBENCH_US_LIVE_HOST_RETURN_CONFLICT')
    for argument in ("version['observation_date']", 'observation'):
        context = context.replace(
            CONTEXT_FIELDS, f"intraday_status='UNKNOWN',**self._standalone_us_context({argument}),**FLAGS)", 1,
        )
    result = source[:start] + context + source[stop:]
    compile(result, HOST_NAME, 'exec')
    return result.encode()


def prepare(active, output):
    if (not output.is_absolute() or not output.parent.is_dir() or output.parent.resolve() != output.parent
            or output.name != HOST_NAME):
        raise ValueError('WORKBENCH_US_LIVE_HOST_FRESH_OUTPUT_REQUIRED')
    patched = transplant(active.read_bytes(), REVIEWED_HOST.read_bytes())
    SafeRoot(output.parent).write_bytes(output.name, patched, require_absent=True)
    return {'path': str(output), 'base_sha256': ACTIVE_HOST_SHA256, 'sha256': sha256(patched).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--active', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.active, args.output), sort_keys=True))
