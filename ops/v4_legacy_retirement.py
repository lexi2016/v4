"""Bounded source namespace projection for owner-specific retirement candidates.

This module never activates services, executes producers, or moves user data.
Each candidate is derived from its own frozen current owner, with an exact
before/after delta receipt. Historical schemas, workload IDs and artifact names
remain unchanged so completed work is still completed after a service rename.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any

TEXT_SUFFIXES = {'.py', '.sh', '.ts', '.vue', '.js', '.html', '.css', '.toml', '.md', '.ps1'}
SKIP_PARTS = {'__pycache__', '.git', 'node_modules', '.venv', 'research_data', '_vendor', 'vendor'}
RENAMES = (
    ('v35_api', 'v4_api'),
    ('v35_native_evidence', 'v4_native_evidence'),
    ('v35_validators', 'v4_validators'),
    ('run_v35_', 'run_v4_'),
    ('launch_v35_', 'launch_v4_'),
    ('install_v35_', 'install_v4_'),
    ('v35_topology', 'v4_topology'),
    ('v35_bindings', 'v4_bindings'),
)
LABELS = {'com.lexi.v35.api-only': 'com.lexi.v4.api',
          'com.lexi.v35.scheduler': 'com.lexi.v4.scheduler',
          'com.lexi.v35.runtime-graph': 'com.lexi.v4.runtime-graph'}
OCR_FILES = ('wechat_macos_ocr.py', 'wechat_common.py', 'wechat_prepare_ocr.py')


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_child(root: Path, relative: str) -> Path:
    root = Path(os.path.abspath(root))
    if root.is_symlink() or root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError('RETIREMENT_ROOT_ALIAS')
    rel = Path(relative)
    if not relative or rel.is_absolute() or str(rel) != relative or '..' in rel.parts:
        raise ValueError('RETIREMENT_RELATIVE_INVALID')
    target = root / rel
    current = root
    for part in rel.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError('RETIREMENT_ANCESTOR_SYMLINK:' + str(current))
        if current != target and not stat.S_ISDIR(mode):
            raise ValueError('RETIREMENT_PARENT_NOT_DIRECTORY')
    if target.resolve(strict=False) != target:
        raise ValueError('RETIREMENT_DESTINATION_ALIAS')
    return target


def namespace_text(text: str) -> str:
    for old, new in RENAMES:
        text = text.replace(old, new)
    text = text.replace('validate_v35_semantics', 'validate_v4_semantics')
    text = text.replace('V35_', 'V4_').replace('_V35', '_V4')
    # This existing manual child explicitly exported both identical release aliases.
    text = text.replace('V4_RELEASE_ID=self.owner_identity["release_id"], V4_RELEASE_ID=self.owner_identity["release_id"]', 'V4_RELEASE_ID=self.owner_identity["release_id"]')
    text = re.sub(r'/api/v3(?=[/\"\'`?]|$)', '/api/v4', text)
    text = text.replace('V3.5', 'V4')
    text = text.replace('venvs/v3.5-mac', 'venvs/v4-mac')
    text = text.replace('venvs/v3.5-hk02', 'venvs/v4-hk02')
    # Exact active default literals only; full historical provenance paths stay immutable.
    text = text.replace('"com.lexi.v35.local"', '"com.lexi.v4.local"')
    text = text.replace("'com.lexi.v35.local'", "'com.lexi.v4.local'")
    text = text.replace('v35-announcement-cycle-hook', 'v4-announcement-cycle-hook')
    text = text.replace('v35-zsxq-pdf-queue-drain', 'v4-zsxq-pdf-queue-drain')
    for old, new in LABELS.items():
        text = text.replace(old, new)
    return text


def mapped_path(relative: str) -> str:
    for old, new in RENAMES:
        relative = relative.replace(old, new)
    return relative


def write_file(path: Path, raw: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for parent in (path.parent, *path.parents):
        if parent.is_symlink():
            raise ValueError('RETIREMENT_WRITE_PARENT_SYMLINK')
    oldmode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    if path.exists():
        path.chmod(oldmode | stat.S_IWUSR)
    path.write_bytes(raw)
    path.chmod(mode if mode is not None else oldmode)


def project_tree(root: Path, *, source_tree: bool = False) -> list[dict[str, Any]]:
    """Transform only business text files, never frozen data/contracts or vendor bytes."""
    changes = []
    files = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [n for n in dirs if n not in SKIP_PARTS and not (Path(directory)/n).is_symlink()]
        for n in names:
            p = Path(directory)/n
            rel = p.relative_to(root)
            if p.is_symlink() or p.suffix not in TEXT_SUFFIXES or any(v in SKIP_PARTS for v in rel.parts):
                continue
            if rel.parts[0] not in {'apps', 'contracts', 'domains', 'infrastructure', 'ops', 'stage_center', 'v4', 'tests', 'docs'} and str(rel) != 'pyproject.toml':
                continue
            if rel.parts[0] == 'docs' and str(rel) != 'docs/README.md':
                continue
            if p.name == 'v4_legacy_retirement.py' or p.name == 'api_namespace.py':
                continue
            files.append(p)
    for p in files:
        rel = str(p.relative_to(root));before=p.read_bytes()
        try:
            after = namespace_text(before.decode('utf-8')).encode('utf-8')
        except UnicodeDecodeError:
            continue
        destination = mapped_path(rel)
        # Two exact V3-owned OCR call sites; helper bytes themselves stay unmodified.
        if rel == 'infrastructure/zsxq_pdf_ingestion.py':
            after = re.sub(rb'VISION_OCR_SOURCE = Path\(\s*"/Users/lexi/Desktop/[^\n]+/v3_system/[^\n]+"\s*"scripts/wechat_macos_ocr.py"\s*\)',
                           b'VISION_OCR_SOURCE = Path(__file__).resolve().parents[1] / "components/wechat_ocr/wechat_macos_ocr.py"', after)
        if rel == 'ops/run_pdf_research_batch.py':
            after = re.sub(rb'V3_OCR_SCRIPTS_ROOT = Path\([^\n]+\)',
                           b'V3_OCR_SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "components/wechat_ocr"', after)
        if rel == 'pyproject.toml':
            after = after.replace(b'name = "v3-5"', b'name = "v4-app"')
        if 'apps/api/' in rel and p.name == 'app.py':
            marker = b'    return app\n'
            if after.count(marker) != 1:
                raise ValueError('API_APP_RETURN_NOT_UNIQUE')
            after = after.replace(marker, b'    from infrastructure.api_namespace import install_legacy_aliases\n    install_legacy_aliases(app)\n\n'+marker)
        if after != before or destination != rel:
            target = safe_child(root, destination)
            if destination != rel and target.exists():
                raise ValueError('RETIREMENT_RENAME_COLLISION:' + destination)
            write_file(target, after, stat.S_IMODE(p.stat().st_mode))
            if destination != rel:
                p.unlink()
            changes.append({'before_path':rel,'path':destination,'before_sha256':sha(before),'sha256':sha(after)})
    resource = root / 'apps/api/v35_api/a_share_lifecycle_notes.json'
    if resource.is_file():
        destination = safe_child(root, 'apps/api/v4_api/a_share_lifecycle_notes.json')
        if destination.exists():
            raise ValueError('RETIREMENT_RESOURCE_COLLISION')
        raw = resource.read_bytes()
        write_file(destination, raw, stat.S_IMODE(resource.stat().st_mode))
        resource.unlink()
        changes.append({'before_path': 'apps/api/v35_api/a_share_lifecycle_notes.json',
                        'path': 'apps/api/v4_api/a_share_lifecycle_notes.json',
                        'before_sha256': sha(raw), 'sha256': sha(raw)})
    # Remove only own empty namespace directories after per-file moves.
    for p in sorted(root.rglob('*'), key=lambda p:len(p.parts), reverse=True):
        if p.is_dir() and not p.is_symlink() and 'v35_api' in p.parts:
            try:p.rmdir()
            except OSError:pass
    return changes


def add_ocr_helpers(root: Path, source: Path) -> list[dict[str, Any]]:
    origins=[]
    for name in OCR_FILES:
        p=source/name
        if p.is_symlink() or p.resolve(strict=True)!=p or not p.is_file():
            raise ValueError('OCR_HELPER_SOURCE_ALIAS')
        raw=p.read_bytes();target=safe_child(root,'components/wechat_ocr/'+name)
        if target.exists() and target.read_bytes()!=raw:
            raise ValueError('OCR_HELPER_TARGET_DRIFT')
        write_file(target,raw,0o644)
        origins.append({'path':str(target.relative_to(root)),'origin':str(p),'sha256':sha(raw)})
    return origins
