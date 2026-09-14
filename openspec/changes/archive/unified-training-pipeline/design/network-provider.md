---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../design.md
---

# Network Provider — Local vs Remote 抽象 + Weights SHM

> 治理 `training-architecture/spec.md` SHALL #4(Inference placement
> orthogonal)+ #9(Weights sync 协议)落地细节。

## 1. Two implementations

### 1.1 LocalNetworkProvider

- 进程内持有 `network: ActorCritic` 副本
- `forward(obs, mask)` 直接 `self.network(obs, mask)`
- `update_weights(version_tag)` 从 Weights SHM slot 拉 state_dict 加载到
  本地 network
- 后台线程 `weights_watcher.py` poll SHM 检测新版本(default 100ms)

```python
class LocalNetworkProvider:
    def __init__(self, network: ActorCritic, weights_shm: WeightsSHM,
                 device: str, version_tag: str = "latest"):
        self.network = network.to(device).eval()
        self.shm = weights_shm
        self.version_tag = version_tag
        self.version = -1
        self._watcher_thread.start()

    def forward(self, obs, mask):
        with torch.no_grad():
            return self.network(obs, mask)

    def update_weights(self, version_tag=None):
        tag = version_tag or self.version_tag
        new_state, new_version = self.shm.read(tag)
        if new_version > self.version:
            self.network.load_state_dict(new_state)
            self.version = new_version
        return self.version
```

### 1.2 RemoteNetworkProvider

- 持 IPC client(Unix socket or shared memory queue)
- `forward(obs, mask)` 序列化 obs → 发请求 → 阻塞等响应
- Inference server K 个进程 + GPU batched forward + 队列消费
- `update_weights` 是 no-op(server 端有自己的 watcher)

```python
class RemoteNetworkProvider:
    def __init__(self, client: InferenceClient, version_tag: str):
        self.client = client
        self.version_tag = version_tag

    def forward(self, obs, mask):
        return self.client.request(obs, mask, self.version_tag)

    def update_weights(self, version_tag=None):
        # no-op; server 端自治 weights
        return self.client.last_server_version()
```

## 2. Provider factory

```python
def build_network_provider(
    inf_cfg: InferenceCfg,
    network: ActorCritic,
    weights_shm: WeightsSHM,
    role: str,                       # "actor" | "eval"
) -> NetworkProvider:
    device = inf_cfg.device or "cpu"
    if inf_cfg.placement == "local":
        return LocalNetworkProvider(
            network=copy_network(network, device),
            weights_shm=weights_shm,
            device=device,
            version_tag=inf_cfg.version_tag,
        )
    elif inf_cfg.placement == "remote":
        client = InferenceClient(
            socket_path=inf_cfg.remote.socket_path,
            timeout_ms=inf_cfg.remote.batch_timeout_ms,
        )
        return RemoteNetworkProvider(client, version_tag=inf_cfg.version_tag)
    raise ValueError(f"unknown placement: {inf_cfg.placement}")
```

R1-R7 schema 校验保证 inf_cfg 已闭合(详
[`./config-layered.md`](./config-layered.md))。

## 3. Weights SHM 协议

```
weights_shm/
├── slot_latest/                   # actor 拉这个,learner 持续覆盖
│   ├── version.int (atomic)
│   ├── state_dict.pt (mmap, double-buffer)
│   └── ready.flag
├── slot_snapshot_<eval_id>/       # eval worker 拉这个,frozen 直到 eval 结束
│   ├── version.int
│   ├── state_dict.pt
│   └── ready.flag
└── lock.fcntl
```

写流程(learner 端):
1. 取 lock_fcntl(slot_latest)
2. 写 state_dict.pt 到 standby buffer
3. atomic swap version pointer
4. 释放 lock

读流程(actor 端):
1. poll version.int(no lock)
2. 若 version > self.version → 取 read lock → mmap state_dict.pt → load
3. 释放 lock

Eval 触发时 learner snapshot:`cp slot_latest → slot_snapshot_<eval_id>`,
EvalWorker 用对应 snapshot,不影响 actors。Multi-version slot 数 = 1 (latest)
+ K (concurrent eval),GICG 默认 K=1。

## 4. Version tag semantics

| version_tag | 来源 | 谁读 |
|---|---|---|
| `"latest"` | Learner 持续覆盖 | Actors(可接受 stale weights) |
| `"snapshot_eval"` | Eval scheduler 触发 snapshot | EvalWorker(eval 期间 frozen) |
| `"snapshot_<id>"` | 显式 ckpt name | Replay tool / arena |

`update_weights` 在 actor 端 poll latest,在 eval 端只 update 一次
(`reset` 时拉对应 snapshot)。

## 5. Stale weights 容忍

Async actor 用落后 weights 采样 GICG 接受(详 memory feedback_stale_weights_ok)。
Stale steps 写 metrics 作监控:`weights_version_lag = learner_version -
actor_version`。Spike > 100 step 算 warning(暗示 SHM I/O 瓶颈)。

## 6. Cross-references

- Async 进程拓扑 → [`./async-pipeline.md`](./async-pipeline.md)
- Cfg placement schema R1-R7 → [`./config-layered.md`](./config-layered.md)
- EpisodeRunner 调 Provider → [`./episode-runner.md`](./episode-runner.md)
- 主 spec → [`../../../../specs/training-architecture/protocols.md`](../../../../specs/training-architecture/protocols.md)
