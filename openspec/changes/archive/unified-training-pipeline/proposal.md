---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
change_id: unified-training-pipeline
---

# unified-training-pipeline — GICG 5 paradigm 统一训练管线

## Why

当前 `training/` 三层布局(`framework/` + `az/` + `cfr/` + `dmc/` + `ppo/`)
是 2026-04 PPO + AZ + CFR 并存时期演化产物,2026-05 加入 DMC + 抽出 BC 后
痛点显化:

1. **`framework/` 与各 paradigm 渗透**:Phase 3.5 DMC review 观察到
   `framework/` import paradigm-specific 类型(违反 ADR-0006 隔离),fix
   只能在 review 时一项项发现。
2. **Actor / eval 各自实现 episode loop**:AZ selfplay 一份、PPO rollout
   一份、DMC actor 一份、eval workers 又一份。Paradigm × runner 笛卡尔
   积,bug fix(如 #152 mirror double-fire)需要 4 处同步。
3. **Inference placement hardcode**:Local vs remote、CPU vs GPU 当前在
   AZ async loop / DMC inference server 中分别硬编码,无法横向迁移。新
   paradigm 接入要重写 inference adapter。
4. **BC 是辅助流程,embedded in AZ + PPO**:`training/az/bc_*.py` +
   `training/ppo/bc_*.py` 重复实现,r009 production model 维护时双修。BC
   无法独立 scale 或被 RL paradigm 作为 warm-start prior 共享。
5. **Cfg device / seed 分散**:每 paradigm 自己读 `meta.device`,fallback
   规则不一致;eval inference 与 train inference 共享 device 字段时无法独
   立 override。
6. **Tools 入口分散**:`tools/launch_*.py` × N + `tools/run_*.py` × N
   paradigm-specific,没法做 paradigm-agnostic 操作(如统一 ckpt inspect、
   统一 metrics aggregation)。

P0-T9 ship 的 `openspec/specs/training-architecture/spec.md` 是 22 SHALL
**骨架**,锚定方向,留 P2 落地详细 protocol + driver + 5 paradigm 边界。
本 change 即 P2 落地。

## What

5 条核心 deliverable:

1. **`training/core/` + `training/paradigms/<name>/` 二分**:删
   `training/framework/`,paradigm-agnostic infra 进 `core/`,paradigm-
   specific 算法进 `paradigms/<name>/`。BC 独立成 `paradigms/bc/`(D1
   first-class)。
2. **6 protocol 形式化**:`Paradigm` / `Collector` / `Buffer` /
   `LossComputer` / `EpisodePolicy` / `NetworkProvider`,全 paradigm
   实现,driver loop paradigm-agnostic。
3. **Placement × Device 二维正交**:Inference 通过 `NetworkProvider`
   抽象屏蔽 local vs remote 差异;device 任意 PyTorch device string,二维
   笛卡尔积全支持。
4. **EpisodeRunner 共享 atom**:Actor(train data collection)+ EvalWorker
   (periodic eval)共用同一 `EpisodeRunner`,parameterized by `EpisodeSpec`
   (scenario_seed / opp / epsilon / deterministic),消除 paradigm × runner
   笛卡尔积。
5. **Cfg 多层继承 + R1-R7 placement schema**:`device` / `seed` 通过
   registry-driven fallback chain;`placement` 7 条 SHALL(R1-R7)保证
   schema 闭合,杜绝 typo / 缺段 / dead field。

## Affected specs

**Modify**(P0-T9 ship 骨架,本 change 落地详细):
- `openspec/specs/training-architecture/spec.md` — delta:5 subtopic 详细
  实施 + 5 paradigm 接入引用 + EpisodeRunner / NetworkProvider 抽象 SHALL

**Add**(7 个新 capability spec):
- `openspec/specs/paradigm-az/` — AZ 算法层 SHALL(MCTS / KL+MSE / replay)
- `openspec/specs/paradigm-dmc/` — DMC 算法层 SHALL(MC / logit-as-Q /
  ε-greedy / SHM replay)
- `openspec/specs/paradigm-cfr/` — CFR 算法层 SHALL(OS-MCCFR / reservoir /
  advantage+strategy / frozen)
- `openspec/specs/paradigm-ppo/` — PPO 算法层 SHALL(GAE / clipped surrogate /
  rollout / frozen)
- `openspec/specs/paradigm-bc/` — BC 算法层 SHALL(dataset / CE/KL / no env /
  first-class)
- `openspec/specs/config-schema/` — R1-R7 placement schema + device/seed
  继承 registry
- `openspec/specs/tools-layout/` — `tools/run.py` 单入口 + 子目录分类

## Out of scope

- **Phase 3.5+ 实施**:本 change 只 ship proposal + design + tasks + spec
  delta(P2 内容);P3 core scaffold + DMC 迁移、P4 4 paradigm 接入、P5 物
  理 git mv 留后续 commit / change。
- **Go 化 G1/G2/G3**:F1-Dn baseline Go 化(G1)、cgo step+encode 合并(G2)、
  DMC actor Go(G3)在 tasks/ 中列 plan,但实施由独立 follow-up change 承
  接,不在本 change 边界内。
- **Obs / action 张量编码**:`openspec/specs/rl-obs/`(待落地 capability)
  治理,本 change 不动 obs 协议。
- **Runs registry / artifact 命名**:`openspec/specs/runs-registry/`(待落地)
  治理,本 change 不动 `docs/4_runs/registry.md` 数据契约。
- **新 paradigm 加入**:本 change 锁定 5 paradigm(AZ / DMC / CFR / PPO /
  BC),后续 paradigm(如 MuZero / IMPALA)按 Paradigm protocol 加入,但不
  在本 change 内列。

## Status

- **Created**:2026-05-16(P2 of OpenSpec migration plan)
- **Phase**:DRAFT — ship 后转 ACTIVE,P3 实施开始
- **Expected ship date**:2026-05-16(proposal/design/tasks/spec delta 落盘
  一次性 commit)
- **Archive trigger**:P3-P6 全部 ship + smoke pass + spec delta merge 进
  `openspec/specs/` → `/opsx:archive unified-training-pipeline`
