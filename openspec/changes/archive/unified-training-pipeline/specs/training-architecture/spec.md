---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
capability: training-architecture
change_id: unified-training-pipeline
---

# Spec delta — training-architecture

> Delta against `openspec/specs/training-architecture/spec.md` v0(P0-T9
> ship 22 SHALL 骨架,2026-05-15)。本 change 在保留骨架基础上,落地详细
> protocol + driver + 5 paradigm 接入引用 + EpisodeRunner / NetworkProvider
> 抽象 SHALL。

## 1. 保留 SHALL(P0-T9 ship 12 invariant)

P0-T9 ship 的 12 SHALL invariants 全部保留,本 change 不改:
- SHALL 1(top-level layout)
- SHALL 2(Paradigm protocol)
- SHALL 3(core paradigm-agnostic)
- SHALL 4(Inference placement orthogonal)
- SHALL 5(EpisodeRunner shared)
- SHALL 6(Eval inference isolation)
- SHALL 7(Pipeline mode dispatch)
- SHALL 8(Cfg 多层继承)
- SHALL 9(Weights sync 协议)
- SHALL 10(BC first-class)
- SHALL 11(Encoder paradigm-agnostic)
- SHALL 12(Single entry tool)

## 2. [MODIFY] SHALL 2 — Paradigm protocol 详细方法签名

**P0-T9 ship 版**(骨架):
> 每 paradigm SHALL implement the `Paradigm` protocol defined in
> `training/core/protocols.py`,提供 `make_network` / `make_collector` /
> `make_buffer` / `make_loss` / `make_optimizer` / `step_schedule`。

**本 change 修订版**:
新增详细方法签名要求:
- `step_schedule(state: PipelineState) -> StepPlan`,返回字段
  `collect, n_episodes, train, n_train_batches, batch_size, eval, advance_step`
- `make_episode_policy(cfg, instance_id, deterministic=False) -> EpisodePolicy`
  (新增方法,供 actor + EvalWorker 调用)
- 每方法的 idempotency / thread-safety 要求(`make_*` 必须 stateless,
  reentrant)

## 3. [ADD] SHALL 13 — NetworkProvider 抽象

`NetworkProvider` protocol SHALL be defined in `training/core/protocols.py`
with 4 methods:`forward / update_weights / current_version / close`。
Local 与 Remote 实现 SHALL both honor protocol;cfg `pipeline.inference.placement`
+ `eval.inference.placement` 字段决定 factory 返回哪种实现。

任何 paradigm 的 EpisodePolicy.act() SHALL only call provider.forward,
SHALL NOT access network 内部状态。

## 4. [ADD] SHALL 14 — EpisodeRunner contract 详细

EpisodeRunner SHALL:
- 接受 `EpisodeSpec(scenario_seed, opponent_id, starting_player, max_rounds,
  deterministic, epsilon, record_mcts_stats, record_value_pred)`
- 不持 paradigm 知识 — 通过 `policy: EpisodePolicy` + `provider:
  NetworkProvider` 注入
- 单进程内 reentrant(同 spec 同 seed → 同 episode trace)
- 返回 `EpisodeRecord(transitions, final_reward, length, opponent_id,
  scenario_seed, runtime_metrics)`

Actor + EvalWorker SHALL both use EpisodeRunner via the same code path
(`training/core/actor/episode_runner.py`)。

## 5. [ADD] SHALL 15 — Paradigm spec 引用

Each paradigm SHALL have a dedicated capability spec at
`openspec/specs/paradigm-<name>/spec.md`,covering algorithm-level
invariants:
- `paradigm-az` — AZ MCTS + KL+MSE loss + replay buffer
- `paradigm-dmc` — DMC MC + logit-as-Q + ε-greedy + SHM replay
- `paradigm-cfr` — CFR OS-MCCFR + reservoir + advantage+strategy
- `paradigm-ppo` — PPO GAE + clipped surrogate + rollout
- `paradigm-bc` — BC dataset + CE/KL + no env

Algorithm-specific SHALL(loss formula / network heads / collector type)
SHALL live in paradigm spec,SHALL NOT 在本 spec 重复。

## 6. [ADD] SHALL 16 — config-schema 引用

Cfg schema(R1-R7 placement rules + INHERITED_FIELDS registry)SHALL
live in `openspec/specs/config-schema/spec.md`。本 spec 的 cfg 字段引用
SHALL 通过 path reference,SHALL NOT 重复字段定义。

## 7. [ADD] SHALL 17 — tools-layout 引用

Tools 重组(`tools/run.py` 单入口 + 子目录分类)SHALL by
`openspec/specs/tools-layout/spec.md`。本 spec SHALL 引用 tools-layout
而 SHALL NOT 列具体目录结构。

## 8. [ADD] Subtopic 索引扩展

P0-T9 ship 5 subtopic(protocols / pipeline / network-sharing / eval /
opponent-mix)保留。本 change 不新加 subtopic 文件,因详细内容(driver
loop / SHM 协议 / provider factory)主要由本 change 的
`../../changes/unified-training-pipeline/design/*.md` 承接,archive 后
该 design 作为 historical record 不 merge 进 capability spec subtopic。

P0-T9 5 subtopic 在本 change archive 时各自补充内容:
- `protocols.md` — 加完整 6 protocol 方法签名(本 change
  `design/core-protocols.md` 内容摘要)
- `pipeline.md` — 加 driver loop pseudocode + StepPlan + PipelineState
- `network-sharing.md` — 加 Local / Remote Provider + Weights SHM 协议
- `eval.md` — 加 EpisodeRunner 共享 + EvalWorker contract
- `opponent-mix.md` — 加 OpponentRegistry baselines list(由
  paradigm-agnostic eval 共享)

## 9. [REMOVE] 无

本 change 不删除任何 P0-T9 SHALL。骨架阶段 invariant 全部 stable。

## 10. Cross-references

- 主 spec(P0-T9 骨架)→ [`../../../../specs/training-architecture/spec.md`](../../../../specs/training-architecture/spec.md)
- 6 protocol 详 → [`../../design/core-protocols.md`](../../design/core-protocols.md)
- EpisodeRunner 详 → [`../../design/episode-runner.md`](../../design/episode-runner.md)
- NetworkProvider 详 → [`../../design/network-provider.md`](../../design/network-provider.md)
- Cfg schema → [`../config-schema/spec.md`](../config-schema/spec.md)
- Tools layout → [`../tools-layout/spec.md`](../tools-layout/spec.md)
- 5 paradigm spec → `../paradigm-{az,dmc,cfr,ppo,bc}/spec.md`
