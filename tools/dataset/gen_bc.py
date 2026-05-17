"""BC dataset generation entry — AZ-shape canonical schema(TL5.1)。

NPZ schema(9 fields,consumed by
``training.paradigms.bc.legacy.bc_dataset.BCDataset``):
per-game ``game_static_obs``;per-decision ``game_id``,``dyn_obs``,
``action_refs``,``action_payments``,``legal_mask``,``tied_mask``,
``chosen_action``,``terminal_z``。

Variant history(B2 2026-05-16):W2A 曾保留 dual-shape dispatcher(AZ+PPO)
因 BC PPO 变体要 flat-MLP obs;FU-W1A-followup(adc6db2/2d0584b/1cb1bec)
退役 BC PPO 变体后 PPO-shape codepath 与 dispatcher 一并退役。

Usage::

    .venv/bin/python -m tools.dataset.gen_bc configs/<bc_data_gen.toml>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from gicg_env import GicgEnv
from training.core.matchup.greedy_player import GreedyPlayer
from training.core.obs_constants import DICE_COLOR_COUNT
from training.core.step_encoding import pad_action_payments, pad_action_refs


# Whitelist of legitimate top-level cfg keys (meta = opaque metadata namespace).
# Stale keys (e.g. teacher_paradigm) SHALL raise per CLAUDE.md "意外输入必须抛异常".
_KNOWN_CFG_KEYS = frozenset(
    'run_label seed teacher teacher_dice_greedy opponent_mix target_decisions max_games max_actions'
    ' fix_dice teams card_pool max_rounds data_dir obs_mask deck_padding pool meta'.split()
)


def _parse_greedy_spec(spec: str, seed: int, dice_greedy: bool) -> GreedyPlayer:
    parts = spec.split('-')
    if len(parts) != 2 or not parts[0].startswith('F') or not parts[1].startswith('D'):
        raise ValueError(f'greedy spec must be F{{i}}-D{{j}}, got {spec!r}')
    return GreedyPlayer(features=parts[0], depth=int(parts[1][1:]), seed=seed, dice_greedy=dice_greedy)


def _legal_mask(env: GicgEnv, max_actions: int) -> tuple[np.ndarray, int]:
    kinds, _ = env.get_legal_actions()
    raw = len(kinds)
    n = min(raw, max_actions)
    m = np.zeros(max_actions, dtype=bool)
    m[:n] = True
    return m, raw


def collect(cfg: dict) -> dict[str, Any]:
    """Run the collection loop. Returns an in-memory dataset dict matching
    BCDataset NPZ schema(9 fields + 'meta')。"""
    rng = np.random.default_rng(cfg['seed'])

    teacher_spec: str = cfg['teacher']
    teacher_dice_greedy: bool = cfg['teacher_dice_greedy']
    opp_mix: list[str] = list(cfg['opponent_mix'])
    target_decisions: int = int(cfg['target_decisions'])
    max_games: int = int(cfg['max_games'])
    max_actions: int = int(cfg['max_actions'])

    fix_dice_raw = cfg['fix_dice']
    fix_dice: list[int] | None = None if fix_dice_raw == 'none' else list(fix_dice_raw)
    teams_p0 = list(cfg['teams'])
    teams_p1 = list(cfg['teams'])
    card_pool = list(cfg['card_pool']) if cfg['card_pool'] else []
    max_rounds = int(cfg['max_rounds'])
    data_dir = cfg['data_dir']
    obs_mask_raw = cfg.get('obs_mask') or []
    obs_mask = list(obs_mask_raw) if obs_mask_raw else None
    deck_padding_raw = cfg.get('deck_padding')
    deck_padding = (
        {'card': str(deck_padding_raw['card']), 'target_size': int(deck_padding_raw['target_size'])}
        if deck_padding_raw
        else None
    )
    pool = cfg.get('pool')
    if pool is not None and not isinstance(pool, str):
        pool = list(pool)

    # Per-game accumulators
    game_static_buf: list[np.ndarray] = []  # (n_games, static_obs_size)

    # Per-decision accumulators
    game_id_buf: list[int] = []
    dyn_obs_buf: list[np.ndarray] = []
    action_refs_buf: list[np.ndarray] = []
    action_payments_buf: list[np.ndarray] = []
    legal_mask_buf: list[np.ndarray] = []
    tied_mask_buf: list[np.ndarray] = []
    chosen_action_buf: list[int] = []

    ep_teacher_side: list[int] = []
    ep_winner: list[int] = []

    n_decisions_dropped_forced = 0
    n_decisions_dropped_oob = 0
    raw_legal_counts: list[int] = []
    games_played = 0
    t_start = time.perf_counter()

    while len(chosen_action_buf) < target_decisions and games_played < max_games:
        episode_id = games_played
        teacher_side = int(rng.integers(0, 2))
        opp_spec = opp_mix[int(rng.integers(0, len(opp_mix)))]

        teacher = _parse_greedy_spec(teacher_spec, int(rng.integers(0, 2**31 - 1)), teacher_dice_greedy)
        opponent = _parse_greedy_spec(opp_spec, int(rng.integers(0, 2**31 - 1)), teacher_dice_greedy)

        env = GicgEnv(
            teams_p0,
            teams_p1,
            card_pool=card_pool,
            seed=int(rng.integers(0, 2**31 - 1)),
            data_dir=data_dir,
            max_rounds=max_rounds,
            fix_dice=fix_dice,
            obs_mask=obs_mask,
            deck_padding=deck_padding,
            pool=pool,
            reward_shaping=None,
        )
        try:
            # Capture static obs once per game (constant across game).
            game_static_buf.append(np.asarray(env.static_obs, dtype=np.float32).copy())

            while not env.done:
                kinds, _ = env.get_legal_actions()
                if len(kinds) == 0:
                    break
                actor = env.acting_player
                if actor == teacher_side:
                    if len(kinds) > 1:
                        a, info = teacher.select_with_info(env)
                        mask, raw_legal = _legal_mask(env, max_actions)
                        raw_legal_counts.append(raw_legal)
                        if int(a) >= max_actions or any(t >= max_actions for t in info['tied']):
                            n_decisions_dropped_oob += 1
                        else:
                            tied_mask = np.zeros(max_actions, dtype=bool)
                            for t in info['tied']:
                                tied_mask[int(t)] = True
                            dyn_obs_np = env._get_obs()
                            refs_np = np.asarray(env.get_action_refs(), dtype=np.int64)
                            payments_np = np.asarray(env.get_legal_action_payments(), dtype=np.float32)
                            game_id_buf.append(episode_id)
                            dyn_obs_buf.append(dyn_obs_np.astype(np.float32, copy=True))
                            action_refs_buf.append(pad_action_refs(refs_np, max_actions))
                            action_payments_buf.append(pad_action_payments(payments_np, max_actions))
                            legal_mask_buf.append(mask)
                            tied_mask_buf.append(tied_mask)
                            chosen_action_buf.append(int(a))
                    else:
                        a = teacher.select_action(env)
                        n_decisions_dropped_forced += 1
                else:
                    a = opponent.select_action(env)
                env.step(a)
            winner = env._engine.winner if env.done else -1
        finally:
            env.close()

        ep_teacher_side.append(teacher_side)
        ep_winner.append(winner)
        games_played += 1

        if games_played % 100 == 0:
            elapsed = time.perf_counter() - t_start
            rate = len(chosen_action_buf) / elapsed if elapsed > 0 else 0.0
            print(
                f'[games={games_played:4d}] decisions={len(chosen_action_buf):6d} '
                f'(target={target_decisions}, dropped_forced={n_decisions_dropped_forced}, '
                f'dropped_oob={n_decisions_dropped_oob}) '
                f'rate={rate:.0f}/s elapsed={elapsed:.1f}s'
            )

    # Resolve terminal_z per decision (teacher-side perspective).
    terminal_z_per_ep: dict[int, float] = {}
    for eid, (side, winner) in enumerate(zip(ep_teacher_side, ep_winner)):
        if winner < 0 or winner == 2:
            terminal_z_per_ep[eid] = 0.0
        elif winner == side:
            terminal_z_per_ep[eid] = 1.0
        else:
            terminal_z_per_ep[eid] = -1.0
    terminal_z_buf = np.asarray(
        [terminal_z_per_ep[eid] for eid in game_id_buf],
        dtype=np.float32,
    )

    teacher_self_wr = float(np.mean([1.0 if z > 0 else 0.0 for z in terminal_z_buf])) if len(terminal_z_buf) else 0.0
    raw_legal_arr = np.asarray(raw_legal_counts, dtype=np.int32)

    return {
        'game_static_obs': np.stack(game_static_buf, axis=0) if game_static_buf else np.zeros((0,), dtype=np.float32),
        'game_id': np.asarray(game_id_buf, dtype=np.int32),
        'dyn_obs': np.stack(dyn_obs_buf, axis=0).astype(np.float32, copy=False)
        if dyn_obs_buf
        else np.zeros((0,), dtype=np.float32),
        'action_refs': np.stack(action_refs_buf, axis=0)
        if action_refs_buf
        else np.zeros((0, max_actions, 3), dtype=np.int64),
        'action_payments': np.stack(action_payments_buf, axis=0)
        if action_payments_buf
        else np.zeros((0, max_actions, DICE_COLOR_COUNT), dtype=np.float32),
        'legal_mask': np.stack(legal_mask_buf, axis=0) if legal_mask_buf else np.zeros((0,), dtype=bool),
        'tied_mask': np.stack(tied_mask_buf, axis=0) if tied_mask_buf else np.zeros((0,), dtype=bool),
        'chosen_action': np.asarray(chosen_action_buf, dtype=np.int32),
        'terminal_z': terminal_z_buf,
        'meta': {
            'teacher': teacher_spec,
            'teacher_dice_greedy': teacher_dice_greedy,
            'opponent_mix': opp_mix,
            'max_actions': max_actions,
            'fix_dice': fix_dice,
            'obs_mask': obs_mask,
            'card_pool': card_pool,
            'max_rounds': max_rounds,
            'teams_p0': teams_p0,
            'teams_p1': teams_p1,
            'games_played': games_played,
            'n_decisions': len(chosen_action_buf),
            'n_dropped_forced': n_decisions_dropped_forced,
            'n_dropped_oob': n_decisions_dropped_oob,
            'teacher_self_wr': teacher_self_wr,
            'raw_legal_mean': float(raw_legal_arr.mean()) if len(raw_legal_arr) else 0.0,
            'raw_legal_p50': int(np.percentile(raw_legal_arr, 50)) if len(raw_legal_arr) else 0,
            'raw_legal_p99': int(np.percentile(raw_legal_arr, 99)) if len(raw_legal_arr) else 0,
            'tied_mean': float(np.mean([m.sum() for m in tied_mask_buf])) if tied_mask_buf else 0.0,
        },
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog='tools.dataset.gen_bc', description='BC dataset gen (AZ-shape).')
    parser.add_argument('config', type=str, help='TOML config path')
    args = parser.parse_args(argv)

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f'[gen_bc] config not found: {cfg_path}', file=sys.stderr)
        return 2

    with cfg_path.open('rb') as f:
        cfg = tomllib.load(f)

    unknown = set(cfg.keys()) - _KNOWN_CFG_KEYS
    if unknown:
        raise ValueError(f'unknown cfg key(s): {sorted(unknown)}; supported: {sorted(_KNOWN_CFG_KEYS)}')

    run_label = cfg['run_label']
    ts = datetime.now().strftime('%Y%m%d%H%M')
    out_dir = Path('artifacts') / f'{ts}_{run_label}'
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f'[gen_bc] writing to {out_dir}')
    data = collect(cfg)

    out_path = out_dir / 'dataset.npz'
    np_kwargs = {k: v for k, v in data.items() if k != 'meta'}
    np.savez_compressed(out_path, **np_kwargs)

    meta_path = out_dir / 'meta.json'
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(data['meta'], f, ensure_ascii=False, indent=2)

    print(f'[gen_bc] DONE. dataset={out_path} meta={meta_path}')
    print(
        f'[gen_bc] decisions={data["meta"]["n_decisions"]} '
        f'games={data["meta"]["games_played"]} '
        f'teacher_self_wr={data["meta"]["teacher_self_wr"]:.3f} '
        f'tied_mean={data["meta"]["tied_mean"]:.2f}'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
