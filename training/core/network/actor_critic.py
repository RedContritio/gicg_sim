"""Generic ActorCritic composition used by AZ, BC, DMC, and PPO.

Composition is configured through:
- ``heads: nn.ModuleDict`` — paradigm picks subset {policy / value / q /
  avg_policy / delta}
- ``typed_damage: TypedDamageEncoder | None`` — optional 7th pool

Forward returns dict {head_name: tensor, '_state_vec', '_action_emb',
'_combined'}; '_*' intermediate features useful for paradigms applying
custom masks externally (e.g. PPO masked_softmax, AZ MCTS prior).

Current contract: ``openspec/specs/training-architecture/network-sharing.md``.
CFR retains its own ``CFRStrategyNet`` and ``AdvantageNet`` composition.
"""

from __future__ import annotations

from typing import Optional

import torch
import torch.nn as nn

from training.core.cfg.shape import ObsShape
from training.core.network.encoder import (
    CardEncoder,
    CounterEncoder,
    CrossAttentionBlock,
    HookEncoder,
)
from training.core.network.heads import (
    AvgPolicyHead,
    DeltaHead,
    PolicyHead,
    QHead,
    ValueHead,
)
from training.core.network.hook_emb import CharSkillPooler, CharSlotEmbedder
from training.core.network.struct_readout import StructReadoutBlock
from training.core.network.typed_damage import TypedDamageEncoder
from training.core.network.buffs import BuffEncoder
from training.core.network.definition_relation import DefinitionRelation
from training.core.network.action_embedding import encode_actions
from training.core.network.perspective import relative_structural
from training.core.obs_constants import (
    DICE_COLOR_COUNT,
    OBS_META_SIZE,
)


HEAD_REGISTRY: dict[str, type[nn.Module]] = {
    'policy': PolicyHead,
    'value': ValueHead,
    'q': QHead,
    'avg_policy': AvgPolicyHead,
    'delta': DeltaHead,
}

# Canonical head order keeps ModuleDict, parameters, and positional
# optimizer state stable across processes. Iterating the input set directly
# would depend on the process hash seed.
_REGISTRY_ORDER: dict[str, int] = {k: i for i, k in enumerate(HEAD_REGISTRY)}

POINTER_HEADS = frozenset({'policy', 'q', 'avg_policy'})
COMBINED_HEADS = frozenset({'value', 'delta'})


class ActorCritic(nn.Module):
    """Thin composition: encoders + readout + heads + optional typed_damage."""

    def __init__(
        self,
        n_counter_slots: int,
        n_hooks: int,
        max_ops_per_hook: int,
        max_actions: int,
        heads: nn.ModuleDict,
        d_model: int = 128,
        n_cross_layers: int = 2,
        dropout: float = 0.0,
        typed_damage: Optional[TypedDamageEncoder] = None,
        fields_per_op: int = 5,
    ) -> None:
        super().__init__()
        self.d_model = d_model
        self.n_counter_slots = n_counter_slots
        self.max_actions = max_actions
        self.dropout = dropout
        # Shape constants needed by external static-obs decoders (e.g. the
        # DMC mp inference server's request decoder). Stored as plain
        # attributes — not registered as buffers; surviving pickle is
        # sufficient (these are ints / not parameters).
        self.n_hooks = n_hooks
        self.max_ops_per_hook = max_ops_per_hook
        self.fields_per_op = fields_per_op

        # HookEncoder consumes a (B, N, max_ops, 5) IR tensor.
        # opcode_vocab=16 and operand_vocab=2048
        # (covers ctx_field/enum/method/builtin/kwarg/bridge/counter ranges).
        self.hook_encoder = HookEncoder(
            opcode_vocab=16,
            operand_vocab=2048,
            token_dim=d_model,
            n_heads=4,
            n_layers=2,
            max_ops=max_ops_per_hook,
            dropout=dropout,
        )
        self.counter_encoder = CounterEncoder(max_slots=2000, embed_dim=d_model)
        self.card_encoder = CardEncoder(d_model=d_model)
        self.cross_layers = nn.ModuleList(
            [CrossAttentionBlock(d_model, n_heads=4, dropout=dropout) for _ in range(n_cross_layers)]
        )
        self.readout = StructReadoutBlock(d_model)
        self.char_skill_pooler = CharSkillPooler(d_model)
        self.char_slot_emb = CharSlotEmbedder(d_model)
        self.card_target_emb = nn.Embedding(2 * self.char_slot_emb.emb.num_embeddings, d_model)
        self.tune_source_emb = nn.Embedding(8, d_model)
        self.tune_action_emb = nn.Parameter(torch.randn(d_model) * 0.02)
        self.definition_relation = DefinitionRelation(d_model)
        self.reroll_color_emb = nn.Embedding(9, d_model)  # eight colors plus confirmation
        self.reroll_count_proj = nn.Linear(2, d_model)
        self.meta_proj = nn.Linear(OBS_META_SIZE, d_model)
        self.end_turn_emb = nn.Parameter(torch.zeros(d_model))
        nn.init.normal_(self.end_turn_emb, std=0.02)
        self.action_emb_norm = nn.LayerNorm(d_model)
        self.dice_combo_proj = nn.Sequential(
            nn.Linear(DICE_COLOR_COUNT, d_model),
            nn.ReLU(),
            nn.Linear(d_model, d_model),
        )

        self.buff_encoder = BuffEncoder(d_model, self.counter_encoder.sid_embed)
        self.typed_damage = typed_damage

        self._n_pools = 7 if typed_damage is not None else 6
        self.pool_norms = nn.ModuleList([nn.LayerNorm(d_model) for _ in range(self._n_pools)])
        self.state_proj = nn.Sequential(
            nn.Linear(self._n_pools * d_model, d_model * 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 2, d_model),
        )

        self.heads = heads

    def encode(
        self,
        counter_values: torch.Tensor,
        counter_sids: torch.Tensor,
        active_slot_mask: torch.Tensor,
        hook_emb_cached: torch.Tensor,
        hook_mask: torch.Tensor,
        card_buckets: torch.Tensor,
        enemy_sizes: torch.Tensor,
        meta: torch.Tensor,
        action_refs: torch.Tensor,
        action_payments: torch.Tensor,
        structural_values: torch.Tensor,
        char_skill_refs: torch.Tensor,
        recent_damage: Optional[torch.Tensor] = None,
        prepare_skill: Optional[torch.Tensor] = None,
        modifier_log: Optional[torch.Tensor] = None,
        buffs: Optional[torch.Tensor] = None,
        *,
        definition_links: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Common encode pipeline → (state_vec, action_emb, combined).

        typed_damage segments required iff ``self.typed_damage is not None``;
        mismatch raises ValueError (catch caller mistakes at entry, not
        deep in forward).
        """
        counter_emb, counter_mask = self.counter_encoder(counter_values, counter_sids, active_slot_mask)

        hook_emb = self.definition_relation(hook_emb_cached, definition_links)
        for layer in self.cross_layers:
            counter_emb, hook_emb = layer(counter_emb, hook_emb, counter_mask, hook_mask)

        counter_valid = counter_mask.unsqueeze(-1).float()
        counter_pool = (counter_emb * counter_valid).sum(dim=1) / counter_valid.sum(dim=1).clamp(min=1)
        hook_valid = hook_mask.unsqueeze(-1).float()
        hook_pool = (hook_emb * hook_valid).sum(dim=1) / hook_valid.sum(dim=1).clamp(min=1)

        char_skill_pool = self.char_skill_pooler(hook_emb, char_skill_refs)
        meta_emb = self.meta_proj(meta)
        card_emb = self.card_encoder(card_buckets, enemy_sizes)
        struct_feat = self.readout(relative_structural(structural_values, meta))

        pools = [counter_pool, hook_pool, char_skill_pool, card_emb, meta_emb, struct_feat]
        if self.typed_damage is not None:
            if recent_damage is None or prepare_skill is None or modifier_log is None:
                raise ValueError(
                    'ActorCritic.encode: typed_damage encoder requires recent_damage + prepare_skill + modifier_log args'
                )
            typed_pool = self.typed_damage(recent_damage, prepare_skill, modifier_log)
            pools.append(typed_pool)
        elif recent_damage is not None or prepare_skill is not None or modifier_log is not None:
            raise ValueError('ActorCritic.encode: typed_damage segments passed but self.typed_damage is None')

        normed = [norm(p) for norm, p in zip(self.pool_norms, pools)]
        combined = torch.cat(normed, dim=-1)
        buff_pool, buff_tokens = self.buff_encoder(buffs, hook_emb, return_tokens=True)
        state_vec = self.state_proj(combined) + buff_pool

        action_emb = encode_actions(self, hook_emb, action_refs, action_payments, buffs, buff_tokens)

        return state_vec, action_emb, combined

    def forward(self, *args, **kwargs) -> dict:
        """encode + run all registered heads → output dict.

        Convention:
            - 'policy' / 'q' / 'avg_policy' heads take (state_vec, action_emb)
            - 'value' / 'delta' heads take combined feature
        """
        state_vec, action_emb, combined = self.encode(*args, **kwargs)
        out: dict = {
            '_state_vec': state_vec,
            '_action_emb': action_emb,
            '_combined': combined,
        }
        for name, head in self.heads.items():
            if name in POINTER_HEADS:
                out[name] = head(state_vec, action_emb)
            else:
                out[name] = head(combined)
        return out


def make_actor_critic(
    cfg: ObsShape,
    head_kinds: set[str],
    use_typed_damage: bool = True,
) -> ActorCritic:
    """Factory: build standard ActorCritic from ObsShape + head specification.

    Args:
        cfg: ObsShape determining input dimensions + d_model.
        head_kinds: subset of {'policy', 'value', 'q', 'avg_policy', 'delta'}
                    — paradigm picks heads it needs (e.g. AZ uses
                    {'policy', 'value', 'delta'}; DMC {'q'}; PPO
                    {'policy', 'value'}). CFR does not use this factory.
        use_typed_damage: if True, include TypedDamageEncoder (ADR-0019
                          §B.3a). 7-pool layout. If False, 6-pool for
                          callers that omit typed observation segments.

    Returns:
        ActorCritic instance — paradigm wraps via AgentBase subclass.

    Raises:
        ValueError: head_kinds contains unknown head name.
    """
    unknown = head_kinds - set(HEAD_REGISTRY.keys())
    if unknown:
        raise ValueError(f'make_actor_critic: unknown head kinds {unknown}; known: {set(HEAD_REGISTRY.keys())}')

    combined_dim = cfg.d_model * (7 if use_typed_damage else 6)
    heads = nn.ModuleDict()
    # Iterate in registry order so checkpointed optimizer state maps to the
    # same parameter order across processes.
    for kind in sorted(head_kinds, key=_REGISTRY_ORDER.__getitem__):
        head_cls = HEAD_REGISTRY[kind]
        if kind in POINTER_HEADS:
            heads[kind] = head_cls(cfg.d_model, dropout=cfg.dropout)
        elif kind == 'value':
            heads[kind] = head_cls(combined_dim, cfg.d_model, dropout=cfg.dropout)
        elif kind == 'delta':
            heads[kind] = head_cls(
                in_dim=combined_dim,
                d_model=cfg.d_model,
                n_counter_slots=cfg.n_counter_slots,
                dropout=cfg.dropout,
            )

    typed_damage = TypedDamageEncoder(cfg.d_model, dropout=cfg.dropout) if use_typed_damage else None

    return ActorCritic(
        n_counter_slots=cfg.n_counter_slots,
        n_hooks=cfg.n_hooks,
        max_ops_per_hook=cfg.max_ops_per_hook,
        max_actions=cfg.max_actions,
        heads=heads,
        d_model=cfg.d_model,
        n_cross_layers=cfg.n_cross_layers,
        dropout=cfg.dropout,
        typed_damage=typed_damage,
        fields_per_op=cfg.fields_per_op,
    )
