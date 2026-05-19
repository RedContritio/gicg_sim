"""Tests for ckpt self-describing schema (config-schema/spec.md invariant N4).

Covers:
- save → load round-trip preserves all metadata
- pre-redesign 2-key schema raises CkptSchemaError on load
- paradigm mismatch warns but doesn't fail (cross-paradigm warm-start)
- tools.ckpt.info CLI succeeds on new ckpt + fails clearly on old
"""

from __future__ import annotations

import subprocess
import sys
import warnings
from pathlib import Path

import pytest
import torch
import torch.nn as nn

from training.core.cfg import ObsShape
from training.core.network.agent_base import AgentBase, AgentConfig, CkptSchemaError
from training.core.network.encoder import HookEncoder


def _make_cfg() -> AgentConfig:
    return AgentConfig(n_counter_slots=8, n_hooks=4, max_ops_per_hook=4, max_actions=6, d_model=16)


def _make_agent(cfg: AgentConfig) -> AgentBase:
    he = HookEncoder(token_dim=cfg.d_model, max_tokens=cfg.max_ops_per_hook, n_heads=4, n_layers=1)

    class _MockNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.linear = nn.Linear(cfg.d_model, cfg.max_actions)

    agent = AgentBase(cfg, hook_encoder=he)
    agent.net = _MockNet()
    return agent


def test_save_load_round_trip(tmp_path: Path):
    cfg = _make_cfg()
    agent = _make_agent(cfg)
    p = tmp_path / 'test.pt'
    agent.save(str(p))
    assert p.exists()

    # Load into fresh agent — round-trip
    agent2 = _make_agent(cfg)
    # Modify agent2's net so round-trip is verifiable
    with torch.no_grad():
        agent2.net.linear.weight.fill_(99.0)
    agent2.load(str(p))
    # weights restored from agent's save
    assert not torch.allclose(agent2.net.linear.weight, torch.full_like(agent2.net.linear.weight, 99.0))


def test_save_metadata_contains_all_keys(tmp_path: Path):
    cfg = _make_cfg()
    agent = _make_agent(cfg)
    p = tmp_path / 'test.pt'
    agent.save(str(p))

    blob = torch.load(str(p), weights_only=True, map_location='cpu')
    required = {
        'schema_version',
        'paradigm',
        'cfg_version',
        'cfg',
        'net_kind',
        'net_state_dict',
        'git_commit',
        'created_at',
    }
    missing = required - set(blob.keys())
    assert not missing, f'missing required keys: {missing}'
    assert blob['schema_version'] == 2
    assert blob['cfg_version'] == '1.0.0'
    assert blob['net_kind'] == '_MockNet'  # from the inner class
    # created_at is iso8601 with timezone
    assert 'T' in blob['created_at']


def test_load_pre_redesign_schema_raises(tmp_path: Path):
    """Old 2-key {'net', 'cfg'} schema must raise CkptSchemaError (no silent compat)."""
    cfg = _make_cfg()
    agent = _make_agent(cfg)
    p = tmp_path / 'old.pt'
    # Manually save in old schema
    torch.save({'net': agent.net.state_dict(), 'cfg': vars(cfg)}, str(p))

    with pytest.raises(CkptSchemaError, match='pre-redesign ckpt schema'):
        agent.load(str(p))


def test_load_paradigm_mismatch_warns(tmp_path: Path):
    """Loading ckpt with different 'paradigm' metadata warns (cross-paradigm warm-start
    is a valid use case but rare; surface it to caller)."""
    cfg = _make_cfg()
    agent = _make_agent(cfg)
    p = tmp_path / 'cross.pt'
    agent.save(str(p))

    # Hack the saved blob to claim different paradigm
    blob = torch.load(str(p), weights_only=True, map_location='cpu')
    blob['paradigm'] = 'some_other_paradigm'
    torch.save(blob, str(p))

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        agent.load(str(p))
        assert any('paradigm' in str(wi.message) for wi in w), 'expected paradigm-mismatch warning'


def test_git_commit_resolvable_in_repo():
    """Inside this repo, _resolve_git_commit should return a real hash, not 'unknown'."""
    commit = AgentBase._resolve_git_commit()
    assert commit != 'unknown', 'expected real git hash inside repo'
    assert len(commit) == 40, f'expected 40-char sha1, got {len(commit)}: {commit!r}'


def test_paradigm_name_resolution_unknown_for_bare_class():
    """Class outside training.paradigms.<X>.* should resolve to 'unknown'."""
    cfg = _make_cfg()
    agent = _make_agent(cfg)
    # AgentBase 自己 module path 是 'training.core.network.agent_base' (no 'paradigms')
    assert agent._resolve_paradigm_name() == 'unknown'


def test_tools_ckpt_info_cli(tmp_path: Path):
    """End-to-end: save ckpt → run CLI → inspect output."""
    cfg = _make_cfg()
    agent = _make_agent(cfg)
    p = tmp_path / 'cli.pt'
    agent.save(str(p))

    result = subprocess.run(
        [sys.executable, '-m', 'tools.ckpt.info', str(p)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f'CLI failed: {result.stderr}'
    out = result.stdout
    assert 'schema_version:  2' in out
    assert 'paradigm:' in out
    assert 'net_kind:' in out
    assert 'git_commit:' in out
    assert 'state_dict:' in out


def test_tools_ckpt_info_rejects_old_schema(tmp_path: Path):
    """CLI on pre-redesign ckpt returns exit code 2 + clear error."""
    cfg = _make_cfg()
    agent = _make_agent(cfg)
    p = tmp_path / 'old_cli.pt'
    torch.save({'net': agent.net.state_dict(), 'cfg': vars(cfg)}, str(p))

    result = subprocess.run(
        [sys.executable, '-m', 'tools.ckpt.info', str(p)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2, f'expected exit 2 for old schema; got {result.returncode}'
    assert 'pre-redesign' in result.stderr
