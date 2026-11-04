"""Exact packaging inputs; directory locations do not participate in the pins."""
import hashlib
import json
from pathlib import Path


PINS = json.loads(Path(__file__).with_name('builder-runtime-pins.json').read_text(encoding='utf-8'))


def generated_cache(name):
    """Loose interpreter/test caches are host state; vendor ZIP bytes stay exact."""
    parts = name.replace('\\', '/').lower().split('/')
    return (any(part in ('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache') for part in parts)
            or parts[-1].endswith(('.pyc', '.pyo')))


def read_files(root, *, omit_caches=False):
    """Read once so the checked bytes are the bytes subsequently packaged."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Runtime input must be a regular directory')
    files = {}
    for path in root.rglob('*'):
        name = path.relative_to(root).as_posix()
        if omit_caches and generated_cache(name):
            continue
        if path.is_symlink():
            raise ValueError('Runtime input contains a symlink: ' + name)
        if path.is_file():
            files[name] = path.read_bytes()
    return files


def inventory_pin(files):
    """SHA-256 of compact ASCII JSON [POSIX path, size, SHA-256] rows, path-sorted."""
    rows = [[name, len(data), hashlib.sha256(data).hexdigest()] for name, data in sorted(files.items())]
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()
    return dict(files=len(rows), sha256=digest)


def validate_inventory(files, expected, label):
    if inventory_pin(files) != expected:
        raise ValueError(label + ' inventory does not match its pin (missing, extra or modified file)')


def windows_files(root):
    files = read_files(root, omit_caches=True)
    required = ('python.exe', 'pythonw.exe', '_tkinter.pyd', '_multiprocessing.pyd',
                'tcl86t.dll', 'tk86t.dll', 'tkinter/__init__.py', 'LICENSE.txt',
                'tcl/tcl8.6/license.terms', 'tcl/tk8.6/license.terms')
    for name in required:
        if not files.get(name):
            raise ValueError('Windows runtime pin: missing or empty ' + name)
    expected = PINS['windows']
    if hashlib.sha256(files.get('python.exe', b'')).hexdigest() != expected['python_exe_sha256']:
        raise ValueError('Windows python.exe does not match its pin')
    validate_inventory(files, expected['inventory'], 'Windows runtime')
    return files


def mac_licence_files(root):
    files = read_files(root)
    validate_inventory(files, PINS['macos']['licences_inventory'], 'Mac runtime licence')
    return files
