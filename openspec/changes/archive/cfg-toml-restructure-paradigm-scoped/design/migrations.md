# cfg-toml-restructure-paradigm-scoped — Migration / Risks / Verification

> Detail extracted from top-level `design.md` at archive time (≤ 200 lines cap)。
> 内容:§3 Migration phase 顺序 + §3.2 test cascading + §4 Risks(4 risks)+
> §5 Rollback + §6 Verification matrix + §7 LOC estimate。

## 3. Migration

### 3.1 Phase 顺序

1. **T0** propose(5 artifact 落盘)
2. **T1** new `training/core/cfg/loader.py` — `load_paradigm_cfg` helper
3. **T2** update `training/core/cfg/__init__.py` — export `load_paradigm_cfg`
4. **T3** update `training/core/config/loader.py::load_cfg` — call
   `load_paradigm_cfg` before paradigm dispatch + change `_build_dataclass`
   signature
5. **T4** update `training/core/config/schema.py::ALLOWED_TOP_LEVEL` — add
   `'shape'`
6. **T5** new `training/tests/test_cfg_toml_hybrid.py` — 5 paradigm dispatch
   / shape override / multi-paradigm ignored / legacy flat raise / round-trip
7. **T6** rewrite 4 paradigm × 2 preset = 8 toml(AZ/BC/CFR/DMC):
   - `configs/az/{default,smoke}.toml`
   - `configs/bc/{default,smoke}.toml`
   - `configs/cfr/{default,smoke}.toml`
   - `configs/dmc/{default,smoke}.toml`
8. **T7** new 2 PPO toml:`configs/ppo/{default,smoke}.toml`
9. **T8** spec delta `openspec/changes/cfg-toml-restructure-paradigm-scoped/
   specs/config-schema/spec.md`
10. **T9** pytest sweep verify
11. **T10** commits(propose + impl)

### 3.2 Test cascading

- 已有 `test_cfg_unification.py` / `test_cfg_version_validation.py` 不用旧
  toml,直接 from_dict — 不破
- 已有 `test_config_loader.py`(legacy AZ loader)走 legacy `[paradigm]`
  flat dict 形态 — 仍 work(legacy loader 不用新 hybrid helper)
- 已有 paradigm smoke test(若用 `load_cfg` 走新 toml)— 需要新 toml 改成
  hybrid 形态(本 change 重写 8 toml)
- 新增 `test_cfg_toml_hybrid.py` 覆盖:
  - 5 paradigm dispatch(load toml + check cfg.paradigm dict 正确)
  - `[shape]` + `[paradigm.X.agent]` merge 优先级(agent override shape)
  - 缺 `[shape]` 段 OK(factory default)
  - 缺 `[paradigm.<name>]` 段 OK(全 default)
  - 旧 flat `[paradigm]` 段(scalar 字段)raise
  - `[paradigm.<wrong_name>]` silent ignored(不影响 dispatch)

## 4. Risks

### 4.1 Tooling 期望 cfg.paradigm 为 flat dict

- **Risk**:`pipeline.py:99` 用 `cfg.paradigm.get('max_grad_norm', 1.0)`
  假设 cfg.paradigm 是 flat dict — paradigm 顶层 hparam 在 root
- **Mitigation**:`_build_dataclass(cfg, paradigm_flat)` 中 paradigm field
  仍是 flat dict(由 `load_paradigm_cfg` 提取)— pipeline 行为不变

### 4.2 CLI override path 失配

- **Risk**:`--override paradigm.lr=1e-4` 走旧 flat path,新结构是
  `paradigm.az.lr` — user override 路径变化
- **Mitigation**:override 仍在 raw TOML 上 apply(`_apply_overrides` 在
  `load_paradigm_cfg` 前);user 需用新 path `paradigm.az.lr=1e-4`。
  Doc string 提示 path 变化。`tools/run.py` 是 only consumer,user 显式
  提供 override 时 hybrid path 是 conscious choice

### 4.3 [shape] 覆盖 vs paradigm.agent 优先级 confused

- **Risk**:user 不清楚 `[shape].d_model=128` + `[paradigm.ppo.agent].
  d_model=256` 谁赢
- **Mitigation**:design.md 明示 "agent overrides shape";test_cfg_toml_hybrid.py
  override priority test 覆盖;每个新 toml 注释说明 override 含义

### 4.4 PPO 历史 d_model=256 与本 change 的 [shape] 默认 128

- **Risk**:`make_ppo_default_shape`(若存在)假设 d_model=256,但
  [shape] 共享段写 128 → override 才 256,可能 user 混淆
- **Mitigation**:CC-302 决策:`[shape] d_model=128` +
  `[paradigm.ppo.agent] d_model=256` 显示 override;PPO test 验证 effective
  d_model 是 256

## 5. Rollback

- Single impl commit(T1-T8),`git revert <commit>` 回到 propose 状态
- 10 toml restructure 是文件改动,revert 还原
- 无 ckpt schema 改动(cfg dataclass 不变),不破 ckpt

## 6. Verification matrix

| Aspect | Method | Pass criterion |
|---|---|---|
| `load_paradigm_cfg` 提取语义 | `pytest test_cfg_toml_hybrid.py -v` | 5 paradigm flat dict 与 from_dict 兼容 |
| `[shape]` override | hybrid test | `[shape].d_model=128 + [paradigm.X.agent].d_model=256` → effective 256 |
| `[shape]` 可选 | hybrid test | 缺 `[shape]` 段 → factory default |
| Multi-paradigm ignored | hybrid test | `[paradigm.az.X] + [paradigm.ppo.X]` + dispatch ppo → 只 ppo 段被 used |
| Legacy flat raise | hybrid test | 旧 `[paradigm].lr=1e-3` flat scalar → raise |
| 10 toml load | hybrid test (parametrize over 10 path) | 5 paradigm × 2 preset 全部 `load_cfg` 不 raise |
| Pytest sweep | per CLAUDE.md command | 0 new failures |
| openspec indices | `tools/_meta/check_openspec_indices.py` | pass |

## 7. LOC estimate

| File | Change | LOC delta |
|---|---|---|
| `core/cfg/loader.py` | new | 0 / +80 |
| `core/cfg/__init__.py` | export | -0 / +3 |
| `core/config/loader.py` | dispatch path | -3 / +10 |
| `core/config/schema.py` | + 'shape' to ALLOWED_TOP_LEVEL | -1 / +2 |
| `configs/{az,bc,cfr,dmc}/{default,smoke}.toml` | restructure 8 files | -300 / +320 |
| `configs/ppo/{default,smoke}.toml` | new 2 files | 0 / +90 |
| `tests/test_cfg_toml_hybrid.py` | new | 0 / +200 |
| `openspec/.../specs/config-schema/spec.md` | delta | 0 / +90 |
| **Total** | | **-304 / +795(net +491)** |
