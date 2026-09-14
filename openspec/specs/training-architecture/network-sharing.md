---
last_updated: 2026-09-14
status: LIVE
schema_version: 0
capability: training-architecture
subtopic: network-sharing
---

# Network Sharing — shared ActorCritic and paradigm boundaries

This subtopic records the network composition that is present in the source
tree. The generic implementation lives in `training/core/network/`; each
paradigm owns the wrapper, loss, collection policy, and checkpoint adapter
needed by its algorithm.

## 1. Current layout

The shared pieces are modules rather than the older proposed `heads/`
subpackage:

```text
training/core/network/
    actor_critic.py   # ActorCritic and make_actor_critic
    encoder.py        # shared hook, counter, card, and cross-attention encoders
    heads.py          # policy, value, Q, average-policy, and delta heads
    agent_base.py     # per-game cache and observation parsing
    typed_damage.py   # optional typed-damage encoder
    ...               # action, buff, relation, readout, and perspective helpers
```

`training/paradigms/{az,bc,dmc,ppo}/` use the generic `ActorCritic` through
their own wrappers. CFR remains a documented exception: `CFRNetwork` composes
`CFRStrategyNet` with two `AdvantageNet` instances and does not call
`make_actor_critic`.

## 2. Shared composition contract

1. `make_actor_critic(cfg, head_kinds, use_typed_damage)` SHALL validate
   `head_kinds` against `policy`, `value`, `q`, `avg_policy`, and `delta`.
2. It SHALL insert heads in registry order. `head_kinds` is set-like, so
   iterating it directly would make parameter and optimizer-state ordering
   depend on `PYTHONHASHSEED`.
3. `ActorCritic` SHALL own the shared encoders and a `ModuleDict` of selected
   heads. Its forward result SHALL contain the selected head outputs plus the
   `_state_vec`, `_action_emb`, and `_combined` intermediate features used by
   paradigm wrappers.
4. Pointer heads (`policy`, `q`, `avg_policy`) consume state and action
   embeddings. `value` and `delta` consume the combined state feature.
5. `use_typed_damage=True` SHALL require the recent-damage, prepared-skill,
   and modifier-log tensors; `False` SHALL reject those tensors.
6. Checkpoints SHALL use each paradigm wrapper's state-dict and loading
   adapter. Cross-paradigm warm starts must account for wrapper prefixes and
   head differences; a bare `strict=False` call is not a complete checkpoint
   compatibility contract.

## 3. Current paradigm mapping

| Paradigm | Network implementation | Heads / modules | Typed damage |
|---|---|---|---|
| AZ | generic `ActorCritic` inside `AZNetwork` | `policy`, `value`, `delta` | yes |
| BC | generic `ActorCritic` inside `BCNetwork` | `policy`, `value`, `delta` | yes |
| DMC | generic `ActorCritic` inside `DMCNetwork` | `q` | yes |
| PPO | generic `ActorCritic` inside `PPONetwork` | `policy`, `value` | yes |
| CFR | `CFRNetwork` with paradigm-local trunks | strategy/value module plus two advantage modules | no |

The CFR row preserves the frozen-research implementation used for its
reproducibility tier. It should not be described as a generic ActorCritic head
selection unless the source is migrated first.

## 4. AgentBase dependency injection

AZ, DMC, and PPO agents construct their network before calling `AgentBase` and
pass the actual `net.hook_encoder` explicitly:

```python
net = make_actor_critic(cfg, head_kinds={...}, use_typed_damage=True)
super().__init__(cfg, hook_encoder=net.hook_encoder, device=device)
self.net = net
```

This keeps static-observation caching independent of an implicit
`self.net.hook_encoder` lookup and lets tests inject a small encoder. CFR uses
its own agent and network path; BC trains through a network wrapper rather
than `AgentBase`.

## 5. Ownership boundaries

- Shared tensor encoders, basic heads, composition, and observation helpers
  belong under `training/core/network/`.
- Head selection, wrapper APIs, loss semantics, exploration, and checkpoint
  adaptation belong under `training/paradigms/<name>/`.
- A change to the shared encoder changes the state-dict contract for every
  generic-ActorCritic consumer and therefore requires coordinated checkpoint
  compatibility review.
- Algorithm-specific behavior should remain in the paradigm wrapper or loss;
  the shared modules should not import paradigm packages.

## 6. References

- [Protocols](./protocols.md) — `Paradigm.make_network` and related contracts
- [Pipeline](./pipeline.md) — network lifecycle and collector synchronization
- [Evaluation](./eval.md) — checkpoint/provider isolation during evaluation
- [`training/core/network/actor_critic.py`](../../../training/core/network/actor_critic.py)
- [`training/core/network/agent_base.py`](../../../training/core/network/agent_base.py)
- [`training/paradigms/cfr/network.py`](../../../training/paradigms/cfr/network.py)

## 7. Status

- **Created**: 2026-05-17 by the archived `core-network-generic-promotion`
  work.
- **Reconciled with source**: 2026-09-14. Corrected the nonexistent
  `core/network/heads/` layout, the CFR exception, current forward fields, and
  the `AgentBase` injection example.
- **Version**: 0; this update documents the shipped interfaces without
  changing their schema.
