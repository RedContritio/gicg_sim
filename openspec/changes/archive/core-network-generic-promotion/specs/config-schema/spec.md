---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: config-schema
---

# Spec delta — config-schema

本 delta 增 `ObsShape` 共享 base + `ParadigmConfigBase` + cfg `version` 字段 + ckpt self-describing schema。详 `../../proposal.md`。

## ADD

### A1. ObsShape 共享 dataclass

> **N1. ObsShape unification**:`training/core/cfg/shape.py::ObsShape`
> SHALL be 5 paradigm 共享的 obs shape dataclass:
>
> ```python
> @dataclass(frozen=True)
> class ObsShape:
>     n_counter_slots: int
>     n_hooks: int
>     max_tokens_per_hook: int
>     max_actions: int
>     d_model: int = 128
>     dropout: float = 0.0
>     n_cross_layers: int = 2
> ```
>
> Paradigm cfg(`AZParadigmConfig` 等)SHALL compose `ObsShape` 作 `shape`
> 字段,SHALL NOT 维护 paradigm-local 替代(如 `AgentShapeCfg` /
> `CFRAgentShapeCfg` / `PPOAgentShapeCfg`)。

### A2. ParadigmConfigBase

> **N2. ParadigmConfigBase**:`training/core/cfg/base.py::ParadigmConfigBase`
> SHALL be 所有 paradigm cfg 的 base:
>
> ```python
> @dataclass(frozen=True)
> class ParadigmConfigBase:
>     version: str = "1.0.0"          # cfg schema version, MUST bump on schema change
>     paradigm: str = ""              # 'az' | 'bc' | 'cfr' | 'dmc' | 'ppo'
>     shape: ObsShape = ...
> ```
>
> 5 paradigm `<Paradigm>ParadigmConfig` SHALL 继承或 compose 这个 base。

### A3. cfg version 字段

> **N3. cfg version contract**:每个 `<Paradigm>ParadigmConfig` SHALL
> include `version: str` 字段,SHALL 默认为 `"1.0.0"`。Cfg schema 任何
> 字段增减 / 类型改 / 默认值改 SHALL trigger version bump。Load 时
> SHALL 校验 `ckpt['cfg_version'] == current_cfg.version`,不匹配 SHALL
> raise clear `CfgVersionMismatchError`,SHALL NOT silent shape-mismatch
> at forward time。

### A4. Ckpt self-describing schema

> **N4. Ckpt self-describing**:`torch.save` SHALL store complete metadata
> blob:
>
> ```python
> {
>     'paradigm': str,                # 'az' | ...
>     'cfg_version': str,             # e.g. '1.0.0'
>     'cfg': dict,                    # asdict(cfg), full reconstructable
>     'net_kind': str,                # 'ActorCritic' | ...
>     'net_state_dict': OrderedDict,  # nn.Module.state_dict()
>     'git_commit': str,              # subprocess.check_output(['git', 'rev-parse', 'HEAD'])
>     'created_at': str,              # iso8601 UTC
> }
> ```
>
> `tools/ckpt/info.py` SHALL provide CLI to dump metadata without loading
> nn.Module(纯 dict inspection)。

### A5. configs/ 按 paradigm 一级组织

> **N5. configs/ layout**:TOML cfg files SHALL be organized by paradigm
> as primary axis:
>
> ```
> configs/<paradigm>/
> ├── default.toml          # 标杆 / 参考
> ├── smoke.toml            # smoke test 用
> └── runs/
>     └── <run_id>.toml     # per-production-run cfg(reproducibility source)
> ```
>
> SHALL NOT 使用生命周期扁平结构(旧 `configs/{active,shipped,smoke,_archived}/`)。

## REMOVE

### R1. Paradigm-local AgentShapeCfg

各 paradigm 自维护 `AgentShapeCfg` / `CFRAgentShapeCfg` / `PPOAgentShapeCfg` 等同语义不同表面的 dataclass SHALL 全部删除,替换为 `core.cfg.ObsShape`。

理由:同语义共享,新加 paradigm 不需 reinvent。

### R2. 旧 ckpt schema(无 paradigm / cfg_version 字段)

旧 ckpt schema `{'net': state_dict, 'cfg': vars(cfg)}` SHALL 不再被支持。Load 旧 ckpt SHALL raise `CkptSchemaError`,SHALL NOT silently downgrade。

理由:无 paradigm 字段 → caller 必须预知,违反 self-describing。新 schema 后任何 ckpt 都可 standalone inspect。

## Cross-references

- `proposal.md` — change 整体动机
- `design.md` 第 2-3 节 — `core/cfg/` 新形态 + ckpt schema 详细
- `tasks.md` Phase 3 — cfg 层重组实施
- `../network-architecture/spec.md` invariant A4 — Backbone unification(cfg ObsShape 共享是 backbone 共享的前提)
