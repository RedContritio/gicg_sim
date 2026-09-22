---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: training-architecture
subtopic: paradigm-onboarding
parent: ./spec.md
---

# Paradigm Onboarding SOP — 如何接入第 6 paradigm

> 本 subtopic 总结 unified-training-pipeline(P0-P6 archive)中 5 paradigm
> (AZ / PPO / DMC / BC / CFR)的接入经验,锚定接入第 6 paradigm 时的
> contract surface / filesystem layout / integration point / 测试范围 /
> 历史教训 / anti-pattern。
>
> 适用范围:接入新 paradigm(MuZero / IMPALA / R2D2 / 等),或 fork 现
> 有 paradigm 做大改造(超出 ablation 范围)。**不**适用范围:cfg
> tweak、ablation、修 bug — 那些走各 paradigm spec / dossier。

## 1. Purpose

### 1.1 何时需要接入新 paradigm vs 替代方案

接入新 paradigm = 在 `training/paradigms/<name>/` 新建目录 + 注册 +
spec。门槛高(~700-3000 LOC adapter + ~15-17 SHALL spec)。

| 触发条件                                | 推荐路径                                 |
|----------------------------------------|-----------------------------------------|
| 新算法(loss / collector / buffer 全变)   | 接入新 paradigm                          |
| 同算法换 hyperparam(epsilon / lr / batch) | cfg ablation(同 paradigm,不接入新)      |
| 同算法换 network(encoder / heads)         | paradigm cfg 加字段(本 spec network-sharing.md) |
| 同算法换 opp pool                       | cfg `eval.opp` 改(opponent-mix.md)      |
| 已有 paradigm fork 做大改造(loss 重写)     | 视改造规模 — 重大 fork 建议新 paradigm     |

第 6 paradigm 出现前 SHALL 通过 OpenSpec change 提案(本 spec invariants
SHALL 17 + protocols.md §2 SHALL 4)。

### 1.2 接入第 6 paradigm 的 5 步骤

1. **OpenSpec change 提案** — `paradigm-<name>-onboarding/` 写 proposal +
   design + tasks + spec delta
2. **Paradigm spec 起草** — `openspec/specs/paradigm-<name>/spec.md`(~15
   SHALL,参考 5 个现成 spec)
3. **Code adapter 实现** — `training/paradigms/<name>/{config,paradigm,
   collector,policy,loss,network}.py`(~700-3000 LOC)
4. **Tests + smoke** — `test_<name>_paradigm.py`(spec compliance)+
   `test_<name>_smoke.py`(`@pytest.mark.smoke` merge gate,详
   [`./smoke-contract.md`](./smoke-contract.md))
5. **Integration** — registry / cfg presets / tools dispatch / dossier

## 2. Contract surface — 6 protocol

新 paradigm SHALL satisfy [`./protocols.md`](./protocols.md) 6 protocol。
本节是 contract surface checklist,所有方法签名以
`training/core/protocols.py` 为准(本节描述与该文件 lockstep)。

### 2.1 Paradigm protocol

入口 class,driver loop 仅通过本 interface 调用。

| 必有属性 / 方法                          | 类型 / 用途                          |
|-----------------------------------------|-------------------------------------|
| `name: str`                              | 全局唯一 enum,`meta.paradigm` 字段值 |
| `requires_network_in_collect: bool`      | True = collect 期间需要 forward(AZ / DMC / CFR / PPO);False = 不需要(BC) |
| `make_network(cfg) -> nn.Module`         | 构造 paradigm-specific 网络         |
| `make_collector(cfg, env_factory, network, opp_pool) -> Collector` | 构造采集器 |
| `make_buffer(cfg) -> Buffer`             | 构造样本存储                         |
| `make_loss(cfg) -> LossComputer`         | 构造 loss 计算                       |
| `make_optimizer(cfg, network) -> Optimizer` | 构造 optimizer                    |
| `make_episode_policy(cfg, instance_id, deterministic) -> EpisodePolicy` | actor + eval 共享 |
| `step_schedule(state, cfg) -> StepPlan`  | 返回 collect/train/eval 调度       |

Base class / Protocol:`training.core.protocols.Paradigm`(`@runtime_checkable`)。
注册位置:`training/paradigms/__init__.py` `PARADIGMS` dict,lazy import。

### 2.2 Collector protocol

数据来源:env episode rollout(AZ / DMC / PPO)、replay traversal(CFR)、
静态 dataset(BC)。

| 必有属性 / 方法                          | 用途                                |
|-----------------------------------------|-------------------------------------|
| `requires_network_in_collect: bool`     | 与 Paradigm 同字段(double-source 容错) |
| `collect(n_units, provider) -> CollectorOutput` | 单轮采集                |
| `close() -> None`                       | 资源释放(MultiProcessActorCollector 退出 actor) |
| `state_dict() / load_state_dict(sd)`    | ckpt support(actor 进度 / RNG state) |

Base:`training.core.protocols.Collector`。Async paradigm 通常配 3 个 variant:
`<X>SerialCollector` / `<X>MultiProcessCollector` / `<X>AsyncCollector`(DMC
模式)。

### 2.3 Buffer protocol

| 必有属性 / 方法                          | 用途                                |
|-----------------------------------------|-------------------------------------|
| `capacity: int`                          | 字段,driver 用于 buffer 占用监控    |
| `push(batch: CollectorOutput) -> None`   | 入库                                |
| `sample(batch_size, rng) -> Batch`       | 采样                                |
| `clear() -> None`                        | on-policy paradigm(PPO)每 iter 调用 |
| `__len__()` / `state_dict` / `load_state_dict` | ckpt + 占用查询           |

Base:`training.core.protocols.Buffer`。常见 family:`ReplayBuffer`(AZ)/
`SHMRingBuffer`(DMC)/ `ReservoirBuffer`(CFR)/ `RolloutBuffer`(PPO)/
`DatasetBuffer`(BC)。

### 2.4 LossComputer protocol

| 必有方法                                  | 用途                                |
|-----------------------------------------|-------------------------------------|
| `compute(network, batch: Batch) -> LossResult` | 返回 `LossResult(loss, breakdown, grad_metrics)` |

Base:`training.core.protocols.LossComputer`。SHALL be pure(无 mutable
state),跨 batch 独立。Loss 公式 SHALL written into paradigm spec
algorithmic invariants(参考 paradigm-az §A2 / paradigm-dmc §D2 etc.)。

### 2.5 EpisodePolicy protocol

| 必有方法                                  | 用途                                |
|-----------------------------------------|-------------------------------------|
| `reset() -> None`                        | 单 episode 起始重置(MCTS / hidden state) |
| `act(obs, mask, provider) -> tuple`      | 返回 `(action_idx, action_meta_dict)`;meta 含 paradigm-specific 字段(MCTS visit / Q / logits) |

Base:`training.core.protocols.EpisodePolicy`。Actor 与 EvalWorker 共
用同一 class — `deterministic=True` 时 SHALL 输出 deterministic(详
protocols.md §6 SHALL 3)。

### 2.6 NetworkProvider protocol

| 必有方法                                  | 用途                                |
|-----------------------------------------|-------------------------------------|
| `forward(obs, mask) -> Any`              | inference,paradigm-specific 返回   |
| `update_weights(version_tag) -> int`     | 加载新 weights(local: load_state_dict;remote: SHM IPC) |
| `current_version() -> int`               | 查询当前 weights version             |
| `close() -> None`                        | 资源释放                             |

Base:`training.core.protocols.NetworkProvider`。**已实现:**`LocalNetworkProvider`
+ `RemoteNetworkProvider` — 新 paradigm SHALL NOT 重新实现,直接复用。

## 3. Filesystem layout

新 paradigm 强制目录布局(参考 5 现成 paradigm `training/paradigms/<X>/`):

```
training/paradigms/<name>/
├── __init__.py          ★必有 — export Paradigm class
├── paradigm.py          ★必有 — Paradigm impl(~200-400 LOC)
├── config.py            ★必有 — <X>ParadigmConfig dataclass + from_dict
├── collector.py         ★必有 — Collector(serial + 可选 async variant)
├── policy.py            ★必有 — EpisodePolicy impl
├── loss.py              ★必有 — LossComputer impl
├── network.py           ★必有 — <X>Network(组装 encoder + heads)
├── buffer.py            按需 — paradigm-specific buffer(若 core/buffer/ 无现成可复用)
└── tests/               按需 — 与 training/tests/test_<X>_*.py 二选一
```

**SHALL NOT**:`legacy/` 子目录(详 §7 anti-pattern)。

### 3.1 Env factory 公共契约(`training/core/env_factory.py`)

所有 paradigm 共享 `training/core/env_factory.py` 提供的 env factory,
canonical signature(ship 2026-05-17,`env-factory-unification`):

```python
def make_env_factory(
    cfg: Any,
    obs_config_json: Optional[dict],
    master_seed: int,
) -> Callable[[int], GicgEnv]
```

**SHALL invariants**(PA-EF1..6):
1. 3 arg 全 required,无 default magic — 避免 dual cfg schema(`cfg.seed`
   vs `cfg.meta.seed`)silent fallback bug
2. `cfg` SHALL 只读 `cfg.scenario`(ScenarioConfig),paradigm-agnostic
3. `obs_config_json=None` 合法 = engine 默认观测配置；当前统一 run
   dispatcher 对所有已注册 paradigm 均传入 `None`
4. 需要自定义观测配置的 caller 显式传入 `ObsConfig.to_engine_json()`；
   factory 不从 paradigm cfg 隐式读取
5. 返回 closure `env_factory(game_idx)`:per-game seed = master_seed +
   game_idx,reset 后返回。可选 keyword `layout_seed` SHALL 仅覆盖构造时观测排列种子；
   不传时保留旧行为。cheap reset SHALL 保持排列。
6. SHALL be the only `make_env_factory` symbol in `training/core/` —
   no `env_factory_legacy.py` / `env_factory_v2.py` 并行版本

serial DMC SHALL 每局调用支持 `layout_seed` 的工厂创建新环境，按 master/episode_seq
分别派生 layout、episode、deck_0、deck_1 种子，记录在 episode_stats；双方 game_start
SHALL 使用新 static_obs。checkpoint SHALL 保存实际 episode_seq 与 RNG，恢复后产生相同后续序列。
该要求已接入 serial DMC；其他范式和异步路径不在本次迁移范围。
`tools.experiments.evaluate_clean` SHALL 每 scenario 派生独立 eval-layout，双方换边及
不同基线共享该布局；评估结果 SHALL 保存布局种子。旧 periodic evaluator 未迁移。

## 4. Integration points

新 paradigm code 落地后 SHALL 更新以下入口(漏一个 = paradigm 无法 dispatch):

### 4.1 必有 5 处更新

1. **`training/paradigms/__init__.py`** — `PARADIGMS` dict 加 `<name>:
   _load_<name>` lazy loader。
2. **`openspec/specs/paradigm-<name>/spec.md`** — 新 capability spec(~15
   SHALL,参照 5 现成)。
3. **`openspec/specs/training-architecture/spec.md`** — Paradigm landscape
   §4 加新 paradigm 行 + Cross-references 加 spec 引用。
4. **`docs/paradigms/<name>/`** dossier — `README.md` 起步 + `runs/` /
   `notes.md`(per `openspec-policy/file-layout.md` §3)。
5. **`configs/<name>/`** 目录 — paradigm-specific cfg presets(`smoke.toml`
   起步)。

### 4.2 按需更新(2 处)

6. **`tools/eval/_paradigm.py`** — `PARADIGMS` dict 加 entry(若想被
   `tools/eval/ckpt.py` / `daemon.py` 复用)。**Pitfall**:DMC dead-ref
   `ModuleNotFoundError`(commit `c4eeb60` 已修),guard 勿回退。
7. **`tools.runs.train <cfg>`** — 用 production 入口启动首个 run；该入口
   原子分配六位 NNN，并在 run 目录写配置快照与 `metadata.toml`。

## 5. Test scaffold

最小测试覆盖位于 `training/tests/test_<name>_paradigm.py`,SHALL cover:

### 5.1 Spec compliance(必有)

```python
from training.core.protocols import Paradigm, PipelineState
from training.paradigms import resolve
from training.paradigms.<name>.config import <X>ParadigmConfig

def test_paradigms_resolve_<name>():
    p = resolve('<name>')
    assert p.name == '<name>'
    assert p.requires_network_in_collect is <bool>

def test_<name>_paradigm_config_from_dict_minimal():
    cfg = <X>ParadigmConfig.from_dict({...minimal required fields...})
    # assert defaults

def test_<name>_paradigm_config_unknown_key_raises():
    with pytest.raises(ValueError, match='unknown paradigm key'):
        <X>ParadigmConfig.from_dict({'no_such_field': 1})

def test_<name>_paradigm_protocol_isinstance():
    p = <X>Paradigm()
    assert isinstance(p, Paradigm)  # runtime_checkable
```

### 5.2 Algorithm invariants(必有)

每条 paradigm spec SHALL 行 SHOULD 配 1 test。例:
- Loss 公式 SHALL → test `LossComputer.compute(network, fake_batch)` 输出 breakdown 键 + 数值范围
- Buffer SHALL → test push/sample/clear/len/state_dict 闭环
- EpisodePolicy deterministic SHALL → test `act(deterministic=True)` 两次同结果

参考完整覆盖示例:`training/tests/test_dmc_paradigm.py`(214 LOC)+
`test_bc_paradigm.py`(231 LOC)。

### 5.3 Smoke test

Pytest-managed `@pytest.mark.smoke` 5 条契约 + 5 paradigm-specific probe
+ smoke_full tier 协议见 [`./smoke-contract.md`](./smoke-contract.md);
SOP §8 链接同。

## 6. 5 paradigm 历史教训

每条来自 P0-P6 archive(unified-training-pipeline)或前序 paradigm-specific
postmortem。新 paradigm 起步前 SHALL 至少快速过一遍这 5 条。

### 6.1 AZ — IS-MCTS leaf eval 网络 placement 不可硬编码

- **教训**:AZ MCTSPolicy.act() 每 leaf 调 `provider.forward()`(paradigm-az
  spec A1.2),原始实现 hardcode local nn.Module + CPU,后期切 mps / cuda
  需重写 collector
- **应用**:新 paradigm if collect 需 forward → SHALL 走 NetworkProvider
  抽象(本 spec protocols.md §7 SHALL 1-3)。`requires_network_in_collect
  = True` 是 first-class 字段,driver 据此走 provider 构造路径
- **Source**:`paradigm-az/spec.md` A5.3 + `archive/unified-training-pipeline/design.md` §75-76

### 6.2 PPO — on-policy buffer 必须每 iter clear

- **教训**:r004 时代 PPO 用 ReplayBuffer 残留 cross-iteration sample,
  importance ratio 漂移导致 clip frac > 0.5;后纠正为 RolloutBuffer +
  iter clear(paradigm-ppo spec P4.1)
- **应用**:新 paradigm if on-policy → SHALL 显式 `buffer.clear()` per
  iter,SHALL NOT 复用 off-policy ReplayBuffer
- **Source**:archives `0007-ppo-bc-warmstart` / `0008-rl-paradigm-pivot`

### 6.3 DMC — async stale weights 容忍度需 spec 化

- **教训**:DMC 24 actor + 1 learner async,early implementation 把 actor
  worker hard-stop 拉新 weights 每 K step throttle throughput;后纠正
  stale tolerance lag p99 ≤ 500 step(D6.2)+ versioned SHM slot
- **应用**:新 paradigm if async → SHALL 显式 spec 出 stale tolerance(以
  SHALL 形式);SHALL NOT silent "差不多就行" — stale 是 distributed RL
  load-bearing 决策
- **Source**:`paradigm-dmc/spec.md` D6.2

### 6.4 BC — first-class 独立,SHALL NOT 嵌入 RL paradigm

- **教训**:BC 原 embedded in `training/az/bc_*.py` + `training/ppo/bc_*.py`
  双修维护痛苦;P4-T2 抽出 `training/paradigms/bc/` first-class(BC6.1)
- **应用**:新 paradigm 辅助流程(pretrain / warm-start / distill)SHALL
  first-class,通过 `init_from_ckpt` 被 RL paradigm 引用(BC6.2);SHALL NOT 嵌入
- **Source**:archive `0009-rl-paradigm-pivot-terminus`

### 6.5 CFR — 不 fit 标准 RL mold 时,做"intentional shim"也要符合 protocol

- **教训**:CFR(OS-MCCFR + reservoir + advantage/strategy 双 head)与 AZ/
  DMC/PPO mold 差异大;初期曾绕 6 protocol,后纠正:CFR 仍 implements
  Paradigm + Collector + Buffer,Collector 内部是 `TraversalCollector`
  (Python thread),Buffer 是双 `ReservoirBuffer`(C3.1)
- **应用**:新 paradigm 与现有 mold 差异大 → SHALL 仍 wrap 进 6 protocol
  (filter 在内部);protocol 真无法满足 → SHALL 走 OpenSpec change 修订
  protocol(SHALL 2),而非 silent 偏离
- **Source**:archive `0006-training-layout` +
  `docs/5_history/reviews/dmc_review.md`

## 7. Anti-patterns

接入新 paradigm 时 SHALL NOT 出现以下模式:

### 7.1 SHALL NOT 创建 `legacy/` 子目录

`paradigms/<name>/legacy/` 是 unified-training-pipeline 迁移期间的
transitional holding(P5-A/B/C/D),已通过 FU-W4-{DMC,PPO} 系列彻底退役
(commit `73c6ed7` / `2e5bc6f` / `decb4a8`)。新 paradigm 一开始就 in-place
写新 code,SHALL NOT 留 `legacy/` 占位,SHALL NOT 留旧实现"以防万一"。

### 7.2 SHALL NOT 创建并行栈

新 paradigm if fork 现有 paradigm → SHALL 在原 paradigm 内 ablation 或
rewrite,SHALL NOT 创建 `paradigms/<X>_v2/` 并行栈。**示例反面**:az-paradigm-
rewrite change(active,`openspec/changes/az-paradigm-rewrite/`)即采用
in-place rewrite,无并行栈。

### 7.3 SHALL NOT 添加 migration shim / adapter

新 paradigm 如果需要 "bridge old API to new API" wrapper → 是 design
problem，SHALL 直接改 caller，不保留并行兼容层。

### 7.4 SHALL NOT silent 偏离 protocol

新 paradigm if 发现 Paradigm protocol 无法满足(例如要 N>1 个 network /
要 collector 返回非 CollectorOutput type)→ SHALL 走 OpenSpec change 修订
本 spec 与 `core/protocols.py`,SHALL NOT 在 paradigm 内部 silent 加字段 /
bypass protocol。Cross-paradigm consistency 是本 capability spec 的核心
价值。

### 7.5 SHALL NOT 嵌入到既有 paradigm

新 paradigm if 是辅助流程(distill / warm-start / opp pool generator)→
仍 first-class(参 §6.4 BC 教训)。嵌入到既有 paradigm 会复刻
PPO+BC / AZ+BC 双修痛苦。

### 7.6 SHALL NOT 留 `_legacy.py` 后缀文件

`core/<name>_legacy.py` transitional file 已通 `core-network-generic-promotion`
Phase 2F + `env-factory-unification` 全部退役。新功能 SHALL 直接落
canonical `core/<name>.py`,与 §7.1 同模一致,锚 user `feedback_no_compat_fallback`。

### 7.7 SHALL NOT 跳过 paradigm spec

新 paradigm 接入 SHALL 先 ship `openspec/specs/paradigm-<name>/spec.md`
(~15 SHALL),后写 code。Spec-first 保证 algorithm invariants 在 commit /
ablation 时有 anchor。SHALL NOT "先写 code 后补 spec" — 实测会漏 SHALL,
后期 review 痛苦。

## 8. Smoke 契约 + paradigm-specific probe

每 paradigm 必须提供 `test_<paradigm>_smoke.py`,实施 5 个 SHALL 子条件
(zero-startup / mini-train / eval probe / paradigm-specific invariant / ≤2min)。
完整规约 + 5 paradigm-specific probe 详节(AZ MCTS visit_counts / BC loss
decrease / DMC Q finite / CFR strategy sums / PPO clip ratio)+ smoke_full
tier 协议见 [`./smoke-contract.md`](./smoke-contract.md)。

SHALL 锚定 → [`./invariants.md` (#18 smoke 契约)](./invariants.md)。

## 9. Cross-references

- 主 spec → [`./spec.md`](./spec.md)
- 6 protocol 详细签名 → [`./protocols.md`](./protocols.md)
- Pipeline driver / Schedule → [`./pipeline.md`](./pipeline.md)
- Network sharing / encoder + heads → [`./network-sharing.md`](./network-sharing.md)
- Eval protocol / EpisodeRunner → [`./eval.md`](./eval.md)
- Opponent mix → [`./opponent-mix.md`](./opponent-mix.md)
- Smoke 契约 / paradigm probe → [`./smoke-contract.md`](./smoke-contract.md)
- 5 现成 paradigm spec → [`../paradigm-az/spec.md`](../paradigm-az/spec.md) /
  [`../paradigm-bc/spec.md`](../paradigm-bc/spec.md) /
  [`../paradigm-cfr/spec.md`](../paradigm-cfr/spec.md) /
  [`../paradigm-dmc/spec.md`](../paradigm-dmc/spec.md) /
  [`../paradigm-ppo/spec.md`](../paradigm-ppo/spec.md)
- File layout 约定 → [`../openspec-policy/file-layout.md`](../openspec-policy/file-layout.md)
- Config schema(`meta.paradigm` dispatch)→ [`../config-schema/spec.md`](../config-schema/spec.md)
- Tools layout(`tools.runs.train` 单入口)→ [`../tools-layout/spec.md`](../tools-layout/spec.md)
- Originating change → [`../../changes/archive/unified-training-pipeline/`](../../changes/archive/unified-training-pipeline/)
- Historical architecture follow-up registry →
  [`docs/3_plans/arch_unification_remaining_2026_05_16.md`](../../../docs/3_plans/arch_unification_remaining_2026_05_16.md)

## 10. Status

- **Created**:2026-05-16(FU-architecture-#11)
- **Version**:0(初始,基于 P0-P6 archive 经验)
- **Revised**:2026-05-17 — `core-network-generic-promotion` /
  `env-factory-unification` ship:§1.2 smoke 必须项 + §3.1 canonical
  `make_env_factory` 锚定;§8 Smoke 契约由 fixup commit 拆到独立
  [`./smoke-contract.md`](./smoke-contract.md)(file-layout §1.1 ≤ 400 cap)
- **Expected revision triggers**:
  - 第 6 paradigm 接入完成 → 回写本 SOP 加该 paradigm 教训
  - Paradigm protocol 扩展(新增 make_* / 改签名)→ §2 contract surface 同步
