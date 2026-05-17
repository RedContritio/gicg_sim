"""Session-building and auxiliary helpers for live_api.py — split out
to stay under the 300-line cap. Owns:

- :class:`LiveSession` and the player protocol
- opponent ckpt allow-list + cache
- ``_build_opponent_player`` / ``_validate_ckpt_path``
- state accessors (``build_legal_actions`` / ``get_winner``)
- ``auto_advance_agent`` loop past non-human phases
- client-safe error sanitizer

The FastAPI router, websocket handler, and message dispatch live in
``live_api``.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gicg_env import GicgEnv
from gicg_env.engine import PHASE_SELECT_ACTIVE
from training.core.matchup.loaders import load_player

# ckpt path allow-list root — any ``ckpt`` field in an opponent spec
# must resolve under this directory. Guards against arbitrary file
# probes (B1 from the Phase-4 review).
# Resolved from this module's location so running uvicorn from a
# non-repo-root cwd still whitelists the correct directory.
_REPO_ROOT = Path(__file__).resolve().parents[2]
CKPT_ALLOW_ROOT = (_REPO_ROOT / 'artifacts').resolve()

# Kill WS sessions that receive no client message for this long. Gives
# a back-pressure point against stuck tabs pinning multi-MB ckpts in
# server memory indefinitely.
WS_IDLE_TIMEOUT_S = 600.0

# Process-level LRU cache for loaded ckpt players. Keyed by
# (opponent_type, resolved_ckpt_path, n_simulations, mtime). mtime
# bust ensures a retrained ckpt at the same path invalidates. We cache
# PlayerBuilder functions (not player instances) — each game still
# calls builder(seed) to get a fresh player with fresh MCTS state.
# Keeping the builder lets us reuse loaded Agent weights across games.
_BUILDER_CACHE_CAP = 4
_builder_cache: 'OrderedDict[tuple, object]' = OrderedDict()


class _PlayerProtocol(Protocol):
    def select_action(self, env: GicgEnv) -> int: ...


@dataclass
class LiveSession:
    env: GicgEnv
    player: _PlayerProtocol
    human_player: int


def build_legal_actions(env: GicgEnv) -> list[dict]:
    """JSON-friendly legal actions list. Each entry carries:
    - index    : the client echoes this back as {'type':'action','index'}
    - kind     : numeric engine kind (0=Skill, 1=Card, 2=Switch, 3=EndTurn)
    - kind_name: "Skill" | "Card" | "Switch" | "EndTurn"
    - name     : DSL-resolved name (skill / card / char)
    - slot     : hand_idx for Card, target char_idx for Switch, -1 otherwise.
                 Disambiguates same-named duplicates so the frontend can
                 match on (name, slot) rather than (name) alone.
    """
    if env.done:
        return []
    kinds, _ = env.get_legal_actions()
    labels = env.get_action_labels()
    actions = []
    for i, k in enumerate(kinds):
        if i < len(labels):
            kind_name, name, slot = labels[i]
        else:
            kind_name, name, slot = '?', '?', -1
        actions.append(
            {
                'index': i,
                'kind': int(k),
                'kind_name': kind_name,
                'name': name,
                'slot': int(slot),
            }
        )
    return actions


def get_winner(env: GicgEnv) -> int:
    """Winner accessor that avoids reaching through env._engine (G1 from
    the review). Exposed here because GicgEnv itself has no public
    winner property yet — wrap once, drop-in when the property lands."""
    return int(env._engine.winner)


def auto_advance_agent(sess: LiveSession) -> None:
    """Step the environment past every phase where the human isn't owed
    a decision: PhaseSelectActive is auto-picked for both sides, and
    every AI-controlled turn in PhaseAction is resolved via the
    opponent player. Returns when the game is done OR when control
    passes back to the human."""
    # PhaseSelectActive: auto-pick first alive for both players.
    while not sess.env.done and sess.env._engine.phase == PHASE_SELECT_ACTIVE:
        sess.env.step(0)

    # Agent turns.
    while not sess.env.done and sess.env.current_player != sess.human_player:
        kinds, _ = sess.env.get_legal_actions()
        if len(kinds) == 0:
            break
        action = sess.player.select_action(sess.env)
        sess.env.step(action)


def _validate_ckpt_path(ckpt: str) -> Path:
    """Reject ckpt paths outside CKPT_ALLOW_ROOT. Returns the resolved
    absolute path on success, raises ValueError on any violation.

    Guard against (a) arbitrary-file probes via error messages,
    (b) traversal via symlinks, (c) absolute paths to sensitive files.
    """
    if not ckpt:
        raise ValueError('ckpt path is empty')
    p = Path(ckpt).expanduser()
    try:
        resolved = p.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        # Don't leak the exact filesystem error to the client; a
        # uniform "not available" covers missing + permission denied
        # + traversal-blocked cases.
        raise ValueError('ckpt not available') from exc
    try:
        resolved.relative_to(CKPT_ALLOW_ROOT)
    except ValueError as exc:
        raise ValueError('ckpt not in artifacts/ (only in-repo trained ckpts are loadable)') from exc
    return resolved


def build_opponent_player(opponent_spec: dict, seed: int) -> _PlayerProtocol:
    """Delegate to matchup's LOADERS. ckpt-bearing specs go through
    _validate_ckpt_path first so an attacker can't use error messages
    to enumerate the filesystem outside artifacts/. Loaded builders
    (which hold the decoded Agent + weights) are cached so pressing
    Restart doesn't reload a multi-MB ckpt every time."""
    if not isinstance(opponent_spec, dict):
        raise ValueError('opponent spec must be an object')
    t = opponent_spec.get('type')
    if t in ('az', 'cfr'):
        ckpt = opponent_spec.get('ckpt', '')
        resolved = _validate_ckpt_path(ckpt)
        # Cache key includes mtime so a retrained ckpt at the same
        # path invalidates immediately.
        try:
            mtime = resolved.stat().st_mtime
        except OSError:
            mtime = 0.0
        n_sim = int(opponent_spec.get('n_simulations', 0))
        cache_key = (t, str(resolved), n_sim, mtime)
        builder = _builder_cache.get(cache_key)
        if builder is None:
            builder = load_player({**opponent_spec, 'ckpt': str(resolved)})
            _builder_cache[cache_key] = builder
            # Evict oldest beyond cap
            while len(_builder_cache) > _BUILDER_CACHE_CAP:
                _builder_cache.popitem(last=False)
        else:
            # Refresh LRU position
            _builder_cache.move_to_end(cache_key)
    else:
        builder = load_player(opponent_spec)
    return builder(seed=seed)


def sanitize_error(exc: Exception) -> str:
    """Client-facing error message. Strip filesystem paths and
    tracebacks — return exception type + short description only."""
    msg = str(exc)
    # Best-effort scrub of absolute paths.
    for token in ('/Users/', '/home/', '/var/', '/tmp/', '/etc/'):
        if token in msg:
            msg = msg.split(token)[0].rstrip(': \'"')
            break
    return f'{type(exc).__name__}: {msg}' if msg else type(exc).__name__
