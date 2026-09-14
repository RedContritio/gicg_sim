---
last_updated: 2026-09-14
status: LIVE
schema_version: 1
capability: paradigm-bc
---

# Paradigm BC — Behavior Cloning 算法层不变量

本规格描述 `training/paradigms/bc/` 的现行静态数据训练接口。旧 r009
结果与 2026 年 5 月迁移结论属于历史；是否存在当前可用 baseline 以
[`docs/0_status/README.md`](../../../docs/0_status/README.md) 和 checkpoint
兼容性检查为准。

## 1. Scope

BC 是统一训练 driver 中的一等 paradigm，但训练数据来自 NPZ dataset，
不通过环境采集 episode。本规格涵盖 dataset、loss、buffer、network 和
schedule；dataset 生成由 `tools/dataset/` 负责。

## 2. Core SHALL invariants

### BC1. Static dataset path

1. **BC1.1** `paradigm.dataset_path` SHALL point to an existing NPZ file
   accepted by `training.core.artifact_io.load_dataset`. An empty or missing
   path SHALL fail before training.
2. **BC1.2** `DatasetCollector` SHALL load the dataset once, emit all dataset
   row indices on its first `collect` call, and return an exhausted no-op on
   subsequent calls.
3. **BC1.3** BC SHALL set `requires_network_in_collect=False` and SHALL NOT
   create an environment or invoke network inference during collection.

### BC2. Loss

4. **BC2.1** `loss_kind='ce'` SHALL train hard expert `chosen_action` labels
   with legal-action masking.
5. **BC2.2** The historical config value `loss_kind='kl'` SHALL use the
   current soft-target cross-entropy implementation: a uniform distribution
   over `tied_mask`. The dataset does not carry arbitrary teacher logits, so
   the mode SHALL NOT be documented as general teacher-logit KL divergence.
6. **BC2.3** `value_coef=0.0` SHALL disable value loss. A positive value
   coefficient SHALL add MSE against `terminal_z`. Entropy is not part of the
   BC loss.

### BC3. Buffer and cadence

7. **BC3.1** The learner buffer SHALL be `training.core.buffer.dataset.DatasetBuffer`.
   Its capacity SHALL be `max(paradigm.buffer_cap, dataset_size)`.
8. **BC3.2** Buffer samples SHALL be row indices transformed by
   `BCDataset.build_batch`; the batch SHALL contain the static and dynamic
   observation fields consumed by `BCNetwork.forward_batch`.
9. **BC3.3** Outer step zero SHALL perform the one-shot collect and one epoch
   of minibatch updates. Later steps SHALL train from the resident dataset
   until `paradigm.n_epochs` is reached.

### BC4. Network and evaluation policy

10. **BC4.1** `BCNetwork` SHALL use the generic typed-observation backbone
    with `BC_HEAD_KINDS={'policy', 'value', 'delta'}`. With the default
    `value_coef=0`, only the policy loss supplies training gradients.
11. **BC4.2** The training forward entry SHALL be
    `BCNetwork.forward_batch(batch_dict)`; plain `forward` is intentionally
    unsupported.
12. **BC4.3** `make_episode_policy` SHALL return the argmax policy used by
    evaluation paths. The training path SHALL NOT use `EpisodeRunner`.
13. **BC4.4** Warm starts SHALL use the common checkpoint load and fingerprint
    rules. The current BC package does not expose an
    `export_for_warm_start` function, so no specification may direct callers
    to that removed/nonexistent entry.

### BC5. Layout

14. **BC5.1** Production code SHALL live directly under
    `training/paradigms/bc/`; a `legacy/` subpackage is not part of the current
    layout.
15. **BC5.2** Current code and docs SHALL refer to `dataset.py`, `loss.py`,
    `network.py`, `collector.py`, and `paradigm.py` at that package root.

## 3. Implementation references

- Config and schedule: `training/paradigms/bc/config.py`,
  `training/paradigms/bc/paradigm.py`
- Dataset and collector: `training/paradigms/bc/dataset.py`,
  `training/paradigms/bc/collector.py`
- Network and loss: `training/paradigms/bc/network.py`,
  `training/paradigms/bc/loss.py`
- Dataset generator: `tools/dataset/gen_bc.py`
- Originating migration history:
  [`openspec/changes/archive/unified-training-pipeline/`](../../changes/archive/unified-training-pipeline/)

## 4. Historical context

The initial specification described YAML/Parquet input, arbitrary soft teacher
logits, an `export_for_warm_start` API, and r009 as a production fallback.
Those statements no longer match the implementation or the current checkpoint
schema. Historical experiment results remain unchanged in their archived files.
