"""Install an exact frozen interpreter/library closure only with --apply.

No network/package installer, no service changes, and no overwrites. The
controller supplies the locally frozen plan after independent review.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

V4_RUNTIME = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime')
PROBE = '''import sys,sysconfig,json,importlib.metadata as m; print(json.dumps({"version_info":list(sys.version_info[:3]),"base_prefix":sys.base_prefix,"purelib":sysconfig.get_path("purelib"),"packages":sorted([{"name":d.metadata.get("Name"),"version":d.version} for d in m.distributions()],key=lambda d:(d["name"] or "").lower())}))'''


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _probe(executable):
    env={k:v for k,v in os.environ.items() if not k.startswith('PYTHON')}
    p=subprocess.run([str(executable),'-I','-B','-c',PROBE],check=True,capture_output=True,text=True,timeout=60,env=env)
    return json.loads(p.stdout)


def _target(path):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts or path.resolve(strict=False)!=path:
        raise ValueError('RUNTIME_TARGET_ALIAS')
    path.relative_to(V4_RUNTIME)
    current=path
    while current != V4_RUNTIME.parent:
        if current.is_symlink():raise ValueError('RUNTIME_TARGET_PARENT_SYMLINK')
        current=current.parent
    return path


def _copy_exact(source, target):
    """Internal symlinks remain internal; old external aliases are physical copies."""
    source=Path(source).resolve(strict=True);target=_target(target)
    if target.exists():raise ValueError('RUNTIME_TARGET_EXISTS:'+str(target))
    shutil.copytree(source,target,symlinks=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for directory,dirs,files in os.walk(target,followlinks=False):
        for name in dirs+files:
            dest=Path(directory)/name
            if not dest.is_symlink():continue
            original=source/dest.relative_to(target);raw=os.readlink(original)
            resolved=original.resolve(strict=True)
            try:
                inside=resolved.relative_to(source)
            except ValueError:
                # System libraries are allowed; executable/library aliases into old V3 roots are not.
                if str(resolved).startswith(('/System/','/usr/lib/')):continue
                dest.unlink()
                if resolved.is_dir():shutil.copytree(resolved,dest,symlinks=False)
                else:shutil.copy2(resolved,dest)
            else:
                if Path(raw).is_absolute():
                    dest.unlink();dest.symlink_to(os.path.relpath(target/inside,dest.parent),target_is_directory=resolved.is_dir())



def _create_venv(source, base_binary, target):
    """Keep the source layout, with interpreter links confined to copied V4 base."""
    source, base_binary, target = Path(source), Path(base_binary), Path(target)
    resolved_base = base_binary.resolve(strict=True)
    if not resolved_base.is_relative_to(V4_RUNTIME):
        raise ValueError('RUNTIME_VENV_BASE_OUTSIDE_V4')
    if target.exists() or target.is_symlink():
        raise ValueError('RUNTIME_DESTINATION_ALREADY_EXISTS')
    layout = '--symlinks' if source.is_symlink() else '--copies'
    subprocess.run([str(base_binary),'-I','-B','-m','venv','--without-pip',layout,str(target)],check=True,timeout=60)
    if layout == '--symlinks':
        python = target / 'bin/python'
        if not python.is_symlink() or python.resolve(strict=True) != resolved_base:
            raise ValueError('RUNTIME_VENV_LINK_OUTSIDE_COPIED_BASE')
        for alias in (target / 'bin').glob('python*'):
            if alias.is_symlink() and alias.resolve(strict=True) != resolved_base:
                raise ValueError('RUNTIME_VENV_LINK_OUTSIDE_COPIED_BASE')
    return layout.removeprefix('--')


def install(item, *, apply=False):
    source=Path(item['source_executable']);target=_target(item['target_venv']);base=_target(item['target_base'])
    if _hash(source.resolve(strict=True)) != item['binary_sha256']:
        raise ValueError('RUNTIME_SOURCE_BINARY_DRIFT')
    before=_probe(source)
    if before['version_info']!=item['version_info'] or before['packages']!=item['packages']:
        raise ValueError('RUNTIME_SOURCE_LIBRARY_VERSION_DRIFT')
    result={'component':item['component'],'source':str(source),'target':str(target),'source_version_and_packages_match':True,'status':'PLAN_VERIFIED_NOT_INSTALLED'}
    if not apply:return result
    if target.exists() or base.exists():raise ValueError('RUNTIME_DESTINATION_ALREADY_EXISTS')
    _copy_exact(Path(before['base_prefix']),base)
    base_binary=base/'bin'/('python'+'.'.join(map(str,item['version_info'][:2])))
    if not base_binary.is_file():raise ValueError('RUNTIME_COPIED_BASE_BINARY_MISSING')
    target.parent.mkdir(parents=True,exist_ok=True)
    layout = _create_venv(source, base_binary, target)
    actual=_probe(target/'bin/python');site=Path(actual['purelib']);source_site=Path(item['purelib']).resolve(strict=True)
    # venv --without-pip creates an empty site-packages. Copy only exact frozen libraries.
    for p in source_site.iterdir():
        if p.name=='__pycache__':continue
        dest=site/p.name
        if dest.exists():raise ValueError('RUNTIME_SITE_COLLISION:'+p.name)
        if p.is_dir():shutil.copytree(p.resolve(strict=True),dest,symlinks=False,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        else:shutil.copy2(p.resolve(strict=True),dest)
    # Base Python may expose other packages from its own base site. Identity check remains exact.
    after=_probe(target/'bin/python')
    if after['version_info']!=item['version_info'] or after['packages']!=item['packages']:
        raise ValueError('RUNTIME_INSTALLED_CLOSURE_MISMATCH')
    if not Path(after['base_prefix']).resolve().is_relative_to(V4_RUNTIME):
        raise ValueError('RUNTIME_BASE_OUTSIDE_V4')
    if _hash((target/'bin/python').resolve(strict=True))!=item['binary_sha256']:
        raise ValueError('RUNTIME_INSTALLED_BINARY_MISMATCH')
    result.update(status='INSTALLED_EXACT_VERSION_CLOSURE',base_prefix=after['base_prefix'],binary_sha256=item['binary_sha256'],package_count=len(after['packages']),venv_layout=layout)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--component',required=True);parser.add_argument('--apply',action='store_true');parser.add_argument('--receipt',type=Path,required=True);args=parser.parse_args()
    plan=json.loads(args.plan.read_text());matches=[x for x in plan['items'] if x['component']==args.component]
    if len(matches)!=1:raise ValueError('RUNTIME_COMPONENT_UNKNOWN_OR_DUPLICATE')
    result=install(matches[0],apply=args.apply)
    with args.receipt.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
