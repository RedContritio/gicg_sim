"""Serial ExIt selfplay on the batched InferenceServer (parallel_rollouts > 1).

When ``paradigm.mcts.parallel_rollouts > 1`` the serial collector boots a
local InferenceServer (separate process, batched forward) and hands an
InferenceClient to the play loops — selfplay._mcts_decide then routes to
mcts_search_parallel. The client implements the full evaluator protocol
(game_start / eval_state / game_end), so both mirror and fixed-opponent
paths work unchanged.

parallel_rollouts == 1 (default) keeps the in-proc evaluator; covered by
the rest of the suite staying green.
"""

from __future__ import annotations

import os

import pytest
import torch

from gicg_env import GicgEnv
from training.core.protocols import PipelineState
from training.paradigms.az import AZParadigm
from training.paradigms.az._opponent import FixedOpponentPool
from training.paradigms.az.collector import AZSelfPlayCollector
from training.paradigms.az.config import AZParadigmConfig
from training.tests.smoke_template import SMOKE_MIRROR_DECK

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')

# Full DSL obs shape (mirrors test_selfplay.py) — the InferenceServer
# rebuilds an Agent from this AgentConfig and runs the real encoder.
N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16
SELFPLAY_DECK = list(SMOKE_MIRROR_DECK)


def _make_env(seed: int = 0) -> GicgEnv:
    env = GicgEnv(
        ['赤蝶'],
        ['赤蝶'],
        seed=seed,
        data_dir=DATA_DIR,
        deck_padding={'card': '碌碌无为', 'target_size': 15},
        pool=['v_legacy', 'test_basic'],
        decks=[SELFPLAY_DECK, SELFPLAY_DECK],
    )
    env.reset(seed=seed)
    return env


def _make_network() -> torch.nn.Module:
    torch.manual_seed(0)
    paradigm = AZParadigm()
    cfg = _build_cfg({'mcts': {'n_rollouts': 4, 'profile': False}})
    return paradigm.make_network(cfg)


def _build_cfg(paradigm_updates: dict | None = None):
    from training.core.config.base import (
        CheckpointCfg,
        MetaCfg,
        PipelineCfg,
        ScenarioCfg,
        TrainingConfig,
    )

    paradigm = {
        'lr': 1e-3,
        'batch_size': 8,
        'buffer_cap': 500,
        'agent': {
            'n_counter_slots': N_COUNTER_SLOTS,
            'n_hooks': 900,
            'max_ops_per_hook': 128,
            'max_actions': 512,
            'd_model': 16,
            'n_cross_layers': 1,
        },
        'mcts': {'n_rollouts': 4, 'profile': False},
    }
    if paradigm_updates:
        paradigm.update(paradigm_updates)
    return TrainingConfig(
        meta=MetaCfg(seed=42, paradigm='az', run_label='test_az_serial_inf', device='cpu'),
        pipeline=PipelineCfg(mode='serial', num_actors=1),
        scenario=ScenarioCfg(
            team_0=['赤蝶'],
            team_1=['赤蝶'],
            pool=['v_legacy', 'test_basic'],
            max_rounds=10,
            deck_padding={'card': '碌碌无为', 'target_size': 15},
            data_dir=DATA_DIR,
            deck_0=SELFPLAY_DECK,
            deck_1=SELFPLAY_DECK,
        ),
        paradigm=paradigm,
        checkpoint=CheckpointCfg(save_every=1000, keep_last_n=3, artifacts_root='artifacts'),
    )


class TestSerialInferenceServer:
    def test_fixed_opponent_parallel_rollouts(self):
        cfg = _build_cfg(
            {
                'mcts': {'n_rollouts': 4, 'parallel_rollouts': 2, 'profile': False},
                'fixed_opponent': {'depth': 1, 'dice_greedy': True},
            }
        )
        pcfg = AZParadigmConfig.from_dict(cfg.paradigm)
        network = _make_network()
        pool = FixedOpponentPool(pcfg.fixed_opponent, seed=1)
        collector = AZSelfPlayCollector(cfg, pcfg, network, _make_env(seed=3), opponent_pool=pool)
        proc = collector._inference_server._process
        try:
            assert collector._inference_client is not None
            out = collector.collect(1, provider=None)
            assert out.n_units > 0
            assert len(out.runtime_metrics['az_trajectories']) == 1
            # game_start/game_end pairing: client idle again after the game.
            assert collector._inference_client._current_game_id == -1
            assert out.episode_stats[0]['winner'] in (0, 1, 2)

            # Weight sync: version advances server-side, observable on the
            # next game_start ack (mirrors the pipeline's per-iteration
            # collector.sync_weights(network) hook).
            v_before = collector._inference_client.current_weight_version
            assert v_before >= 0
            new_version = collector.sync_weights(network)
            assert new_version == v_before + 1
            env2 = _make_env(seed=99)
            try:
                collector._inference_client.game_start(env2.static_obs)
                assert collector._inference_client.current_weight_version > v_before
                collector._inference_client.game_end()
            finally:
                env2.close()
        finally:
            collector.close()
        # Lifecycle: server process exits with the collector (no orphans).
        assert proc is not None and not proc.is_alive()
        assert collector._inference_server is None

    def test_mirror_parallel_rollouts(self):
        cfg = _build_cfg({'mcts': {'n_rollouts': 4, 'parallel_rollouts': 2, 'profile': False}})
        pcfg = AZParadigmConfig.from_dict(cfg.paradigm)
        network = _make_network()
        collector = AZSelfPlayCollector(cfg, pcfg, network, _make_env(seed=4))
        proc = collector._inference_server._process
        try:
            out = collector.collect(1, provider=None)
            assert out.n_units > 0
            assert collector._inference_client._current_game_id == -1
        finally:
            collector.close()
        assert proc is not None and not proc.is_alive()

    def test_parallel_rollouts_default_no_server(self):
        """parallel_rollouts == 1 (default): no server, in-proc evaluator."""
        cfg = _build_cfg()
        pcfg = AZParadigmConfig.from_dict(cfg.paradigm)
        network = _make_network()
        collector = AZSelfPlayCollector(cfg, pcfg, network, _make_env(seed=5))
        try:
            assert collector._inference_server is None
            assert collector._inference_client is None
            # sync_weights is a safe no-op without a server.
            assert collector.sync_weights(network) == 1
        finally:
            collector.close()

    def test_sync_weights_raises_loudly_when_server_died(self):
        """Wedge forensics: a dead InferenceServer must fail LOUDLY on
        sync_weights (check_alive), not wedge the pipeline on a
        weight_queue.put that blocks once OS buffers fill."""
        from training.core.inference.server import InferenceServer

        # Unstarted server: not alive, check_alive raises.
        server = InferenceServer(
            agent_config=None,
            n_workers=1,
            network_factory_path='training.paradigms.az.network.Agent',
            inference_handlers_module_path='training.paradigms.az._inference_handlers',
        )
        assert server.is_alive() is False
        with pytest.raises(RuntimeError, match='not alive'):
            server.check_alive()

        cfg = _build_cfg({'mcts': {'n_rollouts': 2, 'parallel_rollouts': 2, 'profile': False}})
        pcfg = AZParadigmConfig.from_dict(cfg.paradigm)
        network = _make_network()
        collector = AZSelfPlayCollector(cfg, pcfg, network, _make_env(seed=6))
        try:
            assert collector._inference_server.is_alive() is True
            collector._inference_server._process.terminate()
            collector._inference_server._process.join(timeout=5.0)
            assert collector._inference_server.is_alive() is False
            with pytest.raises(RuntimeError, match='not alive'):
                collector.sync_weights(network)
        finally:
            collector.close()

    def test_step_schedule_sync_bit_serial_parallel(self):
        """Serial + parallel_rollouts > 1 flips StepPlan.sync_weights so
        the pipeline republishes weights every steady iteration."""
        paradigm = AZParadigm()
        cfg_pr = _build_cfg({'mcts': {'parallel_rollouts': 2}})
        paradigm.make_network(cfg_pr)
        state = PipelineState.fresh(seed=42)
        state.total_transitions = 10_000  # past warm-up
        assert paradigm.step_schedule(state, cfg_pr).sync_weights is True

        cfg_default = _build_cfg()
        paradigm2 = AZParadigm()
        paradigm2.make_network(cfg_default)
        state2 = PipelineState.fresh(seed=42)
        state2.total_transitions = 10_000
        assert paradigm2.step_schedule(state2, cfg_default).sync_weights is False
