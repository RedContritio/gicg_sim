"""Schema-fetch + schema-walk helpers for ``tools.send_matchup``.

Split out of send_matchup.py to stay under the 300-line pre-commit cap.
Contents:

  * ``fetch_schema`` — socket round-trip to eval_service to pull its
    JSON Schema.
  * ``kind_schema`` / ``resolve_ref`` / ``variant_by_discriminator`` /
    ``field_schema_for_path`` — walk the schema to resolve the type
    for a dotted CLI path. Returns ``None`` on unresolved paths so
    the caller can fall back to heuristic typing.

These are pure helpers with no dependency on the CLI layer."""

from __future__ import annotations

import json
import socket
from typing import Any, List, Optional


def fetch_schema(sock_path: str) -> dict:
    """Query the service for its request schema. Raises on any failure;
    the caller decides whether to proceed without (we choose not to —
    silent fallback to heuristic types is how bodies end up rejected
    server-side after a schema bump)."""
    req = {'kind': 'schema'}
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect(sock_path)
    s.sendall(json.dumps(req).encode('utf-8') + b'\n')
    buf = b''
    while b'\n' not in buf:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    resp = json.loads(buf.decode('utf-8').strip())
    if resp.get('status') != 'ok' or 'schema' not in resp:
        raise RuntimeError(f'eval_service returned unexpected schema response: {resp}')
    return resp['schema']


def kind_schema(schema: dict, kind: str) -> Optional[dict]:
    """Pick the ``oneOf`` branch whose ``kind`` const matches."""
    for branch in schema.get('oneOf', []):
        const = branch.get('properties', {}).get('kind', {}).get('const')
        if const == kind:
            return branch
    return None


def resolve_ref(schema: dict, ref: str) -> dict:
    """Resolve a ``#/$defs/name`` reference against the top-level schema."""
    if not ref.startswith('#/'):
        raise ValueError(f'only local refs supported, got {ref!r}')
    node: Any = schema
    for seg in ref[2:].split('/'):
        node = node[seg]
    return node


def variant_by_discriminator(
    schema: dict,
    item_schema: dict,
    current: dict,
) -> Optional[dict]:
    """If ``item_schema`` is an ``oneOf`` of player variants (or any
    variants), pick the one whose ``type`` const matches
    ``current.get("type")``. Lets us resolve further path steps inside
    a player spec once its type has been set."""
    variants = item_schema.get('oneOf')
    if not variants:
        return None
    t = current.get('type')
    if t is None:
        return None
    for v in variants:
        v_resolved = resolve_ref(schema, v['$ref']) if '$ref' in v else v
        const = v_resolved.get('properties', {}).get('type', {}).get('const') or v_resolved.get('properties', {}).get(
            'type', {}
        ).get('enum')
        if const == t or (isinstance(const, list) and t in const):
            return v_resolved
    return None


def field_schema_for_path(
    schema: dict,
    kind_branch: dict,
    path: List[Any],
    req: dict,
) -> Optional[dict]:
    """Walk ``path`` inside ``kind_branch`` and return the leaf field
    schema. Returns None if path can't be resolved (e.g. player type
    not yet set when --players.0.ckpt arrives first); caller falls
    back to heuristic typing in that case."""
    node: Any = kind_branch
    # Also keep a parallel walk through the current req dict so we
    # can read the discriminator.
    current_req: Any = req
    for seg in path:
        if isinstance(seg, int):
            # Array — descend into `items`.
            items = node.get('items')
            if items is None:
                return None
            if '$ref' in items:
                items = resolve_ref(schema, items['$ref'])
            if items.get('oneOf'):
                # Discriminated union. Need to look at the already-set
                # fields of the current array element to pick a variant.
                if not isinstance(current_req, list) or seg >= len(current_req):
                    return None
                elem = current_req[seg]
                if not isinstance(elem, dict):
                    return None
                variant = variant_by_discriminator(schema, items, elem)
                if variant is None:
                    return None
                node = variant
                current_req = elem
            else:
                node = items
                if isinstance(current_req, list) and seg < len(current_req):
                    current_req = current_req[seg]
                else:
                    current_req = {}
        else:
            # Object key — look in properties.
            props = node.get('properties', {})
            if seg not in props:
                return None
            node = props[seg]
            if isinstance(current_req, dict):
                current_req = current_req.get(seg, {})
            else:
                current_req = {}
            if '$ref' in node:
                node = resolve_ref(schema, node['$ref'])
    return node
