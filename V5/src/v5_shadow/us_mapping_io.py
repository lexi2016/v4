"""Constrain original owner I/O to private V5 roots, including dir-fd writes.

These are Python guards around pinned original code, not an OS sandbox.
"""
import os
from pathlib import Path
import re
import stat
import sys
import threading


def install_owner_boundary(safe_root_class, private_input, output, target, input_names):
    roots = (Path(private_input), Path(output))
    root_ids = {(p.stat().st_dev, p.stat().st_ino) for p in roots}
    ancestors = {(p.stat().st_dev, p.stat().st_ino) for root in roots for p in (root, *root.parents)}
    context = threading.local()
    violations = []
    writable_fds = {}
    original_init = safe_root_class.__init__
    original_read = safe_root_class.read_bytes
    original_write = safe_root_class.write_bytes
    original_unlink = safe_root_class.unlink_if_same
    original_visible = safe_root_class._open_visible

    def deny(reason):
        violations.append(reason)
        raise PermissionError(reason)

    def inside(fd):
        current = os.dup(fd)
        try:
            for _ in range(128):
                info = os.fstat(current)
                identity = (info.st_dev, info.st_ino)
                if identity in root_ids:
                    return True
                parent = os.open('..', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                parent_info = os.fstat(parent)
                same = identity == (parent_info.st_dev, parent_info.st_ino)
                os.close(current)
                current = parent
                if same:
                    return False
            return False
        finally:
            os.close(current)

    def parent_allowed(name, directory=None):
        if isinstance(name, int):
            info = os.fstat(name)
            return writable_fds.get(name) == (info.st_dev, info.st_ino)
        path = Path(os.fsdecode(name))
        if directory not in (None, -1):
            return len(path.parts) == 1 and path.name not in ('.', '..') and inside(directory)
        if not path.is_absolute():
            path = Path.cwd() / path
        from v5_shadow.module_api import _open_directory
        try:
            parent = _open_directory(path.parent)
        except OSError:
            return False
        try:
            return inside(parent)
        finally:
            os.close(parent)

    def mkdir_is_existing_ancestor(name, directory):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         dir_fd=None if directory in (None, -1) else directory)
        except OSError:
            return False
        try:
            info = os.fstat(fd)
            return (info.st_dev, info.st_ino) in ancestors
        finally:
            os.close(fd)

    def allowed_file(instance, relative, writing):
        root = Path(instance.root)
        if root == roots[0]:
            return relative in ({'.import.lock'} if writing else set(input_names) | {'.import.lock', '.import.lock.mutex'})
        if root != roots[1] or not isinstance(relative, str):
            return False
        return bool(re.fullmatch(r'us_mapping_research/' + target + r'/(?:latest\.json|runs/[0-9a-f]{32}\.json)', relative))

    def init(instance, root):
        if Path(root).absolute() not in roots:
            deny('US_OWNER_ROOT_NOT_BOUND')
        original_init(instance, root)

    def read(instance, relative, **kwargs):
        if not allowed_file(instance, relative, False):
            deny('US_OWNER_READ_NOT_BOUND')
        return original_read(instance, relative, **kwargs)

    def write(instance, relative, raw, **kwargs):
        if not allowed_file(instance, relative, True):
            deny('US_OWNER_WRITE_NOT_BOUND')
        return original_write(instance, relative, raw, **kwargs)

    def unlink(instance, relative, expected):
        if Path(instance.root) != roots[0] or relative != '.import.lock':
            deny('US_OWNER_UNLINK_NOT_BOUND')
        return original_unlink(instance, relative, expected)

    def visible(name, flags, mode=0o777, *, dir_fd=None):
        writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        if writing and not parent_allowed(name, dir_fd):
            deny('US_OWNER_FD_WRITE_NOT_BOUND')
        previous = getattr(context, 'open', None)
        context.open = (os.fsdecode(name), flags & ~getattr(os, 'O_CLOEXEC', 0)) if writing else None
        try:
            fd = original_visible(name, flags, mode, dir_fd=dir_fd)
            if writing:
                info = os.fstat(fd)
                writable_fds[fd] = (info.st_dev, info.st_ino)
            return fd
        finally:
            context.open = previous

    safe_root_class.__init__ = init
    safe_root_class.read_bytes = read
    safe_root_class.write_bytes = write
    safe_root_class.unlink_if_same = unlink
    safe_root_class._open_visible = staticmethod(visible)

    def audit(event, args):
        if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn', 'os.posix_spawn')) or event in ('os.system', 'os.fork', 'os.forkpty'):
            deny('US_OWNER_NETWORK_OR_PROCESS_DENIED')
        if event == 'os.kill' and args[1] != 0:
            deny('US_OWNER_SIGNAL_DENIED')
        if event == 'open':
            name, mode, flags = args
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if isinstance(name, int):
                    if not parent_allowed(name):
                        deny('US_OWNER_UNSCOPED_FD_WRITE')
                elif getattr(context, 'open', None) != (os.fsdecode(name), flags & ~getattr(os, 'O_CLOEXEC', 0)):
                    deny('US_OWNER_UNSCOPED_OPEN_WRITE')
        elif event == 'os.mkdir':
            name, _mode, directory = args
            if not parent_allowed(name, directory) and not mkdir_is_existing_ancestor(name, directory):
                deny('US_OWNER_MKDIR_NOT_BOUND')
        elif event in ('os.rename', 'os.link'):
            source, destination, source_dir, destination_dir = args
            if not parent_allowed(source, source_dir) or not parent_allowed(destination, destination_dir):
                deny('US_OWNER_MOVE_NOT_BOUND')
        elif event in ('os.remove', 'os.rmdir'):
            if not parent_allowed(args[0], args[1]):
                deny('US_OWNER_REMOVE_NOT_BOUND')
        elif event in ('os.chmod', 'os.chown', 'os.utime', 'os.symlink', 'os.setxattr', 'os.removexattr'):
            deny('US_OWNER_METADATA_MUTATION_DENIED')
        elif event == 'os.truncate' and not parent_allowed(args[0]):
            deny('US_OWNER_TRUNCATE_NOT_BOUND')

    sys.addaudithook(audit)
    return violations
