"""DMC paradigm adapter — bridges PeriodicEvaluator + DmcAgent + baseline
builder behind the paradigm-agnostic interface in _paradigm.py."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def build_eval_agent(cfg, ckpt_path: Path):
    """Load DmcAgent in eval mode from ckpt blob.

    Ckpt schema 兼容:production async pipeline 保存 `DMCInferenceNet(actor_critic)`
    wrapped state_dict (keys 含 `net.` 前缀, per `paradigms/dmc/paradigm.py:sync_weights`);
    eval 端用 raw ActorCritic, 需 strip 前缀。 旧 ckpt (无前缀, e.g. local smoke) 仍直载。
    W1-T4 后 prefix-strip 由 ``training.core.checkpoint.load_net_state_dict`` 统一处理。
    """
    from training.core.checkpoint import load_net_state_dict
    from training.paradigms.dmc._agent import DmcAgent

    agent = DmcAgent(cfg.agent, device='cpu', lr=cfg.learning_rate, epsilon=0.0)
    state_dict = load_net_state_dict(ckpt_path, map_location='cpu')
    agent.net.load_state_dict(state_dict)
    agent.net.eval()
    return agent


def build_evaluator(cfg):
    from tools.eval._dmc_evaluator import PeriodicEvaluator

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
    from tools.eval._dmc_evaluator import _build_baseline_player

    return _build_baseline_player(name, seed=seed, dmc_cfg=cfg)


def ckpt_frame(ckpt_path: Path) -> Optional[int]:
    """Read TrainState.frames out of ckpt blob (latest.pt / ckpt_<N>.pt)."""
    import torch

    try:
        blob = torch.load(ckpt_path, map_location='cpu', weights_only=False)
    except Exception:
        return None
    return (blob.get('state') or {}).get('frames')
