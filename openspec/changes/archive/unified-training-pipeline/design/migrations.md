---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../design.md
---

# Migrations — 5 paradigm 物理迁移 + framework 融入 core

> 治理 D1 / D2 / D3 / D5 决策落地步骤。本文件聚焦 git mv + import 重写 +
> 老 tools 合并。**P3-P5 实施细节**;P2 ship 时不实际执行,仅形式化计划。

## 1. D3 — `training/framework/` 融入 `training/core/`

**Current**(P2 前):

```
training/framework/
├── __init__.py
├── agent_base.py
├── inference/
│   ├── server.py
│   ├── client.py
│   ├── server_loop/
│   └── ...
├── network/
│   ├── typed_damage.py
│   └── ...
├── obs_constants.py
├── step_encoding.py
├── static_dedup_buffer.py
├── training_config_base.py
└── matchup/
```

**Target**(P3 后):

```
training/core/
├── __init__.py
├── protocols.py                # 新建,包 AgentBase 等价物
├── pipeline.py                 # 新建
├── config/
│   ├── base.py                 # FROM framework/training_config_base.py
│   ├── loader.py               # 新建
│   ├── schema.py               # 新建
│   └── inheritance.py          # 新建
├── network/
│   ├── encoder.py              # FROM framework/network/(部分)
│   ├── heads.py                # 新建(抽 az/dmc/ppo/cfr 共享)
│   ├── actor_critic.py         # 新建(整合各 paradigm 当前 actor_critic.py)
│   ├── struct_readout.py       # 抽 az/c1v7 实现
│   └── hook_emb.py             # 抽 framework/network/hook_attn.py
├── buffer/
│   ├── base.py                 # FROM framework/static_dedup_buffer.py
│   ├── replay.py               # 抽 az/replay.py 共享部分
│   ├── reservoir.py            # FROM cfr/reservoir.py
│   ├── rollout.py              # FROM ppo/rollout.py
│   ├── dataset.py              # 新建(BC)
│   ├── static_dedup.py         # FROM framework/static_dedup_buffer.py
│   └── shared.py               # FROM dmc/shared_buffer.py
├── actor/
│   ├── episode_runner.py       # 新建(抽 az+dmc+ppo runner 共性)
│   ├── actor_process.py        # FROM dmc/_actor.py
│   ├── inference_server.py     # FROM framework/inference/server.py
│   ├── inference_client.py     # FROM framework/inference/client.py
│   ├── network_provider.py     # 新建
│   ├── provider_factory.py     # 新建
│   ├── shared_buffer.py        # FROM dmc/shared_buffer.py
│   ├── weights_shm.py          # FROM framework/inference/weights_*.py
│   ├── weights_watcher.py
│   ├── policy.py               # 新建(EpisodePolicy 基类)
│   ├── runtime.py              # 新建
│   └── ipc/                    # FROM framework/inference/server_loop/
├── eval/
│   ├── periodic.py             # 新建
│   ├── server.py               # FROM framework/matchup/ + eval service
│   ├── worker.py               # 新建
│   ├── job.py                  # 新建
│   ├── baselines.py            # 抽 az/eval/baselines.py
│   ├── scenario.py             # 新建
│   ├── statistics.py           # FROM framework/eval/statistics.py
│   └── matchup.py              # FROM framework/matchup/
├── opponent/
│   ├── pool.py                 # FROM az/opponent_pool.py(适配)
│   └── mix.py                  # 新建
├── env_factory.py              # FROM az/env_factory.py(paradigm-agnostic)
├── scenario_factory.py         # 新建
├── obs_constants.py            # FROM framework/obs_constants.py
├── step_encoding.py            # FROM framework/step_encoding.py
├── checkpoint.py               # 新建(整合 az/checkpoint.py + dmc 等)
├── logging.py                  # 新建(metrics.jsonl + TB)
└── nan_guard.py                # FROM dmc/nan_guard.py
```

`training/framework/` SHALL 完全删除。任意 import `training.framework` 转
`training.core`。

## 2. D1 — BC first-class

**Current**:BC 嵌入两处:
- `training/az/bc_dataset_az.py` + `training/az/bc_train_az.py`
- `training/ppo/bc_dataset.py` + `training/ppo/bc_train.py`

两者各自实现 dataset format + train loop + ckpt 协议,重复代码 ~600 LOC。

**Target**:`training/paradigms/bc/`:

```
training/paradigms/bc/
├── __init__.py
├── paradigm.py                 # BCParadigm
├── config.py                   # BCParadigmConfig
├── collector.py                # DatasetCollector(load YAML/Parquet)
├── buffer.py                   # DatasetBuffer
├── loss.py                     # BCLoss(CE 或 KL)
├── policy.py                   # BCPolicy(argmax logits)
└── network.py                  # head 组装(policy only)
```

迁移步骤:
1. P4-T2.1:抽 BC 共性进 `paradigms/bc/`
2. P4-T2.2:`training/az/bc_*` 删除 + import 重写为 `from training.paradigms.bc import ...`(若 AZ warm-start 还需要)
3. P4-T2.3:`training/ppo/bc_*` 删除 + 同上
4. P4-T2.4:`tools/gen_bc_dataset_az.py` → `tools/dataset/gen_bc_dataset.py`(paradigm-agnostic)

## 3. D2 — PPO 迁移而非 archive

**Decision rationale**:`docs/paradigms/ppo/README.md` verdict = closed,但
保留 reproducibility 路径,理由:
- 跨 paradigm 验证 lever 时 PPO 是 fast baseline(2026-04 ablation 用过)
- DSL 改造 / obs 改造时 PPO smoke 是廉价回归测试
- Reimplement 成本 > 迁移成本(估 1-2 days vs 5+ days reimplement)

**迁移步骤**(P4):
1. P4-T3.1:抽 `training/ppo/` 共性逻辑 → `training/paradigms/ppo/`
2. P4-T3.2:PPOLoss / PPOPolicy / RolloutBuffer 适配 6 protocol
3. P4-T3.3:smoke run cfg(`configs/ppo/archive_repro.toml`)跑过验证

PPO smoke 成功后该 paradigm tier = `frozen`,文档明示不接受 new run。

## 4. D5 — 老 tools 合并分类

**Strategy**:不直接删,git mv + adapter 化。

迁移步骤(P5):
1. P5-T1:创建子目录 `tools/{eval,remote,debug,probe,profile,bench,replay,dataset}`
2. P5-T2:`git mv` 工具进对应子目录
3. P5-T3:工具入口 adapter 化(`--az-ckpt` → `--ckpt`,从 cfg 读 paradigm)
4. P5-T4:删除 `tools/launch_*.py` / `tools/run_*.py`(被 `tools/run.py` 取代)
5. P5-T5:加 `tools/<sub>/README.md` 说明 scope

## 5. Imports 重写

涉及面:
- `from training.framework.*` → `from training.core.*` (~80 files)
- `from training.az.bc_* import ...` → `from training.paradigms.bc.* import ...` (~10 files)
- `from training.ppo.bc_* import ...` → `from training.paradigms.bc.* import ...` (~5 files)
- `tools/<flat>.py` → `tools/<sub>/<flat>.py`,调用方 `python -m tools.<sub>.<flat>`

P5-T6:全 grep 验证 0 残留 + 全 pytest pass + ruff format + gofmt。

## 6. Ckpt 兼容性

P3-P5 ckpt format SHOULD 保持兼容(load 旧 ckpt 必能 resume)。具体协议
`training/core/checkpoint.py`:
- ckpt schema version 字段(int)
- v0 = framework era;v1 = core era
- v0 → v1 migrator 函数(rename keys 等)
- v1 SHALL load v0(向下兼容)

若必须 break(如 obs schema 改),走独立 ADR(memory project_typed_obs_ckpt_break
即历史前例)。

## 7. Cross-references

- 决策起点 → [`../proposal.md`](../proposal.md) "Why"
- 物理 mv plan → [`../tasks/phase5-physical-mv-tools.md`](../tasks/phase5-physical-mv-tools.md)
- Tools 重组细节 → [`./tools-layout.md`](./tools-layout.md)
- 历史 ADR-0006 → [`../../archive/0006-training-layout/`](../../archive/0006-training-layout/)
- BC history → `docs/paradigms/bc/README.md`
- PPO history → `docs/paradigms/ppo/README.md`
