"""Bounded, non-following source-copy policy shared by the two canary tools.

An external link can only be quarantined, never copied or dereferenced. The
policy is part of the exact SOURCE_MAP contract, not a command-line escape hatch.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile


POLICY = "CANARY_SOURCE_POLICY.json"
MANIFEST = "CANARY_SOURCE_MANIFEST.json"
IGNORED = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".cache"})
SHA = re.compile(r"[0-9a-f]{64}\Z")


def digest(raw):
    return sha256(raw).hexdigest()


def no_links(path):
    for component in reversed((path, *path.parents)):
        if component.is_symlink():
            raise ValueError(f"SYMLINK_PATH_COMPONENT:{component}")


def read_regular(path):
    no_links(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"NOT_REGULAR_FILE:{path}")
        return stream.read()


def _relative(value, *, allow_root=False):
    if allow_root and value == ".":
        return value
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or PurePosixPath(value).is_absolute() or str(PurePosixPath(value)) != value
            or any(part in {".", ".."} for part in PurePosixPath(value).parts)):
        raise ValueError("SOURCE_POLICY_RELATIVE_PATH_INVALID")
    return value


def load_policy(package, mapping, group, ignored):
    path = package / POLICY
    expected = mapping.get("canary_source_policy_sha256")
    if not os.path.lexists(path):
        if expected is not None:
            raise ValueError("SOURCE_POLICY_MISSING")
        return {"copy_roots": ["."], "optional_roots": [], "symlinks": {},
                "sha256": None, "ignored": frozenset(ignored)}
    raw = read_regular(path)
    if not isinstance(expected, str) or not SHA.fullmatch(expected) or digest(raw) != expected:
        raise ValueError("SOURCE_POLICY_SHA_MISMATCH")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_version") != "V4_CANARY_SOURCE_POLICY_V1":
        raise ValueError("SOURCE_POLICY_SCHEMA_INVALID")
    groups = value.get("groups")
    if not isinstance(groups, dict) or group not in groups or not isinstance(groups[group], dict):
        raise ValueError("SOURCE_POLICY_GROUP_MISSING")
    selected = groups[group]
    roots, optional = selected.get("copy_roots"), selected.get("optional_roots", [])
    if not isinstance(roots, list) or not roots or not isinstance(optional, list):
        raise ValueError("SOURCE_POLICY_ROOTS_INVALID")
    for item in [*roots, *optional]:
        _relative(item, allow_root=True)
        if any(part in ignored or part == MANIFEST for part in PurePosixPath(item).parts):
            raise ValueError("SOURCE_POLICY_ROOT_IGNORED")
    if len(set(roots + optional)) != len(roots + optional):
        raise ValueError("SOURCE_POLICY_ROOT_DUPLICATE")
    declarations = selected.get("symlinks", [])
    if not isinstance(declarations, list):
        raise ValueError("SOURCE_POLICY_LINKS_INVALID")
    links = {}
    for row in declarations:
        if not isinstance(row, dict):
            raise ValueError("SOURCE_POLICY_LINK_INVALID")
        relative = _relative(row.get("relative_path"))
        text, action = row.get("link_text"), row.get("action")
        if relative in links or not isinstance(text, str) or not text or "\x00" in text:
            raise ValueError("SOURCE_POLICY_LINK_INVALID")
        if action == "preserve_internal":
            _relative(text)
        elif action == "quarantine":
            if not Path(text).is_absolute() or ".." in Path(text).parts:
                raise ValueError("SOURCE_POLICY_EXTERNAL_LINK_INVALID")
        else:
            raise ValueError("SOURCE_POLICY_LINK_ACTION_INVALID")
        links[relative] = dict(row)
    return {"copy_roots": roots, "optional_roots": optional, "symlinks": links,
            "sha256": expected, "ignored": frozenset(ignored)}


def in_scope(relative, policy, *, ancestor=True):
    for root in policy["copy_roots"] + policy["optional_roots"]:
        if root == "." or relative == root or relative.startswith(root + "/"):
            return True
        if ancestor and (relative == "." or root.startswith(relative + "/")):
            return True
    return False


def _ignored(relative, policy):
    return (relative == MANIFEST or any(part in policy["ignored"] for part in PurePosixPath(relative).parts)
            or not in_scope(relative, policy))


def tree_id(entries):
    return digest(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode())


def snapshot(root, policy, *, candidate=False):
    """Read only selected roots; never walk through a symlink, including exclusions."""
    no_links(root)
    root_stat = root.stat()
    entries = {".": {"type": "directory", "mode": stat.S_IMODE(root_stat.st_mode)}}
    links, excluded = [], []
    for relative in policy["copy_roots"]:
        if relative != "." and not os.path.lexists(root / relative):
            raise ValueError(f"SOURCE_POLICY_REQUIRED_ROOT_MISSING:{relative}")
    pending = [root]
    while pending:
        directory = pending.pop()
        no_links(directory)
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            with os.scandir(descriptor) as children:
                names = sorted(entry.name for entry in children)
        finally:
            os.close(descriptor)
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if _ignored(relative, policy):
                excluded.append(relative)
                continue
            info = path.lstat()
            row = {"mode": stat.S_IMODE(info.st_mode)}
            declaration = policy["symlinks"].get(relative)
            if stat.S_ISLNK(info.st_mode):
                text = os.readlink(path)
                if declaration is None or text != declaration["link_text"]:
                    raise ValueError(f"SOURCE_TREE_SYMLINK_UNDECLARED_OR_CHANGED:{relative}")
                action = declaration["action"]
                if candidate and action == "quarantine":
                    raise ValueError(f"QUARANTINED_LINK_PRESENT_IN_CANDIDATE:{relative}")
                row.update(type="symlink", link_text=text, action=action)
                observed = {"relative_path": relative, "actual_path": str(path), "link_text": text,
                            "action": action, "device": info.st_dev, "inode": info.st_ino,
                            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
                            "target_contents_read": False}
                if action == "preserve_internal":
                    target = Path(os.path.normpath(str(path.parent / text)))
                    if root not in target.parents or not in_scope(target.relative_to(root).as_posix(), policy, ancestor=False):
                        raise ValueError(f"INTERNAL_LINK_TARGET_OUTSIDE_SOURCE_SET:{relative}")
                    no_links(target)
                    if not target.is_dir():
                        raise ValueError(f"INTERNAL_LINK_TARGET_NOT_DIRECTORY:{relative}")
                    target_stat = target.stat()
                    observed.update(lexical_target=str(target), target_relative_path=target.relative_to(root).as_posix(),
                                    target_device=target_stat.st_dev, target_inode=target_stat.st_ino)
                    row["target_relative_path"] = observed["target_relative_path"]
                else:
                    # Do not stat, resolve, list, or read the external target.
                    observed["lexical_target"] = text
                links.append(observed)
            elif declaration is not None:
                raise ValueError(f"DECLARED_SYMLINK_REPLACED_BY_NONLINK:{relative}")
            elif stat.S_ISDIR(info.st_mode):
                row["type"] = "directory"
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                row.update(type="file", sha256=digest(read_regular(path)))
            else:
                raise ValueError(f"SOURCE_TREE_SPECIAL_FILE:{relative}")
            entries[relative] = row
    return {"entries": entries, "links": links, "excluded_roots": sorted(excluded),
            "root_device": root_stat.st_dev, "root_inode": root_stat.st_ino}


def copy_entries(source_snapshot):
    return {name: dict(row) for name, row in source_snapshot["entries"].items()
            if row.get("action") != "quarantine"}


def copy_tree(source, destination, policy):
    def ignore(directory, names):
        skipped = []
        for name in names:
            relative = (Path(directory) / name).relative_to(source).as_posix()
            if _ignored(relative, policy) or policy["symlinks"].get(relative, {}).get("action") == "quarantine":
                skipped.append(name)
        return skipped
    shutil.copytree(source, destination, symlinks=True, ignore=ignore)


@contextmanager
def _writable_directory(root, path):
    """Only a directory inode already inside the new copy is temporarily writable."""
    if path != root and root not in path.parents:
        raise ValueError("CANDIDATE_WRITE_OUTSIDE_ROOT")
    no_links(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    original = stat.S_IMODE(os.fstat(descriptor).st_mode)
    try:
        if not original & stat.S_IWUSR:
            os.fchmod(descriptor, original | stat.S_IWUSR)
        yield
    finally:
        try:
            os.fchmod(descriptor, original)
        finally:
            os.close(descriptor)


def write_candidate(root, relative, raw, *, expected_sha256, mode):
    """Atomic replacement/addition with exact preimage and restored parent modes."""
    target = root / _relative(relative)
    no_links(target)
    for parent in reversed(target.parent.parents):
        if parent == root or root in parent.parents:
            if not parent.exists():
                with _writable_directory(root, parent.parent):
                    parent.mkdir(mode=0o755)
                    parent.chmod(0o755)
    if not target.parent.exists():
        with _writable_directory(root, target.parent.parent):
            target.parent.mkdir(mode=0o755)
            target.parent.chmod(0o755)
    if expected_sha256 is None:
        if os.path.lexists(target):
            raise ValueError(f"ADD_TARGET_ALREADY_EXISTS:{relative}")
    elif digest(read_regular(target)) != expected_sha256:
        raise ValueError(f"DESTINATION_PREIMAGE_CHANGED:{relative}")
    temporary = None
    with _writable_directory(root, target.parent):
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(raw)
                output.flush()
                os.fchmod(output.fileno(), mode)
            no_links(target)
            if expected_sha256 is None:
                # link() gives add no-overwrite semantics, including a concurrent add.
                os.link(temporary, target, follow_symlinks=False)
                temporary.unlink()
            else:
                if digest(read_regular(target)) != expected_sha256:
                    raise ValueError(f"DESTINATION_PREIMAGE_CHANGED:{relative}")
                os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def verify_manifest(root, policy, map_sha256, observed):
    path = root / MANIFEST
    if not os.path.lexists(path):
        return None
    raw = read_regular(path)
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != "V4_CANARY_SOURCE_MANIFEST_V1"
            or manifest.get("canary_source_policy_sha256") != policy["sha256"]
            or manifest.get("source_map_sha256") != map_sha256
            or manifest.get("candidate_tree_sha256") != tree_id(observed["entries"])):
        raise ValueError("CANDIDATE_SOURCE_MANIFEST_MISMATCH")
    return {"sha256": digest(raw), "manifest": manifest}
