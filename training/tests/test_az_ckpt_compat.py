"""AZ ckpt self-describing keys — save-side emission + in-place backfill.

Pipeline CheckpointManager payloads (``{'net', 'optimizer', 'state',
'cfg_run_label', 'runtime'}``) now additionally carry ``cfg``
(AgentConfig dict) + ``net_state_dict`` (inner-net state dict), making
them directly loadable by the matchup player loader
(``training/paradigms/az/_player_loader.py``). ``tools.ckpt.az_compat``
backfills the same keys into already-landed ckpts (provenance preserved).
"""

from __future__ import annotations

import os

import pytest
import torch

from training.core.artifact_io import load_checkpoint, save_checkpoint
from training.core.checkpoint import CheckpointManager
from training.core.network import AgentConfig
from training.core.protocols import PipelineState
from training.paradigms.az import AZParadigm
from training.paradigms.az.config import AZParadigmConfig

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')

_TINY_AGENT = {
    'n_counter_slots': 8,
    'n_hooks': 4,
    'max_ops_per_hook': 4,
    'max_actions': 8,
    'd_model': 8,
    'n_cross_layers': 1,
}


def _build_cfg():
    from training.core.config.base import (
        CheckpointCfg,
        MetaCfg,
        PipelineCfg,
        ScenarioCfg,
        TrainingConfig,
    )
    from training.tests.smoke_template import SMOKE_MIRROR_DECK

    return TrainingConfig(
        meta=MetaCfg(seed=42, paradigm='az', run_label='test_az_ckpt', device='cpu'),
        pipeline=PipelineCfg(mode='serial', num_actors=1),
        scenario=ScenarioCfg(
            team_0=['赤蝶'],
            team_1=['赤蝶'],
            pool=['v_legacy', 'test_basic'],
            max_rounds=10,
            deck_padding={'card': '碌碌无为', 'target_size': 15},
            data_dir=DATA_DIR,
            deck_0=list(SMOKE_MIRROR_DECK),
            deck_1=list(SMOKE_MIRROR_DECK),
        ),
        paradigm={
            'lr': 1e-3,
            'batch_size': 8,
            'buffer_cap': 500,
            'agent': dict(_TINY_AGENT),
            'mcts': {'n_rollouts': 4, 'profile': False},
        },
        checkpoint=CheckpointCfg(save_every=1000, keep_last_n=3, artifacts_root='artifacts'),
    )


def _loader_players(ckpt_path: str):
    """Build both player kinds through the registered az loader."""
    from training.core.matchup.loaders import _AgentArgmaxPlayer, _AgentMCTSPlayer
    from training.paradigms.az._player_loader import _loader_az

    argmax_builder = _loader_az({'ckpt': str(ckpt_path), 'n_simulations': 0})
    mcts_builder = _loader_az({'ckpt': str(ckpt_path), 'n_simulations': 2, 'max_rollout_depth': 10})
    return argmax_builder(seed=0), mcts_builder(seed=0), _AgentArgmaxPlayer, _AgentMCTSPlayer


def test_pipeline_ckpt_carries_self_describing_keys(tmp_path):
    """Save-side: CheckpointManager payloads gain cfg + net_state_dict
    (purely additive) and load directly through the az player loader."""
    cfg = _build_cfg()
    paradigm = AZParadigm()
    network = paradigm.make_network(cfg)
    optimizer = torch.optim.AdamW(network.parameters(), lr=1e-3)
    buffer = paradigm.make_buffer(cfg)
    ckpt_mgr = CheckpointManager(cfg, network, optimizer, buffer)
    ckpt_mgr.init_artifacts_dir(prebuilt=tmp_path)

    path = ckpt_mgr.save(PipelineState.fresh(seed=42))

    blob = load_checkpoint(path, weights_only=True, map_location='cpu')
    # Legacy keys intact + new self-describing keys.
    for key in ('net', 'optimizer', 'state', 'cfg_run_label', 'runtime', '_training_provenance'):
        assert key in blob, f'legacy key {key!r} missing'
    assert blob['cfg'] == dict(vars(AgentConfig.from_obs_shape(AZParadigmConfig.from_dict(cfg.paradigm).agent)))
    assert 'net_state_dict' in blob
    assert set(blob['net_state_dict']) == set(network.agent.net.state_dict())

    # Both loader player kinds construct from the fresh ckpt.
    argmax_player, mcts_player, argmax_cls, mcts_cls = _loader_players(path)
    assert isinstance(argmax_player, argmax_cls)
    assert isinstance(mcts_player, mcts_cls)


def _write_run_dir(run_dir, tmp_path, d_model: int = 8) -> None:
    """Minimal but schema-valid AZ run dir: cfg_resolved.toml + an
    old-format (no cfg / net_state_dict) ckpt."""
    from training.tests.smoke_template import SMOKE_MIRROR_DECK

    deck = ', '.join(f'"{c}"' for c in SMOKE_MIRROR_DECK)
    (run_dir / 'cfg_resolved.toml').write_text(
        f"""[meta]
seed = 42
paradigm = "az"
run_label = "compat_run"
device = "cpu"

[pipeline]
mode = "serial"
num_actors = 1

[scenario]
team_0 = ["赤蝶"]
team_1 = ["赤蝶"]
pool = ["v_legacy", "test_basic"]
max_rounds = 10
data_dir = {os.path.join(os.path.dirname(__file__), '..', '..', 'data')!r}
deck_0 = [{deck}]
deck_1 = [{deck}]

[scenario.deck_padding]
card = "碌碌无为"
target_size = 15

[shape]
n_counter_slots = 8
n_hooks = 4
max_ops_per_hook = 4
max_actions = 8
d_model = {d_model}
n_cross_layers = 1
dropout = 0.0

[paradigm.az]
version = "1.0.0"
paradigm = "az"
lr = 1e-3

[paradigm.az.mcts]
n_rollouts = 4
""",
        encoding='utf-8',
    )
    # Old-format ckpt: exactly what CheckpointManager saved pre-fix.
    cfg = _build_cfg()
    paradigm = AZParadigm()
    if d_model != 8:
        paradigm_dict = dict(cfg.paradigm)
        paradigm_dict['agent'] = {**paradigm_dict['agent'], 'd_model': d_model}
        object.__setattr__(cfg, 'paradigm', paradigm_dict)
    network = paradigm.make_network(cfg)
    ckpts = run_dir / 'ckpts'
    ckpts.mkdir(parents=True)
    ckpt_path = ckpts / 'ckpt_33.pt'
    save_checkpoint(
        {
            'net': network.state_dict(),
            'optimizer': None,
            'state': PipelineState.fresh(seed=42).snapshot(),
            'cfg_run_label': 'compat_run',
            'runtime': {},
        },
        ckpt_path,
    )


def test_az_compat_backfills_legacy_ckpt(tmp_path):
    """One-shot converter: in-place backfill of cfg + net_state_dict from
    the run dir's cfg snapshot; provenance preserved; idempotent."""
    from tools.ckpt.az_compat import backfill_az_ckpt

    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    _write_run_dir(run_dir, tmp_path)
    ckpt_path = run_dir / 'ckpts' / 'ckpt_33.pt'

    summary = backfill_az_ckpt(ckpt_path, run_dir)
    assert summary['added'] == ['cfg', 'net_state_dict']

    # Provenance preserved (load_checkpoint validation passes) and the
    # legacy keys are untouched alongside the new ones.
    blob = load_checkpoint(ckpt_path, weights_only=True, map_location='cpu')
    for key in ('net', 'optimizer', 'state', 'cfg_run_label', 'runtime', '_training_provenance'):
        assert key in blob
    assert blob['cfg']['d_model'] == 8

    # Both loader player kinds construct from the backfilled ckpt.
    argmax_player, mcts_player, argmax_cls, mcts_cls = _loader_players(ckpt_path)
    assert isinstance(argmax_player, argmax_cls)
    assert isinstance(mcts_player, mcts_cls)

    # Idempotent: second call is a no-op.
    assert backfill_az_ckpt(ckpt_path, run_dir)['noop'] is True


def test_az_compat_aborts_on_shape_mismatch(tmp_path):
    """Safety: a cfg whose shape does not match the ckpt weights must
    abort BEFORE writing (strict-load probe), leaving the ckpt intact."""
    from tools.ckpt.az_compat import backfill_az_ckpt

    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    _write_run_dir(run_dir, tmp_path, d_model=16)  # ckpt weights: d_model=16
    # cfg snapshot claims d_model=8 shape → strict load must fail.
    (run_dir / 'cfg_resolved.toml').write_text(
        (run_dir / 'cfg_resolved.toml').read_text(encoding='utf-8').replace('d_model = 16', 'd_model = 8'),
        encoding='utf-8',
    )
    ckpt_path = run_dir / 'ckpts' / 'ckpt_33.pt'
    before = ckpt_path.read_bytes()

    with pytest.raises(RuntimeError):
        backfill_az_ckpt(ckpt_path, run_dir)
    assert ckpt_path.read_bytes() == before
