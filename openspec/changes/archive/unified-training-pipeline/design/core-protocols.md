---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../design.md
---

# Core Protocols — 6 protocol 接口契约

> 详细定义 6 个 paradigm-agnostic protocol 的方法签名 + 实现 contract。
> 锚定 `training-architecture/spec.md` SHALL #2(Paradigm protocol)+ #4
> (NetworkProvider 抽象)+ #5(EpisodeRunner 共享)。

## 1. Paradigm

`training/core/protocols.py` 主接口。每 paradigm SHALL 实现:

```python
class Paradigm(Protocol):
    name: str
    config: ParadigmConfig

    def make_network(self, cfg: TrainingConfig) -> ActorCritic:
        """构造 ActorCritic(共享 encoder + paradigm head 组合)。"""

    def make_collector(self, cfg: TrainingConfig, network: ActorCritic) -> Collector:
        """构造 Collector(serial or async,由 cfg.pipeline.mode 决定)。"""

    def make_buffer(self, cfg: TrainingConfig) -> Buffer:
        """构造 Buffer(replay / reservoir / rollout / dataset)。"""

    def make_loss(self, cfg: TrainingConfig) -> LossComputer:
        """构造 LossComputer(paradigm-specific loss aggregation)。"""

    def make_optimizer(self, network: ActorCritic) -> torch.optim.Optimizer:
        """构造 optimizer(Adam / SGD,由 paradigm cfg 决定)。"""

    def step_schedule(self, state: PipelineState) -> StepPlan:
        """driver 调用,返回本 step 的 collect / train / eval flag。"""
```

`step_schedule` 是 paradigm 自治 cadence 关键:on-policy(PPO)每 collect
必 train,off-policy(AZ/DMC)collect 与 train 解耦比 N:M。

## 2. Collector

```python
class Collector(Protocol):
    requires_network_in_collect: bool  # AZ/DMC/PPO/CFR True; BC False

    def collect(self, n_episodes: int, provider: NetworkProvider) -> CollectResult:
        """跑 N 个 episode(serial)或返回最近收到的 SHM 切片(async)。

        Returns CollectResult(transitions, episode_stats, runtime_metrics).
        """

    def close(self) -> None:
        """释放进程 / SHM(async only)。"""
```

实现:
- `EpisodeCollector`(serial,for smoke / debug)
- `MultiProcessActorCollector`(async,N 进程 + SHM ring + provider)
- `TraversalCollector`(CFR,parallel by thread)
- `RolloutCollector`(PPO,vec env)
- `DatasetCollector`(BC,一次性 push,no env)

## 3. Buffer

```python
class Buffer(Protocol):
    capacity: int
    size: int

    def push(self, batch: TransitionBatch) -> None:
        """加入 batch。SHM buffer 由 actor 端直接写,push 仅 learner 端
        bookkeeping。"""

    def sample(self, n: int, rng: np.random.Generator) -> TrainBatch:
        """随机采样 n 条(可选 dedup by key)。"""

    def clear(self) -> None:
        """清空(PPO 每 iter call)。"""
```

实现 in `training/core/buffer/`:
- `ReplayBuffer`(static dedup,for AZ/DMC)
- `ReservoirBuffer`(CFR,for advantage / strategy reservoir)
- `RolloutBuffer`(PPO,每 iter clear)
- `DatasetBuffer`(BC,全量 in-memory or memmap)
- `SHMRingBuffer`(async-mode,multi-process 共享)

## 4. LossComputer

```python
class LossComputer(Protocol):
    def compute(self, network: ActorCritic, batch: TrainBatch) -> LossResult:
        """returns LossResult(loss, breakdown_dict, grad_metrics)。

        breakdown_dict 列 policy_loss / value_loss / entropy 等,driver 写
        metrics.jsonl 时 unpack。"""
```

每 paradigm 自有 Loss:
- AZ:`AlphaZeroLoss`(KL policy + MSE value)
- DMC:`DMCLoss`(MSE logit-as-Q + value MSE,详 dmc_review §B.1)
- CFR:`CFRLoss`(advantage MSE + strategy MSE,reservoir-weighted)
- PPO:`PPOLoss`(clipped surrogate + value MSE + entropy bonus)
- BC:`BCLoss`(CE hard target 或 KL soft target)

## 5. EpisodePolicy

```python
class EpisodePolicy(Protocol):
    deterministic: bool          # eval=True, actor=False
    epsilon: float               # for ε-greedy paradigms

    def act(self, obs: Obs, mask: ActionMask, provider: NetworkProvider) -> ActionOut:
        """返回 (action_idx, action_meta)。

        action_meta 含 logits / value / mcts_stats(per paradigm)以供 buffer
        push 用。"""

    def reset(self) -> None:
        """新 episode 开始(reset MCTS tree / clear history)。"""
```

每 paradigm 自有 EpisodePolicy:
- AZ:`MCTSPolicy`(IS-MCTS + leaf eval via provider)
- DMC:`EpsilonGreedyPolicy`(argmax Q + ε exploration)
- CFR:`AveragePolicyAct`(avg strategy network forward)
- PPO:`PPOPolicy`(sample from policy logits)
- BC:`BCPolicy`(argmax policy logits)

`EpisodeRunner` 调 `policy.act()`,完全 paradigm-agnostic。

## 6. NetworkProvider

```python
class NetworkProvider(Protocol):
    def forward(self, obs: Obs, mask: ActionMask) -> NetworkOut:
        """前向。Local 直接 model.forward;Remote 走 IPC 发 server。"""

    def update_weights(self, version_tag: str = "latest") -> int:
        """拉取最新 weights(local poll SHM / remote no-op)。返回新版本号。"""

    def current_version(self) -> int:
        """当前 weights 版本(供 metrics 写 stale_steps)。"""

    def close(self) -> None:
        """释放 IPC / SHM 句柄。"""
```

实现:
- `LocalNetworkProvider`(model copy 在进程内,poll SHM 同步 weights)
- `RemoteNetworkProvider`(IPC 调 inference server)

`provider_factory.build_network_provider(inference_cfg, network)` 根据
`placement` 字段返回对应实现(详
[`./network-provider.md`](./network-provider.md))。

## 7. Cross-references

- 主 spec → [`../../../../specs/training-architecture/protocols.md`](../../../../specs/training-architecture/protocols.md)
- Driver loop 调用 protocol → [`./pipeline-driver.md`](./pipeline-driver.md)
- EpisodeRunner 调 EpisodePolicy + NetworkProvider →
  [`./episode-runner.md`](./episode-runner.md)
- Provider 实现细节 → [`./network-provider.md`](./network-provider.md)
- Paradigm-specific 接入 → 各 `../specs/paradigm-<name>/spec.md`
