"""DMCGoActorCollector e2e smoke — verify full Go path produces buffer-ready episodes。

跑 collector.collect → 拿 runtime_metrics['dmc_episodes'] → 验证 DmcTransition shape
+ winner 可用。 不跑真 DMCInferenceNet(用 stub),验证 wiring 不验证 RL signal。

Mac-only(libgicg_actor.dylib 路径)。 Win 同测在 P1.5 stress test 跑 build dll。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
import torch
import torch.nn as nn

from training.paradigms.dmc.go_collector import DMCGoActorCollector


class _StubInferenceNet(nn.Module):
    """Stub DMCInferenceNet — 暴露 actor_critic-like attributes the collector reads。

    architecture params 设为 scenario 实际值(StaticObsSize parse 需精准 sizing,不能
    随便填)— 这些必须匹配 gicg_engine/hook.go(ObsMaxHooks=900,ObsMaxOpsPerHook=64,
    ObsFieldsPerOp=5)+ 实测 stage3 scenario StaticObsSize:n_counter_slots 推算 1832。
    此 stub forward 返 zero logits over max_actions。
    """

    def __init__(self) -> None:
        super().__init__()
        # 匹配 Go engine constants(gicg_engine/hook.go + observation.go):
        self.n_counter_slots = 1832  # 推算自 stage3 实测 StaticObsSize=293628
        self.n_hooks = 900  # gicg_engine ObsMaxHooks
        self.max_ops_per_hook = 64  # gicg_engine ObsMaxOpsPerHook
        self.fields_per_op = 5  # gicg_engine ObsFieldsPerOp
        self.d_model = 64
        self.dummy = nn.Linear(1, 2048)

    def forward(self, obs_dict):  # noqa: ARG002
        return {'logit_as_q': torch.zeros(1, 2048)}


def _libs_built() -> bool:
    repo_root = Path(__file__).resolve().parents[4]
    ext = {'darwin': 'dylib', 'win32': 'dll'}.get(sys.platform, 'so')
    return all((repo_root / 'gicg_env' / f'lib{n}.{ext}').exists() for n in ('gicg', 'gicg_actor'))


class _StubCfg:
    """Minimal cfg shape DMCGoActorCollector reads(pipeline.inference_max_batch etc.)。"""

    class _Pipeline:
        inference_max_batch = 1
        inference_batch_timeout_ms = 2

    pipeline = _Pipeline()


def build_stub_zero_forward(*, device_str, shared_cache, network, max_actions=2048):  # noqa: ARG001
    """Test-only forward callback:zero logits 不走 decode_dmc_request,无 hook_encoder
    依赖。 collector wiring 测试用,production 路径走 build_dmc_socket_forward_callback。"""
    import numpy as np

    from training.core.actor.inference_server_socket_wire import INFER_STATUS_OK, InferResponse

    def cb(req):  # noqa: ARG001
        return InferResponse(status=INFER_STATUS_OK, logits=np.zeros(max_actions, dtype=np.float32))

    return cb


@pytest.mark.smoke_full
@pytest.mark.skipif(not _libs_built(), reason='libgicg{,_actor} not built')
def test_dmc_go_collector_e2e_smoke():
    """Start collector,let actors run ~5s,verify ≥1 episode assembled with DmcTransition shape。

    Uses stub net (zero logits) — pipeline 验证,not RL signal。
    """
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
        # 生产 max_actions=2048 —— v_legacy 真实 nLegal 可超 30,过小会触发
        # pickActionEpsilonGreedy 的 fail-loud panic(I29 T-RR.6)。
        'max_actions': 2048,
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
        # Test stub forward — bypass decode_dmc_request(production path needs hook_encoder)
        socket_forward_builder_path='training.paradigms.dmc.tests.test_go_collector_e2e.build_stub_zero_forward',
        socket_forward_builder_kwargs={'max_actions': 2048},
    )
    try:
        # T-RR.3 后 collect() lazy-ingest:阻塞至 n_episodes 个 episode 组装完 或 10s
        # deadline。 首次 collect 含 bootstrap(起 InfServer / listener / Go pool),期间
        # actor 已开跑;collect 多轮累积,确保拿到 ≥1 个 assembled episode 验 shape。
        out = collector.collect(n_episodes=5, provider=None)
        for _ in range(5):
            if out.n_episodes >= 1:
                break
            time.sleep(2.0)
            out = collector.collect(n_episodes=5, provider=None)
        assert out.n_episodes >= 1, f'no episodes drained (got {out.n_episodes})'

        # Verify episode_stats shape + dmc_episodes payload structure
        for stat in out.episode_stats:
            assert 'n_transitions' in stat
            assert 'winner' in stat and stat['winner'] in (-1, 0, 1)
            assert 'G' in stat
            assert 'source' in stat and stat['source'] == 'go_actor'

        # runtime_metrics carries actual DmcTransition objects
        eps = out.runtime_metrics.get('dmc_episodes', [])
        assert len(eps) == out.n_episodes
        for transitions, G in eps:
            assert len(transitions) >= 1
            for t in transitions:
                assert hasattr(t, 'obs_dict')
                assert hasattr(t, 'action_idx')
                assert isinstance(t.obs_dict, dict)
                # Verify obs_dict has expected DMC fields (from _capture_obs_np)
                expected_keys = {
                    'counter_values',
                    'meta',
                    'card_buckets',
                    'enemy_sizes',
                    'recent_damage',
                    'prepare_skill',
                    'modifier_log',
                    'action_refs',
                    'action_payments',
                    'legal_mask',
                    'n_legal',
                    'counter_sids',
                    'active_slot_mask',
                    'char_skill_refs',
                    'hook_ir',
                    'hook_mask',
                }
                missing = expected_keys - set(t.obs_dict.keys())
                assert not missing, f'obs_dict missing keys: {missing}'
            assert G in (-1.0, 0.0, 1.0), f'winner G must be ±1 or 0, got {G}'

        # Assembler stats reflect cache hit ≥ 1
        stats = out.runtime_metrics.get('assembler_stats', {})
        assert stats.get('n_static_cache_entries', 0) >= 1
    finally:
        collector.close()
