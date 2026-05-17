"""DMC paradigm adapter — bridges PeriodicEvaluator + DmcAgent + baseline
builder behind the paradigm-agnostic interface in _paradigm.py."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def build_eval_agent(cfg, ckpt_path: Path):
    """Load DmcAgent in eval mode from ckpt blob."""
    import torch
    from training.paradigms.dmc._agent import DmcAgent

    agent = DmcAgent(cfg.agent, device='cpu', lr=cfg.learning_rate, epsilon=0.0)
    blob = torch.load(ckpt_path, map_location='cpu', weights_only=False)
    agent.net.load_state_dict(blob['net'])
    agent.net.eval()
    return agent


def build_evaluator(cfg):
    from tools.eval._dmc_evaluator import PeriodicEvaluator

    return PeriodicEvaluator(cfg)


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
