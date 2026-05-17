"""Diagnostic 1: IS-MCTS with UNIFORM prior vs open-info MCTS.

If IS-MCTS with no network (uniform prior) still loses badly to
open-info MCTS, the problem is in the search architecture itself
(determinization quality, IS-UCT formula, snapshot/restore), not
the learned prior. If it's competitive, the search engine is fine
and the problem is the network.

We test:
  A) IS-MCTS(uniform, 100 rollouts) vs open-MCTS(50 rollouts)
  B) IS-MCTS(uniform, 100 rollouts) vs open-MCTS(200 rollouts)
  C) IS-MCTS(uniform, 100 rollouts) vs random

"Uniform prior" = use an Agent with freshly-random-init weights
(effectively random softmax = near-uniform prior over legal actions).
"""

import random
import time

import numpy as np
import torch

from gicg_env import GicgEnv
from training.paradigms.az.config import fixed_1v1_config
from training.paradigms.az.determinize import SharedFixedPool
from training.paradigms.az.mcts import MCTSConfig, mcts_search
from training.paradigms.az.network import Agent
from training.paradigms.az.pool_spec import resolve_pool_refs
from training.core.matchup.players import MCTSPlayer


class _RandomPlayer:
    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def select_action(self, env):
        kinds, _ = env.get_legal_actions()
        return self.rng.randrange(len(kinds))


def play_series(agent, spec, opp, env_factory, n_games, mcts_cfg):
    rng = random.Random(12345)
    wins = losses = draws = 0
    for g in range(n_games):
        side = g % 2
        env = env_factory(g)
        agent.game_start(env.static_obs)
        try:
            while env._engine.phase == 1:
                env.step(0)
                if env.done:
                    break
            while not env.done:
                acting = env.acting_player
                if acting == side:
                    chosen, _ = mcts_search(
                        env,
                        agent,
                        spec,
                        rng,
                        viewing_player=acting,
                        config=mcts_cfg,
                        game_step=0,
                    )
                else:
                    chosen = opp.select_action(env)
                env.step(chosen)
            w = env._engine.winner
            if w == side:
                wins += 1
            elif w == 1 - side:
                losses += 1
            else:
                draws += 1
        finally:
            agent.game_end()
            env.close()
    decisive = max(1, wins + losses)
    return {
        'wins': wins,
        'losses': losses,
        'draws': draws,
        'wr': round(wins / decisive, 3),
    }


def main():
    cfg = fixed_1v1_config(data_dir='data')
    pool_refs = resolve_pool_refs(cfg.scenario)
    spec = SharedFixedPool(pool_refs)

    def env_factory(i):
        seed = 55000 + i
        env = GicgEnv(
            cfg.scenario.team_0,
            cfg.scenario.team_1,
            card_pool=cfg.scenario.card_pool,
            seed=seed,
            data_dir=cfg.scenario.data_dir,
        )
        env.reset(seed=seed)
        return env

    # Fresh random-init agent = uniform-ish prior
    torch.manual_seed(999)
    agent = Agent(cfg.agent)
    agent.net.eval()

    mcts_cfg = MCTSConfig(
        n_rollouts=100,
        max_rollout_depth=400,
        dirichlet_eps=0.0,
        temperature=0.0,
        temperature_switch_step=0,
    )

    N = 10
    opponents = [
        ('random', _RandomPlayer(seed=77)),
        ('open_mcts_50', MCTSPlayer(n_rollouts=50, max_rollout_depth=400, seed=1)),
        ('open_mcts_200', MCTSPlayer(n_rollouts=200, max_rollout_depth=400, seed=2)),
    ]

    print(
        f'IS-MCTS(uniform prior, 100 rollouts) vs opponents, {N} games each:',
        flush=True,
    )
    for name, opp in opponents:
        t0 = time.perf_counter()
        r = play_series(agent, spec, opp, env_factory, N, mcts_cfg)
        dt = time.perf_counter() - t0
        print(f'  vs {name}: {r}  ({dt:.1f}s)', flush=True)


if __name__ == '__main__':
    main()
