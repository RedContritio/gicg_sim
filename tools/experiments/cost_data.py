"""Fresh engine-labelled examples; split by game seed and whole card combination."""

import hashlib
from pathlib import Path

import numpy as np
import torch

from gicg_env import GicgEnv
from gicg_env._constants import OBS_CHAR_ELEMENT_SLOTS, OBS_CHAR_SKILL_REFS_SIZE, OBS_COUNTER_SLOTS
from training.core.artifact_io import save_dataset
from training.core.step_encoding import pad_buffs_np, parse_buffs_np


def collect(cards, seeds, path):
    examples = []
    env = GicgEnv(
        ['赤蝶', '墨客'],
        ['墨客', '赤蝶'],
        card_pool=cards,
        pool=['v_legacy', 'test_basic'],
        data_dir='data',
        max_rounds=6,
        fix_dice=[0, 0, 0, 0, 0, 0, 0, 12],
    )
    try:
        for seed in seeds:
            rng = np.random.default_rng(seed)
            env.reset(seed=seed)
            static = env._static_obs
            start = OBS_COUNTER_SLOTS * 3 + OBS_CHAR_SKILL_REFS_SIZE
            ir = static[start:-OBS_CHAR_ELEMENT_SLOTS].reshape(-1, 128, 5)
            ir = ir[(ir[:, :, 0] != 0).any(-1)]
            for step in range(256):
                if env.done:
                    break
                refs = np.asarray(env.get_action_refs())
                # Sample action kinds uniformly to avoid tuning variants dominating.
                kind = rng.choice(np.unique(refs[:, 0]))
                index = int(rng.choice(np.flatnonzero(refs[:, 0] == kind)))
                if not env._engine.has_pending:
                    buffs = parse_buffs_np(env._get_obs(), OBS_COUNTER_SLOTS)
                    payments = np.asarray(env.get_legal_action_payments())
                    for selected in rng.choice(len(refs), size=min(3, len(refs)), replace=False):
                        examples.append((buffs.copy(), refs[selected].copy(), float(payments[selected].sum()), seed))
                env.step(index)
        if not examples:
            raise ValueError('empty collection')
        data = {
            'hook_ir': ir,
            'buffs': pad_buffs_np([x[0] for x in examples]),
            'action_refs': np.stack([x[1] for x in examples]),
            'costs': np.array([x[2] for x in examples], dtype=np.float32),
            'game_seed': np.array([x[3] for x in examples]),
            'group': hashlib.sha256('|'.join(sorted(cards)).encode()).hexdigest(),
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        save_dataset(path, **data)
        return data
    finally:
        env.close()


def tensors(data):
    return {
        k: torch.as_tensor(v, dtype=torch.float32 if k in ('buffs', 'costs') else torch.long)
        for k, v in data.items()
        if k in ('hook_ir', 'buffs', 'costs', 'action_refs')
    }


def predict(probe, data, indices):
    # Encode one shared rule program per batch; gradients still reach the encoder.
    ir = data['hook_ir'].unsqueeze(0)
    mask = torch.ones(ir.shape[:2], dtype=torch.bool)
    hooks = probe.hook_encoder(ir, mask).expand(len(indices), -1, -1)
    refs = data['action_refs'][indices]
    valid = refs[:, 1] >= 0
    action = hooks[torch.arange(len(indices)), refs[:, 1].clamp_min(0)] * valid.unsqueeze(-1)
    action = action + probe.query(refs[:, [0, 2]].float())
    buff = probe.buff_encoder(data['buffs'][indices], hooks)
    return probe.head(torch.cat((action, buff), dim=-1)).squeeze(-1)
