"""DMC adapter episode driver — capture_obs / play_one_episode / collate_batch.

Relocated from ``training/paradigms/dmc/legacy/_episode.py`` (FU-W4-DMC).
FU-W4-DMC-pt2 finished the legacy retirement; ``DmcAgent`` now lives at
adapter top-level (``_agent.py``) and ``tools/eval/`` shares the same
import path.

The episode driver records the *acting player's* transitions as
``DmcTransition`` records (defined in :mod:`training.paradigms.dmc.buffer`)
and returns ``(transitions, G, n_steps)`` where ``G`` is the MC return
from the agent's perspective (γ=1, ±1 terminal).
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

import numpy as np
import torch

from gicg_env import GicgEnv
from training.core.step_encoding import (
    build_legal_mask,
    pad_action_payments,
    pad_action_refs,
)
from training.paradigms.dmc._agent import DmcAgent

if TYPE_CHECKING:  # avoid cyclic import at runtime
    from training.paradigms.dmc.buffer import DmcTransition


def capture_obs(env: GicgEnv, agent: DmcAgent) -> dict:
    """Snapshot all obs arrays needed to reproduce ``forward_batch``."""
    dyn_obs = env._get_obs()
    kinds, _ = env.get_legal_actions()
    n_legal = int(len(kinds))
    if n_legal == 0:
        return {}
    refs_np = env.get_action_refs()
    pay_np = env.get_legal_action_payments()

    refs_padded = pad_action_refs(refs_np, agent.cfg.max_actions)
    pay_padded = pad_action_payments(pay_np, agent.cfg.max_actions)
    legal_mask = build_legal_mask(agent.cfg.max_actions, n_legal)

    (
        counter_values_t,
        meta_t,
        card_buckets_t,
        enemy_sizes_t,
        recent_damage_t,
        prepare_skill_t,
        modifier_log_t,
    ) = agent._parse_dynamic_single(dyn_obs)

    return {
        'counter_values': counter_values_t.squeeze(0).cpu().numpy().astype(np.float32),
        'meta': meta_t.squeeze(0).cpu().numpy().astype(np.float32),
        'card_buckets': card_buckets_t.squeeze(0).cpu().numpy().astype(np.float32),
        'enemy_sizes': enemy_sizes_t.squeeze(0).cpu().numpy().astype(np.float32),
        'recent_damage': recent_damage_t.squeeze(0).cpu().numpy().astype(np.float32),
        'prepare_skill': prepare_skill_t.squeeze(0).cpu().numpy().astype(np.float32),
        'modifier_log': modifier_log_t.squeeze(0).cpu().numpy().astype(np.float32),
        'action_refs': refs_padded.astype(np.int64),
        'action_payments': pay_padded.astype(np.float32),
        'legal_mask': legal_mask.astype(bool),
        'n_legal': n_legal,
        # Static obs replicated per transition for storage simplicity.
        'counter_sids': agent._counter_sids.squeeze(0).cpu().numpy().astype(np.int64),
        'active_slot_mask': agent._active_slot_mask.squeeze(0).cpu().numpy().astype(bool),
        'char_skill_refs': agent._char_skill_refs.squeeze(0).cpu().numpy().astype(np.int64),
        'hook_types': agent._hook_types_cache.cpu().numpy().astype(np.int64)
        if agent._hook_types_cache is not None
        else None,
        'hook_values': agent._hook_values_cache.cpu().numpy().astype(np.float32)
        if agent._hook_values_cache is not None
        else None,
        'hook_mask': agent._hook_mask.squeeze(0).cpu().numpy().astype(bool),
    }


def terminal_z(winner: int, perspective: int) -> float:
    """+1 if perspective player won, -1 if lost, 0 if draw / unknown."""
    if winner < 0:
        return 0.0
    if winner == perspective:
        return 1.0
    if winner == 2:
        return 0.0
    return -1.0


def play_one_episode(
    env: GicgEnv,
    agent: DmcAgent,
    opponent,
    *,
    agent_side: int,
    max_steps: int,
    rng_action: random.Random,
) -> tuple[list['DmcTransition'], float, int]:
    """Play one full episode; agent controls ``agent_side`` (0 or 1).

    Returns ``(transitions, G, n_steps)``: agent-side decisions, MC return
    in ±1, total env step count.
    """
    # Late import to avoid cycle with buffer.py.
    from training.paradigms.dmc.buffer import DmcTransition

    if env.done:
        return [], terminal_z(env._engine.winner, agent_side), 0

    agent.game_start(env.static_obs)
    if hasattr(opponent, 'game_start'):
        opponent.game_start(env.static_obs)

    transitions: list[DmcTransition] = []
    step_idx = -1
    for step_idx in range(max_steps):
        if env.done:
            break
        kinds, _ = env.get_legal_actions()
        n_legal = len(kinds)
        if n_legal == 0:
            break

        acting = env.acting_player
        if acting == agent_side:
            obs = capture_obs(env, agent)
            if not obs:
                break
            action_idx, _logit = agent.act_with_logit(env)
            transitions.append(DmcTransition(obs_dict=obs, action_idx=int(action_idx), G=0.0))
        else:
            action_idx = opponent.select_action(env)
            if action_idx < 0 or action_idx >= n_legal:
                action_idx = 0
        env.step(action_idx)

    G = terminal_z(env._engine.winner, agent_side)
    return transitions, G, step_idx + 1


def collate_batch(transitions: list['DmcTransition'], device: str = 'cpu') -> tuple[dict, torch.Tensor, torch.Tensor]:
    """Stack a list of ``DmcTransition`` into a torch batch for
    ``forward_batch``.

    Variable-shape hook fields are padded to batch-max ``n_active``; fixed
    fields are simply stacked. Returns
    ``(batch_dict, action_idx_tensor, returns_tensor)``.
    """
    if not transitions:
        raise ValueError('collate_batch: empty transition list')

    B = len(transitions)
    out: dict = {}
    fixed_keys = (
        'counter_values',
        'meta',
        'card_buckets',
        'enemy_sizes',
        'recent_damage',
        'prepare_skill',
        'modifier_log',
        'action_refs',
        'action_payments',
        'legal_mask',
        'counter_sids',
        'active_slot_mask',
        'char_skill_refs',
    )
    for k in fixed_keys:
        out[k] = np.stack([t.obs_dict[k] for t in transitions], axis=0)

    hook_types_list = [t.obs_dict['hook_types'] for t in transitions]
    hook_values_list = [t.obs_dict['hook_values'] for t in transitions]
    hook_mask_list = [t.obs_dict['hook_mask'] for t in transitions]
    max_n_active = max(ht.shape[0] for ht in hook_types_list)
    max_tokens = hook_types_list[0].shape[1]

    hook_types = np.zeros((B, max_n_active, max_tokens), dtype=np.int64)
    hook_values = np.zeros((B, max_n_active, max_tokens), dtype=np.float32)
    hook_mask = np.zeros((B, max_n_active), dtype=bool)
    for i, (ht, hv, hm) in enumerate(zip(hook_types_list, hook_values_list, hook_mask_list)):
        n_act = ht.shape[0]
        hook_types[i, :n_act] = ht
        hook_values[i, :n_act] = hv
        hook_mask[i, :n_act] = hm
    out['hook_types'] = hook_types
    out['hook_values'] = hook_values
    out['hook_mask'] = hook_mask

    action_idx = torch.tensor([t.action_idx for t in transitions], dtype=torch.long, device=device)
    returns = torch.tensor([t.G for t in transitions], dtype=torch.float32, device=device)
    return out, action_idx, returns
