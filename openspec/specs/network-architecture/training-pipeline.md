---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: network-architecture
subtopic: training-pipeline
---

# Training Pipeline — 进程拓扑 + 训练循环 + RPC

> 本 subtopic 锚定 GICG AZ training 的 shipped 进程拓扑与 RPC 契约 —
> inference server(1 proc)+ self-play workers(N proc,MCTS + env)+
> trainer main(buffer + train_step + arena/gauntlet)。与
> [`openspec/specs/training-architecture/`](../training-architecture/spec.md)
> 的 paradigm-agnostic skeleton 衔接:本 subtopic 治理 network 视角的
> RPC 字段 + train_step 接 loss / encoder 的细节,training-architecture
> 治理 protocol / driver / opponent mix 顶层骨架。
>
> 上下文:loss 见 [`./loss.md`](./loss.md);encoder/head 见
> [`./encoders.md`](./encoders.md) / [`./heads.md`](./heads.md)。

## 1. Scope

本 subtopic 覆盖:

- 进程拓扑(server + N workers + trainer + eval service)
- Self-play worker 一局流程(game_start → 每决策点 mcts_search →
  game_end)
- Trainer main loop(buffer 更新 → train_step → weight push →
  arena/gauntlet)
- `train_step` 内 forward / loss / backward / clip / AdamW
- Inference RPC schema(worker → server)
- Stale weights 容忍

## 2. 进程拓扑

### 2.1 SHALL invariants

1. Training SHALL run as 3 进程类型:
   - **inference server**(1 proc):pre-encode static obs + serve `eval`
     RPC + apply weight updates from queue
   - **N self-play workers**:MCTS tree + env step,virtual-loss
     parallel(`par=4`)
   - **trainer main**(1 proc):buffer + train_step + arena/gauntlet
     orchestration + launcher
2. Inference server SHALL run on a single dedicated proc(不与 trainer
   合并)— 防 train forward 与 inference forward 互相阻塞。
3. Eval gauntlet SHALL run via independent `tools.eval.eval_service` proc
   (固定 socket `/tmp/gicg_eval.sock`),trainer 通过 socket 发
   gauntlet request,service 跑完结果写回 run 的 `gauntlet_results.jsonl`。
4. Worker count N SHALL be cfg-driven(当前 default `n_workers=4`);
   workers share inference server but each holds own env + MCTS tree。

### 2.2 拓扑图

```
┌──────────────┐                   ┌─────────────────┐
│ inference    │←──weight push─────│ main process    │
│ server       │                   │ ├─ trainer loop │
│ (1 proc)     │                   │ ├─ buffer (50k) │
└──────┬───────┘                   │ ├─ arena        │
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
   │ tools.eval.eval_service  │   ← /tmp/gicg_eval.sock
   │     (independent proc)     │
   └────────────────────────────┘
```

## 3. Self-play worker 一局流程

### 3.1 SHALL invariants

1. Worker SHALL call `game_start` RPC at episode begin,passing
   `static_obs`(reformatted from engine output)。Server SHALL respond
   with **raw tokens** for training path(`hook_types` / `hook_values` /
   `hook_mask` / `counter_sids` / `active_slot_mask`);server SHALL
   internally cache **pre-encoded** `hook_emb` / `hook_mask` /
   `counter_sids` / `active_slot_mask` for subsequent `eval` RPCs。
2. Each decision point SHALL invoke `mcts_search(env, n_rollouts,
   value_mix_lambda, prior_mix_lambda)`。`effective_lambda` SHALL be
   computed via `compute_annealed_lambda(game_idx)`(0 → 0.8 over
   1500 games default)。
3. Each MCTS rollout SHALL:
   - snapshot env → restore on next rollout
   - determinize(SharedFixedPool 采样对手手牌/牌堆)
   - descend(PUCT + virtual loss)to leaf
   - issue **one** `inference_client.eval(dyn, refs, payments)` →
     server batched forward(no_grad)
   - rollout to terminal for `value_rollout`
   - `value_leaf = λ · value_net + (1-λ) · value_rollout`
   - backup tree
4. `pi_target = visits / sum(visits)` at decision point。Temperature
   sampling decides action → env.step。
5. At game end:`winner → z_target`(+1/-1/0 from actor 视角),每个
   step 反填 z(交替翻转视角)。Worker SHALL send `game_end` RPC,
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
3. Every `sync_weights_every_train_steps` train steps(default 10),
   trainer SHALL push current weights to server via weight queue。
4. Trainer SHALL trigger arena every `games_per_arena`(self-play
   diagnostic ladder)+ gauntlet every `games_per_gauntlet`(eval vs
   external baselines)。
5. Trainer SHALL ensure `eval_service` is alive **before** training
   start;missing service SHALL raise(silent skip is a known
   regression — 详 memory `feedback_eval_service_precheck`)。

### 4.2 流程伪码

```text
trainer:
  buffer = ReplayBuffer(capacity=50000)
  for game_idx in count():
    traj, z = result_queue.get()
    buffer.push(traj, z)
    for _ in range(cfg.train_steps_per_game):
      train_step(buffer.sample(B=256), model, optimizer)
    if game_idx % cfg.sync_weights_every == 0:
      weight_queue.put(model.state_dict())
    if game_idx % cfg.games_per_arena == 0:
      run_arena(model)
    if game_idx % cfg.games_per_gauntlet == 0:
      run_gauntlet(model)
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

1. RPC SHALL be **one-way** worker → server query;server SHALL NOT
   call worker back。Weight push SHALL flow trainer → server(单向),
   不与 worker eval 路径共享 channel。
2. RPC SHALL expose 3 kinds:
   - `game_start(static_obs)` → returns raw tokens `(hook_types,
     hook_values, hook_mask, counter_sids, active_slot_mask)`;server
     internally caches pre-encoded `hook_emb`
   - `eval(dyn_obs, refs, payments)` → returns `(prior, value_scalar)`;
     no_grad batched forward,uses cached `hook_emb`
   - `game_end()` → ack;server clears per-game cache
3. Server SHALL drain `weight_update_queue` at idle points and apply
   newest weights atomically(non-blocking;in-flight evals continue
   with prior weights — see §7 stale weights)。

### 6.2 协议表

| RPC | Worker → Server | Server → Worker |
|---|---|---|
| `game_start` | `{kind: "game_start", static_obs: ...}` | `{hook_types, hook_values, hook_mask, counter_sids, active_slot_mask}` |
| `eval` | `{kind: "eval", dyn_obs, action_refs, action_payments}` | `{prior, value}` |
| `game_end` | `{kind: "game_end"}` | `{ack: true}` |

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
  `tools.eval.eval_service` 接口与本 subtopic gauntlet trigger 衔接
- **Loss**:[`./loss.md`](./loss.md) — `train_step` 内 `AZLoss`
  调用细节(paradigm-local)
- **Encoders**:[`./encoders.md`](./encoders.md) §2 — hook_encoder
  with-grad / no-grad 路径区分
