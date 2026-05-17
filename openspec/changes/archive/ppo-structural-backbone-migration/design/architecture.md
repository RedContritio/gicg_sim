---
last_updated: 2026-05-17
status: ARCHIVED
schema_version: 0
change_id: ppo-structural-backbone-migration
parent: ../design.md
---

# Architecture detail — ppo-structural-backbone-migration

> 详细 architecture + tradeoff 推导,从 active `design.md` 拆出,保留作
> 历史。Archive-time retrospective summary 见 [`../design.md`](../design.md)。

## 1. Architecture

### 1.1 Component map(target)

```
training/paradigms/ppo/
├── network.py          # PPONetwork — thin nn.Module wrapper(generic backbone)
├── agent.py            # NEW — PPOAgent(AgentBase) per-game cache + eval_state
├── _rollout.py         # rewrite — game_start cache + per-step eval_state
├── collector.py        # rewrite — structured transition payload
├── _async.py           # adjust — drain path 适配新 payload schema
├── loss.py             # adjust — forward_batch(collated) 取代 forward(obs)
├── policy.py           # adjust — Categorical 走 legal logits 而非 max_actions slot
├── paradigm.py         # rewrite — 删 _probe_obs_size,改 structural cfg 派生
└── config.py           # adjust — PPOAgentShapeCfg 字段重设计
```

### 1.2 PPOAgent 接口(对齐 DmcAgent)

```python
# training/paradigms/ppo/agent.py(新)
class PPOAgent(AgentBase):
    """ActorCritic-backed PPO agent — generic backbone + AgentBase per-game cache."""

    PPO_HEAD_KINDS = frozenset({'policy', 'value'})

    def __init__(self, cfg: AgentConfig, device: str = 'cpu') -> None:
        net = make_actor_critic(cfg, head_kinds=self.PPO_HEAD_KINDS, use_typed_damage=True).to(device)
        super().__init__(cfg, hook_encoder=net.hook_encoder, device=device)
        self.net = net

    def act(self, env, rng, *, deterministic: bool = False) -> tuple[int, dict]:
        """Sample one action.返回 (action_idx, {'log_prob','value','n_legal'})。
        deterministic=True → argmax;False → Categorical sample。
        log_prob 是 legal-softmax 下选中 action 的 log;value 是 V(s) scalar。"""
        ...

    def forward_batch(self, collated: dict) -> tuple[torch.Tensor, torch.Tensor]:
        """Batched forward(对齐 BC / DMC / AZ);返回 (policy_logits, value)。
        policy_logits shape (B, max_actions);value shape (B,)。"""
        ...
```

### 1.3 Transition payload schema(structured)

Buffer 内 `Transition.payload` 改为:

```python
{
    # Static reference — encoded once per game,buffer 内多 transition 复用。
    # 索引 game_id → AgentBase.encode_static 后 numpy snapshot。
    'static_idx': int,

    # Per-step dynamic obs(numpy float32 vector,len = env.obs_size — 但不
    # 直接喂 MLP,而是 forward_batch 内 _parse_dynamic_single 切 typed segments)。
    'dyn_obs': np.ndarray,

    # Action refs / payments — env.get_action_refs / get_legal_action_payments
    # output,padded to max_actions,与 AZ / DMC 同。
    'refs': np.ndarray,           # (max_actions, 3) int64
    'payments': np.ndarray,        # (max_actions, DICE_COLOR_COUNT) float32
    'n_legal': int,                # 当前 step 合法 action 数(loss 做 legal slice)

    # PPO-specific:
    'log_prob': float,             # old-policy log_prob(legal softmax)
    'value': float,                # V(s) prediction at action 时
    'advantage': float,            # GAE 算后 fill(per-trajectory pass)
    'return': float,               # advantage + value
}
```

Collector 维护 `static_snapshots: list[dict]`(per-game once),`static_idx`
索引这个 list;loss 时 collate_batch 把 batch 各 transition 的 static
snapshot **重新塞** 到 collated dict(因为 buffer 内 transition 物理
duplicates,collate 时按 index 取)。

### 1.4 Loss path(structural)

```python
# loss.py rewrite
def compute(self, network: Any, batch: Batch) -> LossResult:
    d = batch.data
    required = ('collated', 'action', 'old_log_prob', 'advantage', 'return')
    # 'collated' = structural batch dict(含 counter_values / hook_types / typed_damage 等)
    # 'action' = chosen action idx per batch element
    # 'old_log_prob' / 'advantage' / 'return' = unchanged

    policy_logits, value = network.forward_batch(d['collated'])
    # 走 PPOAgent.masked_policy(legal_mask) — Categorical on legal-softmax
    legal_mask = d['collated']['legal_mask']
    dist = self._masked_dist(policy_logits, legal_mask)
    new_lp = dist.log_prob(d['action'])
    entropy = dist.entropy().mean()
    ratio = torch.exp(new_lp - d['old_log_prob'])
    # ... 余下 clip + value MSE + entropy bonus 数学不变 ...
```

### 1.5 Rollout simplification

```python
# _rollout.py(简化版,删 ~80 LOC fixed-opponent inline,改走 agent)
def run_training_game(agent, scen, pcfg, rng, device, p1_opponent):
    env = GicgEnv(...)
    agent.game_start(env.static_obs)  # encode + cache once

    is_self_play = p1_opponent is None
    bufs = [TrajBuf() for _ in range(2)]
    for _ in range(pcfg.rollout.max_steps_per_game):
        if env.done: break
        kinds, _ = env.get_legal_actions()
        if not kinds: break
        actor = env.acting_player
        use_net = is_self_play or actor == 0

        if use_net:
            dyn_obs = env._get_obs()
            refs = env.get_action_refs()
            payments = env.get_legal_action_payments()
            a, meta = agent.act(env, rng, deterministic=False)
            bufs[actor].push(dyn_obs, refs, payments, len(kinds), a, meta)
        else:
            a = p1_opponent(env)
        _, reward, done, _ = env.step(a)
        if use_net:
            bufs[actor].set_last_reward(float(reward))
        if done: break

    for b in bufs: b.set_last_done()
    return ([bufs[0]] if not is_self_play else bufs), {...}
```

## 2. Tradeoffs

### 2.1 PPOAgent inherits AgentBase vs custom cache(SELECTED: AgentBase)

**Pros**: 与 AZ/DMC/BC 100% 对称;encode_static / parse_dynamic_single 复用;
hook_encoder DI 已经在 base;5 paradigm spec invariant 一致。
**Cons**: AgentBase 假设 self.net 是 nn.Module — PPOAgent.net 是 ActorCritic
满足;AgentBase save/load 是 self-describing schema(D-203 已 ship),PPO 自动
受益。
**Verdict**: SELECTED — 对称 + DRY > 自维护 cache。

### 2.2 log_prob_old 何时算(SELECTED: 在 agent.act 内同步算 + 返回)

**Pros**: 一次 forward 同时算 logits + log_prob,无 redundant forward;
collector 直接存 meta['log_prob'];loss 时不需重算 old log_prob。
**Cons**: agent.act 接口 surface 略宽(返回 dict 而非 int);需要 careful 在
deterministic path 也产出 valid log_prob(argmax 选择的 action 的 log_softmax)。
**Verdict**: SELECTED — explicit 一次产出。

### 2.3 transition payload 存 cached_static_hash vs static_idx(SELECTED: static_idx)

**Pros (hash)**: 完全独立索引,collator 端可校验;Cons: hash 比对 overhead +
collator 需 dict 查找。
**Pros (idx)**: list-index 直接 O(1);buffer 内 game-level coherence 自然(PPO
on-policy 一 iter clear,无跨 iter 漂移);Cons: refactor 需要约定 collector
端 list 顺序。
**Verdict**: SELECTED idx — PPO 是 on-policy buffer 每 iter clear,无 lifecycle
issues。

### 2.4 PPOAgentShapeCfg 字段重设计(SELECTED: 与其它 AgentShapeCfg 字段对齐)

**Before**: `d_model + n_hidden_layers + max_actions`(3 字段,flat MLP 专用)。
**After**: `n_counter_slots + n_hooks + max_tokens_per_hook + max_actions +
d_model + n_cross_layers + dropout`(对齐 AgentShapeCfg)。
**Pros**: 与 BC/AZ/DMC AgentShapeCfg 字段一致 → 未来 ObsShape unification
(D-201 follow-up)1 步切完;PPO cfg TOML 更标准化。
**Cons**: 老 PPO cfg(s021-s054)字段名不兼容 — 但 per D-302 已 accept;新 PPO
production run 也不预期(P6 frozen)。
**Verdict**: SELECTED — 字段层对齐是 cheap follow-up step 的前置。

### 2.5 typed_damage on/off(SELECTED: on)

**Pros**: 与 AZ/BC/DMC 7-pool 一致;ckpt schema 同源 → 未来 cross-paradigm
warm-start 可能;PPO 也受益于 typed damage segments(原 _PPOMLPTrunk 完全忽略
这部分 obs)。
**Cons**: 6→7 pool 增加 ~d_model 参数 + ~10% forward cost;但 PPO frozen,
production train 几乎不跑,cost 可忽略。
**Verdict**: SELECTED on — 一致性 > marginal cost。
