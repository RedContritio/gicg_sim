# ppo-cfg-shape-alignment — Design Retrospective

> Archive-time retrospective(≤ 200 lines per archive cap)。本 change 是
> 轻量 follow-up(~60 LOC code + 200 LOC docs),无 design/ subdir 拆分必要;
> 本文档完整记录决策与验证。

## Verdict

**成功** — PPO cfg dataclass 完全对齐 4 paradigm(AZ/BC/CFR/DMC),
5/5 paradigm cfg 实现统一:`PPOAgentShapeCfg = ObsShape` alias、
`PPOParadigmConfig` inherit `ParadigmConfigBase`、`from_dict` 加 version +
paradigm 校验、`make_ppo_default_shape()` factory 提供 default。关闭
`cfg-schema-unification` [CC-206] PPO defer 残留,关闭
`core-network-generic-promotion` DECISIONS D3 endpoint 推荐。

实施单 day / 5 task all done / `pytest -k "ppo or cfg"` 160/160 pass /
`pytest training/tests/test_config_loader.py` 12/12 pass / full sweep
1159 passed / 10 skipped / 0 failed。

## What we built

- `training/core/cfg/factories.py` — 加 `make_ppo_default_shape() -> ObsShape`
  (d_model=128 / n_cross_layers=2,与 AZ 同 baseline,post-#4 structural
  defaults),module docstring "5 paradigm × 1 factory each"(原 "4 paradigm")
- `training/core/cfg/__init__.py` — export `make_ppo_default_shape`,
  update `__all__` + docstring 列出 5 个 factory
- `training/paradigms/ppo/config.py` rewrite —
  - import `ObsShape + ParadigmConfigBase + build_shape_from_toml +
    make_ppo_default_shape` from `training.core.cfg`
  - `PPOAgentShapeCfg = ObsShape` alias(CC-202 pattern extended to PPO),
    替代历史独立 dataclass def
  - `PPOParadigmConfig(ParadigmConfigBase)` inheritance + `paradigm: str =
    'ppo'`(原无 base 继承)
  - `agent: ObsShape = field(default_factory=make_ppo_default_shape)`
  - `from_dict`:加 version 校验(`_VALID_VERSIONS` enum)+ paradigm
    mismatch raise + `build_shape_from_toml(agent_d, make_ppo_default_shape)`
    走 unified merge path
- Bundled fixes from #6 sweep:
  - 5 `configs/<paradigm>/smoke_full.toml`:加 `paradigm = "<X>"` 字段
    to `[meta]` section(per `cfg-toml-restructure-paradigm-scoped` dispatch
    convention 要求)
  - `training/tests/test_config_loader.py::test_shipped_configs_load_successfully`:
    加 hybrid TOML format detection(`extends` in meta / `paradigm.X` nested
    → unified loader path,skip legacy AZ loader),修 #6 smoke_full.toml
    hybrid 格式被 legacy loader 误抓的 false positive

## Tradeoffs revisited

- **type alias vs 新 dataclass def**:预期 + 实际 SELECTED alias ✓ — 沿用
  `cfg-schema-unification` [CC-202] pattern,4 paradigm 已用 alias
  (`AgentShapeCfg = ObsShape` / `CFRAgentShapeCfg = ObsShape`);PPO 同 pattern
  保证 5 paradigm 对称。Alias 让 `isinstance(cfg.agent, PPOAgentShapeCfg)`
  仍 True,任何 import `PPOAgentShapeCfg` 的 caller(test / docstring xref)
  0 改动。
- **agent 字段名(不重命名为 shape)**:预期 + 实际 ✓ — 沿用
  `cfg-schema-unification` [CC-201] 决策,PPO 也用 `agent` 字段名,与 4
  paradigm 一致。
- **make_ppo_default_shape d_model=128 / n_cross_layers=2**:预期 + 实际
  ✓ — 与 AZ baseline 同(`make_az_default_shape`),post-#4 structural
  backbone defaults;flat-MLP 历史 d_model=256 + n_hidden_layers=3
  已在 #4 retired,新 factory 不复活。
- **bundled #6 sweep fixes 是否独立 change**:预期 独立 / 实际 bundled ✓ —
  5 smoke_full.toml `paradigm = "<X>"` field + 1 test_config_loader fix
  都是 1-line / 6-line trivial fixes,scope ~10 LOC;独立 change overhead
  (propose/tasks/archive)大于 bundle cost。原 #6 sweep 后 baseline verify
  暴露的 false positive,本 change baseline verify 时一并修。

## Surprises

- **CC-202 pattern 扩展到 PPO 0 churn**:预期 PPO alias 切换可能涉及
  test 改动(test 用 `isinstance(cfg.agent, PPOAgentShapeCfg)` assert
  独立 dataclass);实际 0 test 改动 — Python alias 是直接 class reference,
  `isinstance(x, ObsShape) is isinstance(x, PPOAgentShapeCfg)`,与
  CFR alias 行为完全一致。
- **bundled #6 smoke_full.toml fixes 是 false positive 不是 bug**:
  #6 (`paradigm-smoke-full-tier`)ship 时 5 smoke_full.toml 走的是
  `meta.extends = "smoke.toml"` 继承,parent smoke.toml 已含 `paradigm`
  字段;但 `test_shipped_configs_load_successfully` 用 legacy AZ loader
  抓所有 `configs/**/*.toml`,smoke_full.toml hybrid 格式被误抓后
  validator 报缺 `paradigm` 字段。修法:test 加 format detection
  (`extends` 或 `paradigm.X` nested 即 hybrid → skip legacy loader),
  并在 smoke_full.toml 显式 redundant 写 `paradigm = "<X>"`(defense in
  depth,direct load 也 OK)。

## Spec delta summary

本 change 修订 **1 个 capability spec**(paradigm-ppo):

- **paradigm-ppo/spec.md**:
  - **MODIFY M-CS-PPO-1** P7.8 `PPOAgentShapeCfg 字段对齐` → 升级为
    `PPOAgentShapeCfg = ObsShape` alias(从字段集对齐 → type 对齐),与
    BC/AZ/DMC `AgentShapeCfg = ObsShape` 一致
  - **MODIFY M-CS-PPO-2**:`PPOParadigmConfig` 新增 `inherit
    ParadigmConfigBase` 子句(P7 新加 SHALL P7.9)
  - **MODIFY M-CS-PPO-3**:`from_dict` 加 version + paradigm 校验
    (P7 新加 SHALL P7.10)
  - **ADD A-CS-PPO-4**:`make_ppo_default_shape() -> ObsShape` factory
    (P7 新加 SHALL P7.11,延续 P7.1-P7.8 编号)
  - Status section +Revised entry(2026-05-17 closure of CC-206 PPO defer)
  - Cross-references 加 `cfg-schema-unification` archive 链接

- **config-schema/obs-shape-unification.md** invariant N1.4 + N5.5:由
  `ppo-structural-backbone-migration` 已修订(PPO 字段对齐已 ship);本
  change 不再触碰,只在 paradigm-ppo/spec.md 加 cross-ref。CC-206 closure
  status 由 5 paradigm coverage 自动满足。

## DECISIONS index

本 change 无新 DECISIONS file(轻量 follow-up,所有决策 inherit from
预 archived 的 cfg-schema-unification CC-201..209 + ppo-structural-backbone-
migration 2.x SELECTED)。Cross-reference:

- `cfg-schema-unification` [CC-202] type alias pattern → applied to PPO
- `cfg-schema-unification` [CC-204] version enum closed set → applied to PPO
- `cfg-schema-unification` [CC-205] paradigm mismatch raise → applied to PPO
- `cfg-schema-unification` [CC-206] PPO defer → **closed** by this change
- `ppo-structural-backbone-migration` [2.4] PPOAgentShapeCfg 字段对齐 →
  本 change 升级为 type alias
- `core-network-generic-promotion` D3 endpoint → fulfilled
