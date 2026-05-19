"""Phase 1 T1.3 — network basic-head composition test.

Phase 1 scope (per tasks.md):
> "basic head composition uses ``core/network/{encoder,heads,actor_critic}``
> directly; **保留 Agent class 引用** Phase 2 处理"

Therefore this test verifies:
1. ``training.paradigms.az.network`` references ``core/network/heads`` (basic
   head classes available for composition / type annotation / future
   factory; not necessarily instantiated yet in Phase 1).
2. ``Agent`` class reference is preserved — re-export via the network
   module so ``from training.paradigms.az.network import Agent``
   resolves (whether via direct re-export or transitive legacy reference
   — both acceptable in Phase 1; Phase 2 inlines Agent).
3. ``AZNetwork`` still wires up via core heads (verified by instantiating
   a minimal AZNetwork and checking its heads tuple matches spec
   A4.1 = ('policy', 'value')).
"""

from __future__ import annotations

import ast
import pathlib

import torch

import training.paradigms.az.network as net_mod
from training.core.network import AgentConfig
from training.paradigms.az.network import AZNetwork


def _tiny_agent_cfg() -> AgentConfig:
    return AgentConfig(
        n_counter_slots=8,
        n_hooks=4,
        max_ops_per_hook=4,
        max_actions=8,
        d_model=8,
        n_cross_layers=1,
        dropout=0.0,
    )


def _collect_import_modules(py_path: pathlib.Path) -> set[str]:
    tree = ast.parse(py_path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


# ---------- core/network/heads referenced ---------- #


def test_network_module_references_core_heads():
    """Phase 1 T1.3 — network must reference core/network/heads (PolicyHead /
    ValueHead) directly so basic head composition path is established.

    Acceptable forms: explicit `from training.core.network.heads import ...`
    OR `from training.core.network import PolicyHead, ValueHead` (re-export
    via package __init__).
    """
    py_path = pathlib.Path(net_mod.__file__)
    modules = _collect_import_modules(py_path)
    # Either training.core.network.heads OR training.core.network is acceptable.
    has_heads_ref = ('training.core.network.heads' in modules) or ('training.core.network' in modules)
    assert has_heads_ref, (
        f'network.py must import from training.core.network.heads (or training.core.network); '
        f'current imports: {sorted(modules)}'
    )


# ---------- Agent class reference preserved ---------- #


def test_network_module_reexports_agent():
    """Agent class reference preserved (Phase 2 inlines).

    Phase 1 accepts either:
    (a) direct re-export: `from training.paradigms.az.network import Agent`
    (b) legacy import lift: `Agent` available as module attribute
    """
    assert hasattr(net_mod, 'Agent'), (
        'training.paradigms.az.network must expose Agent (re-export or legacy ref) — '
        'Phase 2 inlines, Phase 1 preserves reference for cross-module consumers'
    )


# ---------- AZNetwork still instantiates + heads correct ---------- #


def test_az_network_heads_policy_value():
    """Spec A4.1 — heads tuple must be ('policy', 'value') after refactor."""
    net = AZNetwork(_tiny_agent_cfg(), device='cpu', lr=1e-3)
    assert net.heads == ('policy', 'value')


def test_az_network_is_nn_module_with_params():
    """Module-API guarantee preserved — driver's optimizer factory needs it."""
    net = AZNetwork(_tiny_agent_cfg(), device='cpu', lr=1e-3)
    assert isinstance(net, torch.nn.Module)
    params = list(net.parameters())
    assert len(params) > 0, 'AZNetwork must have trainable parameters'
    sd = net.state_dict()
    assert isinstance(sd, dict)
    assert any('net.' in k for k in sd.keys()), (
        'AZNetwork.state_dict must register inner ActorCritic params under "net.*"'
    )


def test_az_network_load_net_only_roundtrip():
    """BC warm-start path (A6) — load_net_only swaps inner ActorCritic SD."""
    net1 = AZNetwork(_tiny_agent_cfg(), device='cpu', lr=1e-3)
    net2 = AZNetwork(_tiny_agent_cfg(), device='cpu', lr=1e-3)
    inner_sd = net1.agent.net.state_dict()
    net2.load_net_only(inner_sd)
    sd2 = net2.agent.net.state_dict()
    for k in inner_sd:
        assert torch.equal(inner_sd[k], sd2[k]), f'load_net_only failed to restore key {k}'


def test_basic_head_classes_content() -> None:
    """Phase 2 seam lock: T2.6 will instantiate CoreActorCritic from BASIC_HEAD_CLASSES items.
    Renaming a key or class would silently break the contract — assert identity, not just keys."""
    from training.core.network.heads import PolicyHead, ValueHead
    from training.paradigms.az import network as net_mod

    assert net_mod.BASIC_HEAD_CLASSES == {'policy': PolicyHead, 'value': ValueHead}
