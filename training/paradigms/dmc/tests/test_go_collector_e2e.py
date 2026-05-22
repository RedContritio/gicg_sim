"""DMCGoActorCollector e2e smoke — verify full Go path produces buffer-ready episodes。

跑 collector.collect → 拿 runtime_metrics['dmc_episodes'] → 验证 DmcTransition shape
+ winner 可用。 I29 T-RR.4(Route A)后无 socket forward builder — collector 内部
用真 DMCNetwork,InfServer 走 ``request_q`` 批处理 + ``decode_dmc_request``,故本测试
端到端覆盖 production socket inference 路径(此前 stub forward bypass 该路径)。

Mac-only(libgicg_actor.dylib 路径)。 Win 同测在 P1.5 stress test 跑 build dll。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest

from training.paradigms.dmc.go_collector import DMCGoActorCollector


def _build_dmc_network() -> Any:
    """Build a production-shape DMCNetwork for the e2e smoke。

    Route A(T-RR.4)后 collector 把 ``network.net``(ActorCritic)wrap 进
    ``DMCInferenceNet`` 喂 InfServer。 结构维度取 IR obs schema 固定常量
    (``make_dmc_default_shape``),与 ``test_go_actor_perf_smoke`` 同。
    """
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


def _libs_built() -> bool:
    repo_root = Path(__file__).resolve().parents[4]
    ext = {'darwin': 'dylib', 'win32': 'dll'}.get(sys.platform, 'so')
    return all((repo_root / 'gicg_env' / f'lib{n}.{ext}').exists() for n in ('gicg', 'gicg_actor'))


class _StubCfg:
    """Minimal cfg shape DMCGoActorCollector reads(pipeline.inference_batch_timeout_ms etc.)。"""

    class _Pipeline:
        inference_max_batch = 1
        inference_batch_timeout_ms = 2

    pipeline = _Pipeline()


@pytest.mark.smoke_full
@pytest.mark.skipif(not _libs_built(), reason='libgicg{,_actor} not built')
def test_dmc_go_collector_e2e_smoke():
    """Start collector,let actors run ~5s,verify ≥1 episode assembled with DmcTransition shape。

    走真 DMCNetwork(T-RR.4 Route A:socket 请求经 request_q 批处理)— pipeline 验证,
    not RL signal。
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
    net = _build_dmc_network()
    collector = DMCGoActorCollector(
        cfg=_StubCfg(),
        network=net,
        paradigm_cfg_dict=paradigm_cfg,
        n_actors=2,
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
