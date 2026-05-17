---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: paradigm-cfr
---

# Paradigm CFR — Deep CFR 算法层不变量

> CFR(Deep Counterfactual Regret Minimization)paradigm 的算法层 SHALL
> invariants。架构层(Paradigm protocol / EpisodeRunner / NetworkProvider)
> 继承 [`../training-architecture/spec.md`](../training-architecture/spec.md),
> 本 spec 只列 CFR-specific 约束。

## 1. Purpose

CFR 是 GICG r008 prototype 时代主路径,2026-04-23 之后因 r008 postmortem
(iter 199 < random + 策略震荡)+ AZ 闭环胜出转入 `frozen-research` tier。
本 spec 治理 CFR 算法层不变量,保证 reproducibility 与可对照:

- OS-MCCFR(Outcome-Sampling Monte Carlo CFR)traversal
- Reservoir buffer(advantage + strategy)
- Advantage MSE + Strategy MSE 双 loss
- (Avg_policy, advantage)双 head 网络

## 2. Scope

**In scope**:
- CFR paradigm 实现的 6 protocol(Paradigm / Collector / Buffer /
  LossComputer / EpisodePolicy / NetworkProvider 各自 CFR-specific 实现要求)
- OS-MCCFR traversal 算法契约(player iteration / cf-reach)
- Reservoir sampling 半生命期约定
- Advantage / Strategy 双 reservoir 隔离

**Out of scope**:
- 通用 EpisodeRunner / NetworkProvider → `training-architecture` spec
- CFR run 历史 / r008 postmortem → `docs/paradigms/cfr/` dossier +
  memory `project_r008_postmortem`
- Obs / action 张量编码 → `openspec/specs/rl-obs/`(待落地)

## 3. Core SHALL invariants

### C1. CFR 算法核心

1. **C1.1** CFR paradigm SHALL use OS-MCCFR(Outcome-Sampling MCCFR)for
   traversal,SHALL NOT 用 vanilla CFR(全树遍历不可行)。
2. **C1.2** Traversal SHALL alternate by `traverser_player` ∈ {0, 1};单
   iteration 内一个 player 为 traverser,另一为 opponent(sampling)。
3. **C1.3** Counterfactual reach probability SHALL be tracked along
   traversal path;regret update SHALL be cf-reach-weighted。

### C2. Loss(双 head)

4. **C2.1** CFR loss SHALL = `advantage_mse + strategy_mse`,两 head 独立
   target,SHARED encoder。
5. **C2.2** Advantage target SHALL = clipped regret(positive part 或
   regret-matching+);strategy target SHALL = normalized cumulative strategy。
6. **C2.3** Loss reduction = mean over batch,no policy-strategy weighting
   override(避免 r008 时观察的 loss-quality 脱钩问题,见 memory)。

### C3. Buffer(reservoir 双隔离)

7. **C3.1** CFR SHALL use **two separate reservoirs**:`advantage_reservoir`
   + `strategy_reservoir`,SHALL NOT 合并(advantage 短期、strategy 长期)。
8. **C3.2** Reservoir SHALL be `ReservoirBuffer`(from
   `training/core/buffer/reservoir.py`),uniform sampling with reservoir
   size cap。
9. **C3.3** Reservoir capacity SHALL be cfg-driven,default advantage =
   200_000,strategy = 1_000_000(history-long retention)。

### C4. Network heads

10. **C4.1** CFR network SHALL have 2 heads:`avg_policy_head(logits)` +
    `advantage_head(per-action scalar)`,both fed by shared encoder。
11. **C4.2** Eval / production inference SHALL use `avg_policy_head` only;
    `advantage_head` is training-only。

### C5. Collector

12. **C5.1** CFR Collector SHALL be `TraversalCollector`,parallel by
    Python thread(I/O-bound,Go engine 持锁释放后并行)。
13. **C5.2** `requires_network_in_collect = True`(advantage 估计需 forward)。
14. **C5.3** Both players SHARE the network during traversal(symmetric
    selfplay assumption)。

### C6. Tier

15. **C6.1** CFR tier SHALL be `frozen-research`(per memory
    `project_rl_routes_closure_2026_05_12`)。
16. **C6.2** **r008 ckpt reproducibility 撤销(SUPERSEDED)** —
    > ~~CFR SHALL preserve r008 reproducibility — 本 change 迁移后,同
    > cfg + 同 seed SHALL 复现 r008 ckpt iter 20 / 100 / 199 win rate
    > (±5% noise band)~~ — SUPERSEDED by `core-network-generic-promotion`
    > (archive 2026-05-17)。理由:r008 ckpt schema 在本 change 后 obsolete
    > (同 r009)。User 决策接受所有旧 ckpt 失效;若未来需要复现 r008 行
    > 为,通过 `git checkout pre-core-network-redesign-2026-05-17` + 老代
    > 码 + 老 cfg 走老路径,不在 main branch 维护并行栈。
17. **C6.3** New CFR production run SHALL NOT be launched without OpenSpec
    change unfreezing tier(避免重复 r008 资源浪费)。

18. **C6.4** Test infrastructure SHALL be allowed to inject a smoke-only
    stub buffer into `CFRParadigm.make_buffer` via env flag
    `GICG_CFR_SMOKE_STUB_BUFFER=1`,**仅** for `pytest -m smoke_full`
    coverage of the generic driver(`training/core/pipeline.py`)→ CFR
    paradigm wiring。Production runs SHALL NOT set this flag;
    `_CFRBufferBundle`(C3.1 双 reservoir)remains the only production
    buffer。Stub buffer SHALL NOT be used for CFR training quality
    verification — its sole purpose is exercising driver collect →
    sample → loss → backward → optimizer.step → ckpt save/resume infra
    when CFR `_CFRBufferBundle.sample()` raises 由 generic single-buffer
    driver contract gap。Tier freeze(C6.1 + C6.3)SHALL NOT be
    considered violated by stub activation — smoke test does not launch
    a "new CFR production run",it only validates infra connectivity
    using a minimal valid `Batch` payload(per CFRLoss `REQUIRED_KEYS`)。

### C7. Filesystem layout(扁平化)+ DI + typed_damage skip

> Added by `core-network-generic-promotion` (archived 2026-05-17) —
> `paradigms/cfr/legacy/` 整目录退役,扁平化到 `cfr/` 主目录;CFR
> `CFRStrategyNet` 接 generic `core/network/encoder.py` HookEncoder + DI
> 注入。

19. **C7.1** `paradigms/cfr/` SHALL be 扁平结构:

    ```
    paradigms/cfr/
    ├── __init__.py
    ├── config.py
    ├── network.py
    ├── paradigm.py
    ├── policy.py
    ├── loss.py
    ├── agent.py           ← 自 cfr/legacy/agent.py mv
    ├── strategy_net.py    ← 自 cfr/legacy/network/strategy_net.py mv
    │                        (扁平化,删 network/ 子目录)
    └── (其它 cfr/legacy/ 内容如 trainer 等同步 mv 上)
    ```

    `cfr/legacy/` 整目录 SHALL 不存在(扁平化到 `cfr/` 主目录)。

20. **C7.2** CFRAgent SHALL 改 DI:`super().__init__(cfg,
    hook_encoder=self.net.hook_encoder, device=device)`。CFR
    `CFRStrategyNet` 内部 own 一个 `HookEncoder` instance(来自
    `core/network/encoder`,不是 ActorCritic 的 encoder),DI 注入这个
    instance。Imports SHALL use generic root:`from training.core.network
    import AgentBase` + `from training.core.network.encoder import
    (HookEncoder, CounterEncoder, CardEncoder, CrossAttentionBlock)`(SHALL
    NOT 引用 `training.core.network.legacy.*`,已 git rm)。

21. **C7.3** **typed_damage 跳过**:若 CFR P3-B 未来切到 generic
    `make_actor_critic`,SHALL 用 `use_typed_damage=False` — CFR 当前 not
    consume typed segments(recent_damage / prepare_skill / modifier_log),
    与 `core-network-generic-promotion` design Tradeoffs 决策对齐。

## 4. Cross-references

- 主 training architecture →
  [`../training-architecture/spec.md`](../training-architecture/spec.md)
- CFR paradigm dossier → `docs/paradigms/cfr/`
- r008 postmortem → memory `project_r008_postmortem`
- CFR closure history → memory `project_rl_routes_closure_2026_05_12`
- Originating change(archived)→
  [`../../changes/archive/unified-training-pipeline/`](../../changes/archive/unified-training-pipeline/)
- Smoke stub fix(archived)→
  [`../../changes/archive/cfr-driver-buffer-multihead-fix/`](../../changes/archive/cfr-driver-buffer-multihead-fix/)

## 5. Status

- **Created**:2026-05-16(unified-training-pipeline P6 archive)
- **Revised**:2026-05-17(`core-network-generic-promotion` archive)—
  MODIFY C6.2 r008 ckpt reproducibility SUPERSEDED;+C7 扁平化 layout +
  DI(CFRAgent → CFRStrategyNet.hook_encoder)+ typed_damage skip(CFR
  not consume typed segments)。Imports 切到 `core/network` root,SHALL
  NOT 引用 `core/network/legacy/*`(已 git rm)。
- **Revised**:2026-05-17(`cfr-driver-buffer-multihead-fix` archive)—
  ADD C6.4 smoke-only stub buffer 允许在 frozen-research tier(env flag
  gated),修复 `paradigm-smoke-full-tier` SF-105 CFR skip;production
  CFR(`_CFRBufferBundle`)未动,tier 状态不变。
- **Version**:0(初始)
- **Implementation**:Phase 4 落地;P4 ship 时 SHALL satisfied;
  `core-network-generic-promotion` Phase 2D(2026-05-17)CFR 扁平化 +
  DI + generic encoder 接入完成
- **Tier**:frozen-research — 仅保留 reproducibility,不接受 new run
