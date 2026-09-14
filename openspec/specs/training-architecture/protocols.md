---
last_updated: 2026-09-14
status: LIVE
schema_version: 1
capability: training-architecture
subtopic: protocols
---

# Training protocols

`training/core/protocols.py` defines the common payloads and six runtime
protocols used by the shared pipeline.

## 1. Paradigm

Each registered paradigm supplies:

- `make_network(cfg)`;
- `make_collector(cfg, env_factory, network, opp_pool)`;
- `make_buffer(cfg)`;
- `make_loss(cfg)`;
- `make_optimizer(cfg, network)`;
- `make_episode_policy(cfg, instance_id, deterministic)`;
- `step_schedule(state, cfg) -> StepPlan`.

The registry lives in `training/paradigms/__init__.py`. The driver depends on
this protocol and does not import concrete paradigm packages. A paradigm object
may cache its parsed config or network; resumable training state belongs in the
pipeline, collector, buffer, network, optimizer, or opponent-pool checkpoint
state rather than in an unrecorded cache.

## 2. Collector and buffer

`Collector.collect(n_units, provider)` SHALL return a `CollectorOutput`.
Collectors also expose `close`, `state_dict`, and `load_state_dict`, plus the
`requires_network_in_collect` flag. Serial and async topology is owned by the
collector, so the driver loop stays the same.

`CollectorOutput` can contain typed transitions, episode statistics, runtime
metrics, an explicit paradigm unit count, and the number of completed episodes.
Payload contents may be paradigm-specific; the driver passes them to the
matching buffer.

`Buffer` exposes `push(CollectorOutput)`, `sample(batch_size, rng) -> Batch`,
`clear`, length, capacity, and checkpoint state. On-policy paradigms request a
post-train clear through `StepPlan.clear_buffer_after_train`.

## 3. Loss and scheduling

`LossComputer.compute(network, batch)` SHALL return `LossResult`, which contains
one scalar loss tensor, a numeric breakdown, and optional gradient metrics. The
driver owns zero-grad, backward, clipping, NaN checks, and optimizer stepping.

`StepPlan` is the paradigm's immutable directive for one driver iteration. It
contains collect/train/eval flags, workload sizes, a state-step increment, and
optional buffer-clear and weight-sync epilogues. Async paradigms use
`async_sync_weights_due` to request weight publication at their configured
cadence.

## 4. Episode policy and provider

`EpisodePolicy` exposes:

- `reset()` at episode start;
- `act(obs, mask, provider) -> (action, metadata)` at our decisions.

The shared `EpisodeRunner` uses this surface for ordinary single-sided actor and
evaluation episodes. AZ self-play has a separate two-sided lifecycle adapter
that wraps its existing `play_self_game` path.

`NetworkProvider` exposes `forward(obs, mask)`, `update_weights(version_tag)`,
`current_version()`, and `close()`. Implementations may hold an in-process
network or route to an inference server.

## 5. Shared state and episode payloads

`PipelineState` is mutable driver-owned state with explicit update methods and a
serializable `snapshot()`. `EpisodeSpec` is an immutable description of seed,
opponent, starting side, round bound, deterministic/epsilon settings, and
optional diagnostic recording. `Transition` and `EpisodeRecord` carry the
per-action and per-episode results.

See [pipeline](./pipeline.md), [evaluation](./eval.md), and
[opponent mix](./opponent-mix.md).
