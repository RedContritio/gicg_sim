---
last_updated: 2026-09-14
status: LIVE
schema_version: 1
capability: paradigm-dmc
---

# Paradigm DMC — Deep Monte Carlo 算法层不变量

本规格描述 `training/paradigms/dmc/` 在统一训练管线中的现行接口。
当前训练目标、运行任务与验收结论以
[`docs/0_status/README.md`](../../../docs/0_status/README.md) 为准；2026 年
5 月的迁移与性能实验保留在历史文档中，不代表当前运行状态。

## 1. Scope

本规格涵盖 Monte Carlo target、logit-as-Q loss、ε-greedy actor、训练
buffer、网络 head 与 collector dispatch。通用 driver、actor runtime、评估
服务分别由 `training-architecture`、`network-architecture` 和
`eval-protocol` 规格治理。

## 2. Core SHALL invariants

### D1. Target and loss

1. **D1.1** DMC SHALL train the selected-action Q logit against the completed
   episode return `G`; the default path SHALL NOT bootstrap from a learned
   value target.
2. **D1.2** `DMCLogitAsQLoss` SHALL compute
   `MSE(logits[action_idx], returns)` with mean reduction.
3. **D1.3** The default network SHALL use the single `q` head declared by
   `training.paradigms.dmc._agent.DMC_HEAD_KINDS`. A value or policy head is
   not part of the current DMC training contract.

### D2. Actor policy

4. **D2.1** Training actors SHALL use ε-greedy action selection over legal Q
   logits: random legal action with probability ε, otherwise argmax.
5. **D2.2** ε SHALL come from `paradigm.epsilon`; the dataclass default is
   `0.05`. Deterministic evaluation SHALL force ε to zero.
6. **D2.3** The current implementation uses a constant ε. Any schedule or
   annealing requires an explicit config field and implementation change.

### D3. Training buffer

7. **D3.1** The learner buffer SHALL be `DMCBuffer`, an in-process bounded
   FIFO of `DmcTransition` records. It SHALL sample uniformly without
   replacement.
8. **D3.2** `buffer_cap` SHALL be config driven; the dataclass default is
   `5_000`, and production configs may override it.
9. **D3.3** Shared memory in the Go and Python async actor paths is transport
   infrastructure. It SHALL NOT be described as the learner's `DMCBuffer` or
   as sample-time static deduplication.

### D4. Network and observation path

10. **D4.1** `DmcAgent` SHALL construct the generic typed-observation backbone
    with `make_actor_critic(..., head_kinds={'q'}, use_typed_damage=True)`.
11. **D4.2** `DMCNetwork.forward_batch` is the training forward entry. Actor
    inference wrappers MAY expose a regular `forward` method for the core
    inference server.
12. **D4.3** Checkpoint compatibility SHALL follow the self-describing
    checkpoint schema and fingerprint checks; historical DMC checkpoint names
    alone do not establish compatibility.

### D5. Collector and cadence

13. **D5.1** `pipeline.mode='serial'` SHALL select `DMCSerialCollector`.
    `pipeline.mode='async'` with `actor_backend='python'` SHALL select
    `DMCMultiProcessCollector`; `actor_backend='go'` SHALL select
    `DMCGoSubprocessCollector`.
14. **D5.2** Actor count SHALL come from `pipeline.num_actors`; the pipeline
    default is one. Production configs may set a larger value after host-level
    resource validation.
15. **D5.3** The schedule SHALL stop when `PipelineState.total_transitions`
    reaches `paradigm.total_frames`, collect without training until at least one
    batch is available, then run `train_ratio` learner batches per outer step.
16. **D5.4** Async weight publication cadence SHALL use
    `sync_weights_every_train_steps` through the shared protocol helper.

## 3. Implementation references

- Config: `training/paradigms/dmc/config.py`
- Paradigm dispatch and schedule: `training/paradigms/dmc/paradigm.py`
- Network and agent: `training/paradigms/dmc/network.py`,
  `training/paradigms/dmc/_agent.py`
- Buffer and loss: `training/paradigms/dmc/buffer.py`,
  `training/paradigms/dmc/loss.py`
- Collectors: `training/paradigms/dmc/collector.py`,
  `training/paradigms/dmc/go_subprocess_collector.py`
- Current training/evaluation status:
  [`docs/0_status/README.md`](../../../docs/0_status/README.md)
- Historical DMC reviews and migration notes:
  [`docs/5_history/`](../../../docs/5_history/)

## 4. Historical context

The original 2026-05 version called DMC the newly active migration target and
described a future Go-actor trigger. Go subprocess collection has since shipped,
and current work uses a newer native semantic-training workflow. Those facts are
historical milestones; they are not current acceptance evidence or a reason to
rename old runs.
