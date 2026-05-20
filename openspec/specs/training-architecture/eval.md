---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: training-architecture
subtopic: eval
---

# Eval Protocol — periodic eval + EpisodeRunner 复用

> 本 subtopic 锚定周期 eval 流程与 actor 基建 100% 复用契约。详细
> EvalJob / EvalReport schema、weights snapshot SHM slot 命名、aggregation
> CI95 公式在 P2 `unified-training-pipeline` change 落地。

## 1. Scope

本 subtopic 覆盖:

- PeriodicEvaluator(driver-side 调度器 + trigger_async + poll_results)
- EvalWorker(独立进程,用 EpisodeRunner + LocalNetworkProvider snapshot)
- EvalJob / EvalReport dataclass 骨架
- Weights snapshot 协议(learner 写 SHM,eval workers 各自 update_weights)
- 复用 actor 基建(EpisodeRunner / EpisodePolicy / EnvFactory /
  OpponentRegistry — 100% 共享)

不覆盖:

- 具体 eval scenario 设计(F1-D2 / mcts_pure / historical)— 由
  `runs-registry` capability spec + opponent-mix subtopic 承接
- Gauntlet / tournament 评估流程的指标定义 — `tools/run_gauntlet*.py` 与
  `tools/eval_*` 实现层细节
- 旧 `tools/eval/eval_service.py` 全局单例的协议 — 现状由
  `memory project_eval_service_global` 承接,P2 后纳入本架构

## 2. 总体形态

```
Driver loop                    EvalWorker × M               EvalServer
─────────────                  ──────────────               ───────────
trigger_async(snapshot_id):    pull EvalJob(snapshot_id):   collect M × N
  freeze_weights → SHM           load weights from SHM        episodes
                                 EpisodeRunner.run N eps      aggregate
                                 push EvalReport             write to
                                                             eval_history
poll_results():
  drain eval_history
```

## 3. Core SHALL invariants

**核心 SHALL**:

1. EpisodeRunner SHALL be the shared atomic episode-execution unit
   (SHALL 5 in 主 spec)— actor(train data collection)与 EvalWorker
   (periodic eval)100% 复用同一实现,parameterized by EpisodeSpec
   (scenario_seed / opp / epsilon / deterministic)。

2. Eval inference path SHALL be independent from train inference path
   (SHALL 6 in 主 spec)— eval worker 持有独立 LocalNetworkProvider
   绑定 snapshot 权重,actors 与 eval workers SHALL NOT share inference
   state。

3. PeriodicEvaluator SHALL trigger eval asynchronously — driver loop
   trigger 后 SHALL NOT block,继续训练;eval workers 独立完成后
   push EvalReport,driver 后续 iteration poll 即可。

4. Weights snapshot SHALL use versioned SHM slots(SHALL 9 in 主 spec)—
   `snapshot_<eval-id>` slot per eval job,eval worker 加载 snapshot 后
   slot 可释放;`latest` slot 仅供 actors live 同步,不用于 eval。

5. EvalWorker SHALL set `deterministic=True` + `epsilon=0` in EpisodeSpec
   — 不允许 hidden randomness 干扰指标。RNG 仍由 scenario_seed 决定
   局面,但 policy 输出 deterministic(详 [`./protocols.md`](./protocols.md)
   EpisodePolicy SHALL 3)。

6. EvalWorker SHALL run swap-sides paired episodes per scenario_seed —
   一个 seed 双方各跑一遍(P0 / P1 站,P2 方启动)消除先后手 advantage。
   聚合 WP 用 paired episode pair。

7. EvalReport SHALL include WP point estimate + CI95(via paired
   bootstrap or Wilson score)— 详细公式 P2 落地。Single-seed 数据
   SHALL NOT 作强度判据(per `memory feedback_ppo_multiseed_required`)。

8. Eval scenario SHALL be cfg-driven — opp 来源(F1-Dn / mcts_pure /
   historical ckpt / pool sample)由 cfg `eval.opp` 字段指定,通过
   OpponentRegistry resolve(详 [`./opponent-mix.md`](./opponent-mix.md))。

## 4. PeriodicEvaluator(driver-side)

PeriodicEvaluator 是 driver loop 内部组件,负责调度 eval job。

**SHALL**:

1. PeriodicEvaluator SHALL be triggered per cfg `pipeline.eval_every_steps`
   — 不允许 paradigm-specific 私自加 eval cadence。

2. PeriodicEvaluator SHALL expose `trigger_async(weights_snapshot,
   eval_spec) -> eval_id` 与 `poll_results() -> list[EvalReport]` 接口。

3. PeriodicEvaluator SHALL write EvalReport into PipelineState
   `eval_history` field(详 [`./pipeline.md`](./pipeline.md) §6)—
   ckpt 包含 eval 历史。

## 5. EvalWorker(独立进程)

EvalWorker 是独立 Python 子进程,持有 EpisodeRunner + LocalNetworkProvider
+ snapshot weights。

**SHALL**:

1. EvalWorker SHALL be spawned at pipeline init(async mode)— 数量
   `cfg.eval.n_workers` 决定;serial mode SHALL NOT spawn,eval 在
   driver 进程内同步跑(可选 skip)。

2. EvalWorker SHALL pull EvalJob from queue,load snapshot weights via
   `network_provider.update_weights(snapshot_id)`,run N episodes via
   EpisodeRunner,push EvalReport to result queue。

3. EvalWorker SHALL use the same EpisodePolicy class as actor — 区别仅
   在 EpisodeSpec 配置(deterministic / epsilon)。

## 6. EvalJob / EvalReport schema 骨架

骨架字段(P2 定 types + 完整字段集):

**EvalJob**:
- `eval_id` — unique identifier
- `snapshot_id` — weights snapshot slot key
- `eval_spec` — N episodes / opp / scenario_seed pool / swap_sides

**EvalReport**:
- `eval_id` — matches EvalJob
- `wp_point` — win probability point estimate
- `ci95_low` / `ci95_high` — 95% CI bounds
- `n_episodes` — total episodes(含 swap-sides pairing)
- `per_seed_results` — list of (seed, p1_win, p2_win)
- `metadata` — opp / scenario / weights step / timestamp

**SHALL**:

1. EvalJob / EvalReport SHALL be plain dataclass — JSON-serializable
   for logging / ckpt;paradigm-agnostic。

2. EvalReport SHALL be paradigm-agnostic — 不允许 paradigm-specific 指标
   字段(MCTS visit count distribution / regret matching delta 等)在
   EvalReport 内出现;那些走 paradigm-specific logging 路径。

## 7. Weights snapshot 协议

Async mode 下 weights snapshot 通过 SHM 多 slot 实现 actor / eval 隔离:

**SHALL**:

1. Learner SHALL write weights to two slot 类:
   - `latest` slot — overwritten per K training steps,actors live read
   - `snapshot_<eval-id>` slot — written on eval trigger,immutable until
     eval 完成 + slot 释放

2. Eval worker SHALL load weights from `snapshot_<eval-id>` slot once
   per EvalJob — N episodes 中 weights 不变,保证 eval 内部一致性。

3. SHM slot 数 SHALL be cfg-driven — `cfg.pipeline.eval_snapshot_slots`
   决定 in-flight eval job 上限,过多 trigger 时新 eval SHALL block 而非
   覆盖未完成 slot。

4. Learner SHALL NOT mutate `snapshot_<eval-id>` slot 内容 — actor
   `latest` slot 与 eval `snapshot_*` slot 物理隔离。

## 8. 复用 actor 基建(100% 共享)

Eval 复用 actor 基建的具体清单:

- **EpisodeRunner** — 同一类,EpisodeSpec 参数化(actor 用 `epsilon>0
  / deterministic=False`,eval 用 `epsilon=0 / deterministic=True`)
- **EpisodePolicy** — 同一 paradigm 的同一类,绑定不同 NetworkProvider
- **EnvFactory** — 同一 env 构造逻辑,scenario_seed 决定具体局面
- **OpponentRegistry** — 同一注册表,opp 来源对二者一致(详
  [`./opponent-mix.md`](./opponent-mix.md))

**SHALL**:

1. Actor 与 eval worker SHALL share `training/core/episode.py`
   (EpisodeRunner 实现位置;P2 落地)— 不允许 paradigm 在自身
   `paradigms/<name>/` 内 reimplement episode loop。

2. Eval-only 特性(swap-sides pairing / 聚合 CI95)SHALL be implemented
   in PeriodicEvaluator + EvalWorker,而非 EpisodeRunner 内 — 后者保
   持 paradigm × actor × eval 三向通用。

## 9. Cross-references

- EpisodeRunner / EpisodePolicy / NetworkProvider protocol 详
  [`./protocols.md`](./protocols.md)
- Pipeline state 持有 eval_history 详 [`./pipeline.md`](./pipeline.md)
- OpponentRegistry 与 BaselineSpec 详 [`./opponent-mix.md`](./opponent-mix.md)
- 训练前启动 eval_service / 训练完必跑 gauntlet → `memory
  feedback_eval_service_precheck` + `memory feedback_post_run_gauntlet`
- Eval service 全局单例约定 → `memory project_eval_service_global`
- Multi-seed eval 要求 → `memory feedback_ppo_multiseed_required`
- DMC Phase 3.5 review eval 相关 issues → `docs/5_history/reviews/dmc_review.md`
