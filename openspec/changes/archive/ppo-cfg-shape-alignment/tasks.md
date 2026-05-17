# ppo-cfg-shape-alignment — tasks

Lightweight follow-up(~30-50 LOC core + bundled fixes from #6 baseline sweep)。

## T1 — Core cfg alignment

- [x] T1.1 `training/core/cfg/factories.py`:add `make_ppo_default_shape() -> ObsShape`(d_model=128 / n_cross_layers=2,与 AZ baseline 同)+ update module docstring "5 paradigm × 1 factory each"
- [x] T1.2 `training/core/cfg/__init__.py`:export `make_ppo_default_shape`,update docstring & __all__
- [x] T1.3 `training/paradigms/ppo/config.py`:
  - import `ObsShape + ParadigmConfigBase + build_shape_from_toml + make_ppo_default_shape` from `training.core.cfg`
  - `PPOAgentShapeCfg = ObsShape` alias(replaces dataclass def)
  - `PPOParadigmConfig(ParadigmConfigBase)` inheritance + `paradigm: str = 'ppo'`
  - `agent: ObsShape = field(default_factory=make_ppo_default_shape)`
  - `from_dict`:add version + paradigm validation + `build_shape_from_toml` for agent merge
- [x] T1.4 verify:`pytest -k "ppo or cfg"` 160/160 pass

## T2 — Bundled #6 sweep fixes(发现自 #7 baseline verify)

- [x] T2.1 5 `configs/<paradigm>/smoke_full.toml`:add `paradigm = "<X>"` 字段 to `[meta]` section(per #5 dispatch convention 要求)
- [x] T2.2 `training/tests/test_config_loader.py::test_shipped_configs_load_successfully`:add hybrid TOML format detection(`extends` in meta / `paradigm.X` nested → unified loader,skip legacy)— 修 #6 smoke_full.toml hybrid 格式被 legacy loader 误抓的 false positive
- [x] T2.3 verify:`pytest training/tests/test_config_loader.py` 12/12 pass

## T3 — Verification

- [x] T3.1 Full sweep:`pytest -n 4 training/tests/ tools/` (per CLAUDE.md ignore list)→ 1159 passed / 10 skipped / 0 failed
- [x] T3.2 openspec_indices pass

## T4 — Commit

- [x] T4.1 commit:1 single commit `ppo-cfg-shape-alignment: ship — 5/5 paradigm cfg dataclass 对称 + smoke_full meta paradigm fix`
- [x] T4.2 archive(post `/opsx:archive`)

## Estimated workload(actual)

| Item | LOC |
|---|---|
| core/cfg/factories.py + __init__.py | +20 / -8 |
| paradigms/ppo/config.py | +30 / -45 |
| 5 smoke_full.toml `paradigm = "<X>"` 1-line each | +5 |
| test_config_loader.py hybrid detect | +6 / -2 |
| OpenSpec propose docs(proposal/tasks/spec delta) | +200 |
| **Total** | **~260 LOC(60 code + 200 docs)** |
