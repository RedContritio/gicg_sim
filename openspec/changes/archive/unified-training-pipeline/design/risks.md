---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../design.md
---

# Risks — 失败模式 + 回滚预案 + smoke 验证策略

> 列出本 change 实施期间的潜在失败 + mitigation。每 risk 标 severity + 触
> 发条件 + 检测方式 + 回滚 / 缓解策略。

## 1. R-A — DMC async migration regression(High)

**Risk**:P3 把 `training/dmc/_actor.py` 抽进 `training/core/actor/actor_process.py`
+ 引入 NetworkProvider 抽象层后,DMC smoke 性能或正确性 regression。

**Trigger**:
- Episode/s 下降 > 20%(per actor)
- F1-D2 win rate 下降 > 0.05(vs P3 前 baseline)
- weights_version_lag spike > 1000 step

**Detection**:P3-T7 跑 DMC smoke vs P2 ship 时的 baseline ckpt
(`artifacts/202605..._s_dmc_baseline/`),比较:
- episodes/s(per actor)
- 50k transitions 训完后的 F1-D2 win rate
- loss curve 拟合

**Mitigation**:
- P3 期间 `training/dmc/` 原 stack 保留(P5 才物理 mv 删除)
- 失败 → revert P3 commit + 重新分析瓶颈
- 若 NetworkProvider 抽象有 IPC overhead → fallback 用 direct model ref
  (LocalNetworkProvider 内联模式)

## 2. R-B — Cfg schema break 旧 cfg(Medium)

**Risk**:R1-R7 placement schema 引入后,旧 cfg(`configs/dmc/v_phase2_*.toml`)
没写 `[pipeline.inference]` 段 → load 失败。

**Trigger**:任意旧 cfg `python -m tools.run <old.toml>` raise ValidationError。

**Detection**:P3-T6 跑全 cfg validation suite:
```
for f in configs/**/*.toml: python -m tools.run --dry-run "$f"
```

**Mitigation**:
- 提供 cfg migrator `tools/_meta/migrate_cfg.py`:旧 cfg → 新 cfg(补默
  认 placement / inference 字段)
- migrator 在 P3 ship 时同步 + 跑过所有 `configs/**/*.toml`
- CI 加 cfg-validation step 防止 regression

## 3. R-C — Stale SHM weights 导致 collapse(Medium)

**Risk**:Async mode 下 actors 用过期 weights 采样,若 lag > N → 训练
distribution shift,policy collapse。

**Trigger**:
- weights_version_lag p99 > 1000 step
- value_pred 与 actual reward divergence
- F1-D2 win rate 单调下降 > 50 step

**Detection**:metrics.jsonl 字段 `actor.{id}.weights_version` vs
`learner.weights_version`,计算 lag。

**Mitigation**:
- 设 `lag_threshold` cfg 字段(默认 500 step),触发 → warn + 减小
  N actor(自动 down-scale)
- 提供 forced sync mode(actor 等 lag 归零再 collect)— 慢但稳

## 4. R-D — Inference server 死锁(Medium)

**Risk**:Remote mode K inference server,actor 请求 timeout 后 retry,server
端 batch 累积 deadlock。

**Trigger**:
- Inference batch p99 > 100ms(目标 < 5ms)
- Actor reports `provider.forward timeout`
- Server CPU 100% but batch_size_p50 = 1

**Detection**:metrics.jsonl `inference.{id}.timeout_count` + 心跳 missing。

**Mitigation**:
- batch_timeout_ms 默认 2ms,超时 fire 不等满 batch
- Server crash → 父进程 restart + actors auto-reconnect
- 最坏 fallback:placement=local(单 actor per process,no batching)

## 5. R-E — Paradigm cfg schema 间冲突(Low)

**Risk**:5 paradigm 的 `[paradigm]` 段字段名空间相同(`epsilon` / `lr` /
`buffer_cap`),manual cfg 写错 paradigm 时校验失败但错误信息不清晰。

**Trigger**:用户写 DMC cfg 但 paradigm=ppo → ParadigmConfig validation 报
"unknown field epsilon"。

**Mitigation**:
- Validation 错误信息 SHALL include `expected paradigm=<X>, got fields={...}`
- 文档 + cfg template 标 paradigm 字段表(每 paradigm capability spec 内)

## 6. R-F — BC dataset 抽取破坏 r009 production(High)

**Risk**:`training/az/bc_*.py` 删除 + 抽进 `paradigms/bc/` 时,r009
production fallback ckpt 加载 fail(state_dict key 不匹配)。

**Trigger**:`python -m tools.replay --ckpt artifacts/.../r009.ckpt` 失败。

**Detection**:P4-T2 ship 前必跑 r009 ckpt smoke(替换前 / 替换后 valid acc 对比)。

**Mitigation**:
- BC 抽出时保留 state_dict key naming(`policy.0.weight` 等)
- ckpt migrator 字段 rename map
- P4-T2 ship 时 r009 acc 必须重现 = baseline ± 0.005

## 7. R-G — PPO 迁移后 reproducibility break(Medium)

**Risk**:`training/ppo/` 迁 `paradigms/ppo/` 后,2026-04 r004 PPO ckpt
不可加载或 cfg 不兼容,失去 reproducibility(D2 决策核心动机失效)。

**Trigger**:`python -m tools.run configs/ppo/archive_repro.toml` 不能重现
2026-04 r004 metrics。

**Mitigation**:
- 迁移时保留 cfg snapshot(`configs/ppo/archive_repro.toml` 标 historical)
- PPO smoke = 重现 2026-04 r004 100 step metrics(允许 ±5% 偏差)
- 失败 → 暂停 PPO 迁移,docs/paradigms/ppo/ 标 "frozen, no migration"

## 8. R-H — `framework/` 删除后 hidden import 残留(Low)

**Risk**:某些 utility script(`tools/`)还 import `training.framework`,删
除时漏掉。

**Trigger**:`grep -r "from training.framework" .` 非空。

**Mitigation**:
- P5-T6 强制 grep + 全 pytest pass(覆盖 utility)
- import-linter 配置(将 `training.framework` 标 forbidden)

## 9. R-I — EpisodeRunner 共享导致 actor 与 eval drift(Medium)

**Risk**:EpisodeRunner shared by actor + eval,但 eval scenarios 期望
独立 RNG state;若 shared opp_registry 副作用导致 actor 状态泄漏到 eval。

**Mitigation**:
- OpponentRegistry SHALL be stateless(只持 factory closure)
- EnvFactory SHALL fork-safe(每 worker 独立 spawn)
- 测试:eval 跑 100 episode → actor 跑 → eval 跑 100 episode,两次 eval
  必 bit-exact

## 10. Smoke 验证策略(每 phase ship 前)

| Phase | Smoke 内容 | 通过门槛 |
|---|---|---|
| P3 | DMC 100k transitions on new pipeline | F1-D2 win rate ≥ baseline - 0.02 |
| P3.5 | F1-Dn Go 化输出对比 | bit-exact match Py impl |
| P4 | AZ + BC + PPO + CFR 各跑 smoke | 各自历史 baseline ± tolerance |
| P5 | full pytest + 全 cfg validate + r009 ckpt acc | 0 regression |
| P6 | Archive workflow dry-run | spec delta merge 成功 |

## 11. Cross-references

- DMC review 41 critique(部分 risk 来自此)→
  `docs/5_history/reviews/dmc_review.md`
- 当前 weights sync 实现 → `training/framework/inference/weights_*.py`
- Cfg validation 历史 silent fail → memory project_v_phase2_eval_schema_gaps
- BC ckpt 兼容性历史 → memory project_typed_obs_ckpt_break
