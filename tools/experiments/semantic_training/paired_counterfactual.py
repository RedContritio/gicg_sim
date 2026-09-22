"""Common-seed paired counterfactual rollouts for action preferences."""

from __future__ import annotations

import random

import torch
import torch.nn.functional as F

from training.core.matchup.outcome import terminal_outcome


def sample_alternative_action(logits: torch.Tensor, chosen: int, temperature: float = 1.0) -> int:
    if temperature <= 0 or logits.ndim != 1 or len(logits) < 2:
        raise ValueError('alternative sampling requires at least two logits and positive temperature')
    if not 0 <= chosen < len(logits):
        raise ValueError('chosen action is outside the logits')
    probabilities = (logits / temperature).softmax(-1)
    probabilities[chosen] = 0
    probabilities /= probabilities.sum()
    return int(torch.multinomial(probabilities, 1))


def reservoir_replace(seen: int, rng: random.Random) -> tuple[int, bool]:
    """Reservoir decision for callers that retain at most one root per game."""
    if seen < 0:
        raise ValueError('seen must be non-negative')
    seen += 1
    return seen, rng.randrange(seen) == 0


def _rollout(root, action, learner, opponent, learner_side: int, simulation_seed: int, max_steps: int):
    if learner_side not in (0, 1):
        raise ValueError('learner_side must be 0 or 1')
    if root.acting_player != learner_side:
        raise ValueError('counterfactual root must belong to the learner side')
    env = root.clone()
    try:
        env.set_simulation_seed(simulation_seed)
        env.step(int(action))
        learner.game_start(env.static_obs)
        if hasattr(learner, 'rng'):
            learner.rng.seed(simulation_seed ^ 0x51A7)
        if hasattr(opponent, 'game_start'):
            opponent.game_start(env.static_obs)
        if hasattr(opponent, 'rng'):
            opponent.rng.seed(simulation_seed ^ 0xD2CE)
        for step in range(max_steps):
            if env.done:
                return terminal_outcome(env.winner, learner_side), step
            player = learner if env.acting_player == learner_side else opponent
            env.step(int(player.select_action(env)))
        raise RuntimeError(f'paired counterfactual exceeded max_steps={max_steps}')
    finally:
        env.close()


def paired_rollouts(
    root,
    chosen_action: int,
    alternative_action: int,
    learner,
    opponent,
    *,
    learner_side: int,
    simulation_seeds,
    max_steps: int = 512,
    decision_type: str = 'ordinary',
) -> dict:
    if chosen_action == alternative_action:
        raise ValueError('paired actions must differ')
    simulation_seeds = list(simulation_seeds)
    rows, ties, total_steps = [], 0, 0
    for seed in simulation_seeds:
        chosen, chosen_steps = _rollout(root, chosen_action, learner, opponent, learner_side, seed, max_steps)
        alternative, alternative_steps = _rollout(
            root, alternative_action, learner, opponent, learner_side, seed, max_steps
        )
        total_steps += chosen_steps + alternative_steps
        if chosen == alternative:
            ties += 1
            continue
        rows.append(
            {
                'chosen_action': chosen_action,
                'alternative_action': alternative_action,
                'preference': 1 if chosen > alternative else -1,
                'decision_type': decision_type,
                'learner_side': learner_side,
                'simulation_seed': seed,
                'chosen_outcome': chosen,
                'alternative_outcome': alternative,
                'chosen_steps': chosen_steps,
                'alternative_steps': alternative_steps,
            }
        )
    return {'pairs': rows, 'ties': ties, 'rollouts': len(simulation_seeds), 'total_steps': total_steps}


def paired_preference_loss(
    logits: torch.Tensor,
    legal_mask: torch.Tensor,
    chosen: torch.Tensor,
    alternative: torch.Tensor,
    preference: torch.Tensor,
    anchor_logits: torch.Tensor,
    *,
    temperature: float = 1.0,
    anchor_beta: float = 0.02,
    sample_weight: torch.Tensor | None = None,
) -> tuple[torch.Tensor, dict]:
    if temperature <= 0 or anchor_beta < 0:
        raise ValueError('temperature must be positive and anchor_beta non-negative')
    if torch.any(~legal_mask.gather(1, chosen[:, None])) or torch.any(~legal_mask.gather(1, alternative[:, None])):
        raise ValueError('paired action is not legal for its observation')
    scaled = logits / temperature
    anchor = anchor_logits / temperature
    margin = scaled.gather(1, chosen[:, None]).squeeze(1) - scaled.gather(1, alternative[:, None]).squeeze(1)
    terms = F.softplus(-preference * margin)
    if sample_weight is None:
        preference_term = terms.mean()
    else:
        if sample_weight.shape != terms.shape or torch.any(sample_weight < 0):
            raise ValueError('sample_weight must be non-negative and batch-shaped')
        preference_term = (terms * sample_weight).sum() / sample_weight.sum().clamp_min(1e-8)
    logp = scaled.masked_fill(~legal_mask, -1e9).log_softmax(-1)
    anchor_logp = anchor.masked_fill(~legal_mask, -1e9).log_softmax(-1)
    kl = (logp.exp() * (logp - anchor_logp)).sum(-1).mean()
    loss = preference_term + anchor_beta * kl
    return loss, {'preference_loss': preference_term, 'anchor_kl': kl, 'signed_margin': (preference * margin).mean()}
