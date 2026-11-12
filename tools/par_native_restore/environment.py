"""Observed local runtime identity; no inferred original Cloud compatibility."""
import importlib.metadata,os,platform,sys


def observed_environment():
    versions={}
    for name in ('numpy','pandas','pyarrow'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]='NOT_INSTALLED'
    return dict(PANEL_PYTHON=os.environ.get('PANEL_PYTHON','UNKNOWN'),actual_python=sys.executable,python_version=platform.python_version(),platform=platform.platform(),packages=versions,original_cloud_runtime='UNKNOWN_NOT_PINNED_BY_AVAILABLE_EVIDENCE',cross_machine_bit_compatibility='CANNOT_CONFIRM',oracle_scope='CURRENT_MAC_ENVIRONMENT_AND_PINNED_ORIGINAL_SOURCE_ONLY')
