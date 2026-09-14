---
last_updated: 2026-09-14
status: LIVE
schema_version: 1
capability: training-architecture
subtopic: eval
---

# Evaluation — periodic jobs and shared episode execution

This subtopic describes the evaluation components currently shipped under
`training/core/eval/`. The standalone gauntlet service has a separate protocol
in [`eval-protocol`](../eval-protocol/spec.md).

## 1. Components

- `PeriodicEvalScheduler` parses `every_<N>_steps`,
  `every_<N>_frames`, or `every_<N>_episodes` and decides when evaluation is
  due.
- `EvalJob`, `EvalResult`, and `EvalReport` are the current plain dataclass
  payloads.
- `EvalWorker` runs deterministic episodes through
  `training/core/actor/episode_runner.py`.
- `EvalServer` assigns jobs round-robin to supplied workers and aggregates
  their results.
- `OpponentRegistry` and the opponent mix are specified in
  [opponent-mix](./opponent-mix.md).

## 2. Scheduling

`PeriodicEvalScheduler` SHALL reject an invalid schedule string. Before its
first completed evaluation, `due(state)` becomes true once the selected state
counter reaches the configured interval. `mark_done(state)` records that
counter, and subsequent checks require another complete interval.

The scheduler stores an optional job list but does not create workers, freeze
weights, or dispatch processes itself. The pipeline calls the configured eval
server when evaluation is due.

## 3. Worker execution

For an `EvalJob`, `EvalWorker` SHALL:

1. derive `n_games` deterministic seeds from the master seed and opponent ID;
2. create a deterministic policy and set epsilon to zero;
3. alternate `our_player` between player 0 and player 1 when
   `starting_player_alternates` is true;
4. execute each game with the shared `EpisodeRunner`;
5. return one `EvalResult` per game.

The injected network provider is independent from the actor provider chosen by
the caller. This module does not implement shared-memory snapshot slots.

## 4. Aggregation

`aggregate_results` SHALL reject an empty result list. It reports wins from our
side separately for the two starting slots, a combined win proportion, Wilson
95% bounds, and average episode length. When results contain only one starting
slot, aggregation falls back to that slot's ordinary win proportion.

`EvalServer.run_jobs` currently executes calls synchronously and assigns jobs
round-robin across the worker objects passed to its constructor. Supplying
process-backed workers can provide process isolation, but `EvalServer` itself
does not spawn processes or manage queues.

## 5. Episode boundary

Actor and core evaluation reuse `EpisodeRunner`. Differences come from the
`EpisodeSpec`, policy, provider, and opponent registry supplied by the caller.
The runner records transitions only for `our_player` actions and enforces a
600-step safety bound.

See [protocols](./protocols.md), [pipeline](./pipeline.md), and
[opponent mix](./opponent-mix.md).
