---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../design.md
---

# Episode Runner — Actor + EvalWorker 共享原子

> 治理 `training-architecture/spec.md` SHALL #5(EpisodeRunner shared)落
> 地。消除 paradigm × runner 笛卡尔积:**1 个 EpisodeRunner + N 个
> EpisodePolicy = 5 paradigm × 2 角色支持**。

## 1. EpisodeRunner contract

`training/core/actor/episode_runner.py` 单文件 ~120 LOC:

```python
class EpisodeRunner:
    def __init__(self, env_factory: EnvFactory, opponent_registry: OpponentRegistry):
        self.env_factory = env_factory
        self.opponent_registry = opponent_registry

    def run(self, spec: EpisodeSpec, policy: EpisodePolicy,
            provider: NetworkProvider) -> EpisodeRecord:
        """单 episode 完整跑完。

        Args:
            spec: scenario_seed / opponent_id / starting_player / max_rounds
            policy: paradigm-specific ActOnly logic
            provider: forward 接口(local 或 remote)

        Returns:
            EpisodeRecord(transitions, reward, length, opponent_id, ...)
        """
        env = self.env_factory.make(spec)
        opp = self.opponent_registry.get(spec.opponent_id)
        policy.reset()

        obs, mask = env.reset()
        transitions = []
        done = False
        while not done:
            if env.current_player == 0:        # our turn
                action_out = policy.act(obs, mask, provider)
                next_obs, reward, done, info = env.step(action_out.action)
                transitions.append(Transition(obs, action_out, reward, mask, info))
            else:                                # opponent turn
                opp_action = opp.act(obs, mask)
                next_obs, _, done, info = env.step(opp_action)
            obs, mask = next_obs, info.get("next_mask", mask)

        return EpisodeRecord(
            transitions=transitions,
            final_reward=info["final_reward"],
            length=len(transitions),
            opponent_id=spec.opponent_id,
            scenario_seed=spec.scenario_seed,
        )
```

## 2. EpisodeSpec

```python
@dataclass(frozen=True)
class EpisodeSpec:
    scenario_seed: int               # determines starting hand / dice
    opponent_id: str                 # registered in OpponentRegistry
    starting_player: int             # 0 or 1
    max_rounds: int = 15
    deterministic: bool = False      # eval=True
    epsilon: float = 0.0             # actor=0.01 typical
    record_mcts_stats: bool = False  # AZ-specific
    record_value_pred: bool = False  # diagnostic
```

`spec.deterministic` + `spec.epsilon` 转发给 `policy.reset()`,policy 用
这些字段决定 act 行为。EpisodeRunner 本身不知道 paradigm。

## 3. Actor 集成

```python
# training/core/actor/actor_process.py
def actor_main(actor_id: int, cfg: TrainingConfig,
               weights_shm: WeightsSHM, transition_queue: SHMRing):
    seed = derive_seed(cfg.meta.seed, "actor", actor_id)
    env_factory = EnvFactory(cfg.scenario, seed=seed)
    opp_registry = OpponentRegistry.from_cfg(cfg.opponents)
    runner = EpisodeRunner(env_factory, opp_registry)

    network = build_network(cfg)
    provider = build_network_provider(cfg.pipeline.inference, network,
                                       weights_shm, role="actor")
    policy = load_paradigm(cfg.meta.paradigm).make_episode_policy(cfg, actor_id)

    while not should_stop():
        spec = sample_episode_spec(cfg, actor_id)
        record = runner.run(spec, policy, provider)
        transition_queue.push(record.transitions)
        log_episode_metrics(record)
        provider.update_weights()             # poll latest
```

## 4. EvalWorker 集成

```python
# training/core/eval/worker.py
def eval_worker_main(worker_id: int, cfg: TrainingConfig,
                     weights_shm: WeightsSHM, job_queue: Queue,
                     result_queue: Queue):
    seed = derive_seed(cfg.meta.seed, "eval_worker", worker_id)
    env_factory = EnvFactory(cfg.scenario, seed=seed)
    opp_registry = OpponentRegistry.from_cfg(cfg.opponents)
    runner = EpisodeRunner(env_factory, opp_registry)

    network = build_network(cfg)
    provider = build_network_provider(cfg.eval.inference, network,
                                       weights_shm, role="eval")
    policy = load_paradigm(cfg.meta.paradigm).make_episode_policy(
        cfg, worker_id, deterministic=True)

    while (job := job_queue.get()) is not None:
        provider.update_weights(version_tag=job.snapshot_tag)
        spec = EpisodeSpec(
            scenario_seed=job.seed, opponent_id=job.opponent,
            starting_player=job.starting_player, deterministic=True,
            epsilon=0.0,
        )
        record = runner.run(spec, policy, provider)
        result_queue.put(EvalResult(record, job))
```

## 5. 关键 invariants

1. **Runner 完全 paradigm-agnostic**:Runner 代码 grep "az\|dmc\|ppo\|cfr\|
   bc" 应 0 命中。
2. **Policy 是 paradigm 唯一变化点**:加新 paradigm = 写 1 个 EpisodePolicy
   类 + register in factory,Runner 不动。
3. **Eval 与 actor 共享 EnvFactory + OpponentRegistry**:scenario 配置变
   更影响双方,消除"actor 用 scenario A,eval 用 scenario B"的 silent
   drift(memory project_v_phase2_eval_schema_gaps fix)。
4. **Determinism 由 Spec 决定**:`spec.deterministic=True` + 同 seed → 同
   episode trace。Eval reproducibility 由此 invariant 保证。
5. **OpponentRegistry 共享**:actor mix(self / mcts_pure / historical
   ckpt)与 eval scenario(F1-Dn / mcts_200 / dice_greedy)用同一注册表,
   名字冲突 SHALL raise(详 [`../../../specs/eval-protocol/spec.md`](../../../specs/eval-protocol/spec.md))。

## 6. 与现状对比

**当前**(P2 前):
- `training/az/selfplay.py` — AZ-specific runner
- `training/az/arena.py` — AZ-specific eval runner
- `training/dmc/_actor.py` — DMC-specific runner
- `training/framework/inference/...` — actor/eval 共享 inference 但 runner 各自
- `training/ppo/rollout.py` — PPO-specific runner
- `training/cfr/traversal.py` — CFR-specific(无 episode 概念)

**P3 后**:1 个 EpisodeRunner + 5 EpisodePolicy + 1 NetworkProvider 抽象。
CFR traversal 非 episode-based,保留独立 traversal collector(不强行套
runner)。

## 7. Cross-references

- 6 protocol 详 → [`./core-protocols.md`](./core-protocols.md)
- Network provider → [`./network-provider.md`](./network-provider.md)
- Async 拓扑 → [`./async-pipeline.md`](./async-pipeline.md)
- Eval protocol 主 spec → [`../../../specs/eval-protocol/spec.md`](../../../specs/eval-protocol/spec.md)
- Mirror match bug fix history → memory feedback_mirror_match_hook_bug
