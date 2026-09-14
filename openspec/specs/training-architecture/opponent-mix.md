---
last_updated: 2026-09-14
status: LIVE
schema_version: 1
capability: training-architecture
subtopic: opponent-mix
---

# Opponent Mix — registry, weighted sampling, and historical snapshots

This subtopic describes the current paradigm-independent opponent
components. The implementation is split between
`training/core/eval/baselines.py`, `training/core/opponent/mix.py`, and
`training/core/opponent/pool.py`.

## 1. Scope

In scope:

- `OpponentRegistry`: name-to-factory registration and seeded player creation.
- `WeightedMix`: seeded weighted selection over registered names.
- `OpponentPool`: actor-side sampling plus an in-memory historical snapshot ring.
- Explicit frozen-checkpoint baselines for evaluation.

Paradigms choose their own mix weights and build their own registry instances.
The shared core implementation keeps player IDs and sampling behavior consistent;
it does not imply that actor and eval processes share a Python object.

## 2. Opponent registry

`OpponentRegistry.register(name, factory)` SHALL reject duplicate names.
`get(name, seed, params)` SHALL fail on an unknown name and otherwise call the
registered factory with the supplied seed and parameter mapping.

`register_default_opponents` installs:

- `random`;
- `F1-D1` through `F1-D4`;
- `mcts_pure_50`, `mcts_pure_100`, `mcts_pure_200`, and
  `mcts_pure_400`.

Frozen checkpoints are registered separately with
`register_historical_baseline`. Their names SHALL start with
`historical_`, and the player is resolved lazily through
`training/core/matchup/loaders.py` using its paradigm-specific loader.

## 3. Weighted sampling

`WeightedMix(names, weights, seed)` SHALL reject:

- different name and weight counts;
- an empty name list;
- negative weights;
- weights whose sum is zero.

`sample()` uses the instance RNG, so a fixed seed and fixed call order are
reproducible. `seed(value)` resets that RNG.

## 4. Actor-side opponent pool

`OpponentPool` accepts a registry, a `{name: weight}` mapping, an optional
historical player factory, and a bounded snapshot ring. All weighted names
except the reserved `historical` entry SHALL exist in the registry.

`sample(episode_seed)` selects one opponent for the episode. A historical
selection chooses a state dict from the ring and passes it to the
paradigm-supplied factory. During cold start, when no historical player can be
built, it falls back to the registered `random` opponent when available.

`add_snapshot(state_dict)` appends to the bounded ring. The ring contains
in-memory state dicts; it is distinct from the frozen checkpoint baselines used
by evaluation.

## 5. Boundaries

- Concrete greedy and pure-MCTS players live in `training/core/matchup/`.
- Paradigm factories and mix defaults live under
  `training/paradigms/<name>/`.
- Evaluation job and report types live in `training/core/eval/job.py`.
- Episode execution lives in `training/core/actor/episode_runner.py`.

See [evaluation](./eval.md), [protocols](./protocols.md), and the
[eval baseline contract](../eval-protocol/baselines.md).
