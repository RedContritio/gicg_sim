"""I29 redesign P0.3 — Go subprocess spawner test (uses bin/gicg_actor binary)。

Cover:
- spawn → READY → alive → terminate (SIGTERM exit 0) cycle
- spawn 错配置 (n_actors=0) → subprocess exit ≠ 0 → fail-loud RuntimeError

Note: P0.4+ main.go 必须 shm.Attach 才能起 sink → spawn 前 master 端 create_owner SHMRing,
否则 subprocess exit rc=3 (shm.Attach errno=2)。
"""

import subprocess
from pathlib import Path

import pytest

from training.core.actor.go_subprocess import GoSubprocessHandle
from training.core.actor.transition_shm_channel import TransitionShmChannel

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BIN = _REPO_ROOT / 'bin' / 'gicg_actor'


@pytest.fixture(scope='module', autouse=True)
def build_go_binary():
    """Build cmd/gicg_actor once per module。"""
    _BIN.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['go', 'build', '-o', str(_BIN), './cmd/gicg_actor'],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f'go build failed: {r.stderr}')


# test_spawn_wait_ready_terminate — P0 PoC placeholder lifecycle test 已删除。
# A4 cleanup (commit `8d893e5`) 退役 PoC placeholder path,Go subprocess 现要求 paradigm
# + inf_server_addr 才能 spawn (cmd/gicg_actor 强制 paradigm-only)。 paradigm 路径
# lifecycle (spawn / READY / SIGTERM) 由 test_go_subprocess_1ep_smoke +
# test_go_subprocess_5ep_e2e 间接 cover (各 spawn_pipeline 包 GoSubprocessHandle 完整生命周期)。


def test_spawn_invalid_config_fails():
    cfg = {'n_actors': 0, 'trans_shm_name': 'x'}  # invalid n_actors
    with pytest.raises(RuntimeError, match='Go subprocess exit'):
        GoSubprocessHandle.spawn(str(_BIN), cfg, ready_timeout_s=5.0)
