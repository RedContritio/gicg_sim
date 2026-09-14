---
last_updated: 2026-09-14
status: LIVE
schema_version: 1
capability: training-architecture
subtopic: pipeline
---

# Pipeline driver — collect, train, evaluate, and checkpoint

`training/core/pipeline.py::run_pipeline` is the shared driver for all five
training paradigms. Paradigm-specific behavior enters through the `Paradigm`
protocol and its `StepPlan`.

## 1. Construction

The driver obtains the network, optimizer, buffer, loss computer, and collector
from the selected paradigm. It then creates a `CheckpointManager`, metrics
logger, and NaN guard. A caller may also inject an opponent pool, an evaluation
server, and a train-time network provider.

`tools.runs.train` creates the run directory before dispatch and passes it as
`prebuilt_artifacts_dir`; the driver writes configuration snapshots,
checkpoints, and logs into that existing directory.

## 2. Iteration order

For each iteration, the driver SHALL:

1. ask `paradigm.step_schedule(state, cfg)` for a `StepPlan`;
2. when `plan.collect` is true, collect, push to the buffer, and update state;
3. when training is enabled and the buffer has enough samples, run the planned
   batches, backpropagate, clip gradients, run the NaN guard, and step the
   optimizer;
4. republish weights when `plan.sync_weights` is true and the collector exposes
   `sync_weights`;
5. clear the buffer when `plan.clear_buffer_after_train` is true;
6. run due evaluation jobs only when an eval server and jobs were supplied;
7. update checkpoint state, add an optional historical opponent snapshot, log
   the iteration, advance the state, and save when due.

The collect gate SHALL depend on `plan.collect` alone. Dataset-driven BC may
truthfully use `n_episodes=0`, so the driver SHALL NOT require a positive
episode count before calling its collector.

## 3. `StepPlan`

`StepPlan` is an immutable per-iteration directive with:

- collect, train, and eval flags;
- episode, batch-count, and batch-size values;
- the state-step increment;
- optional buffer-clear and async weight-sync epilogues.

The paradigm computes the plan from its configuration and current
`PipelineState`. The driver interprets these common fields and does not import
paradigm implementations.

## 4. Pipeline state

`PipelineState` is deliberately mutable. It tracks `step`, total episodes and
transitions, train steps, weight version, last eval/checkpoint steps, elapsed
wall time, RNG state, and metadata. `snapshot()` returns its serializable
dictionary form for checkpoints and NaN diagnostics.

The checkpoint manager stores network, optimizer, pipeline-state snapshot, and
registered runtime components. Resume restores those objects from an explicit
checkpoint under a run's `ckpts/` directory.

## 5. Serial and async collection

The driver loop is the same for serial and async modes. The collector owns the
execution topology:

- serial collectors run in process;
- async AZ uses actor processes, a shared inference server, and an SHM result
  ring;
- async CFR and PPO publish weights through `WeightsSHM`;
- DMC supports Python multiprocess collection and its separate Go-subprocess
  path.

These implementations do not share one universal process diagram. In
particular, the core pipeline does not automatically spawn eval workers or
shared-memory evaluation snapshots.

## 6. Evaluation and shutdown

Core periodic evaluation is optional and synchronous from the driver's point of
view: `EvalServer.run_jobs` is called only when injected, scheduled, and given
jobs. The normal `tools.runs.train` dispatch currently passes
`eval_server=None`. Standalone gauntlet and polling daemons are documented in
[`eval-protocol`](../eval-protocol/spec.md).

The driver saves final state when the loop finishes. In `finally`, it closes the
collector, metrics logger, and trace sink. A partially failed iteration SHALL
NOT overwrite the previous resumable checkpoint boundary.

See [protocols](./protocols.md), [evaluation](./eval.md), and
[network sharing](./network-sharing.md).
