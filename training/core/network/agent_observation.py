"""Shared static observation cache and dynamic tensor parsing."""

from __future__ import annotations

import hashlib

import numpy as np
import torch

from training.core.network.obs_layout import validate_static_layout
from training.core.network.static_links import parse_definition_links_np
from training.core.obs_constants import (
    OBS_CHAR_SKILL_REFS_SIZE,
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
    OBS_MAX_CHARS,
    OBS_MAX_SKILLS_PER_CHAR,
    OBS_META_SIZE,
    OBS_MODIFIER_LOG_FIELD_COUNT,
    OBS_MODIFIER_LOG_K_MOD,
    OBS_RECENT_DAMAGE_EVENTS,
    OBS_RECENT_DAMAGE_FIELD_COUNT,
)
from training.core.structural import compute_structural_obspos


class _AgentObservationMixin:
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
            hook_ir,
            char_skill_refs,
            definition_links,
        ) = self.encode_static_tensors_with_tokens(static_obs_np)
        self._hook_emb = hook_emb.unsqueeze(0)
        self._hook_mask = hook_mask.unsqueeze(0)
        self._counter_sids = counter_sids.unsqueeze(0)
        self._active_slot_mask = active_slot_mask.unsqueeze(0)
        self._char_skill_refs = char_skill_refs.unsqueeze(0)
        self._definition_links = definition_links.unsqueeze(0)
        self._structural_obspos = compute_structural_obspos(
            self._counter_sids,
            self._active_slot_mask,
        )
        self._hook_ir_cache = hook_ir

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
        hook_ir, char_skill_refs, definition_links)``."""
        validate_static_layout(static_obs_np, self.cfg)
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

            # IR-4: hook section = (n_hooks, max_ops, fields_per_op=5) int32.
            # Each op is (opcode, dst, op1, op2, op3). Active hook = opcode!=0
            # in any op position (NOP-padded slots are zero).
            ops_per_hook = self.cfg.max_ops_per_hook
            fields_per_op = self.cfg.fields_per_op
            hook_size = self.cfg.n_hooks * ops_per_hook * fields_per_op
            hook_ir_all = (
                static[meta_size + refs_size : meta_size + refs_size + hook_size]
                .reshape(self.cfg.n_hooks, ops_per_hook, fields_per_op)
                .long()
            )
            opcodes_all = hook_ir_all[:, :, 0]
            non_empty = (opcodes_all != 0).any(dim=-1)
            n_active = int(non_empty.sum().item())

            if n_active > 0:
                active_ir = hook_ir_all[non_empty]  # (n_active, max_ops, 5)
                active_mask = torch.ones(1, n_active, dtype=torch.bool, device=self.device)
                hook_emb = self._hook_encoder(active_ir.unsqueeze(0), active_mask).squeeze(0)
                hook_mask = torch.ones(n_active, dtype=torch.bool, device=self.device)
            else:
                hook_emb = torch.zeros(1, self.cfg.d_model, device=self.device)
                hook_mask = torch.zeros(1, dtype=torch.bool, device=self.device)
                active_ir = torch.zeros(
                    1,
                    ops_per_hook,
                    fields_per_op,
                    dtype=torch.long,
                    device=self.device,
                )

            definition_links = torch.as_tensor(
                parse_definition_links_np(
                    static_obs_np,
                    n_counter_slots=self.cfg.n_counter_slots,
                    n_hooks=self.cfg.n_hooks,
                    max_ops_per_hook=self.cfg.max_ops_per_hook,
                    fields_per_op=self.cfg.fields_per_op,
                ),
                dtype=torch.long,
                device=self.device,
            )

        return (
            hook_emb,
            hook_mask,
            counter_sids,
            active_slot_mask,
            active_ir,
            char_skill_refs,
            definition_links,
        )

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

    def _parse_buff_single(self, dyn_obs_np):
        from training.core.step_encoding import parse_buffs_np

        return torch.as_tensor(parse_buffs_np(dyn_obs_np, self.cfg.n_counter_slots), device=self.device).unsqueeze(0)

    def game_start(self, static_obs_np: np.ndarray) -> dict:
        """Evaluator protocol: encode + cache static, return per-game dict for replay buffer."""
        self.encode_static(static_obs_np)
        return {
            'hook_ir': self._hook_ir_cache.detach().cpu().numpy().astype(np.int64),
            'hook_mask': self._hook_mask.squeeze(0).detach().cpu().numpy().astype(bool),
            'counter_sids': self._counter_sids.squeeze(0).detach().cpu().numpy().astype(np.int64),
            'active_slot_mask': self._active_slot_mask.squeeze(0).detach().cpu().numpy().astype(bool),
            'char_skill_refs': self._char_skill_refs.squeeze(0).detach().cpu().numpy().astype(np.int64),
            'definition_links': self._definition_links.squeeze(0).detach().cpu().numpy().astype(np.int64),
        }

    def game_end(self) -> None:
        """Evaluator protocol: no-op (cache overwritten on next game_start)."""
        pass
