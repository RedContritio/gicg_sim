---
last_updated: 2026-09-14
status: LIVE
schema_version: 0
capability: network-architecture
subtopic: training-pipeline
---

# Training Pipeline — 进程拓扑 + 训练循环 + RPC

> 本 subtopic 锚定 GICG AZ training 的 shipped 进程拓扑与 RPC 契约 —
> inference server(1 proc)+ self-play workers(N proc,MCTS + env)+
> trainer main(buffer + train_step + optional periodic eval)。与
> [`openspec/specs/training-architecture/`](../training-architecture/spec.md)
> 的 paradigm-agnostic skeleton 衔接:本 subtopic 治理 network 视角的
> RPC 字段 + train_step 接 loss / encoder 的细节,training-architecture
> 治理 protocol / driver / opponent mix 顶层骨架。
>
> 上下文:loss 见 [`./loss.md`](./loss.md);encoder/head 见
> [`./encoders.md`](./encoders.md) / [`./heads.md`](./heads.md)。

## 1. Scope

本 subtopic 覆盖:

- serial / async 进程拓扑，以及独立 gauntlet service 的边界
- Self-play worker 一局流程(game_start → 每决策点 mcts_search →
  game_end)
- Trainer main loop(buffer 更新 → train_step → weight push → optional eval)
- `train_step` 内 forward / loss / backward / clip / AdamW
- Inference RPC schema(worker → server)
- Stale weights 容忍

## 2. 进程拓扑

### 2.1 SHALL invariants

1. `pipeline.mode='async'` 的 AZ training SHALL run as 3 进程类型:
   - **inference server**(1 proc):pre-encode static obs + serve `eval`
     RPC + apply weight updates from queue
   - **N self-play workers**:MCTS tree + env step,virtual-loss
     parallel(`par=4`)
   - **trainer main**(1 proc):buffer + train_step + optional eval
     orchestration + launcher
2. Async inference server SHALL run on a single dedicated proc(不与 trainer
   合并)。`pipeline.mode='serial'` 则在 trainer 进程内使用本地 network，
   不启动 worker 或 inference-server subprocess。
3. Core periodic eval SHALL run only when the caller injects an
   `eval_server` and jobs. The current `tools.runs.train` dispatch passes
   `eval_server=None`; standalone gauntlet requests use the independent
   `tools.eval.eval_service` localhost TCP process。
4. Worker count N SHALL be `pipeline.num_actors` driven(default 1);
   workers share inference server but each holds own env + MCTS tree。

### 2.2 拓扑图

```
┌──────────────┐                   ┌─────────────────┐
│ inference    │←──weight push─────│ main process    │
│ server       │                   │ ├─ trainer loop │
│ (1 proc)     │                   │ ├─ buffer       │
└──────┬───────┘                   │ ├─ optional eval│
       │                           │ └─ launcher     │
    eval RPC                       └───┬─────────────┘
       │                               │
┌──────▼─────────────────┐       trajectory
│ N self-play workers    │───────────┘
│  MCTS tree + env step  │
│  IS-UCT + λ 混合       │
│  virtual-loss par=4    │
└────────────────────────┘

   ┌────────────────────────────┐
   │ tools.eval.eval_service  │   ← localhost:9100
   │     (independent proc)     │
   └────────────────────────────┘
```

## 3. Self-play worker 一局流程

### 3.1 SHALL invariants

1. Worker SHALL call `game_start` at episode begin with `static_obs`。
   Async server SHALL respond with the replay-buffer `game_static` fields
   (`hook_ir` / `hook_mask` / `counter_sids` / `active_slot_mask` /
   `char_skill_refs` / `definition_links`) and cache the corresponding
   encoded tensors for later `eval` requests。
2. Each decision point SHALL select the configured MCTS backend: Go,
   parallel Python for an `InferenceClient`, or serial Python otherwise。
   Lambda annealing SHALL run only when `lambda_anneal_games > 0`; the
   checked-in AZ production default uses 0 → 0.8 over 1500 games。
3. Each MCTS rollout SHALL:
   - snapshot env → restore on next rollout
   - determinize(SharedFixedPool 采样对手手牌/牌堆)
   - descend(PUCT + virtual loss)to leaf
   - evaluate a leaf through `evaluator.eval_state(dyn, refs, payments)` →
     server batched forward(no_grad)
   - rollout to terminal for `value_rollout`
   - `value_leaf = λ · value_net + (1-λ) · value_rollout`
   - backup tree
4. `pi_target = visits / sum(visits)` at decision point。Temperature
   sampling decides action → env.step。
5. At game end:`winner → z_target`(+1/-1/0 from actor 视角),每个
   step 按该 step 的 acting player 反填 z。Worker SHALL send `game_end`,
   server clears cache。Worker SHALL put trajectory to main's
   `result_queue`。

### 3.2 流程伪码

```text
worker:
  env = make_env(sample_teams(cfg.char_pool))
  static_obs = env.get_static_obs()
  game_static = rpc("game_start", static_obs=static_obs)
  trajectory = []
  while not env.done:
    λ = compute_annealed_lambda(game_idx)
    pi = mcts_search(env, n_rollouts=200,
                     value_mix_lambda=λ, prior_mix_lambda=λ)
    action = sample(pi, temp)
    trajectory.append((dyn, action, pi))
    env.step(action)
  z = winner_z(env.winner, actor_p=trajectory[0].p)
  rpc("game_end")
  result_queue.put(trajectory, z)
```

## 4. Trainer main loop

### 4.1 SHALL invariants

1. Trainer SHALL drain `result_queue` then push trajectory tuples to
   replay buffer。Buffer SHALL apply priority on discovery events
   (paradigm-specific,详 az/buffer)。
2. Per finished game,trainer SHALL trigger `train_steps_per_game`
   times of `train_step`(default 4)。
3. Async weight publication SHALL follow
   `sync_weights_every_train_steps`; 0 or 1 means every training iteration。
4. When `plan.eval` is true and an injected scheduler is due, the pipeline
   SHALL run its configured jobs and log the returned reports。
5. A standalone gauntlet workflow SHALL start and check
   `tools.eval.eval_service` explicitly; ordinary training with
   `eval_server=None` has no service dependency。

### 4.2 流程伪码

```text
trainer:
  buffer = ReplayBuffer(capacity=50000)
  for game_idx in count():
    traj, z = result_queue.get()
    buffer.push(traj, z)
    for _ in range(cfg.train_steps_per_game):
      train_step(buffer.sample(B=256), model, optimizer)
    if weight_sync_due(state, cfg):
      weight_queue.put(model.state_dict())
    if plan.eval and eval_scheduler.due(state):
      reports = eval_server.run_jobs(eval_scheduler.jobs)
      log_eval(reports)
```

## 5. `train_step`

### 5.1 SHALL invariants

1. `train_step` SHALL sample a batch from replay buffer。Batch fields
   SHALL include raw `hook_types` / `hook_values` / `hook_mask` /
   `counter_sids` / `active_slot_mask`(for training-path hook_encoder
   forward),plus per-step `dyn_obs` / `action_refs` / `action_payments` /
   `pi_target` / `z_target` / optional `counter_target`。
2. `forward_batch` SHALL run hook_encoder **with grad**(详
   [`./encoders.md`](./encoders.md) §2)— SHALL NOT consume cached
   `hook_emb`(违反 = C1v6 hook-gradient bug 复发)。
3. Loss SHALL be paradigm-local `AZLoss(...)` (`training/paradigms/az/
   loss.py`) from [`./loss.md`](./loss.md)。
4. After `total.backward()`,SHALL apply `clip_grad_norm_(max=1.0)`
   then `optimizer.step()`(AdamW)。
5. NaN/Inf guard:任一 loss 分量非有限 SHALL raise immediately,
   SHALL NOT silently skip step。

### 5.2 流程伪码

```text
def train_step(batch, model, optimizer):
  # 1. sample (caller-side, B=256, priority sampling on discovery)
  # 2. forward
  hook_emb = hook_encoder(batch.hook_types, batch.hook_values,
                          batch.hook_mask)  # with grad
  global_state = trunk_forward(hook_emb, batch.counter_sids,
                               batch.active_slot_mask, batch.dyn, ...)
  logits, value, delta_pred = heads_forward(global_state,
                                            batch.action_refs,
                                            batch.action_payments)
  # 3. loss
  total = AZLoss.compute(logits, value, batch.legal_mask, batch.pi_target,
                         batch.z_target, model,
                         l2_coef=cfg.l2_coef, entropy_coef=cfg.entropy_coef,
                         delta_aux_coef=cfg.delta_aux_coef, ...)
  # 4. backward + clip + step
  total.backward()
  clip_grad_norm_(model.parameters(), max=1.0)
  optimizer.step()
  optimizer.zero_grad()
```

## 6. Inference RPC schema

### 6.1 SHALL invariants

1. Worker requests and server acknowledgements SHALL use the worker's
   `multiprocessing.Pipe`; the server does not initiate a worker request。
   Weight push SHALL flow trainer → server through the separate weight queue。
2. RPC SHALL expose 3 kinds:
   - `game_start(static_obs)` → `game_start_ack` with `weight_version` and
     `game_static`;server internally caches pre-encoded static tensors
   - `eval(dyn_obs, refs, payments)` → `eval_ack(prior, value_scalar)`;
     no_grad batched forward,uses cached `hook_emb`
   - `game_end()` → ack;server clears per-game cache
3. Server SHALL drain `weight_update_queue` at idle points and apply
   newest weights atomically(non-blocking;in-flight evals continue
   with prior weights — see §7 stale weights)。

### 6.2 协议表

| RPC | Worker → Server | Server → Worker |
|---|---|---|
| `game_start` | `{kind: "game_start", worker_id, game_id, static_obs}` | `{kind: "game_start_ack", weight_version, game_static}` |
| `eval` | `{kind: "eval", worker_id, game_id, dyn, refs, payments}` | `{kind: "eval_ack", prior, value}` |
| `game_end` | `{kind: "game_end", worker_id, game_id}` | `{kind: "game_end_ack"}` |

## 7. Stale weights 容忍

### 7.1 SHALL invariants

1. Worker SHALL tolerate **stale weights**(typically 10-30 games 落
   后)。This is by design:AZ 收敛不依赖 worker 与 trainer 严格同步
   的 weights — `z` / `pi_mcts` 都是 on-policy to worker 当时 weights。
2. Server weight apply SHALL be atomic — in-flight `eval` SHALL finish
   with prior weights;next `eval` 用新 weights。
3. Worker SHALL NOT block waiting for weight push — `eval` 路径不感
   知 weight version。

### 7.2 设计契约

Stale weights 是 AZ 异步采样架构的 invariant,与 PPO 严格 on-policy
栈(每个 worker 收到的 weights 必须是 trainer 最新)对比。Trainer ↔
server ↔ worker 三角异步可见 `docs/5_history/network_design_history.md::
stale_weights_ok`。

## 8. Cross-reference

- **Paradigm-agnostic skeleton**:
  [`openspec/specs/training-architecture/protocols.md`](../training-architecture/protocols.md) —
  `NetworkProvider` / `Collector` / `Paradigm` protocols(本 subtopic
  RPC 在 P2 unified-training-pipeline 改造时 normalize 为 NetworkProvider
  抽象)
- **Pipeline driver**:
  [`openspec/specs/training-architecture/pipeline.md`](../training-architecture/pipeline.md) —
  顶层 driver loop;本 subtopic 描述 AZ 当前 shipped 拓扑作为参考
- **Eval protocol**:
  [`openspec/specs/training-architecture/eval.md`](../training-architecture/eval.md) —
  core periodic jobs；standalone gauntlet transport 另见
  [`eval-protocol`](../eval-protocol/spec.md)
- **Loss**:[`./loss.md`](./loss.md) — `train_step` 内 `AZLoss`
  调用细节(paradigm-local)
- **Encoders**:[`./encoders.md`](./encoders.md) §2 — hook_encoder
  with-grad / no-grad 路径区分
