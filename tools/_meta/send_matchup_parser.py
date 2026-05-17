"""Argv tokenize + dotted-path parse + type coercion for send_matchup.

Split out of send_matchup.py to keep each file under the 300-line
pre-commit cap. The surface area is a single entry point, ``build_request``,
plus the lower-level helpers it composes (tokenize, parse_path, assign,
coerce). Coercion is schema-driven when a field schema is resolvable and
falls back to best-effort auto-detection otherwise."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from tools._meta.send_matchup_schema import field_schema_for_path, kind_schema


def coerce_scalar(value: str, field_schema: Optional[dict]) -> Any:
    """Coerce a single CLI token. Schema-driven when possible; else
    best-effort auto-detect."""
    if field_schema is not None:
        types = field_schema.get('type')
        if isinstance(types, str):
            types = [types]
        if types:
            for t in types:
                if t == 'null':
                    if value.lower() in ('null', 'none'):
                        return None
                    continue
                if t == 'boolean':
                    low = value.lower()
                    if low == 'true':
                        return True
                    if low == 'false':
                        return False
                    continue
                if t == 'integer':
                    try:
                        return int(value)
                    except ValueError:
                        continue
                if t == 'number':
                    try:
                        return float(value)
                    except ValueError:
                        continue
                if t == 'string':
                    return value
            # Fell through every declared type — schema mismatch, let
            # caller surface as a validation error downstream.
            return value
    # No schema available for this field — heuristic auto-detect.
    low = value.lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    if low in ('null', 'none'):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def coerce(
    values: List[str],
    field_schema: Optional[dict],
) -> Any:
    """Coerce a sequence of CLI tokens. If field is an array, return a
    list (even if one token). Otherwise require exactly one token."""
    is_array = field_schema is not None and 'array' in (
        field_schema.get('type') if isinstance(field_schema.get('type'), list) else [field_schema.get('type')]
    )
    if is_array:
        item_schema = field_schema.get('items')
        if isinstance(item_schema, dict) and 'type' in item_schema:
            return [coerce_scalar(v, item_schema) for v in values]
        return [coerce_scalar(v, None) for v in values]
    if len(values) == 1:
        return coerce_scalar(values[0], field_schema)
    # Multi-token, non-array field — fall through to list (heuristic).
    return [coerce_scalar(v, None) for v in values]


def parse_path(key: str) -> List[Any]:
    """Split ``foo-bar.0.baz-qux`` → ``['foo_bar', 0, 'baz_qux']``."""
    path: List[Any] = []
    for seg in key.split('.'):
        if seg.isdigit():
            path.append(int(seg))
        else:
            path.append(seg.replace('-', '_'))
    return path


def assign(root: Any, path: List[Any], value: Any) -> None:
    for i, seg in enumerate(path):
        is_last = i == len(path) - 1
        if isinstance(seg, int):
            if not isinstance(root, list):
                raise ValueError(f'path segment {seg!r} is int but parent is {type(root).__name__}')
            while len(root) <= seg:
                root.append(None)
            if is_last:
                root[seg] = value
            else:
                next_seg = path[i + 1]
                if root[seg] is None:
                    root[seg] = [] if isinstance(next_seg, int) else {}
                root = root[seg]
        else:
            if not isinstance(root, dict):
                raise ValueError(f'path segment {seg!r} is str but parent is {type(root).__name__}')
            if is_last:
                root[seg] = value
            else:
                next_seg = path[i + 1]
                if seg not in root or root[seg] is None:
                    root[seg] = [] if isinstance(next_seg, int) else {}
                root = root[seg]


def tokenize(argv: List[str]) -> List[Tuple[str, List[str]]]:
    """Group argv into ``(flag, [values...])``. Every argv entry must
    start with ``--`` or be a value immediately following a flag."""
    out: List[Tuple[str, List[str]]] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if not tok.startswith('--'):
            raise ValueError(f'position {i}: expected --flag, got {tok!r}')
        key = tok[2:]
        values: List[str] = []
        i += 1
        while i < len(argv) and not argv[i].startswith('--'):
            values.append(argv[i])
            i += 1
        if not values:
            raise ValueError(f'--{key} has no value')
        out.append((key, values))
    return out


def build_request(
    schema: dict,
    argv: List[str],
    seed_req: Optional[dict] = None,
) -> dict:
    """Two-pass parse:
    1. Heuristic-type pass — parse everything with best-effort typing
       so discriminator fields (``players.0.type``) land first.
    2. Schema-aware pass — re-coerce each field using the now-populated
       request as context (so variant sub-schemas are reachable).
    """
    req: dict = dict(seed_req) if seed_req else {}
    tokens = tokenize(argv)

    # Pass 1: heuristic — builds a skeleton request so path resolution
    # can read the discriminator and size of arrays.
    for key, values in tokens:
        path = parse_path(key)
        scratch = coerce(values, field_schema=None)
        assign(req, path, scratch)

    # Pass 2: re-coerce with schema-resolved types.
    kind = req.get('kind', 'gauntlet')
    kind_branch = kind_schema(schema, kind)
    if kind_branch is None:
        return req  # unknown kind; nothing else we can do here
    for key, values in tokens:
        path = parse_path(key)
        field = field_schema_for_path(schema, kind_branch, path, req)
        coerced = coerce(values, field)
        assign(req, path, coerced)
    return req
