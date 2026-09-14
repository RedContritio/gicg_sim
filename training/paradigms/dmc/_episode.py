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
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
from training.core.step_encoding import pad_buffs_np
from training.core.matchup.outcome import terminal_outcome
import torch

from gicg_env import GicgEnv
from training.paradigms.dmc._agent import DmcAgent

if TYPE_CHECKING:  # avoid cyclic import at runtime
    from training.paradigms.dmc.buffer import DmcTransition


def capture_obs(env: GicgEnv, agent: DmcAgent) -> dict:
    """Snapshot all obs arrays needed to reproduce ``forward_batch``.

    I29 P2 (wire v3) — action_refs/action_payments/legal_mask 存 nlegal-sized,
    不 pad 到 max_actions(per-trans mem ~10x 降);collate_batch sample 时
    pad 到 cfg.max_actions(see ``collate_batch``)。 Go actor 路径走
    ``_capture_obs_np``,与本 Python actor 路径 buffer obs_dict 格式统一。
    """
    dyn_obs = env._get_obs()
    kinds, _ = env.get_legal_actions()
    n_legal = int(len(kinds))
    if n_legal == 0:
        return {}
    refs_np = np.asarray(env.get_action_refs(), dtype=np.int64)
    pay_np = np.asarray(env.get_legal_action_payments(), dtype=np.float32)
    # env.* 返 (n_real_legal, ...) 已经是 nlegal-sized — trim 到 n_legal 防 racy padding。
    refs_nlegal = refs_np[:n_legal]
    pay_nlegal = pay_np[:n_legal]

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
        'buffs': agent._parse_buff_single(dyn_obs).squeeze(0).cpu().numpy(),
        # nlegal-sized — pad-to-max_actions deferred to collate_batch。
        'action_refs': refs_nlegal,
        'action_payments': pay_nlegal,
        'legal_mask': np.ones(n_legal, dtype=bool),
        'n_legal': n_legal,
        # Static obs replicated per transition for storage simplicity.
        'counter_sids': agent._counter_sids.squeeze(0).cpu().numpy().astype(np.int64),
        'active_slot_mask': agent._active_slot_mask.squeeze(0).cpu().numpy().astype(bool),
        'char_skill_refs': agent._char_skill_refs.squeeze(0).cpu().numpy().astype(np.int64),
        'hook_ir': agent._hook_ir_cache.cpu().numpy().astype(np.int64) if agent._hook_ir_cache is not None else None,
        'hook_mask': agent._hook_mask.squeeze(0).cpu().numpy().astype(bool),
        'definition_links': agent._definition_links.squeeze(0).cpu().numpy().astype(np.int64),
    }


def terminal_z(winner: int, perspective: int) -> float:
    """Only engine-confirmed terminal outcomes may supervise Monte Carlo returns."""
    return float(terminal_outcome(winner, perspective))


def play_one_episode(
    env: GicgEnv,
    agent: DmcAgent,
    opponent,
    *,
    agent_side: int,
    max_steps: int,
    rng_action: random.Random,
    provider: Optional[Any] = None,
) -> tuple[list['DmcTransition'], float, int]:
    """Play one full episode; agent controls ``agent_side`` (0 or 1).

    Returns ``(transitions, G, n_steps)``: agent-side decisions, MC return
    in ±1, total env step count.

    If ``provider`` is supplied, the agent's per-turn inference routes
    through ``agent.act_via_provider(env, provider)`` — used by the
    unified NetworkProvider abstraction (LocalNetworkProvider wrapping a
    DMCInferenceNet, or RemoteNetworkProvider for cross-process / GPU
    inference). When ``provider is None`` (default), falls back to the
    in-proc ``agent.act_with_logit(env)`` path for backward compat.
    """
    # Late import to avoid cycle with buffer.py.
    from training.paradigms.dmc.buffer import DmcTransition

    if env.done:
        return [], terminal_z(env.winner, agent_side), 0

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
            if provider is not None:
                action_idx, _logit = agent.act_via_provider(env, provider)
            else:
                action_idx, _logit = agent.act_with_logit(env)
            transitions.append(DmcTransition(obs_dict=obs, action_idx=int(action_idx), G=0.0))
        else:
            action_idx = opponent.select_action(env)
        if action_idx < 0 or action_idx >= n_legal:
            raise ValueError('DMC episode player returned illegal action')
        env.step(action_idx)

    if not env.done:
        raise RuntimeError('DMC episode ended before terminal state; increase step budget or fix the environment')
    G = terminal_z(env.winner, agent_side)
    return transitions, G, step_idx + 1


def collate_batch(
    transitions: list['DmcTransition'],
    device: str = 'cpu',
    *,
    max_actions: int,
) -> tuple[dict, torch.Tensor, torch.Tensor]:
    """Stack a list of ``DmcTransition`` into a torch batch for
    ``forward_batch``.

    I29 P2 (wire v3) — action_refs/action_payments/legal_mask 在 transition
    存 nlegal-sized,本函数 pad 到 ``max_actions`` 生成 (B, max_actions, ...)
    batch tensor(网络 forward 期待 fixed-size action 维度;批内不同 n_legal
    走 zero-pad + legal_mask)。

    Variable-shape hook fields are padded to batch-max ``n_active``; truly
    fixed fields simply stacked. Returns ``(batch_dict, action_idx_tensor,
    returns_tensor)``.

    ``max_actions`` is required kwarg — caller (DMCBuffer.sample) 透传
    cfg.max_actions(must == 网络 AgentConfig.max_actions),避免静默 mismatch。
    """
    if not transitions:
        raise ValueError('collate_batch: empty transition list')
    if max_actions <= 0:
        raise ValueError(f'collate_batch: max_actions must be positive, got {max_actions}')

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
        'counter_sids',
        'active_slot_mask',
        'char_skill_refs',
    )
    from training.core.obs_constants import OBS_BUFF_FIELDS

    out['buffs'] = pad_buffs_np(
        [t.obs_dict.get('buffs', np.zeros((1, OBS_BUFF_FIELDS), dtype=np.float32)) for t in transitions]
    )
    for k in fixed_keys:
        out[k] = np.stack([t.obs_dict[k] for t in transitions], axis=0)

    # Variable per-trans action 维度 pad 到 max_actions(I29 P2 wire v3 起,refs/pay/
    # legal_mask 在 transition 是 nlegal-sized;collate 时统一 pad 出 batch tensor)。
    # n_legal > max_actions 必意味 actor 端 sample 漏校验或 cfg drift —— fail-loud,
    # 不静默截断(动作空间缩小是 silent corruption)。
    refs_pad = np.zeros((B, max_actions, 3), dtype=np.int64)
    pay_pad = np.zeros((B, max_actions, 8), dtype=np.float32)
    mask_pad = np.zeros((B, max_actions), dtype=bool)
    for i, t in enumerate(transitions):
        refs_i = t.obs_dict['action_refs']
        pay_i = t.obs_dict['action_payments']
        mask_i = t.obs_dict['legal_mask']
        n_legal = refs_i.shape[0]
        if n_legal > max_actions:
            raise ValueError(
                f'collate_batch: transition {i} n_legal={n_legal} > max_actions={max_actions} '
                f'(network action capacity exceeded; cfg.agent.max_actions or actor encoder mismatch)'
            )
        refs_pad[i, :n_legal] = refs_i
        pay_pad[i, :n_legal] = pay_i
        mask_pad[i, :n_legal] = mask_i
    out['action_refs'] = refs_pad
    out['action_payments'] = pay_pad
    out['legal_mask'] = mask_pad

    hook_ir_list = [t.obs_dict['hook_ir'] for t in transitions]
    hook_mask_list = [t.obs_dict['hook_mask'] for t in transitions]
    max_n_active = max(h.shape[0] for h in hook_ir_list)
    max_ops = hook_ir_list[0].shape[1]
    fields_per_op = hook_ir_list[0].shape[2]

    hook_ir = np.zeros((B, max_n_active, max_ops, fields_per_op), dtype=np.int64)
    hook_mask = np.zeros((B, max_n_active), dtype=bool)
    for i, (h, hm) in enumerate(zip(hook_ir_list, hook_mask_list)):
        n_act = h.shape[0]
        hook_ir[i, :n_act] = h
        hook_mask[i, :n_act] = hm
    out['hook_ir'] = hook_ir
    out['hook_mask'] = hook_mask

    link_list = [t.obs_dict['definition_links'] for t in transitions]
    max_links = max(rows.shape[0] for rows in link_list)
    definition_links = np.full((B, max_links, 2), -1, dtype=np.int64)
    for i, rows in enumerate(link_list):
        definition_links[i, : rows.shape[0]] = rows
    out['definition_links'] = definition_links

    action_idx = torch.tensor([t.action_idx for t in transitions], dtype=torch.long, device=device)
    returns = torch.tensor([t.G for t in transitions], dtype=torch.float32, device=device)
    return out, action_idx, returns
