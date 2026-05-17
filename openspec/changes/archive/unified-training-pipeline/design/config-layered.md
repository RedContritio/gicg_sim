---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../design.md
---

# Config Layered — TOML schema + R1-R7 placement + device/seed 继承

> 治理 `training-architecture/spec.md` SHALL #8(Cfg 多层继承)落地。完
> 整字段规约由本 change 的 `../specs/config-schema/spec.md` ship 进
> `openspec/specs/config-schema/`。本文件聚焦设计意图 + 完整示例 +
> R1-R7 规则解释。

## 1. 完整 cfg 示例

```toml
# meta
[meta]
seed = 42                       # 必填(无 hard default)
device = "cpu"                  # hard default,可被各 component 覆盖
paradigm = "dmc"
run_label = "r013_dmc_v_phase2_stage3"

# pipeline
[pipeline]
mode = "async"                  # "serial" | "async"
num_actors = 24

[pipeline.inference]
placement = "local"             # "local" | "remote"
version_tag = "latest"
# device 省略 → 继承 meta.device

# 仅当 placement = "remote" 时读
# [pipeline.inference.remote]
# pool_size = 2
# max_batch = 64
# batch_timeout_ms = 2

[pipeline.learner]
# device 省略 → 继承 meta.device

# eval
[eval]
n_workers = 4
schedule = "every_1000_steps"

[eval.inference]
placement = "local"
version_tag = "snapshot_eval"
# device 省略 → 继承 meta.device(独立 fallback,不跟 pipeline.inference)

# scenario / env
[scenario]
pool = "v_phase2"
team_0 = ["凯亚"]
team_1 = ["凯亚"]
max_rounds = 15
deck_padding = { card = "碌碌无为", target_size = 15 }

# paradigm-specific(schema 由 cfg.meta.paradigm 决定)
[paradigm]
epsilon = 0.01
batch_size = 32
buffer_cap = 100_000
lr = 1e-4
weight_decay = 1e-4
```

## 2. INHERITED_FIELDS registry

```python
INHERITED_FIELDS = {
    "device": {
        "mode": "fallback",
        "hard_default": "cpu",
        "chains": {
            "pipeline.learner.device":   ["meta.device"],
            "pipeline.inference.device": ["meta.device"],
            "pipeline.inference.remote.device": [
                "pipeline.inference.device", "meta.device",
            ],
            "eval.inference.device":     ["meta.device"],
            "eval.inference.remote.device": [
                "eval.inference.device", "meta.device",
            ],
        },
    },
    "seed": {
        "mode": "fallback+derive",
        "hard_default": None,                  # meta.seed 必填
        "chains": {
            "pipeline.learner.seed":  ["__derive(learner)"],
            "pipeline.actor.seed":    ["__derive(actor, instance_id)"],
            "eval.scenario.seed":     ["__derive(eval_scenario)"],
            "eval.worker.seed":       ["__derive(eval_worker, instance_id)"],
        },
    },
}

def derive_seed(master: int, role: str, instance_id: int = 0) -> int:
    h = hashlib.blake2s(f"{role}/{instance_id}".encode(), digest_size=4).digest()
    return (master ^ int.from_bytes(h, "big")) & 0x7FFFFFFF
```

`device` 是单纯 fallback chain;`seed` 增加 `__derive(role, id)` 机制
保证多 actor / multi worker 各自 RNG 独立 + 可重现。

## 3. R1-R7 placement schema 规则

| # | Rule | Trigger |
|---|---|---|
| **R1** | `placement` 必填,枚举 ∈ `{"local", "remote"}`(case-sensitive) | typo / 缺失 → raise |
| **R2** | `placement == "local"` ⟺ 无 `[pipeline.inference.remote]` 段 | local + 有 remote 段 → raise |
| **R3** | `placement == "remote"` ⟺ 有 `[remote]` 段且段内 `pool_size`/`max_batch`/`batch_timeout_ms` 必填 | placement=remote 缺段 / 段内缺字段 → raise |
| **R4** | InferenceCfg 顶层字段封闭 `{placement, device, version_tag, remote}` | 顶层写 pool_size → raise unknown |
| **R5** | Device 全链路 None → raise "device unresolved" | meta / inference / remote 三层 device 全省 → raise(虽然 hard_default="cpu",but explicit) |
| **R6** | extends 继承时 placement override 必须同步子段 | child 改 placement="remote" 但未提供 [remote] 段 → raise |
| **R7** | dataclass:`InferenceCfg(placement: str, device: Optional[str], version_tag: str, remote: Optional[RemoteCfg])` | 无 dead field |

R5 边界 nuance:`hard_default="cpu"` 适用于 `meta.device`;若链中所有
override 节点都显式置 `device = ""`(空 string)→ raise(因为是 explicit
取消 fallback,vs 省略 = 接受 fallback)。

## 4. extends 链(多层继承)

Cfg 支持继承:

```toml
# configs/dmc/v_phase2_stage3.toml
extends = "configs/dmc/v_phase2_base.toml"

[paradigm]
buffer_cap = 200_000              # override base
```

resolver 顺序:
1. 递归加载 extends chain(深度 ≤ 5 防环)
2. 按从深到浅 deep merge(child override parent)
3. 解析 INHERITED_FIELDS fallback chain(注意:fallback 是同一 layer 内的 fallback,跟 extends 正交)
4. 检验 R1-R7
5. 检验 paradigm cfg schema(由 cfg.meta.paradigm 决定)

`extends` 是字段 in `[meta]` section,可选(无 extends 即 standalone)。

## 5. Cfg 校验时机

```python
# tools/run.py
def main(cfg_path: str, overrides: list[str]):
    cfg_dict = load_toml_with_extends(cfg_path)
    cfg_dict = apply_overrides(cfg_dict, overrides)  # --paradigm.lr=1e-5
    cfg_dict = resolve_inheritance(cfg_dict)         # device / seed
    validate_schema(cfg_dict)                        # R1-R7 + paradigm-specific
    cfg = build_training_config(cfg_dict)            # frozen dataclass
    run_pipeline(cfg)
```

`validate_schema` 失败 → raise ValueError + 错误字段路径 + 期望 vs 实际。
no silent fallback,no auto-fix。

## 6. Paradigm-specific cfg schema

`[paradigm]` 段的 schema 由 `cfg.meta.paradigm` 决定。每 paradigm
`paradigms/<name>/config.py` 定义:

```python
@dataclass(frozen=True)
class DMCParadigmConfig:
    epsilon: float
    batch_size: int
    buffer_cap: int
    lr: float
    weight_decay: float

    @classmethod
    def from_toml(cls, d: dict) -> "DMCParadigmConfig":
        validate_fields(d, expected=cls.__dataclass_fields__)
        return cls(**d)
```

`validate_fields` 校验:
- 字段名集合精确匹配(extra / missing → raise)
- 类型匹配(int / float / str / bool)
- 显式范围(e.g. epsilon ∈ [0, 1])

## 7. Cross-references

- Spec delta → [`../specs/config-schema/spec.md`](../specs/config-schema/spec.md)
- Provider factory 调 InferenceCfg → [`./network-provider.md`](./network-provider.md)
- Async pipeline 读 pipeline.async 字段 → [`./async-pipeline.md`](./async-pipeline.md)
- 主 spec(继承字段引用)→ [`../../../specs/training-architecture/spec.md`](../../../specs/training-architecture/spec.md) SHALL #8
- Thresholds 表(inheritance 字段 registry)→
  [`../../../specs/openspec-policy/thresholds.md`](../../../specs/openspec-policy/thresholds.md) §6
