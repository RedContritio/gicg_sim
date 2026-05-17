---
last_updated: 2026-05-17
status: ARCHIVED
schema_version: 0
change_id: ppo-structural-backbone-migration
parent: ../design.md
---

# Migrations + Risks + Verification — ppo-structural-backbone-migration

> 详细 migration plan + risks + verification matrix + LOC estimate,从
> active `design.md` 拆出,保留作历史。Archive-time retrospective summary
> 见 [`../design.md`](../design.md)。

## 3. Migration plan

### 3.1 Phase 顺序

1. **T0** propose(本文件 + proposal + tasks + 3 spec deltas)
2. **T1** rewrite `config.py` — PPOAgentShapeCfg 字段对齐
3. **T2** add `agent.py` — PPOAgent(AgentBase) + act + forward_batch
4. **T3** rewrite `network.py` — PPONetwork thin wrapper
5. **T4** rewrite `_rollout.py` — game_start cache + per-step eval
6. **T5** rewrite `collector.py` — structured transition payload + collate
7. **T6** adjust `loss.py` — forward_batch 取代 forward(obs)
8. **T7** adjust `policy.py` — provider.forward 接口对齐(EpisodePolicy path)
9. **T8** adjust `paradigm.py` — 删 _probe_obs_size + AgentConfig 派生
10. **T9** adjust `_async.py` — drain 路径 + Transition payload schema 适配
11. **T10** rewrite 3 test files(test_ppo_paradigm.py / test_ppo_smoke.py /
    test_ppo_collector_smoke.py)
12. **T11** pytest sweep verify(全 train/tools 走过,无 regression)
13. **T12** commits — propose / impl(可拆 2-4 commit,按 component 边界)

### 3.2 Test rewrite 策略

| Test | Before | After |
|---|---|---|
| `test_ppo_paradigm.py` | 大部分用 `PPONetwork(obs_size=..., max_actions=..., d_model=..., n_hidden_layers=...)` 直接构造 + flat obs batch | 用 AgentConfig + PPOAgent;batch.data 用 structural dict |
| `test_ppo_smoke.py` | bypass make_network + 直接 flat MLP;synthetic flat obs batch | 用 paradigm.make_network(cfg);batch 走 `make_structural_batch_dict` |
| `test_ppo_collector_smoke.py` | 走 real GicgEnv;探针 obs_size | 删 obs_size 探针;走 cfg + AgentConfig;collector 输出 structural payload |

### 3.3 Async collector adaptation

`_async.py` 内 `_PPOActorProvider.forward` 接口与 LocalNetworkProvider 现签名
是 `(obs, mask) → (logits, value)` 或 dict。新 PPOAgent.act 在 actor 进程内
直接调 self.net.forward (走 ActorCritic structural pipeline)— actor 端无需
provider 抽象的细化,简化即可。

但 W3b-PPO frozen tier 接通 actor 实际是 future work(per D-302 描述 — frozen
tier 不接 production train),smoke 测试 mock 充分,本 change 不深入重写 mp
分支,只确保 Transition payload schema 与 sync 路径一致。

## 4. Risks

### 4.1 Smoke wall budget

**Risk**: structural backbone 比 flat MLP 慢 3-5×;PPO smoke 走 generic
ActorCritic + 7-pool forward,可能超 60s。

**Mitigation**:
- Cfg 用 tiny shape(d_model=16, n_hooks=4, max_tokens_per_hook=8,
  max_actions=6, n_counter_slots=128)— 与 BC/DMC smoke 同
- Smoke 只跑 1 train step(per smoke_template.run_symmetric_smoke);
  不跑 full e2e episode
- 实测 BC/DMC smoke 各 ~3-10s on Mac;PPO 同 size 应同档

### 4.2 Loss numerical regression

**Risk**: 新 forward path(structural)与老 path(flat MLP)数值不同;现有
loss 数学测试 `test_ppo_loss_clipped_surrogate_*` 用 PPONetwork(obs_size=4,...)
直接构造,改 structural 后需要重写 fixture。

**Mitigation**:
- Loss 数学公式不变(clip + min(surr1,surr2) + value MSE + entropy)— 重写
  fixture 而非 reformulate
- 加 `test_ppo_clip_frac_with_structural_backbone` test:确认 clip_frac
  computation 仍正确(独立于 backbone)

### 4.3 AsyncCollector schema break

**Risk**: `_async.py` 内 `_PPOActorProvider.forward(obs, mask)` 与新 agent.act
接口冲突;若改 actor 路径,mp 部分需要 careful schema 同步。

**Mitigation**:
- W3b-PPO 是 frozen tier(per D-302 — 不预期 production)— smoke 测的是
  protocol surface,不是 production correctness
- 现有 `test_ppo_async.py` 走 mock 完全充分;本 change 修 mock 期望以匹配
  新 schema 而非实际 mp run
- 必要时,_async.py drain 路径里直接调 PPOAgent.forward_batch 而非走 actor
  provider(简化)

### 4.4 PPOEpisodePolicy provider 接口 mismatch

**Risk**: 现 PPOEpisodePolicy.act 接 `provider.forward(obs, mask) → (logits, value)`
是 flat MLP 假设;新 backbone 下,该 path 怎么调?

**Mitigation**:
- PPOEpisodePolicy 在 serial collector path 中 **不直接被调** — _rollout 里
  直接 net.forward,policy 是 mp/async path 才走的
- 改 PPOEpisodePolicy.act 期望 `provider.forward(dyn_obs, refs, payments,
  static_cache)` 返回 dict {logits, value};legacy `(obs, mask)` 签名 deprecate
- 现 `test_ppo_episode_policy_*` 测试用 _StubProvider 走 numpy logits 直接
  inject;改成 stub 期望 structural input → 测试本身仍 fast

### 4.5 PPO ckpt 不兼容

**Risk**: 现有 PPO ckpt(s021-s054 时代)load 失败,因为 PPONetwork 内部
state_dict 形状全变。

**Mitigation**:
- 已 accept per D-302;memory `project_v_phase2_eval_schema_gaps` 已记
  PPO ablation 复现失效
- AgentBase.load 抛 CkptSchemaError(D-203 已 ship)— PPO 老 ckpt 走旧
  schema 也已 unload
- 不实施 backward-compat;新 PPO ckpt 走 self-describing schema 与其它
  paradigm 同源

## 5. Rollback

- 4-5 commits 实施(propose / config+agent+network / rollout+collector+loss
  / policy+paradigm+async / tests);任一 commit 失败可 `git revert <hash>` 还原
- propose commit 与 impl commit 分开;若 impl 失败可保留 propose,impl
  分多次重试
- Spec delta 在 specs/ 子目录,archive 前不影响 live spec
- 无 prod run 触发(PPO frozen),无 ckpt 升级压力,rollback 风险最低

## 6. Verification matrix

| Aspect | Method | Pass criterion |
|---|---|---|
| Structural backbone integration | `grep "_PPOMLPTrunk\|flat MLP" training/paradigms/ppo/` | 0 hit in production code |
| make_actor_critic call | `grep "make_actor_critic" training/paradigms/ppo/` | ≥ 1 hit(PPOAgent.__init__) |
| AgentBase inheritance | `grep "class PPOAgent.*AgentBase" training/paradigms/ppo/` | 1 hit |
| Smoke pass | `pytest training/tests/test_ppo_smoke.py -v` | green |
| Paradigm tests pass | `pytest training/tests/test_ppo_paradigm.py training/tests/test_ppo_collector_smoke.py training/tests/test_ppo_async.py -v` | green |
| Cross-paradigm zero regression | full sweep per CLAUDE.md test command | no new failures vs pre-change baseline |
| Spec invariant 一致 | `tools/_meta/check_openspec_indices.py --staged` | green |

## 7. LOC estimate

| File | Change | LOC delta |
|---|---|---|
| `config.py` | shape fields rewrite | -10 / +30 |
| `agent.py` | NEW | 0 / +130 |
| `network.py` | rewrite | -50 / +50 |
| `_rollout.py` | rewrite | -180 / +120 |
| `collector.py` | rewrite | -100 / +130 |
| `loss.py` | adjust | -10 / +30 |
| `policy.py` | adjust | -20 / +20 |
| `paradigm.py` | rewrite | -60 / +40 |
| `_async.py` | adjust drain | -20 / +30 |
| `test_ppo_paradigm.py` | rewrite | -200 / +250 |
| `test_ppo_smoke.py` | rewrite | -80 / +90 |
| `test_ppo_collector_smoke.py` | rewrite | -130 / +130 |
| `test_ppo_async.py` | adjust mock expectations | -30 / +30 |
| Spec deltas + change docs | new | 0 / +500 |
| **Total** | | **-890 / +1580**(≈ net +690) |
