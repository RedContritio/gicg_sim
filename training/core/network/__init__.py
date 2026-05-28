"""training.core.network — paradigm-agnostic network primitives.

Generic primitives shared by all 5 paradigms (AZ / BC / CFR / DMC / PPO).
Composition via ``make_actor_critic`` factory (paradigm picks head subset
+ optional typed_damage).

Owns:
- ``actor_critic`` — generic ``ActorCritic`` thin composition + ``make_actor_critic`` factory
- ``agent_base`` — per-game cache + obs parse scaffolding (DI hook_encoder)
- ``typed_damage`` — TypedDamageEncoder (ADR-0019, optional 7th pool)
- ``encoder`` — Hook + Counter + Card encoders + CrossAttention
- ``heads`` — PolicyHead / ValueHead / QHead / AvgPolicyHead / DeltaHead
- ``struct_readout`` — C1v7 struct readout block (绕过 cross-attn 零空间)
- ``hook_emb`` — char-skill / char-slot helpers

Phase 1 (core-network-generic-promotion) note: ``core/network/legacy/`` 同时
存在,5 paradigm 仍使用其老 ActorCritic / AgentBase / typed_damage 副本;
Phase 2 逐 paradigm 切到本 module,Phase 2 末尾删 legacy/。
"""

from training.core.network.actor_critic import (
    HEAD_REGISTRY,
    ActorCritic,
    make_actor_critic,
)
from training.core.network.agent_base import AgentBase, AgentConfig
from training.core.network.agent_module_wrapper import AgentModuleWrapper
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
from training.core.network.struct_readout import StructReadoutBlock
from training.core.network.typed_damage import TypedDamageEncoder

__all__ = [
    'ActorCritic',
    'AgentBase',
    'AgentConfig',
    'AgentModuleWrapper',
    'HEAD_REGISTRY',
    'make_actor_critic',
    'TypedDamageEncoder',
    'CardEncoder',
    'CounterEncoder',
    'CrossAttentionBlock',
    'HookEncoder',
    'AvgPolicyHead',
    'DeltaHead',
    'PolicyHead',
    'QHead',
    'ValueHead',
    'StructReadoutBlock',
]
