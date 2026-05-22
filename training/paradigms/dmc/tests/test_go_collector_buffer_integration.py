"""I29 P1.4j — DMCGoActorCollector → DmcReplayBuffer.push_episode integration test。

验证 Go-native actor pool 产 DmcTransition 可以直接喂到现 DmcReplayBuffer 走标准
G-backfill + sample 路径,与 Python actor pool 产 DmcTransition 行为一致。 这是
Go path producing trainable data 的端到端 verification。

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

import pytest
import torch
import torch.nn as nn

from training.paradigms.dmc.buffer import DmcReplayBuffer
from training.paradigms.dmc.go_collector import DMCGoActorCollector


class _StubInferenceNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.n_counter_slots = 1832
        self.n_hooks = 900
        self.max_ops_per_hook = 64
        self.fields_per_op = 5
        self.d_model = 64
        self.dummy = nn.Linear(1, 30)

    def forward(self, obs_dict):  # noqa: ARG002
        return {'logit_as_q': torch.zeros(1, 30)}


class _StubCfg:
    class _Pipeline:
        inference_max_batch = 1
        inference_batch_timeout_ms = 2

    pipeline = _Pipeline()


def build_stub_zero_forward(*, device_str, shared_cache, network, max_actions=30):  # noqa: ARG001
    import numpy as np

    from training.core.actor.inference_server_socket_wire import INFER_STATUS_OK, InferResponse

    def cb(req):  # noqa: ARG001
        return InferResponse(status=INFER_STATUS_OK, logits=np.zeros(max_actions, dtype=np.float32))

    return cb


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
        'max_actions': 30,
        'max_episode_steps': 360,
        'my_player_strategy': 'fixed_0',
        'base_seed': 42,
        'epsilon': 0.05,
    }
    net = _StubInferenceNet()
    collector = DMCGoActorCollector(
        cfg=_StubCfg(),
        network=net,
        paradigm_cfg_dict=paradigm_cfg,
        n_actors=2,
        socket_forward_builder_path=(
            'training.paradigms.dmc.tests.test_go_collector_buffer_integration.build_stub_zero_forward'
        ),
        socket_forward_builder_kwargs={'max_actions': 30},
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
