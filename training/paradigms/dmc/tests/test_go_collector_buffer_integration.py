"""I29 P1.4j — DMCGoActorCollector → DmcReplayBuffer.push_episode integration test。

验证 Go-native actor pool 产 DmcTransition 可以直接喂到现 DmcReplayBuffer 走标准
G-backfill + sample 路径,与 Python actor pool 产 DmcTransition 行为一致。 这是
Go path producing trainable data 的端到端 verification。

I29 T-RR.4(Route A)后无 socket forward builder — collector 内部用真 DMCNetwork,
InfServer 走 request_q 批处理 + decode_dmc_request。

Mac-only(libgicg_actor.dylib 路径)。 Win 同测在 P1.5 stress 跑 build dll 验证。

Pipeline tested:
- DMCGoActorCollector.collect → runtime_metrics['dmc_episodes'] = [(transitions, G)]
- For each (transitions, G):buffer.push_episode(transitions, G) 走 standard 路径
- 验证:buffer 含 expected 数量 DmcTransition + sample 返合法 DmcTransition + G 全 ±1/0
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest

from training.paradigms.dmc.buffer import DmcReplayBuffer
from training.paradigms.dmc.go_collector import DMCGoActorCollector


def _build_dmc_network() -> Any:
    """Build a production-shape DMCNetwork。 Route A 后 collector wrap network.net
    进 DMCInferenceNet 喂 InfServer。 结构维度取 IR obs schema 固定常量。"""
    from training.core.network import AgentConfig
    from training.core.cfg import make_dmc_default_shape
    from training.paradigms.dmc.network import DMCNetwork

    shape = make_dmc_default_shape()
    agent_cfg = AgentConfig(
        n_counter_slots=shape.n_counter_slots,
        n_hooks=shape.n_hooks,
        max_ops_per_hook=shape.max_ops_per_hook,
        max_actions=shape.max_actions,
        d_model=128,
        n_cross_layers=2,
    )
    return DMCNetwork(agent_cfg, device='cpu', epsilon=0.05)


class _StubCfg:
    class _Pipeline:
        inference_max_batch = 1
        inference_batch_timeout_ms = 2

    pipeline = _Pipeline()


def _libs_built() -> bool:
    repo_root = Path(__file__).resolve().parents[4]
    ext = {'darwin': 'dylib', 'win32': 'dll'}.get(sys.platform, 'so')
    return all((repo_root / 'gicg_env' / f'lib{n}.{ext}').exists() for n in ('gicg', 'gicg_actor'))


@pytest.mark.smoke_full
@pytest.mark.skipif(not _libs_built(), reason='libgicg{,_actor} not built')
def test_go_collector_to_buffer_integration():
    """Go actor pool → DmcReplayBuffer end-to-end:训练器可消费 Go-produced episodes。"""
    paradigm_cfg = {
        'game_spec': {
            'pools': ['v_legacy'],
            'seed': 42,
            'players': [
                {'chars': [{'name': '赤蝶'}]},
                {'chars': [{'name': '墨客'}]},
            ],
        },
        'opponent_mix': {'random': 1.0},
        # 生产 max_actions=2048 —— 必须 == 网络 action 容量(make_dmc_default_shape);
        # v_legacy 真实 nLegal 可超 30,过小会触发 pickActionEpsilonGreedy fail-loud panic。
        'max_actions': 2048,
        'max_episode_steps': 360,
        'my_player_strategy': 'fixed_0',
        'base_seed': 42,
        'epsilon': 0.05,
    }
    net = _build_dmc_network()
    collector = DMCGoActorCollector(
        cfg=_StubCfg(),
        network=net,
        paradigm_cfg_dict=paradigm_cfg,
        n_actors=2,
    )
    buffer = DmcReplayBuffer(capacity=10_000, seed=42)

    try:
        # Bootstrap + warm up actors
        _ = collector.collect(n_episodes=10, provider=None)
        time.sleep(5.0)

        # Drain assembled episodes
        out = collector.collect(n_episodes=100, provider=None)
        assert out.n_episodes >= 1, f'no episodes drained after 5s warmup (got {out.n_episodes})'

        # Push each (transitions, G) to buffer — mirror Python actor pool 走 DMCBuffer.push 路径
        eps = out.runtime_metrics.get('dmc_episodes', [])
        n_transitions_pushed = 0
        for transitions, G in eps:
            buffer.push_episode(transitions, G)
            n_transitions_pushed += len(transitions)

        # Buffer 含预期 transition 数量
        assert len(buffer) == n_transitions_pushed, f'buffer size {len(buffer)} != pushed {n_transitions_pushed}'

        # G 已 backfilled 到每个 transition
        all_G = {t.G for t in buffer.buf}
        assert all_G.issubset({-1.0, 0.0, 1.0}), f'unexpected G values: {all_G}'

        # Sample 返合法 DmcTransition + obs_dict shape OK
        if len(buffer) >= 4:
            batch = buffer.sample(batch_size=4)
            assert len(batch) == 4
            for t in batch:
                assert isinstance(t.obs_dict, dict)
                assert 'action_refs' in t.obs_dict
                assert 'action_payments' in t.obs_dict
                assert 'counter_sids' in t.obs_dict
                assert 'hook_ir' in t.obs_dict
                assert isinstance(t.action_idx, int)
                assert t.G in (-1.0, 0.0, 1.0)

        # Total_seen ≥ pushed(可能跨多 episode)
        assert buffer.total_seen == n_transitions_pushed
    finally:
        collector.close()
