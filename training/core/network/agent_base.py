"""Shared per-game observation cache and agent lifecycle scaffolding.

Subclasses bind their own ``self.net`` (e.g. ActorCritic / CFRStrategyNet)
and override ``forward_batch`` / ``eval_state`` per algorithm. AgentBase
provides:

- Static obs encoding + cache (per-game once via ``encode_static``)
- Dynamic obs parsing into 7 typed tensors (per-step)
- Evaluator protocol (``game_start`` / ``game_end``)
- Default save/load

The hook encoder is injected at construction. A subclass typically passes
``self.net.hook_encoder`` after constructing its own network.

Current contract: ``openspec/specs/training-architecture/network-sharing.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import torch
import torch.nn as nn

from training.core.artifact_io import load_checkpoint, save_checkpoint
from training.core.network.agent_observation import _AgentObservationMixin


@dataclass
class AgentConfig:
    """Shape parameters needed to instantiate per-algorithm network.

    Its eight fields mirror ``training.core.cfg.ObsShape``. Use
    ``AgentConfig.from_obs_shape(obs_shape)`` at paradigm boundaries. The
    two dataclasses remain distinct because ``ObsShape`` is frozen while
    this compatibility wire type is mutable.
    """

    n_counter_slots: int
    n_hooks: int
    max_ops_per_hook: int
    max_actions: int
    # IR-4: per-op field count in obs (opcode, dst, op1, op2, op3 = 5).
    fields_per_op: int = 5
    d_model: int = 64
    dropout: float = 0.0
    n_cross_layers: int = 2

    @classmethod
    def from_obs_shape(cls, obs_shape: Any) -> 'AgentConfig':
        """Construct from an object exposing the eight shape fields."""
        return cls(
            n_counter_slots=obs_shape.n_counter_slots,
            n_hooks=obs_shape.n_hooks,
            max_ops_per_hook=obs_shape.max_ops_per_hook,
            max_actions=obs_shape.max_actions,
            fields_per_op=obs_shape.fields_per_op,
            d_model=obs_shape.d_model,
            dropout=obs_shape.dropout,
            n_cross_layers=obs_shape.n_cross_layers,
        )


class AgentBase(_AgentObservationMixin):
    """Per-game static caching + dynamic-obs parse scaffolding.

    Subclasses build their own ``self.net`` in ``__init__`` and pass the
    hook_encoder (typically ``self.net.hook_encoder``) via super().__init__.

    Example subclass:

        class MyAgent(AgentBase):
            def __init__(self, cfg, device='cpu'):
                self.net = make_actor_critic(cfg, head_kinds={'policy', 'value'})
                super().__init__(cfg, hook_encoder=self.net.hook_encoder, device=device)
    """

    def __init__(self, cfg, hook_encoder: nn.Module, device: str = 'cpu') -> None:
        self.cfg = cfg
        self.device = torch.device(device)
        self._hook_encoder = hook_encoder

        # Static caches — refreshed per game by encode_static().
        self._hook_emb: Optional[torch.Tensor] = None  # (1, n_active, D)
        self._hook_mask: Optional[torch.Tensor] = None  # (1, n_active)
        self._counter_sids: Optional[torch.Tensor] = None  # (1, n_slots)
        self._active_slot_mask: Optional[torch.Tensor] = None  # (1, n_slots) bool
        self._char_skill_refs: Optional[torch.Tensor] = None  # (1, 2, MC, MSPC)
        self._definition_links: Optional[torch.Tensor] = None  # (1, n_links, 2)
        # IR-4: replaced hook_types/hook_values caches with single hook_ir cache.
        self._hook_ir_cache: Optional[torch.Tensor] = None  # (n_active, max_ops, 5) long
        self._structural_obspos: Optional[torch.Tensor] = None
        self._static_hash: Optional[str] = None

    # --- Shape helpers ---------------------------------------------- #

    @property
    def d_model(self) -> int:
        return self.cfg.d_model

    @property
    def max_actions(self) -> int:
        return self.cfg.max_actions

    @property
    def n_counter_slots(self) -> int:
        return self.cfg.n_counter_slots

    # --- Static obs caching ----------------------------------------- #

    # --- Dynamic obs parse ------------------------------------------ #

    # --- Protocol-compatible lifecycle helpers ---------------------- #

    # --- Persistence ------------------------------------------------ #

    CKPT_SCHEMA_VERSION = 3  # v3 adds canonical definition-relation parameters

    def _resolve_paradigm_name(self) -> str:
        """Derive paradigm id from class module path. AZ Agent → 'az', etc.
        Subclass can override if heuristic doesn't fit."""
        mod = self.__class__.__module__
        # Module path conventionally training.paradigms.<paradigm>.network etc
        parts = mod.split('.')
        for i, p in enumerate(parts):
            if p == 'paradigms' and i + 1 < len(parts):
                return parts[i + 1]
        return 'unknown'

    @staticmethod
    def _resolve_git_commit() -> str:
        """Best-effort git HEAD hash; fallback 'unknown' on any error
        (e.g. running outside repo, no git installed)."""
        import subprocess

        try:
            out = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'],
                stderr=subprocess.DEVNULL,
                timeout=5.0,
            )
            return out.decode('ascii').strip()
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return 'unknown'

    def save(self, path: str) -> None:
        """Save self-describing ckpt with metadata.

        Schema (CKPT_SCHEMA_VERSION = 3):
            {
                'schema_version': int,            # for forward-compat detection
                'paradigm': str,                  # 'az' | 'bc' | 'cfr' | 'dmc' | 'ppo'
                'cfg_version': str,               # paradigm cfg schema version, '1.0.0' default
                'cfg': dict,                      # vars(cfg) — complete reconstructable
                'net_kind': str,                  # net.__class__.__name__
                'net_state_dict': OrderedDict,    # nn.Module.state_dict()
                'git_commit': str,                # subprocess git rev-parse HEAD, 'unknown' on failure
                'created_at': str,                # iso8601 UTC
            }

        Checkpoints without ``schema_version`` are rejected by ``load``.
        """
        from datetime import datetime, timezone

        if not hasattr(self, 'net'):
            raise RuntimeError(f'{self.__class__.__name__}.save: subclass must set self.net (nn.Module) before saving')
        cfg_version = getattr(self.cfg, 'version', '1.0.0')
        blob = {
            'schema_version': self.CKPT_SCHEMA_VERSION,
            'paradigm': self._resolve_paradigm_name(),
            'cfg_version': cfg_version,
            'cfg': vars(self.cfg) if hasattr(self.cfg, '__dict__') else dict(self.cfg.__dict__),
            'net_kind': self.net.__class__.__name__,
            'net_state_dict': self.net.state_dict(),
            'git_commit': self._resolve_git_commit(),
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        save_checkpoint(blob, path)

    def load_for_adaptation(self, path: str) -> list[str]:
        """Warm-start old weights/new primitive rows; start a fresh optimizer."""
        from training.core.network.adaptation import load_for_adaptation

        blob = load_checkpoint(path, weights_only=True, map_location=self.device)
        changed = load_for_adaptation(self.net, blob['net_state_dict'])
        self._static_hash = None
        return changed

    def load(self, path: str) -> None:
        """Load a checkpoint whose schema version is at least the current one."""
        if not hasattr(self, 'net'):
            raise RuntimeError(f'{self.__class__.__name__}.load: subclass must set self.net (nn.Module) before loading')
        blob = load_checkpoint(path, weights_only=True, map_location=self.device)
        if not isinstance(blob, dict) or 'schema_version' not in blob:
            raise CkptSchemaError(
                f'{self.__class__.__name__}.load: {path} has no schema_version; '
                f'retrain or convert the checkpoint before loading it.'
            )
        if blob['schema_version'] < self.CKPT_SCHEMA_VERSION:
            raise CkptSchemaError(
                f'{self.__class__.__name__}.load: ckpt schema_version={blob["schema_version"]} '
                f'< current {self.CKPT_SCHEMA_VERSION}; migration not supported'
            )
        # Optional sanity: paradigm match (don't enforce — allow cross-paradigm warm-start)
        my_paradigm = self._resolve_paradigm_name()
        ckpt_paradigm = blob.get('paradigm', 'unknown')
        if ckpt_paradigm != my_paradigm and ckpt_paradigm != 'unknown':
            import warnings

            warnings.warn(
                f'{self.__class__.__name__}.load: ckpt paradigm={ckpt_paradigm} != current {my_paradigm} '
                f'(may indicate cross-paradigm warm-start, intentional or accidental — verify caller intent)',
                stacklevel=2,
            )
        self.net.load_state_dict(blob['net_state_dict'])


class CkptSchemaError(RuntimeError):
    """Raised when checkpoint schema metadata is missing or too old."""

    pass
