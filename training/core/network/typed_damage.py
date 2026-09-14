"""TypedDamageEncoder — ADR-0019 §B.2/§B.3c typed obs segments → d_model.

Consumes the three typed segments appended to dynamic obs:
  * recent_damage : (B, K=8, 11)            — per-event typed snapshot
  * prepare_skill : (B, 2, 2)               — (char_idx, skill_slot) per player
  * modifier_log  : (B, K=8, K_mod=4, 5)    — per-stage Modifier list

Produces a single (B, d_model) pooled vector that's concatenated into
the policy/value combined feature alongside counter/hook/card/meta/struct.

Design constraints:
  * **Separate player and char embeddings** — player_idx ∈ {-1, 0, 1}
    and char_idx ∈ {-1, 0..5} use separate embedding tables.
  * **prepare_skill concat over players, not mean** — mean would erase
    "P0 prepares X / P1 prepares Y" vs the swap, breaking under mirror
    match. The encoder concatenates both players' (char + slot) embeddings into
    (B, 2*d_model) → Linear → d_model. Player order is fixed by obs
    perspective (P0 = canonical-acting), so positional concat is safe.
  * **modifier_log fused per-event before pooling** — stage-pool first
    produces (B, K, d_model), which is fused with the matching event,
    pool over events → (B, d_model). Per-event modifier sequence stays
    attached to its event.
  * **Explicit shape errors** — invalid shapes raise ``ValueError`` even
    when Python runs with optimization enabled.

Padding uses ``-2`` for categorical fields and zero for scalars. These
rows use dedicated learned categorical embeddings and remain in the mean
pool; there is no separate validity mask.

# TODO(future ablation): if RL training shows typed_pool fails to
# disentangle player vs char (e.g. attention probe shows uniform
# attention over symmetrical mirror states), revisit by:
#   - adding a position-aware fusion before mean pool, or
#   - replacing mean with attention pool.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from training.core.obs_constants import (
    OBS_MAX_CHARS,
    OBS_MAX_SKILLS_PER_CHAR,
    OBS_MODIFIER_LOG_FIELD_COUNT,
    OBS_MODIFIER_LOG_K_MOD,
    OBS_RECENT_DAMAGE_EVENTS,
    OBS_RECENT_DAMAGE_FIELD_COUNT,
)


# Embedding vocab sizes use a uniform +2 offset for
# every categorical field, allowing both "padding sentinel" (-2 from
# engine) and "real -1" (no-actor / no-prepare / sentinel reserved by
# DSL) as distinct vocab slots:
#   vocab idx 0  ← engine padding (-2)
#   vocab idx 1  ← real "-1" (no-actor / no-char / no-prepare)
#   vocab idx 2+ ← real values 0..N
#
# Sizes: real_max + 3 (2 sentinel slots + 1 spare).
#   element: ElemNone..ElemPiercing (0..9) → 13 (1 spare)
#   reaction_kind: 0 (none) + ~8 declared → 16 (4 spare)
#   modifier_kind: ModBoost..ModAfterDamage (0..3) → 8 (3 spare)
#   player: 0/1 → 5 (-2/-1/0/1 + 1 spare)
#   char: 0..MAX_CHARS-1 → MC + 3 (-2/-1/MC + 1 spare)
#   skill_slot: 0..MSPC-1 → MSPC + 3 (-2/-1/MSPC + 1 spare; engine
#     emits -1 for "no prepare" via encodePrepareSkill, never -2)
ELEMENT_VOCAB = 13
REACTION_VOCAB = 16
MODIFIER_KIND_VOCAB = 8
PLAYER_VOCAB = 5  # {-2 padding, -1 no-actor real, 0, 1, spare}
CHAR_VOCAB = OBS_MAX_CHARS + 3  # 9 (handles -2/-1/0..MC-1/spare)
SKILL_SLOT_VOCAB = OBS_MAX_SKILLS_PER_CHAR + 3  # 13 (-2/-1/0..MSPC-1/spare)


class TypedDamageEncoder(nn.Module):
    """Encode (recent_damage, prepare_skill, modifier_log) → (B, d_model)."""

    def __init__(self, d_model: int, dropout: float = 0.1):
        super().__init__()
        self.d_model = d_model

        # Player and character identifiers have distinct semantics and
        # therefore use distinct tables.
        self.element_emb = nn.Embedding(ELEMENT_VOCAB, d_model)
        self.reaction_emb = nn.Embedding(REACTION_VOCAB, d_model)
        self.modifier_kind_emb = nn.Embedding(MODIFIER_KIND_VOCAB, d_model)
        self.player_emb = nn.Embedding(PLAYER_VOCAB, d_model)
        self.char_emb = nn.Embedding(CHAR_VOCAB, d_model)
        self.skill_slot_emb = nn.Embedding(SKILL_SLOT_VOCAB, d_model)
        # Apply dropout after sparse categorical lookups.
        self.embed_dropout = nn.Dropout(dropout)

        # Per-event projection: actor_player + actor_char + target_player
        # + target_char + element + reaction (6 categorical) + 5 scalars
        # (raw_value/final_value/absorbed/is_piercing/is_hit). Dropout
        # after ReLU follows the dropout pattern used by ActorCritic's
        # state_proj/value_head/delta_head — typed signal is sparse so
        # the encoder is dropout-prone.
        self.event_proj = nn.Sequential(
            nn.Linear(6 * d_model + 5, d_model),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, d_model),
        )

        # Per-modifier projection: kind + element_before + element_after
        # (3 categorical) + value_before/value_after (2 scalar)
        self.modifier_proj = nn.Sequential(
            nn.Linear(3 * d_model + 2, d_model),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, d_model),
        )

        # Concatenation lets the projection learn the relative weight of
        # event and modifier features.
        self.event_mod_fuse = nn.Sequential(
            nn.Linear(2 * d_model, d_model),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, d_model),
        )

        # Keep both players' (char + slot) embeddings positional rather than
        # mean-pooling them — mirror match would otherwise erase
        # "who's preparing what".
        self.prepare_proj = nn.Sequential(
            nn.Linear(2 * d_model, d_model),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, d_model),
        )

        # Modifier information is already fused per event in damage_pool.
        self.out_proj = nn.Sequential(
            nn.Linear(2 * d_model, d_model),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, d_model),
        )

        # ActorCritic normalizes this pool alongside the other pools.

    def _safe_player(self, idx: torch.Tensor) -> torch.Tensor:
        """Map -2 (padding) → 0, -1 (real no-actor) → 1, 0/1 (perspective-
        relative self/enemy) → 2/3. Padding and real -1 use distinct
        slots; player_id is perspective-relative, so 0 = self and 1 = enemy.

        Raise on out-of-range: an engine value above 1 means
        an absolute player identifier leaked through or the observation is
        corrupt.
        """
        return self._safe_categorical(idx, 'player', PLAYER_VOCAB, real_max=1)

    def _safe_char(self, idx: torch.Tensor) -> torch.Tensor:
        """Map -2 (padding) → 0, -1 (real no-char) → 1, 0..MC-1 → 2..MC+1.
        Raises on out-of-range."""
        return self._safe_categorical(idx, 'char', CHAR_VOCAB, real_max=OBS_MAX_CHARS - 1)

    def _safe_element(self, idx: torch.Tensor) -> torch.Tensor:
        """Map -2 (padding) → 0, -1 unused → 1, 0..9 (ElemNone..Piercing)
        → 2..11. Raises on out-of-range."""
        # Element enum 0..ElemPiercing (=9).
        return self._safe_categorical(idx, 'element', ELEMENT_VOCAB, real_max=9)

    def _safe_reaction(self, idx: torch.Tensor) -> torch.Tensor:
        """Map -2 (padding) → 0, -1 unused → 1, 0..N (ReactionKind real)
        → 2..N+1. Raises on out-of-range.

        The maximum is ``REACTION_VOCAB - 3`` to reserve two sentinel
        slots and one spare entry.
        """
        return self._safe_categorical(idx, 'reaction_kind', REACTION_VOCAB, real_max=REACTION_VOCAB - 3)

    def _safe_modifier_kind(self, idx: torch.Tensor) -> torch.Tensor:
        """Map -2 (padding) → 0, -1 unused → 1, 0..3 (ModBoost..ModAfterDamage) → 2..5.
        Raises on out-of-range."""
        # ModBoost..ModAfterDamage = 0..3
        return self._safe_categorical(idx, 'modifier_kind', MODIFIER_KIND_VOCAB, real_max=3)

    def _safe_categorical(
        self,
        idx: torch.Tensor,
        field_name: str,
        vocab_size: int,
        real_max: int,
    ) -> torch.Tensor:
        """Validate and offset a categorical field for embedding lookup.

        Valid ranges:
          - -2 (padding sentinel)
          - -1 (real "no-X")
          - 0..real_max (real values)

        +2 offset maps to vocab idx 0..real_max+2; clamp range checked.
        Out-of-range input raises ``ValueError``.
        """
        idx_long = idx.long()
        too_low = idx_long < -2
        too_high = idx_long > real_max
        if (too_low | too_high).any():
            bad = idx_long[too_low | too_high]
            raise ValueError(
                f'{field_name} out of range [-2, {real_max}]: got values {bad.tolist()}. '
                f'Engine emitted value beyond vocab (size={vocab_size}) — bug, not noise.'
            )
        return idx_long + 2

    def _safe_skill_slot(self, idx: torch.Tensor) -> torch.Tensor:
        """Map -2 (padding, never emitted by encodePrepareSkill but
        encoder is uniform), -1 (no prepare real), 0..MSPC-1 → 2..MSPC+1.

        A slot outside [-2, OBS_MAX_SKILLS_PER_CHAR) means the engine
        emitted a slot beyond the network's vocabulary, indicating either
        an engine bug or an OBS_MAX_SKILLS_PER_CHAR drift between Go and
        Python.
        """
        idx_long = idx.long()
        too_low = idx_long < -2
        too_high = idx_long >= OBS_MAX_SKILLS_PER_CHAR
        if (too_low | too_high).any():
            bad = idx_long[too_low | too_high]
            raise ValueError(
                f'skill_slot out of range [-2, {OBS_MAX_SKILLS_PER_CHAR}): '
                f'got values {bad.tolist()}. Engine emitted slot beyond '
                f'OBS_MAX_SKILLS_PER_CHAR={OBS_MAX_SKILLS_PER_CHAR} or a '
                'corrupt obs index — bug, not noise.'
            )
        return idx_long + 2

    def forward(
        self,
        recent_damage: torch.Tensor,
        prepare_skill: torch.Tensor,
        modifier_log: torch.Tensor,
    ) -> torch.Tensor:
        """
        Args:
            recent_damage:  (B, K, 11) — fields 0..10:
                actor_player / actor_char / target_player / target_char /
                element / raw_value / final_value / absorbed /
                is_piercing / is_hit / reaction_kind
            prepare_skill:  (B, 2, 2)  — per player (char_idx, skill_slot)
            modifier_log:   (B, K, K_mod, 5) — fields 0..4:
                kind / value_before / value_after /
                element_before / element_after
        Returns:
            (B, d_model)
        """
        # Use explicit exceptions so checks remain active under ``python -O``.
        if recent_damage.shape[1] != OBS_RECENT_DAMAGE_EVENTS:
            raise ValueError(
                f'recent_damage shape[1]={recent_damage.shape[1]}, '
                f'expected OBS_RECENT_DAMAGE_EVENTS={OBS_RECENT_DAMAGE_EVENTS}'
            )
        if recent_damage.shape[2] != OBS_RECENT_DAMAGE_FIELD_COUNT:
            raise ValueError(
                f'recent_damage shape[2]={recent_damage.shape[2]}, '
                f'expected OBS_RECENT_DAMAGE_FIELD_COUNT={OBS_RECENT_DAMAGE_FIELD_COUNT}'
            )
        if modifier_log.shape[1] != OBS_RECENT_DAMAGE_EVENTS:
            raise ValueError(
                f'modifier_log shape[1]={modifier_log.shape[1]}, '
                f'expected OBS_RECENT_DAMAGE_EVENTS={OBS_RECENT_DAMAGE_EVENTS}'
            )
        if modifier_log.shape[2] != OBS_MODIFIER_LOG_K_MOD:
            raise ValueError(
                f'modifier_log shape[2]={modifier_log.shape[2]}, '
                f'expected OBS_MODIFIER_LOG_K_MOD={OBS_MODIFIER_LOG_K_MOD}'
            )
        if modifier_log.shape[3] != OBS_MODIFIER_LOG_FIELD_COUNT:
            raise ValueError(
                f'modifier_log shape[3]={modifier_log.shape[3]}, '
                f'expected OBS_MODIFIER_LOG_FIELD_COUNT={OBS_MODIFIER_LOG_FIELD_COUNT}'
            )
        if prepare_skill.shape[1:] != (2, 2):
            raise ValueError(f'prepare_skill shape[1:]={tuple(prepare_skill.shape[1:])}, expected (2, 2)')

        # ---- Recent damage events (B, K, 11) ----
        # Apply dropout independently to each categorical lookup.
        ap_emb = self.embed_dropout(self.player_emb(self._safe_player(recent_damage[..., 0])))
        ac_emb = self.embed_dropout(self.char_emb(self._safe_char(recent_damage[..., 1])))
        tp_emb = self.embed_dropout(self.player_emb(self._safe_player(recent_damage[..., 2])))
        tc_emb = self.embed_dropout(self.char_emb(self._safe_char(recent_damage[..., 3])))
        elem_emb = self.embed_dropout(self.element_emb(self._safe_element(recent_damage[..., 4])))
        rk_emb = self.embed_dropout(self.reaction_emb(self._safe_reaction(recent_damage[..., 10])))
        scalars = torch.stack(
            [
                recent_damage[..., 5],  # raw_value
                recent_damage[..., 6],  # final_value
                recent_damage[..., 7],  # absorbed
                recent_damage[..., 8],  # is_piercing
                recent_damage[..., 9],  # is_hit
            ],
            dim=-1,
        )
        event_input = torch.cat([ap_emb, ac_emb, tp_emb, tc_emb, elem_emb, rk_emb, scalars], dim=-1)
        event_emb = self.event_proj(event_input)  # (B, K, d_model)

        # ---- Modifier log (B, K, K_mod, 5) ----
        mk_emb = self.embed_dropout(self.modifier_kind_emb(self._safe_modifier_kind(modifier_log[..., 0])))
        meb_emb = self.embed_dropout(self.element_emb(self._safe_element(modifier_log[..., 3])))
        mea_emb = self.embed_dropout(self.element_emb(self._safe_element(modifier_log[..., 4])))
        m_scalars = torch.stack(
            [modifier_log[..., 1], modifier_log[..., 2]],
            dim=-1,
        )
        mod_input = torch.cat([mk_emb, meb_emb, mea_emb, m_scalars], dim=-1)
        mod_emb = self.modifier_proj(mod_input)  # (B, K, K_mod, d_model)
        # Stage-axis pool first → (B, K, d_model). Each event keeps its own
        # modifier summary; alignment to event_emb is preserved.
        per_event_mod = mod_emb.mean(dim=2)
        # Learned fusion preserves separate event and modifier inputs.
        event_with_mod_input = torch.cat([event_emb, per_event_mod], dim=-1)  # (B, K, 2*d_model)
        event_with_mod = self.event_mod_fuse(event_with_mod_input)  # (B, K, d_model)
        damage_pool = event_with_mod.mean(dim=1)  # (B, d_model)

        # ---- Prepare skill (B, 2, 2) — concat over players ----
        ps_char_emb = self.embed_dropout(self.char_emb(self._safe_char(prepare_skill[..., 0])))
        ps_slot_emb = self.embed_dropout(self.skill_slot_emb(self._safe_skill_slot(prepare_skill[..., 1])))
        per_player = ps_char_emb + ps_slot_emb  # (B, 2, d_model)
        B = per_player.shape[0]
        prepare_concat = per_player.reshape(B, 2 * self.d_model)
        prepare_pool = self.prepare_proj(prepare_concat)  # (B, d_model)

        # ---- Fuse ----
        combined = torch.cat([damage_pool, prepare_pool], dim=-1)
        return self.out_proj(combined)
