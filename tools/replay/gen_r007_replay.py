"""Generate one replay YAML for r007 ckpt_g01200 vs mcts_pure_100
on a fixed 2v2 matchup. Useful for post-hoc behavior diagnosis of
the collapse (ckpt after arena win_rate=0.025).

Usage:
    .venv/bin/python -m tools.gen_r007_replay
"""

from __future__ import annotations

import sys
from pathlib import Path

from gicg_env import GicgEnv
from training.core.matchup.loaders import load_player
from training.core.matchup.matchup import _play_one


CKPT = 'artifacts/202604211058_r007_slow_1500g/ckpt_g01200.pt'
TEAM_0 = ['赤蝶', '墨客']
TEAM_1 = ['猫咪', '刻师傅']
SEED = 42
OPP_N_SIM = 100


def main() -> int:
    if not Path(CKPT).exists():
        print(f'ckpt not found: {CKPT}', file=sys.stderr)
        return 1

    az_spec = {'type': 'az', 'ckpt': CKPT, 'n_simulations': 0}  # argmax
    mcts_spec = {'type': 'mcts_pure', 'n_simulations': OPP_N_SIM}

    env = GicgEnv(TEAM_0, TEAM_1, seed=SEED, data_dir='data')
    env.reset(seed=SEED)

    az_builder = load_player(az_spec)
    mcts_builder = load_player(mcts_spec)
    p0 = az_builder(SEED)  # r007 on side 0
    p1 = mcts_builder(SEED + 10_000)  # mcts_pure on side 1

    print(
        f'playing: {TEAM_0} (r007 AZ argmax) vs {TEAM_1} (mcts_pure n_sim={OPP_N_SIM}), seed={SEED}',
        flush=True,
    )
    winner = _play_one(env, p0, p1, max_game_steps=400)
    yaml = env.export_replay()
    env.close()

    out = Path(f'artifacts/202604211058_r007_slow_1500g/diag_replay_vs_mcts{OPP_N_SIM}_seed{SEED}.yaml')
    out.write_text(yaml)
    winner_s = {0: 'AZ (r007)', 1: 'mcts_pure', -1: 'draw'}.get(
        winner,
        f'code={winner}',
    )
    print(f'winner: {winner_s}')
    print(f'saved: {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
