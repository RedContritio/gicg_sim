"""Thin schema-driven client for ``tools.remote.eval_service``.

Fetches the service's JSON Schema at startup and uses it to:

  - Coerce CLI argument values to the correct types (int / float / bool
    / string / list) instead of relying on heuristic auto-detection.
  - Validate the constructed request body client-side so failures
    surface before the socket round-trip.
  - Generate ``--help`` text enumerating every field of every request
    kind. Adding a new field or a new request kind requires only a
    schema edit — no CLI code change.

CLI mirrors the JSON body directly. Each flag is a dotted path:

  --kind gauntlet                  → req["kind"] = "gauntlet"
  --game-marker 1500               → req["game_marker"] = 1500
  --team-0 赤蝶 墨客               → req["team_0"] = ["赤蝶", "墨客"]
  --players.0.type cfr             → req["players"][0]["type"] = "cfr"
  --players.0.ckpt /path/to/ckpt   → req["players"][0]["ckpt"] = "..."

Rules:

  * Hyphens in flag names → underscores in JSON keys.
  * Integer path segments → list indices.
  * Multi-token values → list; single token → typed scalar.
  * Value type is taken from the schema (when resolvable); else best-
    effort auto-detect (int → float → bool → string).

Escape hatches for programmatic use:

  --body <path.json>   load request body from JSON file
  --stdin              load request body from stdin

``--socket PATH`` overrides the default socket. ``--help`` prints
usage + per-kind field reference (built from the fetched schema).

Examples::

    # CFR challenger vs pure-MCTS sweep (fixed 2v2, no side swap)
    for N in 50 100 200; do
      python -m tools.send_matchup \\
        --kind gauntlet \\
        --mode fixed \\
        --team-0 赤蝶 墨客 \\
        --team-1 猫咪 刻师傅 \\
        --players.0.type cfr \\
        --players.0.ckpt artifacts/<r008>/cfr_strategy_iter000199.pt \\
        --players.1.type mcts_pure \\
        --players.1.n-simulations $N \\
        --game-marker 1500 \\
        --games-per-cell 10 \\
        --swap-sides false \\
        --data-dir data \\
        --result-path artifacts/<r008>/gauntlet_results.jsonl
    done

    # Query service health
    python -m tools.send_matchup --kind status

Module split (kept under 300-line cap):

    send_matchup.py         — CLI entry + socket send + dispatch
    send_matchup_schema.py  — schema fetch + walk helpers
    send_matchup_parser.py  — tokenize / dotted-path / coercion
    send_matchup_help.py    — --help text renderer
"""

from __future__ import annotations

import json
import socket
import sys
from typing import List, Optional, Tuple

from tools.remote.eval_service import DEFAULT_SOCKET_PATH
from tools._meta.send_matchup_help import help_from_schema
from tools._meta.send_matchup_parser import build_request
from tools._meta.send_matchup_schema import fetch_schema


def _send(sock_path: str, req: dict) -> Tuple[int, dict]:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(10.0)
    s.connect(sock_path)
    s.sendall(json.dumps(req, ensure_ascii=False).encode('utf-8') + b'\n')
    buf = b''
    while b'\n' not in buf:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    resp = json.loads(buf.decode('utf-8').strip()) if buf else {}
    status = resp.get('status')
    return (0 if status in ('accepted', 'ok', 'stopping') else 1), resp


def main() -> int:
    argv = sys.argv[1:]

    # Extract global flags first.
    sock_path = DEFAULT_SOCKET_PATH
    body_path: Optional[str] = None
    use_stdin = False
    want_help = False
    remaining: List[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--socket':
            sock_path = argv[i + 1]
            i += 2
        elif a == '--body':
            body_path = argv[i + 1]
            i += 2
        elif a == '--stdin':
            use_stdin = True
            i += 1
        elif a == '--help' or a == '-h':
            want_help = True
            i += 1
        else:
            remaining.append(a)
            i += 1

    # Fetch schema up front (once). Required — no silent fallback.
    try:
        schema = fetch_schema(sock_path)
    except Exception as exc:
        print(f'ERROR: could not fetch schema from {sock_path}: {exc}', file=sys.stderr)
        print(
            '  Is eval_service running? Start with: python -m tools.remote.eval_service',
            file=sys.stderr,
        )
        return 2

    if want_help:
        print(help_from_schema(schema))
        return 0

    # Body from file / stdin bypasses CLI parsing entirely.
    if body_path:
        with open(body_path, 'r', encoding='utf-8') as f:
            req = json.load(f)
    elif use_stdin:
        req = json.loads(sys.stdin.read())
    else:
        try:
            req = build_request(schema, remaining)
        except ValueError as exc:
            print(f'ERROR: parse: {exc}', file=sys.stderr)
            return 2

    rc, resp = _send(sock_path, req)
    print(json.dumps(resp, ensure_ascii=False))
    return rc


if __name__ == '__main__':
    sys.exit(main())
