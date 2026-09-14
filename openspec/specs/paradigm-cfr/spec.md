---
last_updated: 2026-09-14
status: LIVE
schema_version: 1
capability: paradigm-cfr
---

# Paradigm CFR — Deep CFR 算法层不变量

CFR is a frozen research adapter retained for code comparison and smoke
coverage. Historical r008 outcomes remain in the history tree; they are not a
current checkpoint compatibility or production-readiness claim.

## 1. Scope

This specification covers OS-MCCFR traversal, the current network modules and
reservoirs, the partial unified-driver adapter, and the explicit smoke-only
path. Common driver and actor contracts live in
[`training-architecture`](../training-architecture/spec.md).

## 2. Core SHALL invariants

### C1. Traversal

1. **C1.1** The production traversal mode SHALL be outcome-sampling MCCFR
   (`sampling_mode='os'`). Traverser selection SHALL follow
   `traversal.traverser_alternation`, whose default is `alternate`.
2. **C1.2** Collection units SHALL mean tree traversals, not complete rollout
   episodes. `traversals_per_iteration` SHALL control the units collected per
   outer step.
3. **C1.3** The serial collector SHALL hold direct references to the two
   advantage networks. The async collector MAY use the shared actor runtime.

### C2. Network and training targets

4. **C2.1** `CFRNetwork` SHALL compose one `CFRStrategyNet` and two
   player-specific `AdvantageNet` modules.
5. **C2.2** `CFRStrategyNet` SHALL produce policy logits and a value estimate.
   The two advantage networks SHALL each produce per-action regret estimates
   for one traverser player.
6. **C2.3** These modules share trunk architecture, not trunk weights. Current
   documentation SHALL NOT describe them as two heads on one shared encoder.
7. **C2.4** The historical trainer's advantage fit SHALL use masked regret MSE.
   Its strategy/value fit SHALL use legal-masked policy cross-entropy plus
   `value_loss_alpha * value MSE`.
8. **C2.5** The protocol adapter `CFRLoss` accepts precomputed `advantage` or
   `strategy` predictions and applies masked MSE to one head at a time. It does
   not run the network forward or compute the historical joint policy/value
   fit.

### C3. Reservoirs

9. **C3.1** The current adapter SHALL maintain four logical reservoirs:
   advantage for player 0, advantage for player 1, strategy, and value.
10. **C3.2** Default capacities SHALL match `CFRParadigmConfig`:
    `100_000` for each advantage reservoir, `200_000` for strategy, and
    `100_000` for value. Production configs may override them.
11. **C3.3** `_CFRBufferBundle.sample(batch_size)` is intentionally ambiguous
    and raises. Head-specific consumers SHALL use `sample_head`.

### C4. Unified-driver limitation and smoke path

12. **C4.1** The generic pipeline's ordinary single-buffer sample/loss loop
    does not implement CFR's head-specific fit schedule. Therefore the real
    `_CFRBufferBundle` path SHALL NOT be presented as a production-ready
    `tools.runs.train` workflow.
13. **C4.2** Smoke configs MAY set
    `debug.cfr_smoke_stub_buffer=true` to exercise generic driver wiring with a
    minimal single-buffer batch. The old
    `GICG_CFR_SMOKE_STUB_BUFFER` environment switch is retired.
14. **C4.3** The smoke stub validates collect/sample/backward/checkpoint
    connectivity only. It SHALL NOT be used as CFR quality or r008
    reproducibility evidence.

### C5. Tier and compatibility

15. **C5.1** CFR SHALL remain `frozen-research` until an explicit OpenSpec
    change restores and validates a real head-specific learner path.
16. **C5.2** Historical r008 checkpoints SHALL be reproduced only with the
    corresponding historical code and config. Current state-dict shape or a
    matching run label does not establish compatibility.
17. **C5.3** Production code SHALL live under `training/paradigms/cfr/`;
    `legacy/` and the former nested `network/` tree are not current paths.

## 3. Implementation references

- Adapter and buffer bundle: `training/paradigms/cfr/paradigm.py`
- Config: `training/paradigms/cfr/config.py`
- Network composition: `training/paradigms/cfr/network.py`,
  `training/paradigms/cfr/strategy_net.py`,
  `training/paradigms/cfr/advantage_net.py`
- Traversal collector: `training/paradigms/cfr/collector.py`,
  `training/paradigms/cfr/_async.py`
- Historical fit implementation: `training/paradigms/cfr/fit_steps.py`
- Protocol loss: `training/paradigms/cfr/loss.py`
- Smoke-only buffer: `training/tests/_cfr_smoke_stub.py`
- Historical pivot evidence:
  [`docs/2_decisions/adr-0008-rl_paradigm_pivot.md`](../../../docs/2_decisions/adr-0008-rl_paradigm_pivot.md)

## 4. Historical context

The 2026-05 specification described two reservoirs, a shared-weight two-head
network, thread-based collection, larger default capacities, and an env-gated
smoke buffer. The current code has four logical reservoirs, separate network
modules, serial or process-based async collection, reduced defaults, and a
config-gated smoke path. Archived r008 observations were not rewritten.
