"""PPO paradigm adapter — implements core.protocols.Paradigm.

Bridges the unified pipeline driver (training.core.pipeline.run_pipeline)
to the PPO loss / rollout / network components. The legacy stack at
``training/paradigms/ppo/legacy/`` was retired in FU-W4-PPO; rollout +
GAE + clip-surrogate behaviour preserved in-place under this package.

Tier: ``frozen`` (per archived ``0008-rl-paradigm-pivot``) — adapter
exists for s021-s054 ablation reproducibility (per D2), NOT for new
PPO production runs."""

from training.paradigms.ppo.paradigm import PPOParadigm

__all__ = ['PPOParadigm']
