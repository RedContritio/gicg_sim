"""Diagnostic: IS-MCTS with random-rollout value (no network) vs opponents.

Tests whether IS-MCTS works when leaf evaluation uses actual random
playout outcomes instead of the network's value head. If this
version beats random and competes with open-info MCTS, the search
engine is sound and the fix is to blend rollout values into the
leaf evaluation (AlphaGo-style).

Usage::

    .venv/bin/python -m tools.debug.diag_is_mcts_with_rollout
"""

from __future__ import annotations

import math
import random
import time

import numpy as np

from gicg_env import GicgEnv
from gicg_env.env import _terminal_z
from tools.debug._diag_az_cfg import diag_cfg
from training.paradigms.az.determinize import (
    SharedFixedPool,
    sample_hidden_state,
    apply_determinization,
)
from training.paradigms.az.mcts import (
    MCTSConfig,
    MCTSNode,
    ActionId,
    legal_ids_from_env,
    _puct_select,
    _find_action_index,
    rng_dirichlet,
)
from training.paradigms.az.pool_spec import resolve_pool_refs
from training.core.matchup.players import MCTSPlayer


def _random_rollout(env: GicgEnv, max_depth: int, rng: random.Random) -> float:
    """Play out the game randomly from the current state and return
    the P0-perspective outcome value."""
    for _ in range(max_depth):
        if env.done:
            break
        kinds, _ = env.get_legal_actions()
        n = len(kinds)
        if n == 0:
            break
        env.step(rng.randrange(n))
    if env.done:
        return _terminal_z(env._engine.winner)
    return 0.0


def _rollout_one(
    root: MCTSNode,
    env,
    config: MCTSConfig,
    rng: random.Random,
) -> None:
    """One IS-MCTS rollout with random-playout leaf evaluation
    instead of network value."""
    path = [root]
    depth = 0
    while True:
        node = path[-1]
        if node.terminal:
            break
        legal_ids = legal_ids_from_env(env)
        if not legal_ids:
            break
        if not node.expanded:
            # Expand with uniform prior + random rollout value
            n_legal = len(legal_ids)
            for aid in legal_ids:
                if aid not in node.children:
                    node.children[aid] = MCTSNode(
                        turn=-1,
                        terminal=False,
                        prior=1.0 / n_legal,
                    )
            v_p0 = _random_rollout(env, config.max_rollout_depth - depth, rng)
            node.leaf_value_p0 = v_p0
            node.expanded = True
            break
        for aid in legal_ids:
            if aid not in node.children:
                node.children[aid] = MCTSNode(
                    turn=-1,
                    terminal=False,
                    prior=1.0 / len(legal_ids),
                )
            node.children[aid].N_avail += 1
        chosen_id = _puct_select(node, legal_ids, config.c_puct)
        action_idx = _find_action_index(legal_ids, chosen_id)
        _, _, done, info = env.step(action_idx)
        child = node.children[chosen_id]
        child.turn = env.acting_player
        child.terminal = bool(done)
        if done:
            child.winner = int(info.get('winner', -1))
            child.leaf_value_p0 = _terminal_z(child.winner)
            child.expanded = True
        path.append(child)
        depth += 1
        if depth > config.max_rollout_depth:
            break
    leaf = path[-1]
    leaf_v = leaf.leaf_value_p0 if leaf.leaf_value_p0 is not None else 0.0
    for node in path:
        node.N += 1
        node.W += leaf_v


def is_mcts_rollout_search(
    env,
    spec,
    rng,
    viewing_player,
    config,
) -> int:
    """IS-MCTS search using random rollout for leaf value + uniform prior."""
    root_snap = env.snapshot()
    try:
        root = MCTSNode(turn=env.acting_player, terminal=False)
        legal_ids_root = legal_ids_from_env(env)
        n_legal = len(legal_ids_root)
        for aid in legal_ids_root:
            root.children[aid] = MCTSNode(
                turn=-1,
                terminal=False,
                prior=1.0 / n_legal,
            )
        v_p0 = _random_rollout(env, config.max_rollout_depth, rng)
        root.leaf_value_p0 = v_p0
        root.expanded = True

        opponent = 1 - viewing_player
        opp_dice_total = env._engine.dice_total(opponent)

        for _ in range(config.n_rollouts):
            env.restore(root_snap)
            hidden = sample_hidden_state(
                env,
                viewing_player,
                spec,
                rng,
                opponent_dice_total=opp_dice_total,
            )
            apply_determinization(env, hidden, opponent)
            _rollout_one(root, env, config, rng)

        env.restore(root_snap)
        legal_ids_final = legal_ids_from_env(env)
        visits = np.array(
            [root.children[aid].N for aid in legal_ids_final],
            dtype=np.float32,
        )
        return int(visits.argmax())
    finally:
        env.snapshot_free(root_snap)


class _RandomPlayer:
    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def select_action(self, env):
        kinds, _ = env.get_legal_actions()
        return self.rng.randrange(len(kinds))


def play_series(search_fn, opp, env_factory, n_games, spec, mcts_cfg):
    rng = random.Random(54321)
    wins = losses = draws = 0
    for g in range(n_games):
        side = g % 2
        env = env_factory(g)
        try:
            while env._engine.phase == 1:
                env.step(0)
                if env.done:
                    break
            while not env.done:
                acting = env.acting_player
                if acting == side:
                    chosen = search_fn(env, spec, rng, acting, mcts_cfg)
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
            env.close()
    decisive = max(1, wins + losses)
    return {
        'wins': wins,
        'losses': losses,
        'draws': draws,
        'wr': round(wins / decisive, 3),
    }


def main():
    cfg = diag_cfg(data_dir='data')
    pool_refs = resolve_pool_refs(cfg.scenario)
    spec = SharedFixedPool(pool_refs)

    def env_factory(i):
        seed = 66000 + i
        env = GicgEnv(
            cfg.scenario.team_0,
            cfg.scenario.team_1,
            card_pool=cfg.scenario.card_pool,
            seed=seed,
            data_dir=cfg.scenario.data_dir,
        )
        env.reset(seed=seed)
        return env

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
        f'IS-MCTS(uniform prior + random rollout value, 100 rollouts) vs opponents, {N} games:',
        flush=True,
    )
    for name, opp in opponents:
        t0 = time.perf_counter()
        r = play_series(is_mcts_rollout_search, opp, env_factory, N, spec, mcts_cfg)
        dt = time.perf_counter() - t0
        print(f'  vs {name}: {r}  ({dt:.1f}s)', flush=True)


if __name__ == '__main__':
    main()
