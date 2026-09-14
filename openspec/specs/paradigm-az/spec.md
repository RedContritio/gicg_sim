---
last_updated: 2026-09-14
status: LIVE
schema_version: 1
capability: paradigm-az
---

# Paradigm AZ — AlphaZero 算法层不变量

This specification describes the current AlphaZero adapter under
`training/paradigms/az/`. Its historical maintenance-tier decision and old run
results are preserved as history; current project activity and acceptance
evidence live in [`docs/0_status/README.md`](../../../docs/0_status/README.md).

## 1. Scope

The contract covers self-play search, replay targets, loss, network heads,
collector dispatch, and schedule. Shared pipeline and network rules are defined
by `training-architecture` and `network-architecture`.

## 2. Core SHALL invariants

### A1. Self-play and targets

1. **A1.1** AZ SHALL generate self-play decisions with the
   `training.paradigms.az.mcts` information-set MCTS implementation. Its MCTS
   backend MAY be selected by `paradigm.mcts.backend`.
2. **A1.2** Search leaf evaluation SHALL use the current AZ network provider;
   the serial self-play path SHALL share the same learner network for both
   sides.
3. **A1.3** Each replay step SHALL carry a legal-masked MCTS visit target
   `pi_target` and terminal outcome target `z_target`. Optional counter-delta
   supervision SHALL use `counter_target` plus `has_counter_target`.

### A2. Loss

4. **A2.1** The base loss SHALL be masked policy cross-entropy against
   `pi_target` plus MSE against `z_target`.
5. **A2.2** `paradigm.train.l2_coef` and `entropy_coef` SHALL control optional
   L2 regularization and entropy bonus. Defaults are `1e-4` and `0.0`.
6. **A2.3** When `delta_aux_coef>0` and counter targets are present,
   `AZLoss` SHALL add the masked counter-delta MSE term. The default coefficient
   is `0.1`.

### A3. Replay buffer

7. **A3.1** `AZBuffer` SHALL use a bounded ring replay store and SHALL dedupe
   per-game static observation payloads through `StaticDedupBufferBase`.
8. **A3.2** Capacity SHALL come from `paradigm.buffer_cap`, whose dataclass
   default is `200_000` transitions.
9. **A3.3** Sampling SHALL use replacement and weight discovery transitions by
   `priority_weight` (default `3.0`). Setting the weight to `1.0` yields
   uniform weights; current sampling is not uniform by default.

### A4. Network

10. **A4.1** `AZNetwork` SHALL construct the generic typed-observation
    ActorCritic with `AZ_HEAD_KINDS={'policy', 'value', 'delta'}`.
11. **A4.2** `BASIC_HEAD_CLASSES` enumerates the policy and value head classes
    for introspection; it SHALL NOT be treated as the complete trained head set
    because the delta head is also present.
12. **A4.3** `AgentBase` SHALL receive the constructed network's
    `hook_encoder` through dependency injection. Current docs and comments
    SHALL use that property rather than the removed `encoders['hook']` path.

### A5. Collector and cadence

13. **A5.1** `pipeline.mode='serial'` SHALL select `AZSelfPlayCollector` and
    `pipeline.mode='async'` SHALL select `AZAsyncCollector`.
14. **A5.2** The AZ adapter SHALL reject `actor_backend='go'`. This does not
    prevent the MCTS search backend itself from using its supported Go bridge.
15. **A5.3** Card-pool dictionaries returned by `resolve_pool_refs` SHALL be
    wrapped by `make_pool_spec` before reaching search or determinization.
16. **A5.4** The schedule SHALL collect until `total_games`, defer training
    until `min_buffer_before_train` transitions exist, then run
    `train_steps_per_game` learner batches per outer step.
17. **A5.5** Async weight publication SHALL follow
    `sync_weights_every_train_steps` through the shared protocol helper.

### A6. Compatibility and tier

18. **A6.1** The AZ adapter remains maintenance tier. New production claims
    require current OpenSpec and evaluation evidence rather than an old r009
    label.
19. **A6.2** `init_from_ckpt` accepts the implemented checkpoint forms in
    `AZParadigm._load_init_ckpt`. Compatibility with the current observation
    and state-dict schema must still be established by the actual load path.
20. **A6.3** Old pre-structural-backbone checkpoints remain historical and
    SHALL NOT be described as current fallbacks.

## 3. Implementation references

- Config and schedule: `training/paradigms/az/config.py`,
  `training/paradigms/az/paradigm.py`
- Search and self-play: `training/paradigms/az/mcts/`,
  `training/paradigms/az/selfplay.py`
- Collector dispatch: `training/paradigms/az/collector.py`,
  `training/paradigms/az/_async.py`
- Network, buffer, and loss: `training/paradigms/az/network.py`,
  `training/paradigms/az/buffer.py`, `training/paradigms/az/loss.py`
- Historical AZ dossier:
  [`docs/paradigms/az/`](../../../docs/paradigms/az/)

## 4. Historical context

The original 2026-05 specification named the Go package as the only MCTS
implementation, described a two-head model, said replay sampling was uniform,
and pointed to private memory and a pending architecture page. The current
contract reflects the shipped adapter while leaving historical run facts in
their archived records.
