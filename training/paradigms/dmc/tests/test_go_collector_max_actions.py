"""I29 T-R3 regression — Go actor obs max_actions 必须 == 网络 action 容量。

``DMCParadigm._make_go_collector`` 旧实现用 ``getattr(pcfg, 'max_actions', 30)``
取 Go actor / assembler / obs 的 max_actions —— ``DMCParadigmConfig`` 无此字段 →
恒落默认 30。 网络却用 ``pcfg.agent.max_actions``(``make_dmc_default_shape`` =
2048)。 真实 GICG 状态合法动作数 > 30 时 ``chosen_action`` ≥ 30,训练
``forward_batch`` 的 logits 宽度由 obs(30 槽)定 → ``gather(action_idx ≥ 30)``
→ CUDA scatter-gather index out of bounds。

修复:Go actor 的 max_actions 取 ``pcfg.agent.max_actions``,与网络 + Python mp
路径(``mp_factories.py``)一致。
"""

from __future__ import annotations

from pathlib import Path

from training.core.config.loader import load_cfg
from training.paradigms.dmc.paradigm import DMCParadigm

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SMOKE_CFG = _REPO_ROOT / 'configs' / 'dmc' / 'smoke.toml'


def test_go_collector_max_actions_matches_network_capacity():
    """Go actor / assembler 的 max_actions 必须 == ``pcfg.agent.max_actions``
    (= 网络 ``AgentConfig.max_actions``),否则 action_idx 可能越出 logits 宽度。"""
    cfg = load_cfg(_SMOKE_CFG)
    p = DMCParadigm()
    network = p.make_network(cfg)
    pcfg = p._resolve_pcfg(cfg)
    collector = p._make_go_collector(cfg, pcfg, network)

    assert collector._max_actions == pcfg.agent.max_actions, (
        f'go collector max_actions {collector._max_actions} != network capacity '
        f'pcfg.agent.max_actions {pcfg.agent.max_actions}'
    )
    assert collector.paradigm_cfg_dict['max_actions'] == pcfg.agent.max_actions
