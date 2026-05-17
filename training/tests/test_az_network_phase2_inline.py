"""Phase 2-δ T2.6 — adapter Agent inline verification.

Per `openspec/changes/az-paradigm-rewrite/tasks.md` T2.6 (critical-risk):
the ~178-LOC Agent class previously lived in
``training.paradigms.az.legacy.network.agent`` and was re-exported by
``training.paradigms.az.network`` (Phase 1). Phase 2-δ inlines the class
into the adapter module so:

* The adapter is self-contained (no `legacy.network` import from
  adapter-level — T2.11 partial verify).
* Production callers in ``core/{matchup,inference}`` keep using the
  legacy module untouched (Phase 3 T3a will switch them; Phase 5 will
  git-rm). The legacy file remains alive.

Tests below cover the four contract slices:

1. Static (importability): all three public names resolve.
2. AST: adapter file does **not** import from
   ``training.paradigms.az.legacy.network`` (Phase 2-δ key invariant).
3. Behavioral: ``Agent()`` instantiates with a minimal `AgentConfig`.
4. Lifecycle: ``game_start(static_obs)`` / ``game_end()`` no-crash + cache
   populated.
"""

from __future__ import annotations

import ast
import pathlib

import numpy as np

from training.core.network import AgentConfig
from training.core.obs_constants import (
    OBS_CHAR_SKILL_REFS_SIZE,
)
from training.paradigms.az import network as net_mod
from training.paradigms.az.network import Agent, AZNetwork, BASIC_HEAD_CLASSES


def _tiny_cfg() -> AgentConfig:
    """Minimal config — enough to instantiate Agent + run encode_static."""
    return AgentConfig(
        n_counter_slots=16,
        n_hooks=4,
        max_tokens_per_hook=4,
        max_actions=4,
        d_model=8,
        n_cross_layers=1,
        dropout=0.0,
    )


def _synthetic_static_obs(cfg: AgentConfig) -> np.ndarray:
    """Synthetic static obs matching the encode_static layout
    (counter meta + char_skill_refs + hook tokens)."""
    meta_size = cfg.n_counter_slots * 3
    refs_size = OBS_CHAR_SKILL_REFS_SIZE
    hook_size = cfg.n_hooks * cfg.max_tokens_per_hook * 2
    obs = np.zeros(meta_size + refs_size + hook_size, dtype=np.float32)
    for i in range(cfg.n_counter_slots):
        obs[i * 3 + 2] = float(i)  # distinct SIDs
    obs[meta_size : meta_size + refs_size] = -1.0
    hook_start = meta_size + refs_size
    stride = cfg.max_tokens_per_hook * 2
    for h in range(cfg.n_hooks):
        obs[hook_start + h * stride + 0] = 1.0  # type
        obs[hook_start + h * stride + 1] = 0.5  # value
    return obs


# ---------- 1. Static: public names resolve from adapter module ---------- #


def test_inline_agent_resolves_from_adapter():
    """``from training.paradigms.az.network import Agent`` works."""
    assert Agent is not None
    assert AZNetwork is not None
    assert BASIC_HEAD_CLASSES is not None
    # __all__ contract
    assert 'Agent' in net_mod.__all__
    assert 'AZNetwork' in net_mod.__all__
    assert 'BASIC_HEAD_CLASSES' in net_mod.__all__


def test_inline_agent_defined_in_adapter_module():
    """After inline, Agent's __module__ should be the adapter, NOT the
    legacy submodule. This proves the symbol is locally defined, not
    re-exported."""
    assert Agent.__module__ == 'training.paradigms.az.network', (
        f'Agent.__module__ = {Agent.__module__!r} (expected adapter); '
        'if it still points at legacy.network.agent the inline did not happen'
    )


# ---------- 2. AST: adapter has zero legacy.network imports ---------- #


def _collect_imports(py_path: pathlib.Path) -> set[str]:
    tree = ast.parse(py_path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def test_adapter_network_no_legacy_network_import():
    """T2.11 partial verify — Phase 2-δ key invariant: the adapter's
    network.py must not import anything from
    ``training.paradigms.az.legacy.network``. Other adapter files /
    production core still may (they're handled in Phase 3 / 5)."""
    py_path = pathlib.Path(net_mod.__file__)
    modules = _collect_imports(py_path)
    bad = [m for m in modules if m.startswith('training.paradigms.az.legacy.network')]
    assert bad == [], f'paradigms/az/network.py must NOT import from legacy.network after T2.6 inline; found: {bad}'


# ---------- 3. Behavioral: Agent() instantiates with minimal cfg ---------- #


def test_inline_agent_instantiates():
    """Minimal smoke: Agent(cfg) succeeds with all defaults and exposes
    ``net`` + ``optimizer`` (the two non-base attributes the class adds)."""
    agent = Agent(_tiny_cfg())
    assert agent.net is not None
    assert agent.optimizer is not None
    # AgentBase contract — caches initialized to None pre-game.
    assert agent._hook_emb is None
    assert agent._hook_mask is None


def test_inline_agent_state_dict_keys_match_actor_critic():
    """state_dict key naming convention preserved: keys live under
    ``self.net.<...>`` (inherited via AgentBase.save), which is what the
    r009 ckpt uses. If inline accidentally wrapped net in another layer,
    keys would gain a prefix and the r009 load smoke would fail."""
    agent = Agent(_tiny_cfg())
    sd = agent.net.state_dict()
    assert len(sd) > 0
    # No extra prefix — keys should match ActorCritic's own state_dict,
    # not e.g. "agent.net.<...>".
    for k in sd:
        assert not k.startswith('agent.'), f'unexpected prefix on key {k!r}'
        assert not k.startswith('net.'), f'unexpected prefix on key {k!r}'


# ---------- 4. Lifecycle: game_start / game_end ---------- #


def test_inline_agent_lifecycle_game_start_end():
    """``game_start(static_obs)`` populates the static cache and returns
    a dict with the per-game tensors; ``game_end()`` is a no-op (cache
    is overwritten on the next game_start)."""
    cfg = _tiny_cfg()
    agent = Agent(cfg)
    static = _synthetic_static_obs(cfg)

    out = agent.game_start(static)
    assert isinstance(out, dict)
    for key in ('hook_types', 'hook_values', 'hook_mask', 'counter_sids', 'active_slot_mask', 'char_skill_refs'):
        assert key in out, f'game_start return dict missing {key!r}'
    # Cache now populated
    assert agent._hook_emb is not None
    assert agent._counter_sids is not None

    # game_end is no-op (just exercise it)
    agent.game_end()
    # Cache stays — that's the documented contract (game_end is a hook;
    # cache is overwritten on next game_start).
    assert agent._hook_emb is not None
