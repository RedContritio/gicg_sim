"""tools.runs._train.cfg_toml — hand-rolled stdlib-only TOML emitter
for ``cfg_resolved.toml`` write (Phase B step 4b).

Internal module — split out of :mod:`tools.runs._train.snapshot` per
the 300-line file budget (per-commit hook). Only supports the cfg
dict shape observed in ``configs/``:

- scalars: bool / int / float / str
- homogeneous lists of scalars (TOML arrays)
- nested dicts → rendered as ``[a.b.c]`` table headers

Array-of-table (list-of-dict) and inline-table values are NOT
supported — the cfg schema does not use them. If a future cfg adds
them, Phase B's round-trip verify (in snapshot.py) catches the
mismatch and this emitter needs extending.

``tomli_w`` was considered but is vendored-only inside pip (not a
top-level project dep). Adding it just for this single emit site is
over-investment when the cfg shape is bounded; stdlib hand-roll keeps
``tools/runs/`` dep-free.
"""

from __future__ import annotations

import math
from typing import Any


def dict_to_toml(d: dict) -> str:
    """Serialize a nested dict to TOML text.

    Emit strategy: collect bare-key (scalar / list) entries first, then
    nested-dict children as ``[parent.child]`` table headers
    recursively. TOML grammar requires bare keys to precede any table
    header within the same section, so the two-pass split is necessary
    (not just stylistic).
    """
    lines: list[str] = []
    _emit_table(d, path=(), lines=lines)
    return '\n'.join(lines).rstrip() + '\n'


def _emit_table(table: dict, path: tuple[str, ...], lines: list[str]) -> None:
    """Emit one table (root or nested) into ``lines``.

    ``path`` is the dotted heading for the current table (empty tuple
    = root, no heading printed). Iteration order preserves dict
    insertion order — Python 3.7+ guarantee. cfg dicts come from
    tomllib parse + deep-merge which preserves insertion order, so
    round-trip ordering is stable (though TOML semantics don't require
    it — diff-friendliness only).
    """
    if path:
        lines.append(f'[{".".join(path)}]')
    scalar_keys: list[str] = []
    nested_keys: list[str] = []
    for k, v in table.items():
        _validate_key(k, path)
        if isinstance(v, dict):
            nested_keys.append(k)
        else:
            scalar_keys.append(k)
    for k in scalar_keys:
        lines.append(f'{_format_key(k)} = {_format_value(table[k])}')
    if scalar_keys and nested_keys:
        # Blank line between bare keys and nested sub-tables — matches
        # tomllib re-emit conventions, easier to diff.
        lines.append('')
    for i, k in enumerate(nested_keys):
        sub_path = path + (k,)
        if i > 0:
            # Blank line between sibling sub-tables.
            lines.append('')
        _emit_table(table[k], sub_path, lines)


def _validate_key(key: Any, path: tuple[str, ...]) -> None:
    """Raise on key types / values the emitter cannot safely serialize."""
    if not isinstance(key, str):
        loc = '.'.join(path) if path else '<root>'
        raise TypeError(f'cfg key under {loc!r} must be str, got {type(key).__name__}: {key!r}')
    if not key:
        loc = '.'.join(path) if path else '<root>'
        raise ValueError(f'cfg key under {loc!r} cannot be empty string')


def _format_key(key: str) -> str:
    """Emit a TOML key. Bare for [A-Za-z0-9_-]+, quoted otherwise."""
    if all(c.isalnum() or c in '_-' for c in key):
        return key
    return _format_string(key)


def _format_value(v: Any) -> str:
    """Emit a single TOML value. Dispatches by Python type."""
    if isinstance(v, bool):
        # bool BEFORE int — bool is a subclass of int in Python.
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return 'nan'
        if math.isinf(v):
            return 'inf' if v > 0 else '-inf'
        s = repr(v)
        if '.' not in s and 'e' not in s and 'E' not in s:
            s += '.0'  # force decimal so re-parse gives float not int
        return s
    if isinstance(v, str):
        return _format_string(v)
    if isinstance(v, list):
        return _format_list(v)
    if isinstance(v, dict):
        # Inline-table emit not supported — nested dicts route through
        # `_emit_table` as section headers. cfg parse yields plain
        # dicts whether the source was inline or `[table]` form, so we
        # never reach here from a real cfg. Kept as defense: explicit
        # raise rather than silent mis-emit if a future caller manually
        # constructs a list-of-inline-dict-valued entry.
        raise TypeError(f'inline-table emit not supported (use _emit_table for nested dicts): {v!r}')
    raise TypeError(f'cfg value type not supported by TOML emitter: {type(v).__name__}={v!r}')


def _format_list(items: list) -> str:
    """Emit a TOML array. Items are scalars (no nested dicts)."""
    parts = []
    for item in items:
        if isinstance(item, dict):
            raise TypeError(
                'cfg list-of-dict (array-of-table) not supported by emitter; '
                'this cfg shape never appeared in observed configs/'
            )
        parts.append(_format_value(item))
    return '[' + ', '.join(parts) + ']'


def _format_string(s: str) -> str:
    """Emit a basic TOML string with required escapes."""
    escaped = s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    return f'"{escaped}"'
