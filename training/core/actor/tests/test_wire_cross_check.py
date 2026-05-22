"""I29 T-RR.8 — Go↔Python wire 协议 header 交叉校验。

穷举审计 #D4:Go 的 binary-encoded header struct 与 Python 的 ``struct`` fmt 之间
此前无任何运行时交叉校验 —— 任一端加字段忘同步另一端 = 静默错位解码。 本测试经
ctypes 读 ``libgicg_actor`` 实际 ``binary.Size``,与 Python ``struct.calcsize``
比对(transition + inference request/response 三路 header + wire version)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from training.core.actor import inference_server_socket_wire as inf_wire
from training.core.actor import transition_sink_wire as trans_wire


def _lib_built() -> bool:
    name = {'darwin': 'libgicg_actor.dylib', 'win32': 'libgicg_actor.dll'}.get(sys.platform, 'libgicg_actor.so')
    return (Path(__file__).resolve().parents[4] / 'gicg_env' / name).exists()


@pytest.mark.skipif(not _lib_built(), reason='libgicg_actor not built')
def test_wire_header_layout_go_python_match():
    """Go ``binary.Size`` == Python ``struct.calcsize``,两路 wire 全部 header。

    任一端 header 加字段未同步 → 对应 size 不符 → 本断言失败,drift 在 CI 即暴露
    (此前只能在跑真 Go↔Python socket 时撞 length-mismatch 错)。"""
    from training.core.actor.go_backend import GoActorBackend

    layout = GoActorBackend().wire_layout()

    assert layout['wire_version'] == trans_wire.WIRE_VERSION, 'transition wire version drift'
    assert layout['wire_version'] == inf_wire.WIRE_VERSION, 'inference wire version drift'
    assert layout['transition_header_size'] == trans_wire.TRANSITION_HEADER_SIZE, (
        f'transition header size drift: Go={layout["transition_header_size"]} '
        f'Python={trans_wire.TRANSITION_HEADER_SIZE}'
    )
    assert layout['infer_request_header_size'] == inf_wire.HEADER_SIZE, (
        f'infer request header size drift: Go={layout["infer_request_header_size"]} Python={inf_wire.HEADER_SIZE}'
    )
    assert layout['infer_response_header_size'] == inf_wire.RESPONSE_HEADER_SIZE, (
        f'infer response header size drift: Go={layout["infer_response_header_size"]} '
        f'Python={inf_wire.RESPONSE_HEADER_SIZE}'
    )
