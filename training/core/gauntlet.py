"""Gauntlet dispatch + eval_service one-shot ACK helper.

DEFAULT_HOST / DEFAULT_PORT are inlined here (not imported from
tools.eval.eval_service) to avoid framework → tools cross-layer
import.
"""

from __future__ import annotations

import json
import os
import socket as _socket
from pathlib import Path
from typing import Optional


# Inlined to break the framework → tools back-import cycle. Mirrors
# tools.eval.eval_service.DEFAULT_HOST / DEFAULT_PORT (env-var-aware
# so container deployment mapping ``-p 9100:9100`` resolves the same
# address on both ends).
DEFAULT_HOST = os.environ.get('GICG_EVAL_HOST', 'localhost')
DEFAULT_PORT = int(os.environ.get('GICG_EVAL_PORT', '9100'))


def dispatch_gauntlet(
    config,
    challenger,
    artifacts_dir: Optional[Path],
    game_marker: int,
    log,
) -> None:
    """Dispatch a panel of matchup requests to the global eval_service.

    Non-blocking: issues each ACK sequentially then returns. If
    eval_service is down, logs a skip and continues.

    Gauntlet challenger ckpt is saved to
    ``<artifacts_dir>/ckpts/gauntlet_g<NNNN>.pt`` (4-digit zero-pad of
    ``game_marker``). Spec ref: ``docs/superpowers/specs/2026-05-18-
    tools-runs-redesign-design.md`` §ckpts/ naming convention (HIGH-X-1).

    Raises ``ValueError`` if ``game_marker >= 10000`` — strict contract
    on the 4-digit width. Production runs producing >9999 gauntlet
    intermediates must widen the prefix via spec amendment (no silent
    overflow into longer filenames).
    """
    if artifacts_dir is None:
        return
    if not (0 <= game_marker < 10_000):
        raise ValueError(
            f'dispatch_gauntlet: game_marker={game_marker} outside '
            f'[0, 10_000) — gauntlet_g<NNNN>.pt prefix is 4-digit zero-pad '
            f'(spec §ckpts/ naming convention). Amend spec + this guard '
            f'before running gauntlet past 9999 intermediates.'
        )
    ckpts_dir = artifacts_dir / 'ckpts'
    ckpts_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = str(ckpts_dir / f'gauntlet_g{game_marker:04d}.pt')
    challenger.save(ckpt_path)

    panel_base = {
        'kind': 'gauntlet',
        'game_marker': game_marker,
        'seed': config.seed + 20_000 + game_marker,
        'mode': 'fixed',
        'team_0': list(config.scenario.team_0),
        'team_1': list(config.scenario.team_1),
        'card_pool': config.scenario.card_pool,
        'deck_padding': config.scenario.deck_padding,
        'pool': config.scenario.pool,
        'data_dir': config.scenario.data_dir,
        'games_per_cell': max(1, config.gauntlet_games_per_opponent // 2),
        'max_game_steps': config.gauntlet_max_game_steps,
        'result_path': str(artifacts_dir / 'gauntlet_results.jsonl'),
    }
    challenger_spec = {'type': 'az', 'ckpt': ckpt_path, 'n_simulations': 0}

    opponents: list[tuple[str, dict]] = [
        ('random', {'type': 'random'}),
    ]
    for r in config.gauntlet_mcts_rollouts:
        opponents.append(
            (
                f'mcts_pure_{r}',
                {'type': 'mcts_pure', 'n_simulations': int(r)},
            )
        )
    for greedy_spec in getattr(config, 'gauntlet_greedy_baselines', []):
        name = greedy_spec['name']
        opponents.append(
            (
                name,
                {
                    'type': 'greedy',
                    'features': str(greedy_spec.get('features', 'F1')),
                    'depth': int(greedy_spec.get('depth', 1)),
                    'dice_greedy': bool(greedy_spec.get('dice_greedy', True)),
                },
            )
        )
    for model_spec in config.gauntlet_model_opponents:
        name = model_spec['name']
        opponents.append(
            (
                name,
                {
                    'type': 'az',
                    'ckpt': model_spec['ckpt_path'],
                    'n_simulations': int(model_spec['rollouts']),
                },
            )
        )

    n_dispatched = 0
    for opp_name, opp_spec in opponents:
        req = {
            **panel_base,
            'id': f'g{game_marker:05d}_{opp_name}',
            'players': [challenger_spec, opp_spec],
        }
        if request_eval(DEFAULT_HOST, DEFAULT_PORT, req):
            n_dispatched += 1
    if n_dispatched > 0:
        log(
            'eval_dispatch',
            {
                'game': game_marker,
                'kind': 'gauntlet',
                'n_opponents': n_dispatched,
            },
        )
    else:
        log(
            'eval_skip',
            {
                'game': game_marker,
                'reason': 'eval_service not running',
            },
        )


def request_eval(host: str, port: int, req: dict) -> bool:
    """Send one eval request via TCP localhost, get ACK. Returns True on
    success, False if the eval_service is unreachable."""
    try:
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect((host, port))
        sock.sendall(json.dumps(req).encode('utf-8') + b'\n')
        resp = sock.recv(4096)
        sock.close()
        data = json.loads(resp.decode('utf-8'))
        return data.get('status') == 'accepted'
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False
