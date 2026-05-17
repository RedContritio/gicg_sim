"""Gauntlet dispatch + eval_service one-shot ACK helper.

DEFAULT_SOCKET_PATH is inlined here (not imported from
tools.remote.eval_service) to avoid framework → tools cross-layer
import.
"""

from __future__ import annotations

import json
import os
import socket as _socket
from pathlib import Path
from typing import Optional


# Inlined to break the framework → tools back-import cycle. Mirrors
# tools.remote.eval_service.DEFAULT_SOCKET_PATH (env-var-aware so
# container deployment using /var/run/gicg/ resolves the same path on
# both ends).
DEFAULT_SOCKET_PATH = os.environ.get('GICG_EVAL_SOCKET', '/tmp/gicg_eval.sock')


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
    """
    if artifacts_dir is None:
        return
    ckpt_path = str(artifacts_dir / f'ckpt_gauntlet_g{game_marker:05d}.pt')
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
        if request_eval(DEFAULT_SOCKET_PATH, req):
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


def request_eval(socket_path: str, req: dict) -> bool:
    """Send one eval request via Unix socket, get ACK. Returns True on
    success, False if the eval_service is unreachable."""
    try:
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(socket_path)
        sock.sendall(json.dumps(req).encode('utf-8') + b'\n')
        resp = sock.recv(4096)
        sock.close()
        data = json.loads(resp.decode('utf-8'))
        return data.get('status') == 'accepted'
    except (ConnectionRefusedError, FileNotFoundError, TimeoutError, OSError):
        return False
