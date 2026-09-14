"""Core protocol contracts — 6 Protocol + supporting dataclasses.

OpenSpec ref:
- design/core-protocols.md (signatures)
- specs/training-architecture/spec.md SHALL #2 / #4 / #5

Every paradigm SHALL implement ``Paradigm``. The driver
(``training.core.pipeline``) only interacts with the protocols here —
adding a new paradigm means writing one ``Paradigm`` subclass + one
``EpisodePolicy`` subclass + paradigm-specific Loss/Buffer, plugged in
via ``Paradigm.make_*``.

Runtime-checkable so tests can ``isinstance(obj, Paradigm)`` smoke. The
contracts are intentionally narrow — paradigm-specific shapes flow
through ``Any`` payloads on ``Transition`` / ``Batch`` etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

import numpy as np


# ---------- Transition / batch payloads (paradigm-agnostic) ---------- #


@dataclass(frozen=True)
class Transition:
    """One step of one episode. payload is paradigm-specific
    (action_meta + value pred + mcts stats etc.)."""

    obs: Any
    action: int
    legal_mask: Any
    reward: float
    done: bool
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EpisodeRecord:
    """Aggregate of one full episode from EpisodeRunner."""

    transitions: list  # list[Transition]
    final_reward: float
    length: int
    winner: int  # 0 / 1 / 2 (draw), or -1 when unavailable
    opponent_id: str
    scenario_seed: int
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CollectorOutput:
    """Wrapped output of a ``Collector.collect`` call."""

    transitions: list  # list[Transition] flattened across episodes
    episode_stats: list  # list[dict] per-episode summary
    runtime_metrics: dict = field(default_factory=dict)
    n_units: int = 0  # transitions or traversals,paradigm-meaningful

    @property
    def n_transitions(self) -> int:
        return len(self.transitions)

    @property
    def n_episodes(self) -> int:
        return len(self.episode_stats)


@dataclass(frozen=True)
class Batch:
    """Sampled training batch handed to LossComputer."""

    data: dict  # tensor / ndarray dict (paradigm-specific keys)
    weights: Optional[Any] = None  # IS / priority weights
    size: int = 0


@dataclass(frozen=True)
class LossResult:
    """Output of LossComputer.compute."""

    loss: Any  # torch.Tensor scalar
    breakdown: dict  # str -> float (policy_loss / value_loss / entropy)
    grad_metrics: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StepPlan:
    """Paradigm-returned cadence directive for one driver iteration.

    ``clear_buffer_after_train`` asks the driver to clear on-policy data after
    training. ``sync_weights`` asks it to republish the network to an async
    collector before the next collection round. Both default to false."""

    collect: bool
    n_episodes: int  # 0 if not collect
    train: bool
    n_train_batches: int  # 0 if not train
    batch_size: int
    eval: bool  # let driver check scheduler due
    advance_step: int = 1
    clear_buffer_after_train: bool = False
    sync_weights: bool = False


def async_sync_weights_due(cfg: Any, state: 'PipelineState', sync_every_train_steps: int) -> bool:
    """Return whether this iteration should republish weights to async actors.

    True 仅当 (1) async mode(serial collector 无 async actor → 恒 False)且
    (2) ``state.train_steps`` 落在 cadence 边界
    (``% max(1, sync_every_train_steps) == 0``;0/1 = 每 train iter)。
    paradigm step_schedule steady-train 分支用它翻 ``StepPlan.sync_weights``
    (warm-up / done 分支不 train,默认 False 不 sync)。"""
    if getattr(cfg.pipeline, 'mode', 'serial') != 'async':
        return False
    return state.train_steps % max(1, sync_every_train_steps) == 0


# ---------- PipelineState (driver-owned mutable state) ---------- #


@dataclass
class PipelineState:
    """Driver-owned mutable state. Frozen=False on purpose: driver
    mutates after_collect / after_train / after_eval / after_ckpt to
    keep state propagation explicit."""

    step: int = 0
    total_episodes: int = 0
    total_transitions: int = 0
    train_steps: int = 0
    weights_version: int = 0
    last_eval_at_step: int = -1
    last_ckpt_at_step: int = -1
    wall_seconds: float = 0.0
    rng_state: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def fresh(cls, seed: int) -> 'PipelineState':
        rng = np.random.default_rng(seed)
        return cls(rng_state={'master': rng.bit_generator.state})

    def after_collect(self, out: CollectorOutput) -> None:
        # Prefer n_units (paradigm-meaningful count) when populated;
        # fall back to len(transitions) for paradigms that materialize
        # typed Transition objects on the CollectorOutput.
        self.total_transitions += out.n_units or out.n_transitions
        self.total_episodes += out.n_episodes

    def after_train(self, loss_breakdown: dict) -> None:
        self.train_steps += 1

    def after_eval(self) -> None:
        self.last_eval_at_step = self.step

    def after_ckpt(self) -> None:
        self.last_ckpt_at_step = self.step

    def advance(self, plan: StepPlan) -> None:
        self.step += plan.advance_step

    def snapshot(self) -> dict:
        return {
            'step': self.step,
            'total_episodes': self.total_episodes,
            'total_transitions': self.total_transitions,
            'train_steps': self.train_steps,
            'weights_version': self.weights_version,
            'last_eval_at_step': self.last_eval_at_step,
            'last_ckpt_at_step': self.last_ckpt_at_step,
            'wall_seconds': self.wall_seconds,
            'rng_state': self.rng_state,
            'metadata': self.metadata,
        }


# ---------- 6 Protocols ---------- #


@runtime_checkable
class NetworkProvider(Protocol):
    """Provider abstraction — LocalNetworkProvider holds an in-process
    network copy; RemoteNetworkProvider talks to an inference server.

    All callers (EpisodePolicy.act / collector / eval worker) go
    through this interface; placement (local vs remote) is invisible
    to them. design/network-provider.md owns full contract."""

    def forward(self, obs: Any, mask: Any) -> Any: ...
    def update_weights(self, version_tag: Optional[str] = None) -> int: ...
    def current_version(self) -> int: ...
    def close(self) -> None: ...


@runtime_checkable
class EpisodePolicy(Protocol):
    """The only paradigm-aware actor-side hook EpisodeRunner sees.
    ``act`` returns (action_idx, action_meta_dict); meta carries
    paradigm-specific fields (policy logits / mcts stats / value pred)
    that Buffer.push consumes."""

    def reset(self) -> None: ...
    def act(self, obs: Any, mask: Any, provider: NetworkProvider) -> tuple: ...


@runtime_checkable
class Collector(Protocol):
    """Wrap one round of paradigm-specific data collection."""

    requires_network_in_collect: bool

    def collect(self, n_units: int, provider: NetworkProvider) -> CollectorOutput: ...
    def close(self) -> None: ...
    def state_dict(self) -> dict: ...
    def load_state_dict(self, sd: dict) -> None: ...


@runtime_checkable
class Buffer(Protocol):
    """Storage + sample contract. capacity / size required for driver
    accounting; clear() called by on-policy paradigms (PPO) per iter."""

    capacity: int

    def push(self, batch: CollectorOutput) -> None: ...
    def sample(self, batch_size: int, rng: Optional[np.random.Generator] = None) -> Batch: ...
    def clear(self) -> None: ...
    def __len__(self) -> int: ...
    def state_dict(self) -> dict: ...
    def load_state_dict(self, sd: dict) -> None: ...


@runtime_checkable
class LossComputer(Protocol):
    """Paradigm-specific loss aggregation. Driver only reads
    ``LossResult.loss`` for backprop + ``breakdown`` for metrics."""

    def compute(self, network: Any, batch: Batch) -> LossResult: ...


@runtime_checkable
class Paradigm(Protocol):
    """Top-level paradigm contract. Driver gets one instance and calls
    make_* + step_schedule. All paradigm-specific cadence lives in
    step_schedule (on-policy vs off-policy / collect:train ratio /
    warm-start phase)."""

    name: str
    requires_network_in_collect: bool

    def make_network(self, cfg: Any) -> Any: ...
    def make_collector(self, cfg: Any, env_factory: Any, network: Any, opp_pool: Any) -> Collector: ...
    def make_buffer(self, cfg: Any) -> Buffer: ...
    def make_loss(self, cfg: Any) -> LossComputer: ...
    def make_optimizer(self, cfg: Any, network: Any) -> Any: ...
    def make_episode_policy(self, cfg: Any, instance_id: int = 0, deterministic: bool = False) -> EpisodePolicy: ...
    def step_schedule(self, state: PipelineState, cfg: Any) -> StepPlan: ...


# ---------- EpisodeSpec (consumed by EpisodeRunner) ---------- #


@dataclass(frozen=True)
class EpisodeSpec:
    """Episode settings shared by actor and evaluation callers.

    ``EpisodeRunner`` consumes the scenario and opponent identifiers directly.
    Callers and policy implementations consume the remaining execution and
    recording options as appropriate.
    """

    scenario_seed: int
    opponent_id: str
    starting_player: int = 0
    max_rounds: int = 15
    deterministic: bool = False
    epsilon: float = 0.0
    record_mcts_stats: bool = False
    record_value_pred: bool = False
