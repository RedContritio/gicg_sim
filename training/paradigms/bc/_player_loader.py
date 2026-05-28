"""BC player loader — registers ``'bc'`` factory with
``training.core.matchup.loaders`` registry。 B4 close audit
finding `core/eval/baselines.py:103-105` "extend LOADERS to add
support" 流毒。

BC paradigm 暂不支持 gauntlet player:BCNetwork 直接包 ActorCritic
(无 `BCAgent` 类),没有 `select_action(env)` / `eval_state(...)`
API。 production BC eval 走 dataset 监督 loss(`BCLoss`),不走
adversarial gauntlet。 真要 BC ckpt 当 opponent,应该:
- 提建 `BCAgent` 类(包 ActorCritic + select_action(env) 实现 = argmax
  over policy head),
- 或写一个 ckpt 加载 + 调 forward_batch 单步 env 的 thin player wrapper
  (~30 LOC)。

留 NotImplementedError 在 loader 里,signal 给 caller "BC 没就绪",
比 silent KeyError(LOADERS miss)清楚。
"""

from __future__ import annotations

from training.core.matchup.loaders import PlayerBuilder, register_loader


def _loader_bc(spec: dict) -> PlayerBuilder:
    raise NotImplementedError(
        "BC player loader is not implemented — BCNetwork wraps ActorCritic directly with "
        "no `select_action(env)` API。 Implement a BCAgent class (or a thin BCArgmaxPlayer "
        'wrapper that loads ckpt + calls forward_batch single-step) to support gauntlet '
        'evaluation of BC checkpoints。'
    )


register_loader('bc', _loader_bc)
