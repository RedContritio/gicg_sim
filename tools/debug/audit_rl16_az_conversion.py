"""Audit behavioral parity between a semantic RL checkpoint and its AZ conversion."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch

from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.paradigms.az._player_loader import _load_az_agent_from_ckpt
from tools.experiments.semantic_training.player_loader import load_semantic_agent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _distribution_stats(values: np.ndarray) -> dict[str, float]:
    clipped = np.clip(values, 1e-30, 1.0)
    entropy = float(-(clipped * np.log(clipped)).sum())
    n = len(values)
    return {
        'entropy': entropy,
        'normalized_entropy': entropy / math.log(n) if n > 1 else 0.0,
        'top1_mass': float(values.max()),
        'top8_mass': float(np.sort(values)[-min(8, n) :].sum()),
    }


def audit(args: argparse.Namespace) -> dict:
    cfg = load_cfg(args.config)
    env_factory = make_env_factory(cfg, None, master_seed=args.seed)
    semantic = load_semantic_agent(
        str(args.semantic),
        verify_provenance=not args.allow_unverified,
    )
    converted = _load_az_agent_from_ckpt(
        str(args.converted),
        verify_provenance=not args.allow_unverified,
    )

    rows = []
    max_legal = 0
    for game_idx in range(args.games):
        env = env_factory(game_idx)
        semantic.game_start(env.static_obs)
        converted.game_start(env.static_obs)
        for step in range(args.max_steps):
            if env.done:
                break
            kinds, _ = env.get_legal_actions()
            n_legal = len(kinds)
            if n_legal == 0:
                break
            max_legal = max(max_legal, n_legal)
            q = semantic.logits(env).detach().cpu().numpy().astype(np.float64)
            q_prior = torch.softmax(torch.from_numpy(q), dim=-1).numpy()
            az_prior, _ = converted.eval_state(
                env._get_obs(),
                env.get_action_refs(),
                env.get_legal_action_payments(),
            )
            az_prior = np.asarray(az_prior, dtype=np.float64)
            decision_type = 'reroll' if np.all(np.asarray(kinds) == 5) else 'ordinary'
            rows.append(
                {
                    'game': game_idx,
                    'step': step,
                    'decision_type': decision_type,
                    'n_legal': n_legal,
                    'argmax_equal': int(np.argmax(q_prior)) == int(np.argmax(az_prior)),
                    'max_probability_error': float(np.max(np.abs(q_prior - az_prior))),
                    'q_min': float(q.min()),
                    'q_max': float(q.max()),
                    'q_std': float(q.std()),
                    'semantic': _distribution_stats(q_prior),
                    'converted': _distribution_stats(az_prior),
                }
            )
            env.step(int(np.argmax(q_prior)))
        else:
            raise RuntimeError(f'game {game_idx} exceeded max_steps={args.max_steps}')

    by_type = {}
    for decision_type in ('reroll', 'ordinary'):
        selected = [row for row in rows if row['decision_type'] == decision_type]
        if not selected:
            continue
        by_type[decision_type] = {
            'states': len(selected),
            'argmax_agreement': sum(row['argmax_equal'] for row in selected) / len(selected),
            'max_probability_error': max(row['max_probability_error'] for row in selected),
            'mean_probability_error': float(np.mean([row['max_probability_error'] for row in selected])),
            'mean_n_legal': float(np.mean([row['n_legal'] for row in selected])),
            'max_n_legal': max(row['n_legal'] for row in selected),
            'semantic_mean_q_range': float(np.mean([row['q_max'] - row['q_min'] for row in selected])),
            'semantic_mean_q_std': float(np.mean([row['q_std'] for row in selected])),
            'semantic_mean_normalized_entropy': float(
                np.mean([row['semantic']['normalized_entropy'] for row in selected])
            ),
            'converted_mean_normalized_entropy': float(
                np.mean([row['converted']['normalized_entropy'] for row in selected])
            ),
            'semantic_mean_top1_mass': float(np.mean([row['semantic']['top1_mass'] for row in selected])),
            'converted_mean_top1_mass': float(np.mean([row['converted']['top1_mass'] for row in selected])),
        }

    return {
        'semantic_checkpoint': str(args.semantic),
        'semantic_sha256': _sha256(args.semantic),
        'converted_checkpoint': str(args.converted),
        'converted_sha256': _sha256(args.converted),
        'config': str(args.config),
        'seed': args.seed,
        'games': args.games,
        'states': len(rows),
        'max_n_legal': max_legal,
        'by_decision_type': by_type,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('semantic', type=Path)
    parser.add_argument('converted', type=Path)
    parser.add_argument('--config', type=Path, default=Path('configs/dmc/native_starter.toml'))
    parser.add_argument('--seed', type=int, default=910_001)
    parser.add_argument('--games', type=int, default=4)
    parser.add_argument('--max-steps', type=int, default=512)
    parser.add_argument('--allow-unverified', action='store_true')
    args = parser.parse_args()
    print(json.dumps(audit(args), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
