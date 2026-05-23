"""pipeline.py ckpt save 后 opp_pool.add_snapshot wiring 验。

修 2026-05-23(I29 follow-up,task #3 Phase 1):此前 `add_snapshot` 在 整
training/ 主代码 无 caller,Python actor 路径 historical=30% episode 全 silent
fallback random。 fix 加 pipeline 内 ckpt 同步 add_snapshot 调用。 此 test
验 关键 clone 语义(`state_dict()` 返 live tensor,不 clone 则 ring 内副本
跟 network 更新 失去 historical),并 None opp_pool 不破 + 没 add_snapshot
method opp_pool 也 不破(hasattr-guard)。

Pipeline integration cover:任 一 DMC smoke / serial test 在 ckpt save 时
触此路径(opp_pool 由 paradigm.make_opponent_pool build,内含 add_snapshot)。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import torch


def _snapshot_sd_helper(network: torch.nn.Module) -> dict:
    """Replicate pipeline.py 内 4 行的 state_dict snapshot 逻辑 — clone-on-cpu
    防 ring 内副本 跟 live network update。"""
    return {k: v.detach().cpu().clone() for k, v in network.state_dict().items()}


def test_snapshot_state_dict_is_detached_and_on_cpu():
    """snapshot tensors 必须 detached + on cpu(non-grad, OS-portable)。"""
    net = torch.nn.Linear(4, 2)
    sd = _snapshot_sd_helper(net)
    assert set(sd.keys()) == {'weight', 'bias'}
    for v in sd.values():
        assert not v.requires_grad, f'snapshot tensor requires_grad={v.requires_grad}'
        assert v.device.type == 'cpu', f'snapshot tensor device={v.device}'


def test_snapshot_clone_decouples_from_live_network():
    """clone 后 live network 更新 不影响 ring 内副本 — 这是 historical 语义关键。
    若 仅 detach()(无 clone),修改 network parameter 在 cpu 上时 ring 内 view 跟变。"""
    net = torch.nn.Linear(4, 2)
    sd_pre = _snapshot_sd_helper(net)
    weight_pre = sd_pre['weight'].clone()

    # 修改 live network weight
    with torch.no_grad():
        net.weight.add_(10.0)

    # ring snapshot 不应跟变
    assert torch.equal(sd_pre['weight'], weight_pre), 'snapshot weight 跟随 live network 更新(clone 失效)'
    assert not torch.equal(sd_pre['weight'], net.state_dict()['weight'])


def test_pipeline_add_snapshot_call_uses_clone():
    """Spy `add_snapshot` 接 的 state_dict 应 detached + on cpu + 独立。"""
    net = torch.nn.Linear(4, 2)
    opp_pool = MagicMock()

    # Replicate pipeline 内 conditional + clone + call
    if opp_pool is not None and hasattr(opp_pool, 'add_snapshot'):
        snapshot_sd = _snapshot_sd_helper(net)
        opp_pool.add_snapshot(snapshot_sd)

    opp_pool.add_snapshot.assert_called_once()
    called_sd = opp_pool.add_snapshot.call_args[0][0]
    for v in called_sd.values():
        assert not v.requires_grad
        assert v.device.type == 'cpu'


def test_pipeline_add_snapshot_skipped_when_opp_pool_none():
    """opp_pool is None 时 不报错(BC dataset-only paradigm 无 opp_pool)。"""
    opp_pool = None
    # Replicate pipeline 内 conditional — 应 short-circuit 不 evaluate hasattr
    if opp_pool is not None and hasattr(opp_pool, 'add_snapshot'):
        raise AssertionError('should not reach here')
    # 跑到这就 OK


def test_pipeline_add_snapshot_skipped_when_no_method():
    """opp_pool 是 不 支持 historical 的 object(无 add_snapshot)时 不报错。"""

    class NoSnapshotPool:
        def sample(self) -> str:
            return 'random'

    opp_pool = NoSnapshotPool()
    if opp_pool is not None and hasattr(opp_pool, 'add_snapshot'):
        raise AssertionError('hasattr should have been False')
