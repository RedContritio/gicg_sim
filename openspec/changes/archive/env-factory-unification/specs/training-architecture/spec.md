---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: training-architecture
---

# Spec delta — training-architecture

本 delta 修订 `paradigm-onboarding.md` subtopic:`env_factory_legacy.py`
正式退役 + 加 `env_factory` 公共契约段。详 `../../proposal.md`。

## ADD

### A1. `env_factory` 公共契约(paradigm-onboarding.md 新章节)

`training/core/env_factory.py` 提供 paradigm-agnostic env factory,
canonical signature:

```python
def make_env_factory(
    cfg: Any,
    obs_config_json: Optional[dict],
    master_seed: int,
) -> Callable[[int], GicgEnv]
```

**SHALL invariants**:

1. **PA-EF1**:`make_env_factory` 的 3 个 arg SHALL 全 required —
   `cfg` / `obs_config_json` / `master_seed`。**NOT** 允许 default
   值(无 `master_seed=None` magic 从 cfg 读取 seed)。

2. **PA-EF2**:`cfg` 参数 SHALL 只读 `cfg.scenario`(ScenarioConfig)。
   **NOT** 允许直接读 `cfg.obs` / `cfg.seed` / `cfg.meta.seed` 等其它
   cfg 字段;这些由 caller 转换后通过 `obs_config_json` /
   `master_seed` 显式传入。

3. **PA-EF3**:`obs_config_json=None` SHALL be 合法输入,语义 ==
   engine 默认 obs config(all-on shuffle + include_char_skill_refs)。
   适用于 paradigm 不持有 `ObsConfig` 字段时(如 DMC / CFR / BC)。

4. **PA-EF4**:`obs_config_json=cfg.obs.to_engine_json()` SHALL 是 AZ
   paradigm 调用方式(AZ 持有 `cfg.obs: ObsConfig`,转 dict 显式传)。

5. **PA-EF5**:返回 closure `env_factory(game_idx: int) -> GicgEnv`
   SHALL 满足:per-game seed = `master_seed + game_idx`,reset 后
   返回。GicgEnv 构造参数 SHALL 严格从 `cfg.scenario` 转发
   (`team_0` / `team_1` / `card_pool` / `data_dir` / `max_rounds` /
   `fix_dice` / `obs_mask` / `deck_padding` / `pool`)。

6. **PA-EF6**:**SHALL** be the only `make_env_factory` symbol in
   `training/core/`。**SHALL NOT** 共存 `env_factory_legacy.py` /
   `env_factory_v2.py` 等并行版本。

## MODIFY

### M1. `paradigm-onboarding.md` § 3 layout — 删 `env_factory_legacy.py`

**Before** § 9 revision triggers 列表项:

> - `core/network/legacy/` / `core/env_factory_legacy.py` 退役 → §3 layout 可能简化

**After**(标完成):

> - `core/network/legacy/` 退役 → §3 layout 简化(`core-network-generic-promotion` Phase 2F ship 2026-05-17)
> - `core/env_factory_legacy.py` 退役 → 已完成(`env-factory-unification` ship)

### M2. `paradigm-onboarding.md` § 3 layout — 不应再出现 `_legacy` 命名

**Before**:`core/` 内任何 `_legacy.py` 文件假设。

**After**:`core/` SHALL NOT 存在 `_legacy.py` 后缀文件 — 新功能直接
落 canonical 路径,过渡期不允许并行栈(per `feedback_no_compat_fallback`
memory + `CLAUDE.md` § 1 "大改造不保留向后兼容")。

## REMOVE

### R1. `_build_env_factory` inline in `tools/run.py`

`tools-layout/spec.md`(若存)隐含 `tools/run.py` 内嵌 `_build_env_factory`
helper 是 acceptable workaround — 本 change SHALL remove。

**Before**:`tools/run.py` 内 `_build_env_factory(cfg)` 27 行 inline
GicgEnv 构造,docstring "Inlined here (instead of using core/env_factory)
because we want obs_config=None"。

**After**:`tools/run.py` SHALL `from training.core.env_factory import
make_env_factory` + 调 `make_env_factory(cfg, None, master_seed=cfg.meta.seed)`。

理由:canonical signature 支持 `obs_config_json=None`,原 inline 的
理由(不想 thread obs_config)被新 signature 直接覆盖。3 source of
truth 收敛到 1 source。

## Cross-references

- `../../proposal.md` — change 整体动机 + 范围
- `../../design.md` — 4 option tradeoff + migration table + LOC
  estimate
- `../../tasks.md` — 10 task 执行清单 + 依赖图
- `core-network-generic-promotion/DECISIONS.md` [D-102] — 本 change 起源
