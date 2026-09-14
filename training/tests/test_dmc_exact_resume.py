"""Real serial DMC: uninterrupted training equals checkpoint continuation."""

from dataclasses import replace

import numpy as np
import pytest
import torch

from training.core.artifact_io import load_checkpoint
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.pipeline import run_pipeline
from training.paradigms.dmc.paradigm import DMCParadigm


def assert_same(a, b):
    if isinstance(a, torch.Tensor):
        torch.testing.assert_close(a, b, rtol=0, atol=0)
    elif isinstance(a, np.ndarray):
        np.testing.assert_array_equal(a, b)
    elif isinstance(a, dict):
        assert a.keys() == b.keys()
        for key in a:
            assert_same(a[key], b[key])
    elif isinstance(a, (tuple, list)):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert_same(x, y)
    elif hasattr(a, 'obs_dict'):
        assert_same(vars(a), vars(b))
    else:
        assert a == b


def run(cfg, directory, steps, resume=None):
    paradigm = DMCParadigm()
    net = paradigm.make_network(cfg)
    pool = paradigm.make_opponent_pool(cfg, net)
    if resume is None:
        directory.mkdir()
    state = run_pipeline(
        cfg,
        paradigm,
        env_factory=make_env_factory(cfg, None, cfg.meta.seed),
        opp_pool=pool,
        max_steps=steps,
        resume_from=resume,
        prebuilt_artifacts_dir=directory if resume is None else None,
    )
    payload = load_checkpoint(directory / 'ckpts/latest.pt', weights_only=False)
    return state, payload


def test_serial_dmc_resume_preserves_learning_and_collection(tmp_path):
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/readiness_base.toml')
    pcfg = {**cfg.paradigm, 'batch_size': 2, 'train_ratio': 1, 'buffer_cap': 100}
    pcfg['agent'] = {**pcfg['agent'], 'd_model': 8, 'dropout': 0.0}
    pcfg['opponent_mix'] = {**pcfg['opponent_mix'], 'random': 0.5, 'f1d2': 0.0, 'historical': 0.5}
    cfg = replace(
        cfg,
        checkpoint=replace(cfg.checkpoint, save_every=1, keep_last_n=2),
        scenario=replace(cfg.scenario, max_rounds=2, fix_dice=[0, 0, 0, 0, 0, 0, 0, 8]),
        paradigm=pcfg,
    )
    full_state, full = run(cfg, tmp_path / 'full', 4)
    _, half = run(cfg, tmp_path / 'split', 2)
    resume = tmp_path / 'split/ckpts/latest.pt'
    split_state, split = run(cfg, tmp_path / 'split', 4, resume)
    for name in ('net', 'optimizer', 'runtime'):
        assert_same(full[name], split[name])
    for name in ('step', 'train_steps', 'total_transitions', 'total_episodes', 'last_ckpt_at_step'):
        assert getattr(full_state, name) == getattr(split_state, name)
    assert half['runtime']['components']['buffer']['transitions']
    assert split['runtime']['components']['opponents']['ring']
    assert len(list((tmp_path / 'split/ckpts').glob('ckpt_*.pt'))) == 2


def test_missing_runtime_is_not_a_valid_continuation():
    from training.core.checkpoint_runtime import restore_runtime

    with pytest.raises(ValueError, match='complete serial runtime'):
        restore_runtime(None, {'collector': object()})
