"""Pinned pure-Python PDF extraction preserving original page positions."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import sys
import threading
import time

_LOCK=threading.RLock()
_TREE='9d4f17bbe8a126246ae5bfbd23f72fe7c4fe8b18cb17450fba1783107d2020cd'
_LICENSE='a97ac230e5f33ef10a5367a850eb01f91f1a0b064e34742c7794d2294557f524'


def pinned_pypdf():
    root=Path(__file__).with_name('_vendor'); package=root/'pypdf'
    with _LOCK:
        manifest=json.loads((root/'DEPENDENCY_MANIFEST.json').read_text())
        files=sorted(p for p in package.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
        h=hashlib.sha256()
        for path in files: h.update(path.relative_to(package).as_posix().encode()+b'\0'+path.read_bytes()+b'\0')
        if (h.hexdigest()!=_TREE or manifest['package_tree_sha256']!=_TREE or manifest['file_count']!=len(files)
                or manifest['license_path']!='licenses/pypdf-6.10.0-LICENSE'
                or hashlib.sha256((root/'licenses/pypdf-6.10.0-LICENSE').read_bytes()).hexdigest()!=_LICENSE):
            raise ValueError('PDF_PINNED_DEPENDENCY_SHA_MISMATCH')
        existing=sys.modules.get('pypdf')
        if existing is not None:
            if Path(existing.__file__).resolve()!=package.joinpath('__init__.py').resolve():
                raise ValueError('PDF_FOREIGN_IMPORT_COLLISION')
            return existing
        spec=importlib.util.spec_from_file_location('pypdf',package/'__init__.py',submodule_search_locations=[str(package)])
        module=importlib.util.module_from_spec(spec);sys.modules['pypdf']=module
        try:
            spec.loader.exec_module(module)
            if module.__version__!='6.10.0': raise ValueError('PDF_PINNED_VERSION_MISMATCH')
        except Exception:
            for name in list(sys.modules):
                if name=='pypdf' or name.startswith('pypdf.'):sys.modules.pop(name,None)
            raise
        return module


def extract_pdf_pages(raw: bytes, *, max_pages=500, max_bytes=32*1024*1024,
                      max_characters=8_000_000, seconds=30, reader_factory=None):
    if not isinstance(raw,bytes) or not raw.startswith(b'%PDF') or len(raw)>max_bytes:
        raise ValueError('PDF_BYTES_INVALID_OR_LIMIT_EXCEEDED')
    if (type(max_pages) is not int or not 1<=max_pages<=500 or type(max_bytes) is not int or max_bytes<1
            or type(max_characters) is not int or max_characters<1
            or type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<=0): raise ValueError('PDF_BUDGET_INVALID')
    factory=reader_factory or pinned_pypdf().PdfReader
    start=time.monotonic(); reader=factory(BytesIO(raw),strict=False); total=len(reader.pages)
    if total<1 or total>max_pages: raise ValueError('PDF_REAL_PAGE_COUNT_INVALID_OR_LIMIT_EXCEEDED')
    pages=[]; characters=0
    for index in range(total):
        result=dict(page_number=index+1,page_total=total,text=None,status='FAILED',error=None)
        if time.monotonic()-start>=seconds:
            result['error']='PDF_COOPERATIVE_TIME_BUDGET_EXCEEDED'
        else:
            try:
                text=reader.pages[index].extract_text()
                if text is None: text=''
                if not isinstance(text,str): raise ValueError('PDF_PAGE_TEXT_TYPE_INVALID')
                characters+=len(text)
                if characters>max_characters: raise ValueError('PDF_TEXT_LIMIT_EXCEEDED')
                result.update(text=text,status='COMPLETE' if text.strip() else 'BLANK',
                    text_sha256=hashlib.sha256(text.encode()).hexdigest())
            except Exception as exc: result['error']=str(exc)[:200]
        pages.append(result)
    complete=all(p['status']=='COMPLETE' for p in pages)
    return dict(pdf_sha256=hashlib.sha256(raw).hexdigest(),page_count=total,pages=pages,
        complete=complete,page_coverage_complete=len(pages)==total,
        nonempty_page_count=sum(p['status']=='COMPLETE' for p in pages),
        gaps=sorted({p['error'] or 'PDF_BLANK_PAGE_REQUIRES_CONFIRMATION' for p in pages if p['status']!='COMPLETE'}))
