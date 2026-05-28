"""H1 (2026-05-28 audit) — InferenceServer 高优先级 CUDA stream tests。

cpu / 非-cuda device 必须返 None + nullcontext 不影响现有 forward 路径;
cuda available 时 stream cache by device_str (同一 device 多次调用复用)。

cuda path 受 `torch.cuda.is_available()` 门控,Mac CI / 无 GPU box 自动 skip。
"""

from __future__ import annotations

import contextlib

import pytest
import torch

from training.core.actor._inference_helpers import (
    _INFER_STREAMS,
    _get_or_create_infer_stream,
    _infer_stream_ctx,
)


def setup_function(_fn):
    """每 test 前清 cache,隔离 case 间 state。"""
    _INFER_STREAMS.clear()


def test_get_stream_cpu_returns_none():
    assert _get_or_create_infer_stream('cpu') is None
    assert 'cpu' not in _INFER_STREAMS


def test_get_stream_unknown_device_returns_none():
    """非 cuda 前缀的 device str (mps / xpu / 未来 backend) → None。"""
    assert _get_or_create_infer_stream('mps') is None
    assert _get_or_create_infer_stream('xpu:0') is None


def test_infer_stream_ctx_cpu_is_nullcontext_compatible():
    """cpu path ctx 必须可作 with 块进出,不抛 + 不影响 GPU global state。"""
    ctx = _infer_stream_ctx('cpu')
    assert isinstance(ctx, contextlib.nullcontext)
    with ctx:
        pass  # 走通即 PASS


@pytest.mark.skipif(not torch.cuda.is_available(), reason='requires CUDA')
def test_get_stream_cuda_returns_stream_object():
    stream = _get_or_create_infer_stream('cuda')
    assert stream is not None
    assert isinstance(stream, torch.cuda.Stream)


@pytest.mark.skipif(not torch.cuda.is_available(), reason='requires CUDA')
def test_get_stream_cuda_cache_hit_returns_same_object():
    """同 device_str 第二次调用必须复用,避免每 inference batch 新 alloc stream。"""
    s1 = _get_or_create_infer_stream('cuda')
    s2 = _get_or_create_infer_stream('cuda')
    assert s1 is s2


@pytest.mark.skipif(not torch.cuda.is_available(), reason='requires CUDA')
def test_infer_stream_ctx_cuda_activates_stream():
    """ctx 进入后 torch.cuda.current_stream() 应该返我们的 high-priority stream。"""
    stream = _get_or_create_infer_stream('cuda')
    with _infer_stream_ctx('cuda'):
        cur = torch.cuda.current_stream()
        assert cur == stream
