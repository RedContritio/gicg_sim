# core-network-generic-promotion — Architecture

本文件承接 design.md Architecture 节详细内容 — 4 个新结构层 + 5 paradigm 全切。

## 1. `core/network/` 新形态

```
training/core/network/                  ← legacy/ 子目录消失
├── __init__.py                         (导出 ActorCritic + AgentBase + 子组件)
├── encoder.py                          (沿用,4 个 encoder class 不变)
├── heads.py                            (沿用,5 个 head class 不变)
├── hook_emb.py                         (沿用)
├── struct_readout.py                   (沿用,C1v7 invariant)
├── typed_damage.py                     ← mv 自 legacy/typed_damage.py
├── actor_critic.py                     ← 重写 thin composition
└── agent_base.py                       ← mv 自 legacy/ + DI 改造
```

**`ActorCritic` thin composition**(~80 行,取代 god class 207 行 + CoreActorCritic 182 行):

```python
class ActorCritic(nn.Module):
    """Composition of encoders + readout + heads. Paradigm picks heads."""
    def __init__(
        self,
        encoders: nn.ModuleDict,           # {hook, counter, card, cross_attn}
        readout: StructReadoutBlock,
        heads: nn.ModuleDict,              # {policy?, value?, q?, avg_policy?, delta?}
        typed_damage: TypedDamageEncoder | None = None,
    ): ...

    def forward(self, obs_dict, refs, payments) -> dict[str, Tensor]:
        # encode → readout → heads dispatch → return {head_name: tensor}
        ...
```

`make_actor_critic(cfg, head_kinds: set[str], use_typed_damage: bool)` 工厂函数装配 5 paradigm 各自需要的 head subset。

**`AgentBase` DI 接口**:

```python
class AgentBase:
    def __init__(self, cfg: AgentConfig, hook_encoder: HookEncoder, device: str = 'cpu'):
        self._hook_encoder = hook_encoder   # DI,不再 self.net.hook_encoder
        # per-game cache slots ...

    def encode_static(self, static_obs_np): ...
    def parse_dynamic(self, dyn_obs_np): ...
    def game_start(self, static_obs_np) -> dict: ...
```

子类构造时注入 `network.encoders['hook']` 作为 `hook_encoder`,解除"self.net 必须是 ActorCritic 且必须有 .hook_encoder attribute"的硬约束(测试可 inject mock)。

## 2. `core/cfg/` 共享 base(新增)

```
training/core/cfg/
├── __init__.py
├── shape.py                            ObsShape dataclass(5 paradigm 共享)
└── base.py                             ParadigmConfigBase(version + paradigm + shape)
```

```python
# core/cfg/shape.py
@dataclass(frozen=True)
class ObsShape:
    n_counter_slots: int
    n_hooks: int
    max_tokens_per_hook: int
    max_actions: int
    d_model: int = 128
    dropout: float = 0.0
    n_cross_layers: int = 2

# core/cfg/base.py
@dataclass(frozen=True)
class ParadigmConfigBase:
    version: str = "1.0.0"
    paradigm: str = ""          # 'az' | 'bc' | 'cfr' | 'dmc' | 'ppo'
    shape: ObsShape = ...
```

Paradigm cfg(`AZParadigmConfig` 等)compose `ParadigmConfigBase` + 各自 sub-cfg(MCTSCfg / TrainStepCfg / RolloutCfg / ...)。原 5 paradigm 的 `AgentShapeCfg` / `CFRAgentShapeCfg` / `PPOAgentShapeCfg` 全部删除,替换为共享 `ObsShape`。

## 3. Ckpt self-describing schema

```python
torch.save({
    'paradigm': cfg.paradigm,           # 'az' | 'bc' | ...
    'cfg_version': cfg.version,
    'cfg': asdict(cfg),                 # 完整,可重构造
    'net_kind': 'ActorCritic',          # | 'PPOActorCritic' (PPO 收编后仍是 ActorCritic)
    'net_state_dict': self.net.state_dict(),
    'git_commit': <hash from subprocess>,
    'created_at': <iso8601>,
}, path)
```

新 `tools/ckpt/info.py`:
```bash
$ python -m tools.ckpt.info artifacts/.../epoch_5.pt
paradigm:    az
cfg_version: 1.0.0
net_kind:    ActorCritic (encoders={hook,counter,card,cross_attn}, heads={policy,value,delta})
git_commit:  abc123def
created_at:  2026-05-17T14:23:11+08:00
shape:       n_counter_slots=256, n_hooks=32, max_actions=128, d_model=128
```

Load 时校验 `paradigm` + `cfg_version` 匹配,否则抛清晰 error(不再 silent shape mismatch)。

## 4. `tools/runs/` registry 工具集(新增)

```
tools/runs/
├── __init__.py
├── schema.py                           Run metadata TOML schema(JSON Schema 等价)
├── register.py                         tools.runs.register CLI
├── complete.py                         tools.runs.complete CLI
├── list.py                             tools.runs.list CLI(取代 registry.md)
├── show.py                             tools.runs.show <run_id> CLI
└── sync.py                             tools.runs.sync pull/push <host> rsync 包装
```

Run metadata 落 `artifacts/runs/<id>.toml`(gitignored),schema:

```toml
run_id = "r013"
label = "r013_first_after_redesign"
type = "r"                              # 'r' | 's'
timestamp = "2026-05-17T14:00:00+08:00"
paradigm = "az"
cfg_file = "configs/az/runs/r013.toml"
cfg_checksum = "sha256:abc..."          # 防 cfg 篡改
git_commit = "abc123def"
host = "macbook-pro"                    # uname -n,跨机 sync 区分
status = "pending"                      # enum: pending|running|done|failed|killed

[summary]
wall = "16.3min"
description = "AZ Stage 3 + init_from_ckpt=r012 epoch_3"

[result.gauntlet]
n = 16
random = 0.875
mcts_pure_200 = 0.5625

[result.training]
final_loss = 1.045
n_games_completed = 400

[notes]
text = "..."
```

`tools.runs.sync` 用 rsync 同步 `artifacts/runs/`(不同步 ckpt / replays):

```bash
tools.runs.sync pull dev@192.0.2.10:/d/gicg_dev/
# 内部: rsync -av --update dev@.../artifacts/runs/ artifacts/runs/

tools.runs.sync push dev@192.0.2.10:/d/gicg_dev/
# 内部: rsync -av --update artifacts/runs/ dev@.../artifacts/runs/
```

## 5. configs/ 按 paradigm 重组

```
configs/                                ← 全删旧 active/shipped/smoke/_archived,重组
├── az/
│   ├── default.toml                    标杆/参考
│   ├── smoke.toml                      test_az_smoke 用
│   └── runs/
│       └── r013_first_after_redesign.toml
├── bc/
│   ├── default.toml
│   ├── smoke.toml
│   └── runs/
├── cfr/
├── dmc/
└── ppo/
```

示例 `configs/az/default.toml`:

```toml
version = "1.0.0"
paradigm = "az"

[shape]
n_counter_slots = 256
n_hooks = 32
max_tokens_per_hook = 8
max_actions = 128
d_model = 128
n_cross_layers = 2

[mcts]
n_simulations = 200
c_puct = 1.5

[train_step]
batch_size = 256
lr = 1e-3
```
