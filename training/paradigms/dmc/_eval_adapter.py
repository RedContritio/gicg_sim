"""DMC paradigm adapter — bridges PeriodicEvaluator + DmcAgent + baseline
builder behind the paradigm-agnostic interface in _paradigm.py."""

from __future__ import annotations

from training.core.artifact_io import load_checkpoint

from pathlib import Path
from typing import Optional


def _infer_agent_cfg(cfg, state_dict: dict):
    """Return AgentConfig with d_model/n_cross_layers inferred from state_dict.

    CheckpointManager ckpts don't embed AgentConfig, so we read it from the
    weight shapes directly.  ``end_turn_emb`` is always ``[d_model]``;
    ``cross_layers`` count is the max ``cross_layers.<N>.`` index + 1.
    Falls back to ``cfg.agent`` if inference fails.
    """
    import copy
    import re

    try:
        d_model = state_dict['end_turn_emb'].shape[0]
        cross_ids = {int(m.group(1)) for k in state_dict if (m := re.match(r'cross_layers\.(\d+)\.', k))}
        n_cross = max(cross_ids) + 1 if cross_ids else cfg.agent.n_cross_layers
        agent_cfg = copy.copy(cfg.agent)
        agent_cfg.d_model = d_model
        agent_cfg.n_cross_layers = n_cross
        return agent_cfg
    except (KeyError, AttributeError):
        return cfg.agent


def build_eval_agent(cfg, ckpt_path: Path):
    """Load DmcAgent in eval mode from ckpt blob.

    Ckpt schema 兼容:production async pipeline 保存 `DMCInferenceNet(actor_critic)`
    wrapped state_dict (keys 含 `net.` 前缀, per `paradigms/dmc/paradigm.py:sync_weights`);
    eval 端用 raw ActorCritic, 需 strip 前缀。 旧 ckpt (无前缀, e.g. local smoke) 仍直载。
    W1-T4 後 prefix-strip 由 ``training.core.checkpoint.load_net_state_dict`` 统一处理。

    d_model + n_cross_layers 从 state_dict 权重形状推断,不依赖 eval cfg
    声明的 agent 字段(避免 d_model 不匹配 load_state_dict size mismatch)。
    """
    from training.core.checkpoint import load_net_state_dict
    from training.paradigms.dmc._agent import DmcAgent

    state_dict = load_net_state_dict(ckpt_path, map_location='cpu')
    agent_cfg = _infer_agent_cfg(cfg, state_dict)
    agent = DmcAgent(agent_cfg, device='cpu', lr=cfg.learning_rate, epsilon=0.0)
    agent.net.load_state_dict(state_dict)
    agent.net.eval()
    return agent


def build_evaluator(cfg):
    from training.paradigms.dmc._eval_periodic import PeriodicEvaluator

    return PeriodicEvaluator(cfg)


def build_random_agent(cfg):
    """Uniform-random baseline agent (no ckpt load, ε=1.0)。 诊断用:与 trained ckpt
    并列跑 gauntlet 看 policy collapse — trained < random 即 collapse 信号。

    2026-05-28 ship 根因:Stage 3 pilot ckpt @ iter 2500 全输 vs F1-D2 (0/256),
    random uniform 拿 22% (7/32) — confirm 模型 collapse 到 degenerate policy。
    """
    from training.paradigms.dmc._agent import DmcAgent

    agent = DmcAgent(cfg.agent, device='cpu', lr=cfg.learning_rate, epsilon=1.0)
    agent.net.eval()
    return agent


def build_baseline(name: str, *, seed: int, cfg):
    from training.paradigms.dmc._eval_periodic import _build_baseline_player

    return _build_baseline_player(name, seed=seed, dmc_cfg=cfg)


def ckpt_frame(ckpt_path: Path) -> Optional[int]:
    """Read TrainState.frames out of ckpt blob (latest.pt / ckpt_<N>.pt)."""
    import torch

    try:
        blob = load_checkpoint(ckpt_path, map_location='cpu', weights_only=False)
    except Exception:
        return None
    return (blob.get('state') or {}).get('frames')
