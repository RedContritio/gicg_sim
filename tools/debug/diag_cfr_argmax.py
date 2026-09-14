"""诊断 CFR argmax 为什么 0/10 vs random。

加载一个 CFR ckpt,和 random 对打 1 局(固定 CFR 为 player 0),每步记:
  - 当前玩家 / n_legal / 选的动作 index
  - top-3 action 的 (label, prior 概率)
  - env.get_action_labels() 中选到的那个动作的人类可读名字

用法:
    .venv/bin/python -m tools.debug.diag_cfr_argmax <ckpt_path> [seed]
"""

from __future__ import annotations

from training.core.artifact_io import load_checkpoint

import random
import sys
from pathlib import Path

import numpy as np
import torch

from gicg_env import GicgEnv
from training.paradigms.cfr.agent import CFRAgent
from training.paradigms.cfr.strategy_net import CFRNetConfig


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: python -m tools.debug.diag_cfr_argmax <ckpt_path> [seed]')
        return 2
    ckpt_path = Path(sys.argv[1])
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    blob = load_checkpoint(ckpt_path, weights_only=True, map_location='cpu')
    cfg = CFRNetConfig(**blob['cfg'])
    agent = CFRAgent(cfg)
    agent.net.load_state_dict(blob['net'])
    agent.net.eval()

    env = GicgEnv(['赤蝶', '墨客'], ['猫咪', '刻师傅'], data_dir='data')
    env.reset(seed=seed)
    agent.encode_static(env.static_obs)
    rng = random.Random(seed)

    step = 0
    print(f'ckpt={ckpt_path.name} seed={seed}')
    print(f'teams: {env.team_0} vs {env.team_1}')
    print()

    while not env.done and step < 300:
        acting = env.acting_player
        kinds, _ = env.get_legal_actions()
        n_legal = len(kinds)
        if n_legal == 0:
            print(f'step {step:3d}: n_legal=0, breaking')
            break
        labels = env.get_action_labels()
        if acting == 0:
            refs = env.get_action_refs()
            payments = env.get_legal_action_payments()
            dyn_obs = env._get_obs()
            prior, value = agent.eval_state(dyn_obs, refs, payments)
            idx = int(np.argmax(prior))
            top3 = np.argsort(-prior)[:3]
            top3_str = ', '.join(
                f'{labels[i][0]}:{labels[i][1]}[i={i} p={prior[i]:.3f}]' for i in top3 if i < len(labels)
            )
            chosen_label = labels[idx] if idx < len(labels) else ('?', '?', -1)
            print(
                f'step {step:3d} [CFR p0 n_legal={n_legal:3d} v={value:+.3f}] → idx={idx} '
                f'{chosen_label[0]}:{chosen_label[1]}  top3=[{top3_str}]'
            )
        else:
            idx = rng.randrange(n_legal)
            chosen_label = labels[idx] if idx < len(labels) else ('?', '?', -1)
            print(f'step {step:3d} [RND p1 n_legal={n_legal:3d}] → idx={idx} {chosen_label[0]}:{chosen_label[1]}')

        env.step(idx)
        step += 1

    print()
    print(f'DONE: steps={step} done={env.done} winner={getattr(env, "winner", "?")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
