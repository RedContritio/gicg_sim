"""Generic ActorCritic — thin composition shared by all 5 paradigms.

Replaces:
- ``core/network/legacy/actor_critic.ActorCritic`` (god class, 207 lines,
  hardcoded heads + typed_damage_encoder always-on)
- prior ``CoreActorCritic`` at this path (P5 雏形, 182 lines, no
  typed_damage)

Single ActorCritic class with composition via:
- ``heads: nn.ModuleDict`` — paradigm picks subset {policy / value / q /
  avg_policy / delta}
- ``typed_damage: TypedDamageEncoder | None`` — optional 7th pool

Forward returns dict {head_name: tensor, '_state_vec', '_action_emb',
'_combined'}; '_*' intermediate features useful for paradigms applying
custom masks externally (e.g. PPO masked_softmax, AZ MCTS prior).

Spec: ``openspec/changes/core-network-generic-promotion/specs/network-architecture/spec.md``
invariants A1 (composition) + A3 (typed_damage first-class) + A4 (5
paradigm unification).
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
from training.core.obs_constants import (
    ACTION_END_TURN,
    ACTION_SWITCH,
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

# Canonical ordering for head iteration in `make_actor_critic` — invariant
# A12.1(network-architecture/spec.md). DICT 保 Python ≥ 3.7 insertion
# order,跨 subprocess stable;sort by this map → `nn.ModuleDict heads`
# 插入顺序 deterministic → `model.parameters()` 顺序 deterministic →
# `optimizer.state_dict()` positional state mapping 跨 ckpt save / resume
# 不错位。直接 `for kind in head_kinds:` 不可(set / frozenset iteration
# 取决于 `hash()` + `PYTHONHASHSEED=random` → 跨 subprocess 不一致)。
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

        # IR-4: HookEncoder consumes (B, N, max_ops, 5) IR tensor instead of
        # token pairs. opcode_vocab=16 (we have 14 ops), operand_vocab=2048
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
        self.meta_proj = nn.Linear(OBS_META_SIZE, d_model)
        self.end_turn_emb = nn.Parameter(torch.zeros(d_model))
        nn.init.normal_(self.end_turn_emb, std=0.02)
        self.action_emb_norm = nn.LayerNorm(d_model)
        self.dice_combo_proj = nn.Sequential(
            nn.Linear(DICE_COLOR_COUNT, d_model),
            nn.ReLU(),
            nn.Linear(d_model, d_model),
        )

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
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Common encode pipeline → (state_vec, action_emb, combined).

        typed_damage segments required iff ``self.typed_damage is not None``;
        mismatch raises ValueError (catch caller mistakes at entry, not
        deep in forward).
        """
        counter_emb, counter_mask = self.counter_encoder(counter_values, counter_sids, active_slot_mask)

        hook_emb = hook_emb_cached
        for layer in self.cross_layers:
            counter_emb, hook_emb = layer(counter_emb, hook_emb, counter_mask, hook_mask)

        counter_valid = counter_mask.unsqueeze(-1).float()
        counter_pool = (counter_emb * counter_valid).sum(dim=1) / counter_valid.sum(dim=1).clamp(min=1)
        hook_valid = hook_mask.unsqueeze(-1).float()
        hook_pool = (hook_emb * hook_valid).sum(dim=1) / hook_valid.sum(dim=1).clamp(min=1)

        char_skill_pool = self.char_skill_pooler(hook_emb, char_skill_refs)
        meta_emb = self.meta_proj(meta)
        card_emb = self.card_encoder(card_buckets, enemy_sizes)
        struct_feat = self.readout(structural_values)

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
        state_vec = self.state_proj(combined)

        B, n_act, _ = action_refs.shape
        kinds = action_refs[..., 0]
        hook_idx = action_refs[..., 1]
        char_idx = action_refs[..., 2]
        n_hooks_cached = hook_emb.shape[1]
        hook_valid_idx = hook_idx.clamp(min=0).long().clamp(max=max(n_hooks_cached - 1, 0))
        mask_hook = hook_idx >= 0
        gathered = torch.gather(
            hook_emb,
            dim=1,
            index=hook_valid_idx.unsqueeze(-1).expand(-1, -1, self.d_model),
        )
        char_embs = self.char_slot_emb(char_idx)
        end_emb = self.end_turn_emb.view(1, 1, -1).expand(B, n_act, -1)

        action_emb = torch.zeros_like(gathered)
        action_emb = torch.where(mask_hook.unsqueeze(-1), gathered, action_emb)
        action_emb = torch.where((kinds == ACTION_SWITCH).unsqueeze(-1), char_embs, action_emb)
        action_emb = torch.where((kinds == ACTION_END_TURN).unsqueeze(-1), end_emb, action_emb)

        pay_emb = self.dice_combo_proj(action_payments.float())
        action_emb = action_emb + pay_emb
        action_emb = self.action_emb_norm(action_emb)

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
                    {'policy', 'value'}; CFR {'avg_policy', 'value'}).
        use_typed_damage: if True, include TypedDamageEncoder (ADR-0019
                          §B.3a). 7-pool layout. If False, 6-pool (CFR
                          historical / future light paradigms).

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
    # A12.1: iterate in `HEAD_REGISTRY` insertion order — NOT in `head_kinds`
    # iteration order. `head_kinds` is `set[str]` / `frozenset[str]` whose
    # iteration order varies across subprocess (PYTHONHASHSEED=random),
    # causing ckpt save / resume optimizer state positional misalignment.
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
