# cfg-schema-unification — Migrations + Verification

> Detail extracted from top-level `design.md` at archive time (≤ 200 lines cap)。
> 内容:§3 Migration phase 顺序 + backward-compat + test cascading + §4 Risks
> + §5 Rollback + §6 Verification matrix + §7 LOC estimate。

## 3. Migration

### 3.1 Phase 顺序

1. **T0** propose(4 artifact 落盘)
2. **T1** `core/cfg/base.py` rewrite — drop `shape` field
3. **T2** `core/cfg/factories.py` new — 4 factory functions
4. **T3** update `core/cfg/__init__.py` — export factories
5. **T4** `paradigms/az/config.py` — inherit ParadigmConfigBase + AgentShapeCfg alias + agent: ObsShape + from_dict version/paradigm validation
6. **T5** `paradigms/bc/config.py` — same pattern
7. **T6** `paradigms/cfr/config.py` — CFRAgentShapeCfg → ObsShape(alias for backward compat)+ same pattern
8. **T7** `paradigms/dmc/config.py` — same pattern
9. **T8** `training/tests/test_obs_shape_factories.py` — 4 factory test
10. **T9** `training/tests/test_cfg_unification.py` — 4 paradigm inherit + agent ObsShape
11. **T10** `training/tests/test_cfg_version_validation.py` — version + paradigm mismatch raise
12. **T11** `training/tests/test_cfg_shape.py` — 修改 test_paradigm_config_base_defaults(去 `shape` 字段断言)
13. **T12** `configs/{az,bc,cfr,dmc}/{default,smoke}.toml` × 4 = 8 toml
14. **T13** `openspec/changes/cfg-schema-unification/specs/config-schema/spec.md` delta
15. **T14** pytest sweep verify
16. **T15** commits(propose / implement / configs)

### 3.2 Backward-compat preservation

| 旧 import | 新行为 |
|---|---|
| `from training.paradigms.az.config import AgentShapeCfg` | OK(`AgentShapeCfg = ObsShape` alias) |
| `from training.paradigms.bc.config import AgentShapeCfg` | OK(alias) |
| `from training.paradigms.dmc.config import AgentShapeCfg` | OK(alias) |
| `from training.paradigms.cfr.config import CFRAgentShapeCfg` | OK(`CFRAgentShapeCfg = ObsShape` alias) |
| `pcfg.agent.X` (paradigm.py / collector.py / loss.py) | OK(field 名 unchanged) |

### 3.3 Test cascading

- `test_az_paradigm_config_phase1.py::test_az_paradigm_config_has_required_agent_fields`:
  AgentShapeCfg = ObsShape,字段集相同(7 字段全在 ObsShape),test 自动通过
- `test_cfg_shape.py`(前 change ship):去 `cfg.shape.n_counter_slots == 0` 断言;改为 only `version + paradigm` 断言
- `test_cfr_paradigm.py::isinstance(cfg.agent, CFRAgentShapeCfg)`:`CFRAgentShapeCfg = ObsShape` alias 后 isinstance 仍 True(同一 class)

## 4. Risks

### 4.1 PPO test 不受影响

**Risk**:本 change 不动 PPO,但 `test_ppo_paradigm.py::isinstance(cfg.agent, PPOAgentShapeCfg)` 应自动通过(PPOAgentShapeCfg 不动)。

**Mitigation**:不触 PPO config.py;sweep verify 时 PPO test 全通过。

### 4.2 ObsShape default 值与 paradigm AgentShapeCfg 差异

**Risk**:`ObsShape` dataclass 字段顺序 / default 值与 paradigm AgentShapeCfg 不完全一致(d_model default 不同;前者 128 后者 32)。

**Mitigation**:factory function 显式传 paradigm-specific d_model;dict-based from_dict 行为不变(toml 没传 d_model = 用 factory default)。

### 4.3 `core/cfg/base.py` drop `shape` field BREAKING

**Risk**:`test_cfg_shape.py` 有 `cfg.shape.n_counter_slots == 0` 断言。

**Mitigation**:T11 同步改 test;不是 production 调用,影响面 1 文件。`core/cfg/__init__.py` 仍 export ParadigmConfigBase,paradigm config.py 用 inherit + 自加 agent 字段。

### 4.4 toml 模板字段错误

**Risk**:8 个新 toml 字段集错(e.g. AZ toml 写到 BC paradigm 字段),loader 在 cfg load 时 raise。

**Mitigation**:每 paradigm config_loader 已有 strict `from_dict`(unknown key raise),CI sweep `pytest tools/` 间接 load configs/ 触发验证;额外加 `test_cfg_toml_load.py` 显式 load 8 toml(若必要)。本 change 优先验证 config code,toml 写入后 manual `python -m training.core.config.loader configs/az/default.toml` 验证。

## 5. Rollback

- 单 implement commit(T1-T13),`git revert <commit>` 还原到 propose 后状态
- propose commit 与 impl commit 分开;若 impl 失败可保留 propose
- 8 toml 是新文件,无 backward compat 负担

## 6. Verification matrix

| Aspect | Method | Pass criterion |
|---|---|---|
| ParadigmConfigBase 字段集 | `pytest training/tests/test_cfg_shape.py -v` | drop shape 后 4 test pass |
| 4 paradigm inherit base | `pytest training/tests/test_cfg_unification.py -v` | issubclass(<X>ParadigmConfig, ParadigmConfigBase) for AZ/BC/CFR/DMC |
| Factory functions | `pytest training/tests/test_obs_shape_factories.py -v` | 4 factory 返回 ObsShape with paradigm d_model |
| version validation | `pytest training/tests/test_cfg_version_validation.py -v` | `version='1.5.0'` raise;`paradigm` mismatch raise |
| Existing paradigm test | `pytest training/tests/test_{az,bc,cfr,dmc,ppo}_paradigm*.py -v` | 4 paradigm test pass(PPO untouched);CFR isinstance 仍 True |
| Pytest sweep | per CLAUDE.md command | 0 new failures |
| openspec indices | `tools/_meta/check_openspec_indices.py` | pass |

## 7. LOC estimate

| File | Change | LOC delta |
|---|---|---|
| `core/cfg/base.py` | rewrite drop shape | -25 / +15 |
| `core/cfg/factories.py` | new | 0 / +45 |
| `core/cfg/__init__.py` | export factories | -1 / +5 |
| `paradigms/az/config.py` | inherit + alias + version | -10 / +30 |
| `paradigms/bc/config.py` | inherit + alias + version | -10 / +30 |
| `paradigms/cfr/config.py` | inherit + alias + version | -10 / +30 |
| `paradigms/dmc/config.py` | inherit + alias + version | -10 / +30 |
| `training/tests/test_cfg_shape.py` | update for drop shape | -10 / +5 |
| `training/tests/test_cfg_unification.py` | new | 0 / +60 |
| `training/tests/test_cfg_version_validation.py` | new | 0 / +80 |
| `training/tests/test_obs_shape_factories.py` | new | 0 / +50 |
| `configs/{az,bc,cfr,dmc}/{default,smoke}.toml` | new 8 files | 0 / +320 (~40/file) |
| `openspec/.../specs/config-schema/spec.md` | delta | 0 / +60 |
| **Total** | | **-76 / +760(≈ net +684)** |
