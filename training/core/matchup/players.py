"""Minimal MCTS player for GICG, using engine snapshot/restore.

No learned components — pure UCT with uniform priors and random rollouts.
Promoted from tools/ into framework/ because matchup.py references it
and the dependency direction must be training → tools, not reverse.
"""

from __future__ import annotations

import argparse
import math
import random
import time
from dataclasses import dataclass, field
from typing import List, Optional

from gicg_env import GicgEnv

DEFAULT_C_PUCT = 1.4


@dataclass
class MCTSNode:
    turn: int  # player (0 or 1) whose turn to move at this state
    terminal: bool = False
    winner: int = -1  # -1 in-progress, 0/1 winner, 2 draw
    n_legal: int = 0
    children: List[Optional['MCTSNode']] = field(default_factory=list)
    N: int = 0
    # W = cumulative "player 0 won" signal. 1.0 for P0 win, 0.0 for P1,
    # 0.5 for draw. For non-P0 perspective, use 1-W/N.
    W: float = 0.0


def _p0_value(winner: int) -> float:
    if winner == 0:
        return 1.0
    if winner == 1:
        return 0.0
    return 0.5  # draw or unknown


def _ucb_score(parent: MCTSNode, child: MCTSNode, c_puct: float) -> float:
    if child.N == 0:
        return float('inf')
    q_p0 = child.W / child.N
    q = q_p0 if parent.turn == 0 else (1.0 - q_p0)
    u = c_puct * math.sqrt(math.log(parent.N + 1) / child.N)
    return q + u


def _random_rollout(env: GicgEnv, max_depth: int, rng: random.Random) -> int:
    """Play random actions until game-over or max_depth reached."""
    for _ in range(max_depth):
        if env.done:
            return env._engine.winner
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            return env._engine.winner
        a = rng.randrange(len(kinds))
        env.step(a)
    return env._engine.winner


def _mcts_search(
    env: GicgEnv,
    root_snap: int,
    n_rollouts: int,
    max_rollout_depth: int,
    c_puct: float,
    rng: random.Random,
) -> tuple[int, List[int]]:
    """Run n_rollouts from the state captured in root_snap."""
    env.restore(root_snap)
    root = MCTSNode(turn=env.current_player)
    if env.done:
        return 0, []
    kinds, _ = env.get_legal_actions()
    root.n_legal = len(kinds)
    if root.n_legal == 0:
        return 0, []
    root.children = [None] * root.n_legal

    for _ in range(n_rollouts):
        env.restore(root_snap)
        path: List[MCTSNode] = [root]
        node = root

        while True:
            if node.terminal or node.n_legal == 0:
                break
            unexpanded = [i for i, c in enumerate(node.children) if c is None]
            if unexpanded:
                a = unexpanded[0]
                env.step(a)
                new_turn = env.current_player
                new_terminal = env.done
                new_winner = env._engine.winner if new_terminal else -1
                new_node = MCTSNode(turn=new_turn, terminal=new_terminal, winner=new_winner)
                if not new_terminal:
                    kk, _ = env.get_legal_actions()
                    new_node.n_legal = len(kk)
                    new_node.children = [None] * new_node.n_legal
                node.children[a] = new_node
                path.append(new_node)
                node = new_node
                break
            best_a, best_s = -1, -float('inf')
            for a, c in enumerate(node.children):
                s = _ucb_score(node, c, c_puct)
                if s > best_s:
                    best_a, best_s = a, s
            env.step(best_a)
            node = node.children[best_a]
            path.append(node)

        if node.terminal:
            winner = node.winner
        else:
            winner = _random_rollout(env, max_rollout_depth, rng)

        v = _p0_value(winner)
        for p in path:
            p.N += 1
            p.W += v

    best_a, best_n = 0, -1
    visits: List[int] = []
    for a, c in enumerate(root.children):
        n = c.N if c is not None else 0
        visits.append(n)
        if n > best_n:
            best_a, best_n = a, n
    return best_a, visits


class MCTSPlayer:
    """UCT player using engine snapshot/restore for tree descent."""

    def __init__(
        self,
        n_rollouts: int = 400,
        max_rollout_depth: int = 80,
        c_puct: float = DEFAULT_C_PUCT,
        seed: int = 0,
    ):
        self.n_rollouts = n_rollouts
        self.max_rollout_depth = max_rollout_depth
        self.c_puct = c_puct
        self.rng = random.Random(seed)
        self.total_search_s: float = 0.0
        self.n_searches: int = 0

    def select_action(self, env: GicgEnv) -> int:
        env.log_suspend()
        try:
            snap = env.snapshot()
            try:
                t0 = time.perf_counter()
                action, _visits = _mcts_search(
                    env,
                    snap,
                    self.n_rollouts,
                    self.max_rollout_depth,
                    self.c_puct,
                    self.rng,
                )
                self.total_search_s += time.perf_counter() - t0
                self.n_searches += 1
                env.restore(snap)
                return action
            finally:
                env.snapshot_free(snap)
        finally:
            env.log_resume()

    def reset_profile(self) -> None:
        self.total_search_s = 0.0
        self.n_searches = 0

    def profile_summary(self) -> dict:
        return {
            'n_searches': self.n_searches,
            'total_search_s': round(self.total_search_s, 3),
            'avg_search_ms': round(1000.0 * self.total_search_s / max(self.n_searches, 1), 1),
        }


def _play_game(
    env: GicgEnv,
    p0,
    p1,
    seed: int,
    max_steps: int = 600,
) -> tuple[int, int]:
    """Play one full game; returns (winner, n_steps)."""
    env.reset(seed=seed)
    players = [p0, p1]
    for step_n in range(max_steps):
        if env.done:
            break
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            break
        acting = env.current_player
        action = players[acting](env) if callable(players[acting]) else players[acting].select_action(env)
        if action < 0 or action >= len(kinds):
            action = 0
        env.step(action)
    return env._engine.winner, step_n + 1


def _random_action(env: GicgEnv) -> int:
    kinds, _ = env.get_legal_actions()
    n = len(kinds)
    if n == 0:
        return 0
    return random.randrange(n)


def _first_action(env: GicgEnv) -> int:
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '--scenario',
        type=str,
        default='1v1_L1',
        choices=['1v1_L1', '1v1_L12', '2v2_L12'],
    )
    ap.add_argument('--rollouts', type=int, default=200)
    ap.add_argument('--games', type=int, default=10)
    ap.add_argument('--opponent', type=str, default='random', choices=['random', 'first'])
    ap.add_argument('--max-depth', type=int, default=80)
    args = ap.parse_args()

    if args.scenario == '1v1_L1':
        team_a, team_b = ['赤蝶'], ['墨客']
        cards = ['碌碌无为']
    elif args.scenario == '1v1_L12':
        team_a, team_b = ['赤蝶'], ['墨客']
        cards = ['碌碌无为', '佛跳墙', '美味烧鸡', '占星', '诅咒']
    else:
        team_a = ['赤蝶', '墨客']
        team_b = ['猫咪', '刻师傅']
        cards = ['碌碌无为', '佛跳墙', '美味烧鸡', '占星', '诅咒']

    env = GicgEnv(team_0=team_a, team_1=team_b, card_pool=cards, seed=0)

    mcts = MCTSPlayer(n_rollouts=args.rollouts, max_rollout_depth=args.max_depth)
    opponent = _random_action if args.opponent == 'random' else _first_action

    print(f'[config] scenario={args.scenario} rollouts={args.rollouts} games={args.games} opponent={args.opponent}')

    wins = {0: 0, 1: 0, 2: 0, -1: 0}
    mcts_wins = 0
    total_steps = 0
    t0 = time.perf_counter()
    for i in range(args.games):
        mcts_side = i % 2
        if mcts_side == 0:
            p0, p1 = mcts, opponent
        else:
            p0, p1 = opponent, mcts
        winner, steps = _play_game(env, p0, p1, seed=1000 + i)
        wins[winner] = wins.get(winner, 0) + 1
        total_steps += steps
        if winner == mcts_side:
            mcts_wins += 1
        print(f'  game {i + 1}: mcts=P{mcts_side} winner=P{winner} steps={steps}')
    dt = time.perf_counter() - t0
    print(
        f'[result] MCTS wins {mcts_wins}/{args.games} '
        f'({100.0 * mcts_wins / args.games:.0f}%), '
        f'raw={wins}, avg_steps={total_steps / args.games:.0f}'
    )
    print(f'[timing] {dt:.1f}s total, {dt / args.games:.2f}s/game')
    env.close()


if __name__ == '__main__':
    main()
