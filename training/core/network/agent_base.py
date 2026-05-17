"""AgentBase — shared per-game cache + obs parse scaffolding (DI redesign).

Subclasses bind their own ``self.net`` (e.g. ActorCritic / CFRStrategyNet)
and override ``forward_batch`` / ``eval_state`` per algorithm. AgentBase
provides:

- Static obs encoding + cache (per-game once via ``encode_static``)
- Dynamic obs parsing into 7 typed tensors (per-step)
- Evaluator protocol (``game_start`` / ``game_end``)
- Default save/load

**DI redesign (per core-network-generic-promotion)**: hook_encoder is
injected at construction (``__init__(cfg, hook_encoder, device)``) instead
of being looked up via ``self.net.hook_encoder`` attribute (the legacy
hard contract).  Subclass typically passes ``self.net.hook_encoder``
after constructing its own net.

Spec: ``openspec/changes/core-network-generic-promotion/specs/network-architecture/spec.md``
invariant A2.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

import numpy as np
import torch
import torch.nn as nn

from training.core.obs_constants import (
    OBS_CHAR_SKILL_REFS_SIZE,
    OBS_ENEMY_SIZES,
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
    OBS_MAX_CHARS,
    OBS_MAX_SKILLS_PER_CHAR,
    OBS_META_SIZE,
    OBS_MODIFIER_LOG_FIELD_COUNT,
    OBS_MODIFIER_LOG_K_MOD,
    OBS_MODIFIER_LOG_SLOTS,
    OBS_PREPARE_SKILL_SLOTS,
    OBS_RECENT_DAMAGE_EVENTS,
    OBS_RECENT_DAMAGE_FIELD_COUNT,
    OBS_RECENT_DAMAGE_SLOTS,
)
from training.core.structural import compute_structural_obspos


@dataclass
class AgentConfig:
    """Shape parameters needed to instantiate per-algorithm network.

    Note: future config-schema cleanup may unify this with
    ``training.core.cfg.ObsShape`` (per config-schema spec); for now both
    coexist — paradigms in transition use whichever they already wire to.
    """

    n_counter_slots: int
    n_hooks: int
    max_tokens_per_hook: int
    max_actions: int
    d_model: int = 64
    dropout: float = 0.0
    n_cross_layers: int = 2


class AgentBase:
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
        self._hook_types_cache: Optional[torch.Tensor] = None
        self._hook_values_cache: Optional[torch.Tensor] = None
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

    @staticmethod
    def _hash_static(static_obs_np: np.ndarray) -> str:
        """md5 of static obs bytes for stale-cache detection."""
        arr = np.ascontiguousarray(static_obs_np, dtype=np.float32)
        return hashlib.md5(arr.tobytes()).hexdigest()

    def encode_static(self, static_obs_np: np.ndarray) -> None:
        """Encode env.static_obs once per game; cached for subsequent eval_state."""
        self._static_hash = self._hash_static(static_obs_np)
        (
            hook_emb,
            hook_mask,
            counter_sids,
            active_slot_mask,
            hook_types,
            hook_values,
            char_skill_refs,
        ) = self.encode_static_tensors_with_tokens(static_obs_np)
        self._hook_emb = hook_emb.unsqueeze(0)
        self._hook_mask = hook_mask.unsqueeze(0)
        self._counter_sids = counter_sids.unsqueeze(0)
        self._active_slot_mask = active_slot_mask.unsqueeze(0)
        self._char_skill_refs = char_skill_refs.unsqueeze(0)
        self._structural_obspos = compute_structural_obspos(
            self._counter_sids,
            self._active_slot_mask,
        )
        self._hook_types_cache = hook_types
        self._hook_values_cache = hook_values

    def encode_static_tensors(
        self,
        static_obs_np: np.ndarray,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Stateless 3-tuple variant — for the inference server's per-game cache."""
        hook_emb, hook_mask, counter_sids, _, _, _, _ = self.encode_static_tensors_with_tokens(static_obs_np)
        return hook_emb, hook_mask, counter_sids

    def encode_static_tensors_with_tokens(
        self,
        static_obs_np: np.ndarray,
    ) -> tuple[
        torch.Tensor,
        torch.Tensor,
        torch.Tensor,
        torch.Tensor,
        torch.Tensor,
        torch.Tensor,
        torch.Tensor,
    ]:
        """Returns ``(hook_emb, hook_mask, counter_sids, active_slot_mask,
        hook_types, hook_values, char_skill_refs)``."""
        with torch.no_grad():
            static = torch.tensor(static_obs_np, dtype=torch.float32, device=self.device)

            meta_size = self.cfg.n_counter_slots * 3
            counter_meta = static[:meta_size].reshape(self.cfg.n_counter_slots, 3)
            active_slot_mask = (counter_meta[:, 0] != 0) | (counter_meta[:, 1] != 0)
            counter_sids = counter_meta[:, 2].long()

            refs_size = OBS_CHAR_SKILL_REFS_SIZE
            char_skill_refs = (
                static[meta_size : meta_size + refs_size]
                .reshape(
                    2,
                    OBS_MAX_CHARS,
                    OBS_MAX_SKILLS_PER_CHAR,
                )
                .long()
            )

            hook_size = self.cfg.n_hooks * self.cfg.max_tokens_per_hook * 2
            hook_data = static[meta_size + refs_size : meta_size + refs_size + hook_size].reshape(
                self.cfg.n_hooks,
                self.cfg.max_tokens_per_hook,
                2,
            )
            hook_types_all = hook_data[:, :, 0].long()
            hook_values_all = hook_data[:, :, 1].float()
            non_empty = hook_types_all.sum(dim=-1) != 0
            n_active = int(non_empty.sum().item())

            if n_active > 0:
                active_types = hook_types_all[non_empty]
                active_values = hook_values_all[non_empty]
                active_mask = torch.ones(1, n_active, dtype=torch.bool, device=self.device)
                # DI: call injected hook_encoder (was self.net.hook_encoder in legacy)
                hook_emb = self._hook_encoder(
                    active_types.unsqueeze(0),
                    active_values.unsqueeze(0),
                    active_mask,
                ).squeeze(0)
                hook_mask = torch.ones(n_active, dtype=torch.bool, device=self.device)
            else:
                hook_emb = torch.zeros(1, self.cfg.d_model, device=self.device)
                hook_mask = torch.zeros(1, dtype=torch.bool, device=self.device)
                active_types = torch.zeros(
                    1,
                    self.cfg.max_tokens_per_hook,
                    dtype=torch.long,
                    device=self.device,
                )
                active_values = torch.zeros(
                    1,
                    self.cfg.max_tokens_per_hook,
                    dtype=torch.float32,
                    device=self.device,
                )

        return (
            hook_emb,
            hook_mask,
            counter_sids,
            active_slot_mask,
            active_types,
            active_values,
            char_skill_refs,
        )

    # --- Dynamic obs parse ------------------------------------------ #

    def _parse_dynamic_single(self, dyn_obs_np: np.ndarray):
        """Parse one dynamic obs vector into 7 tensors with leading batch dim 1.

        Returns:
            (counter_values, meta, card_buckets, enemy_sizes,
             recent_damage, prepare_skill, modifier_log)

        Per ADR-0019 §B.2/§B.3c: typed segments use shared
        ``typed_segment_offsets()`` for slice positions.
        """
        from training.core.step_encoding import typed_segment_offsets

        dyn = torch.tensor(dyn_obs_np, dtype=torch.float32, device=self.device).unsqueeze(0)
        meta = dyn[:, :OBS_META_SIZE]
        c_end = OBS_META_SIZE + self.cfg.n_counter_slots
        counter_values = dyn[:, OBS_META_SIZE:c_end]
        hand_end = c_end + OBS_HAND_BUCKETS * OBS_MAX_CARD_TYPES
        card_buckets = dyn[:, c_end:hand_end].view(1, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES)
        off = typed_segment_offsets(self.cfg.n_counter_slots)
        enemy_sizes = dyn[:, hand_end : off['enemy_end']]
        recent_damage = dyn[:, off['enemy_end'] : off['rd_end']].view(
            1, OBS_RECENT_DAMAGE_EVENTS, OBS_RECENT_DAMAGE_FIELD_COUNT
        )
        prepare_skill = dyn[:, off['rd_end'] : off['ps_end']].view(1, 2, 2)
        modifier_log = dyn[:, off['ps_end'] : off['ml_end']].view(
            1, OBS_RECENT_DAMAGE_EVENTS, OBS_MODIFIER_LOG_K_MOD, OBS_MODIFIER_LOG_FIELD_COUNT
        )
        return counter_values, meta, card_buckets, enemy_sizes, recent_damage, prepare_skill, modifier_log

    # --- Protocol-compatible lifecycle helpers ---------------------- #

    def game_start(self, static_obs_np: np.ndarray) -> dict:
        """Evaluator protocol: encode + cache static, return per-game dict for replay buffer."""
        self.encode_static(static_obs_np)
        return {
            'hook_types': self._hook_types_cache.detach().cpu().numpy().astype(np.int64),
            'hook_values': self._hook_values_cache.detach().cpu().numpy().astype(np.float32),
            'hook_mask': self._hook_mask.squeeze(0).detach().cpu().numpy().astype(bool),
            'counter_sids': self._counter_sids.squeeze(0).detach().cpu().numpy().astype(np.int64),
            'active_slot_mask': self._active_slot_mask.squeeze(0).detach().cpu().numpy().astype(bool),
            'char_skill_refs': self._char_skill_refs.squeeze(0).detach().cpu().numpy().astype(np.int64),
        }

    def game_end(self) -> None:
        """Evaluator protocol: no-op (cache overwritten on next game_start)."""
        pass

    # --- Persistence (self-describing schema per core-network-generic-promotion) ----- #

    CKPT_SCHEMA_VERSION = 2  # bump on schema change (was 1 with {'net', 'cfg'} 2-key)

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

        Schema (CKPT_SCHEMA_VERSION = 2):
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

        Per core-network-generic-promotion spec config-schema/spec.md invariant N4.
        Old schema ({'net', 'cfg'} 2-key, no paradigm/git_commit/etc) is REJECTED
        on load (CkptSchemaError) — user accepted ckpt 全删 (Phase 0), no
        backward-compat needed.
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
        torch.save(blob, path)

    def load(self, path: str) -> None:
        """Load ckpt — requires self-describing schema (CKPT_SCHEMA_VERSION ≥ 2)."""
        if not hasattr(self, 'net'):
            raise RuntimeError(f'{self.__class__.__name__}.load: subclass must set self.net (nn.Module) before loading')
        blob = torch.load(path, weights_only=True, map_location=self.device)
        if not isinstance(blob, dict) or 'schema_version' not in blob:
            raise CkptSchemaError(
                f'{self.__class__.__name__}.load: {path} uses pre-redesign ckpt schema (no schema_version key); '
                f'core-network-generic-promotion Phase 0 removed all pre-redesign ckpts. '
                f'Retrain on new schema or load via git checkout pre-core-network-redesign-2026-05-17 + old code.'
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
    """Raised on ckpt schema mismatch (pre-redesign 2-key or future version too new)."""

    pass
