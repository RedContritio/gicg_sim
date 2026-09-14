---
last_updated: 2026-09-14
status: LIVE
schema_version: 1
capability: paradigm-ppo
---

# Paradigm PPO — Proximal Policy Optimization 算法层不变量

PPO is retained as a frozen adapter in the unified training tree. Historical
s021–s054 experiments and their checkpoint shapes remain historical evidence;
they do not establish numerical reproducibility with the current structural
backbone.

## 1. Scope

This specification covers GAE rollouts, PPO loss, the on-policy buffer, current
network and collector dispatch, and the adapter's actual schedule. Common
pipeline and evaluation behavior is specified elsewhere.

## 2. Core SHALL invariants

### P1. Rollout and targets

1. **P1.1** PPO SHALL collect on-policy trajectories and compute GAE with
   config-driven `gamma` and `gae_lambda`; defaults are `0.99` and `0.95`.
2. **P1.2** Rollout size SHALL be expressed as
   `paradigm.rollout.n_games_per_iter` and
   `paradigm.rollout.max_steps_per_game`. The current config has no
   `pipeline.rollout.n_steps` or `vec_env_size` field.
3. **P1.3** Each transition SHALL retain the selected action's old log
   probability, value estimate, advantage, return, and structural observation
   inputs needed by the update.
4. **P1.4** Training action selection SHALL sample from the legal masked policy
   distribution. Deterministic evaluation SHALL choose argmax.

### P2. Loss

5. **P2.1** `PPOLoss` SHALL compute the clipped policy surrogate, value MSE,
   and entropy term:
   `policy_loss + value_coef * value_loss - entropy_coef * entropy`.
6. **P2.2** The importance ratio SHALL be
   `exp(new_log_prob - old_log_prob)`, with `clip_epsilon` defaulting to
   `0.2`. `value_coef` and `entropy_coef` default to `0.5` and `0.01`.
7. **P2.3** The current loss uses unclipped value MSE. Documentation SHALL NOT
   claim that clipped value loss is implemented.
8. **P2.4** `PPOLoss.compute` SHALL accept either resident rollout
   `Transition` objects or a pre-collated structural batch and SHALL call
   `network.forward_batch`.

### P3. Buffer and schedule

9. **P3.1** The learner buffer SHALL be
   `training.core.buffer.rollout.RolloutBuffer`, with capacity set by the
   explicit `paradigm.buffer_cap` field (default `50_000`).
10. **P3.2** Sampling SHALL choose a random minibatch without replacement from
    the current buffer. The buffer SHALL be cleared after each outer training
    step so no transition crosses iteration boundaries.
11. **P3.3** The adapter currently places `paradigm.n_epochs` directly into
    `StepPlan.n_train_batches`. The generic pipeline therefore performs that
    many sampled minibatch updates; it does not multiply by the number of
    minibatches needed to sweep the full rollout.
12. **P3.4** Training SHALL stop after `paradigm.total_iterations` outer
    steps.

### P4. Network and provider output

13. **P4.1** `PPONetwork` SHALL use the generic structural ActorCritic through
    `PPOAgent`, with `PPO_HEAD_KINDS={'policy', 'value'}` and typed-damage
    inputs enabled.
14. **P4.2** Static observations SHALL be cached per game and dynamic
    observations SHALL be collated into structural fields. The retired flat
    `_PPOMLPTrunk` path is not current.
15. **P4.3** `PPOEpisodePolicy` currently accepts either a dict containing
    `policy`/`logits` plus `value`, or a two-item `(logits, value)` tuple from a
    provider. Documentation SHALL preserve both supported forms until the
    fallback is removed in code.
16. **P4.4** There is no current `heads_share_trunk` config field. Network
    sharing SHALL follow `PPOAgent` and the generic ActorCritic construction.

### P5. Collector and tier

17. **P5.1** `pipeline.mode='serial'` SHALL select `PPORolloutCollector` and
    `pipeline.mode='async'` SHALL select `PPOAsyncCollector`.
18. **P5.2** The PPO adapter SHALL reject `actor_backend='go'`; its current
    collectors use Python.
19. **P5.3** PPO SHALL remain frozen for new production work unless an
    explicit change reopens and validates the route. Smoke tests establish
    wiring, not historical win-rate reproduction.

## 3. Implementation references

- Config and schedule: `training/paradigms/ppo/config.py`,
  `training/paradigms/ppo/paradigm.py`
- Collectors and policy: `training/paradigms/ppo/collector.py`,
  `training/paradigms/ppo/_async.py`, `training/paradigms/ppo/policy.py`
- Network and loss: `training/paradigms/ppo/network.py`,
  `training/paradigms/ppo/agent.py`, `training/paradigms/ppo/loss.py`
- Buffer: `training/core/buffer/rollout.py`
- Historical pivot:
  [`docs/2_decisions/adr-0008-rl_paradigm_pivot.md`](../../../docs/2_decisions/adr-0008-rl_paradigm_pivot.md)

## 4. Historical context

The 2026-05 specification used a fixed-step rollout model, described a full
epoch sweep per update, required dict-only provider output, and exposed a
nonexistent trunk-sharing knob. Those claims have been replaced with the
behavior of the current adapter; archived experiment results remain unchanged.
