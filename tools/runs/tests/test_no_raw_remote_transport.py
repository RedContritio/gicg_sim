"""Guard production code against spawning remote transport binaries directly."""

from __future__ import annotations

import ast
from pathlib import Path


_TRANSPORT_BINARIES = {'ssh', 'scp', 'rsync'}
_SUBPROCESS_METHODS = {'run', 'Popen', 'check_output', 'check_call'}
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ROOTS = ('tools', 'training')
_SELF = Path(__file__).resolve()
_TRANSPORT = (_REPO_ROOT / 'tools' / 'runs' / '_host.py').resolve()
_DIRECT_EXEC_BOUNDARY = (
    (_REPO_ROOT / 'tools' / 'runs' / '_ssh.py').resolve(),
    (_REPO_ROOT / 'tools' / 'runs' / 'tail.py').resolve(),
)


def _iter_production_py_files():
    for rel in _ROOTS:
        root = _REPO_ROOT / rel
        if not root.is_dir():
            continue
        for path in root.rglob('*.py'):
            if any(part in {'tests', '__pycache__', '.claude'} for part in path.parts):
                continue
            if path.name.startswith('test_'):
                continue
            if path.resolve() in {_SELF, _TRANSPORT}:
                continue
            yield path


def _offenders(path: Path) -> list[tuple[int, str, str]]:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    module_aliases = {'subprocess'}
    function_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'subprocess':
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == 'subprocess':
            for alias in node.names:
                if alias.name in _SUBPROCESS_METHODS:
                    function_aliases.add(alias.asname or alias.name)

    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = ''
        if isinstance(node.func, ast.Attribute):
            if not isinstance(node.func.value, ast.Name) or node.func.value.id not in module_aliases:
                continue
            if node.func.attr not in _SUBPROCESS_METHODS:
                continue
            method = f'subprocess.{node.func.attr}'
        elif isinstance(node.func, ast.Name) and node.func.id in function_aliases:
            method = node.func.id
        if not method:
            continue

        argv = node.args[0] if node.args else None
        if argv is None:
            argv = next((kw.value for kw in node.keywords if kw.arg == 'args'), None)
        if not isinstance(argv, (ast.List, ast.Tuple)) or not argv.elts:
            continue
        binary = argv.elts[0]
        if isinstance(binary, ast.Constant) and binary.value in _TRANSPORT_BINARIES:
            found.append((node.lineno, method, binary.value))
    return found


def _direct_subprocess_calls(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    module_aliases = {'subprocess'}
    function_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'subprocess':
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == 'subprocess':
            for alias in node.names:
                if alias.name in _SUBPROCESS_METHODS:
                    function_aliases.add(alias.asname or alias.name)

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            if not isinstance(node.func.value, ast.Name) or node.func.value.id not in module_aliases:
                continue
            if node.func.attr in _SUBPROCESS_METHODS:
                found.append((node.lineno, f'subprocess.{node.func.attr}'))
        elif isinstance(node.func, ast.Name) and node.func.id in function_aliases:
            found.append((node.lineno, node.func.id))
    return found


def test_production_code_uses_host_transport_boundary():
    offenders = []
    for path in _iter_production_py_files():
        for lineno, method, binary in _offenders(path):
            rel = path.relative_to(_REPO_ROOT)
            offenders.append(f'{rel}:{lineno}: {method}({binary!r}, ...)')
    assert not offenders, 'Production code must route ssh/scp/rsync through tools.runs._host:\n  ' + '\n  '.join(
        offenders
    )


def test_streaming_transport_uses_host_boundary():
    offenders = []
    for path in _DIRECT_EXEC_BOUNDARY:
        for lineno, method in _direct_subprocess_calls(path):
            offenders.append(f'{path.relative_to(_REPO_ROOT)}:{lineno}: {method}')
    assert not offenders, (
        'Streaming transport must route process execution through tools.runs._host:\n  ' + '\n  '.join(offenders)
    )
