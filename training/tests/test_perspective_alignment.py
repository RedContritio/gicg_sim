"""Canonical SID bindings, observation masking and relative readout regression."""

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv, OBS_COUNTER_SLOTS, OBS_META_SIZE, N_STRUCTURAL
from training.core.network.perspective import relative_structural
from training.core.step_encoding import parse_buffs_np, parse_dynamic_np
from training.core.structural import compute_structural_obspos, compute_structural_values


def test_asymmetric_normalization_and_enemy_mask_follow_actual_identity():
    with GicgEnv(
        ['赤蝶'],
        ['墨客', '赤蝶'],
        pool=['v_legacy'],
        card_pool=[],
        obs_mask=['enemy_dice'],
        data_dir='data',
        max_rounds=3,
    ) as env:
        env.reset(seed=43)
        meta = env.static_obs[: OBS_COUNTER_SLOTS * 3].reshape(-1, 3)
        labels = env._engine.get_active_counter_slot_labels()
        valid = (meta[:, 0] != 0) | (meta[:, 1] != 0) | (meta[:, 2] != 0)
        sids = meta[:, 2].astype(np.int64)
        seen = set()
        for _ in range(40):
            p = env.acting_player
            seen.add(p)
            obs = env._get_obs()
            counters, public, _, _ = parse_dynamic_np(obs, OBS_COUNTER_SLOTS)
            assert public[18] == p
            raw = env._engine.get_counters().copy()  # independently SID-indexed
            rows = parse_buffs_np(obs, OBS_COUNTER_SLOTS)
            for row in rows:
                if row[0] and row[12] in (3, 4):
                    sid = int(row[13])
                    raw[sid] = int(raw[sid] >= 0)
            expected = (raw[sids[valid]] - meta[valid, 0]) / np.maximum(meta[valid, 1] - meta[valid, 0], 1)
            masked = np.array([label.startswith(f'P{1 - p}:') and 'dice_' in label for label in labels])
            expected[masked[valid]] = 0
            np.testing.assert_allclose(counters[valid], expected)
            for observer in (0, 1):
                wire = env._engine.get_dynamic_obs(observer)
                np.testing.assert_array_equal(
                    wire[OBS_META_SIZE : OBS_META_SIZE + OBS_COUNTER_SLOTS][valid], raw[sids[valid]]
                )
            kinds, _ = env.get_legal_actions()
            if env.done or not len(kinds):
                break
            # End declaration ensures both decision-makers are exercised.
            ends = np.flatnonzero(kinds == 3)
            env.step(int(ends[0]) if len(ends) else 0)
        assert seen == {0, 1}


def test_relative_readout_mixed_replay_batch_and_gradient():
    # Deliberately permute the static counter layout. SID-based gathering must
    # happen BEFORE the own/enemy projection, and independently for each row.
    perm = torch.randperm(N_STRUCTURAL)
    sids = perm.repeat(2, 1)
    absolute = torch.arange(N_STRUCTURAL, dtype=torch.float32).repeat(2, 1)
    values = absolute[:, perm].clone().requires_grad_()
    pos = compute_structural_obspos(sids, torch.ones_like(sids, dtype=torch.bool))
    gathered = compute_structural_values(values, pos)
    meta = torch.zeros(2, OBS_META_SIZE)
    meta[1, 18] = 1
    actual = relative_structural(gathered, meta)
    torch.testing.assert_close(actual[0], absolute[0])
    # Independent checks of HP/energy/alive/active, dice and alive-count blocks.
    torch.testing.assert_close(actual[1, :24], absolute[1, 24:48])
    torch.testing.assert_close(actual[1, 24:48], absolute[1, :24])
    torch.testing.assert_close(actual[1, 48:56], absolute[1, 56:64])
    torch.testing.assert_close(actual[1, 56:64], absolute[1, 48:56])
    torch.testing.assert_close(actual[1, 64:], absolute[1, [65, 64]])
    actual.sum().backward()
    torch.testing.assert_close(values.grad, torch.ones_like(values))
    meta[1, 18] = 2
    with pytest.raises(ValueError, match='perspective'):
        relative_structural(gathered, meta)
    with pytest.raises(ValueError, match='meta layout'):
        relative_structural(gathered, meta[:, :18])


@pytest.mark.parametrize('paradigm', ['az', 'ppo', 'dmc', 'bc', 'cfr'])
def test_actual_paradigm_mixed_batch_readout(paradigm):
    from types import SimpleNamespace
    from training.core.config.loader import load_cfg
    from training.paradigms import resolve
    from training.tests.smoke_template import make_structural_batch_dict

    shape = dict(n_counter_slots=128, n_hooks=4, max_ops_per_hook=8, max_actions=6, d_model=16, n_cross_layers=1)
    cfg = load_cfg(
        f'configs/{paradigm}/smoke.toml',
        overrides=[f'paradigm.{paradigm}.agent.{key}={value}' for key, value in shape.items()],
    )
    network = resolve(paradigm).make_network(cfg).eval()
    batch = make_structural_batch_dict(SimpleNamespace(**shape, fields_per_op=5), batch_size=2)
    batch['counter_values'][:] = np.arange(128)
    batch['meta'][:] = 0
    batch['meta'][1, 18] = 1
    received = []
    handles = []
    for name, module in network.named_modules():
        if name.endswith('readout') or name.endswith('struct_head'):
            handles.append(module.register_forward_pre_hook(lambda m, args: received.append(args[0].detach().clone())))
    try:
        with torch.no_grad():
            if paradigm != 'cfr':
                network.forward_batch(batch)
            else:
                tensors = {k: torch.as_tensor(v) for k, v in batch.items()}
                for model in [network.strategy_net, *network.advantage_nets]:
                    kwargs = {
                        k: tensors[k]
                        for k in [
                            'counter_values',
                            'counter_sids',
                            'active_slot_mask',
                            'hook_mask',
                            'card_buckets',
                            'enemy_sizes',
                            'meta',
                            'action_refs',
                            'action_payments',
                            'char_skill_refs',
                            'definition_links',
                        ]
                    }
                    kwargs['hook_emb_cached'] = model.trunk.hook_encoder(tensors['hook_ir'], tensors['hook_mask'])
                    pos = compute_structural_obspos(tensors['counter_sids'], tensors['active_slot_mask'])
                    kwargs['structural_values'] = compute_structural_values(tensors['counter_values'], pos)
                    model(**kwargs)
    finally:
        for handle in handles:
            handle.remove()
    assert len(received) == (3 if paradigm == 'cfr' else 1)
    for actual in received:
        assert actual[0, 0] == 0 and actual[1, 0] == 24  # own HP
        assert actual[0, 24] == 24 and actual[1, 24] == 0  # enemy HP
        assert actual[0, 48] == 48 and actual[1, 48] == 56  # own dice
        assert actual[0, 64] == 64 and actual[1, 64] == 65  # own alive count
