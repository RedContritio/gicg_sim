# gicg_env 层审计报告

> 2026-04-17。网络层发现六项修复后，对 `gicg_env/env.py` + `gicg_env/engine.py` 做同级系统审查。
> 目标：发现类似 hook-gradient bug 这种"基础设施级"问题。

## 🔴 发现一项 critical bug

### E-1：`_get_obs()` 视角错位（forced-switch pending 时）

**位置**：`gicg_env/env.py::GicgEnv._get_obs` → `gicg_env/engine.py::GicgEngine.get_dynamic_obs(perspective=None)`

**bug**：`get_dynamic_obs` 在 `perspective=None` 时默认用 `self.turn`：
```python
def get_dynamic_obs(self, perspective=None):
    ...
    if perspective is None:
        perspective = self.turn
    ...
```

但 MCTS / selfplay 一致**用 `env.acting_player`** 作为决策方视角：
- `mcts.py` B3 注释："Node.turn is read from env.acting_player (not env.turn)"
- `mcts.py` L561/694：`child.turn = env.acting_player`
- `selfplay.py` L133：`acting = env.acting_player`
- pi_target / z_target 都按 `acting_player` 视角 backfill

**正常情况下** `acting_player == turn`，没问题。

**forced-switch pending 时** 不同：
- `g.Turn` = 原本行动方（死亡前的 active player）
- `acting_player` = 死亡方（需要决定切谁的 victim）
- 这两者差一个视角

**影响链**：
1. forced-switch pending 状态下 MCTS 需要为 `victim` 决策选哪个角色切
2. MCTS 拿 `env._get_obs()` → 用 `self.turn`（= 原 actor）视角
3. obs 里的 "己方 counters" 实际是**原 actor** 的 counter，"敌方" 是 victim
4. MCTS 以这个 obs 喂给网络，但决策者是 victim → **counter 归属翻转了**
5. 网络学到的 value / policy 在 forced-switch 决策点上 systemic flipped

**触发频率**：每局几次（每次死亡就触发一次 forced switch pending），每次持续 1 步。按 C1v6 局均 33 步 × 平均 3 次死亡，约 9% 的训练步受影响。

**修复**（简单）：
```python
# gicg_env/env.py::GicgEnv._get_obs
def _get_obs(self):
    raw = self._engine.get_dynamic_obs(
        perspective=self._engine.acting_player,  # was: None (→ turn)
    )
    ...
```

Go 端 `BuildDynamicObs(perspective)` 已经正确处理参数，只要 Python 传正确值即可。

**修复影响**：会改变训练数据的分布（对 forced-switch 步骤的观察翻转）。**C1v6 是用旧行为训的**，修复后应该算新的 run（C1v7）。严谨起见，修复后跑 smoke 确认 train_step 不崩。

---

## 🟡 设计 hack（非 bug）

### E-2：`step` 里副作用调用 `GameGetLegalActionCount`

`engine.py::step` 在 `GameStep` 返回后立刻调 `GameGetLegalActionCount` 丢弃返回值：

```python
def step(self, action_idx):
    ...
    result = self._lib.GameStep(self._handle, action_idx)
    self._lib.GameGetLegalActionCount(self._handle)  # 副作用：auto-advance
    return result
```

注释解释：Go 端 `PhaseRoundStart` 里有 auto-advance hooks（round start 自动触发后抽牌、AP 重置等），只有查询 legal actions 时才触发。Python 侧这里强制调一次确保 auto-advance 执行。

**评估**：工程 hacky 但**设计明确**。风险：若 Go 端内部改变 auto-advance 触发条件（例如改成 `GetPhase` 触发），Python 端的显式调用就失效。

**改进建议**：Go 端加一个独立 `GameStepFinalize` API 明确做 advance，Python 端调用这个而不是 "副作用丢弃 legal_count"。但这是 nice-to-have，不是 bug。

---

## 🟢 审计通过的项

### E-3：per-slot normalization 设计正确
`_get_obs` 的 counter 归一化用 `(raw - slot_min) / slot_denom`（`slot_denom = max(max-min, 1.0)`）。每 slot 固定缩放，不依赖每步全局 max。和设计意图一致，和 counter 维度一致。

### E-4：`done=True` 返回 zeros obs
在 terminal 步骤 `_get_obs()` 返回 `np.zeros(obs_size)`。训练代码 (`selfplay.py _build_step_dict`) 只在非终局步骤调用，不会被误用。

### E-5：`has_pending` 从引擎查
`env.has_pending` 直接查 engine，不用 local flag。跨 snapshot/restore 一致。

### E-6：`set_player_hand/deck/dice` 确定化注入
实现简单直接，参数校验（`player in (0,1)`、`len(counts) == 8`）都在。Go 侧错误返回会 raise。

### E-7：`clone` 共享 static_obs
`clone()` 共享 `_static_obs` numpy（不 deepcopy）。合理——static obs 整局不变，多 env 共享节省内存。不会出现修改其中一个影响另一个（numpy 都是只读使用）。

### E-8：`reset` 只重置 dynamic
`reset_dynamic` 只重置 engine dynamic state，保留 DSL、ruleset。这是性能优化（避免 DSL 重 load），也是正确的——scenario config 固定时，DSL 不变。

---

## 总结

| 类别 | 数 | 问题 |
|---|---|---|
| 🔴 Critical | 1 | E-1 `_get_obs` 视角错位（forced-switch pending 时 9% 训练步受影响）|
| 🟡 Hack | 1 | E-2 副作用调用（设计明确但不雅）|
| 🟢 通过 | 6 | — |

E-1 是**真实 bug**，和网络层的 hook gradient 断同级别——都是 training infrastructure 层面无声污染训练数据。对 MCTS 的 value estimate 在 forced-switch 决策点有系统性偏差。

---

## 建议

**对 C1v6**：不修。让 C1v6 按当前代码跑完拿到 hook channel 激活判据（核心目标）。E-1 影响的是 forced-switch 节点上的训练数据质量，不影响 hook channel 是否被用。

**对 C1v7（如果跑）**：修 E-1。1 行改动：`perspective=None` → `perspective=self._engine.acting_player`。加单元测试：构造一个 forced-switch pending 状态，对比 `obs(perspective=turn)` 和 `obs(perspective=acting_player)` 在 counter 布局上是镜像的。

**工程建议**：`get_dynamic_obs` 的 `perspective=None` 默认值改为 `acting_player` 而不是 `turn` —— 让默认值 match 大部分 caller 的实际意图（MCTS / training）。改完以后显式 pass `perspective=turn` 的 caller 极少（若有，是 debugging 或 replay 相关的，不影响训练主路径）。
