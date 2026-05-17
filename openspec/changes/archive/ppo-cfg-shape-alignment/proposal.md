# PPO cfg dataclass alignment — 闭 5/5 paradigm cfg 对称

**Status:** Active change(implementation complete,pending archive)
**Date opened:** 2026-05-17
**Supersedes:** None
**Affected specs:**
- `paradigm-ppo/spec.md`(MODIFY — closes CS-PPO-1 ObsShape unification gap)
- `config-schema/spec.md` invariant N1.2(closes CC-206 PPO partial)

## Why

post `core-network-generic-promotion` 4 个 follow-ups ship 后,5 paradigm 中 4 个(AZ/BC/CFR/DMC)cfg dataclass 已通过 `cfg-schema-unification`(#3)用 `ObsShape` + `ParadigmConfigBase` 统一,但 PPO 仍 paradigm-local `PPOAgentShapeCfg` dataclass(字段已与 BC `AgentShapeCfg` 对齐 per `ppo-structural-backbone-migration` #4 CS-PPO-1,但 type 未 unify)。

DECISIONS log:
- `cfg-schema-unification` CC-206:PPO 不接(等 #4 backbone 后)
- `ppo-structural-backbone-migration` D-101 closure:5 paradigm 共用 backbone done,cfg dataclass 对称 follow-up
- `core-network-generic-promotion` DECISIONS endpoint:推荐 D3(此 change)闭 5/5 cfg dataclass 对称

scope ~30-50 LOC + 1 ADR + 1 spec delta。**轻量 follow-up**,完成本 change 后 5 paradigm cfg 完全对称(剩 5% 是 CFR algorithm-inherent paradigm-specific divergence per D1/D2 intentional defer)。

## What

1. **PPO config.py**:
   - inherit `ParadigmConfigBase`(version + paradigm metadata,N2)
   - `PPOAgentShapeCfg = ObsShape` alias(CC-202 pattern,extended to PPO)
   - `agent: ObsShape = field(default_factory=make_ppo_default_shape)`
   - `from_dict` 加 `version + paradigm` 校验(CC-204/205 pattern)
   - 用 `build_shape_from_toml(agent_d, make_ppo_default_shape)` 而非直接 ObsShape 构造
2. **core/cfg/factories.py**:加 `make_ppo_default_shape() -> ObsShape`(d_model=128 / n_cross_layers=2,与 AZ 同 baseline,post-#4 structural defaults)
3. **core/cfg/__init__.py**:export `make_ppo_default_shape`
4. **Bundled fixes**(发现自 #6 ship 后 baseline sweep):
   - 5 `configs/<paradigm>/smoke_full.toml`:加 `paradigm = "<X>"` to `[meta]` section(per #5 dispatch convention)
   - `training/tests/test_config_loader.py::test_shipped_configs_load_successfully`:加 hybrid TOML format detection(`extends` / `paradigm.X` nested → unified loader path,skip legacy AZ loader)

## Affected specs

- `paradigm-ppo/spec.md` MODIFY CS-PPO-1 (closure note)+ add cross-ref to `config-schema/spec.md` N1.2
- `config-schema/spec.md` invariant N1.2 已 5/5 paradigm coverage(CC-206 closure note)

## Out of scope

- PPO smoke_full 4/5 skip 修复(per #6 SF-105 4 个 follow-up changes 已 queued:az-pool-spec-type-fix / ppo-rollout-card-pool-none-fix / cfr-driver-buffer-multihead-fix / bc-smoke-dataset-fixture)
- CFR backbone unification(D1 intentional defer)
- CFR ckpt schema unification(D2 intentional defer per D-207)

## Verification

- `pytest -k "ppo or cfg"` pass(160 tests post-change)
- `pytest training/tests/test_config_loader.py` pass(12 tests)
- Full sweep 1159 passed / 10 skipped / 0 failed
