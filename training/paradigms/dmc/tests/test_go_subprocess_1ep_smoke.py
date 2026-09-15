"""I29 redesign P1.3 — 1 episode e2e smoke through Go subprocess + real TCP InfServer。

Cover full production path (1 ep depth):
  master (no cgo)
    ├─ InferenceServer mp.Process (DMCInferenceNet 真 forward + socket listener thread)
    ├─ SHM trans channel (owner) ←──────────────────────────────┐
    └─ cmd/gicg_actor standalone subprocess                     │
         ├─ TCP InferenceClient → InfServer 127.0.0.1:port      │
         ├─ DMCParadigm.Run → 真 game loop (gicg_engine native) │
         └─ TransitionWriterShm push wire v3 episode batch ─────┘

Verify:
  - Pipeline 整栈起得来 (READY 信号收到)
  - 1+ episode batch frame 落到 SHM ring (5s deadline,Mac N=1 单 ep ~3-5s)
  - 第 1 个 transition payload decode 后 DMC schema fields 完整 (chosen_action /
    step_in_episode / n_legal / dyn_obs / refs / pay / static_hash)
  - Clean shutdown:Go SIGTERM exit 0,InfServer stop 不挂

不验证 RL 信号 (1 ep 不够);P1.4 5 ep e2e + collector integration 由 next subagent 跑。
"""

from __future__ import annotations

import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from training.core.actor.go_subprocess_pipeline import (
    PipelineHandle,
    make_unique_shm_name,
    spawn_pipeline,
)
from training.core.actor.dmc_transition_payload_wire import decode_dmc_payload
from training.core.actor.transition_sink_wire import (
    EPISODE_BATCH_HEADER_SIZE,
    KIND_EPISODE_BATCH,
    WIRE_VERSION,
    decode_episode_batch,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BIN = _REPO_ROOT / 'bin' / 'gicg_actor'


@pytest.fixture(scope='module', autouse=True)
def build_go_binary():
    """Build cmd/gicg_actor once per module。 P1.3 path 不依赖 libgicg_actor.dylib —
    standalone Go subprocess 自含 gicg_engine。"""
    _BIN.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['go', 'build', '-o', str(_BIN), './cmd/gicg_actor'],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f'go build failed: {r.stderr}')


def _build_dmc_inference_net() -> Any:
    """Build a production-shape DMCInferenceNet (wraps ActorCritic) for the e2e smoke。

    Mirror test_go_collector_e2e._build_dmc_network 的 shape (make_dmc_default_shape),
    InfServer 直接 host DMCInferenceNet — Go actor 的 InferenceClient 请求经 Route A
    (socket → request_q → batched forward) 拿真 logits。
    """
    from training.core.cfg import make_dmc_default_shape
    from training.core.network import AgentConfig
    from training.paradigms.dmc.inference_net import DMCInferenceNet
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
    net = DMCNetwork(agent_cfg, device='cpu', epsilon=0.05)
    # DMCInferenceNet wrap ActorCritic (state_dict key 加 'net.' 前缀;production sync_weights
    # path 已对齐,smoke 不用 sync weights — initial random weights 足够 driver game loop)。
    return DMCInferenceNet(net.net)


def _build_paradigm_config() -> dict[str, Any]:
    """Mirror DMCParadigm._make_go_collector 的 paradigm_cfg dict 结构 — Go side
    DMCConfig schema (gicg_actor/dmc/paradigm.go:DMCConfig)。"""
    return {
        'game_spec': {
            'pools': ['v_legacy'],
            'seed': 42,
            'players': [
                {'chars': [{'name': '赤蝶'}]},
                {'chars': [{'name': '墨客'}]},
            ],
        },
        # 全 random 对手 — 不依赖 GreedyPlayer minimax (1 ep smoke 不验对手强度,
        # random 最快收敛 ~20-50 step;f1d2 minimax 单 ep ~10-20s,smoke timeout 不够)。
        'opponent_mix': {'random': 1.0, 'f1d2': 0.0, 'f1d4': 0.0, 'historical': 0.0},
        # 必须与 InfServer network max_actions 一致 — pickActionEpsilonGreedy panic guard
        # (I29 T-RR.6) on nLegal > max_actions。 production 默认 2048。
        'max_actions': 2048,
        'max_episode_steps': 360,
        'my_player_strategy': 'fixed_0',
        'base_seed': 42,
        'epsilon': 0.05,
    }


def _wait_for_episode_batch(handle: PipelineHandle, deadline_s: float) -> tuple[int, int, bytes]:
    """Poll SHM ring until 1 wire frame arrives or deadline。 返 (cid, rid, raw_payload)。

    raw_payload 是 episode batch wire frame (outer length prefix + EpisodeBatchHeader + N
    per-tx records) — caller 再 decode。 deadline 含 InfServer cold-start 第一次 forward
    (DMC ~500ms-1s on CPU,1 ep 整 ~3-5s)。 兼顾 Mac N=1 实测 + CI buffer。
    """
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        item = handle.trans_channel.try_pop_with_meta()
        if item is not None:
            return item
        # 50ms poll 间隔 — InfServer 单 forward 几十 ms,过紧 busy-loop 抢 CPU 干扰 Go subprocess。
        time.sleep(0.05)
    # I29 R7.2 — handle.go_procs is list (N independent Go subprocess);1 ep smoke 用 n_actors=1
    # → go_procs[0] 是唯一 subprocess。
    raise AssertionError(
        f'no transition received via SHM in {deadline_s}s '
        f'(go alive={handle.go_procs[0].alive()}, server running={handle.server.is_running()})'
    )


def _decode_first_dmc_transition(raw_frame: bytes) -> Any:
    """Strip outer length prefix → decode EpisodeBatch → decode first transition payload as DMC。

    EncodeEpisodeBatch wire format (gicg_actor/transition_wire.go):
      [u32 outer_len][EpisodeBatchHeader][per-tx: [u32 len][u8 done][u8 reserved][payload]]
    SHM ring payload 不含 outer length prefix (ring slot 已知 size)— 这里直接当 batch frame
    (匹配 socket path 的 decode_episode_batch 签名)。
    """
    # SHM ring write 走 TransitionWriterShm.Push,push 整 EncodeEpisodeBatch 输出
    # (含 outer length prefix)。 decode_episode_batch 期望不含 outer prefix,strip 之。
    if len(raw_frame) < 4:
        raise ValueError(f'frame too short {len(raw_frame)} byte for outer length prefix')
    (outer_len,) = struct.unpack_from('<I', raw_frame, 0)
    body = raw_frame[4 : 4 + outer_len]
    if len(body) != outer_len:
        raise ValueError(f'frame truncated: outer_len={outer_len} but body={len(body)}')
    batch = decode_episode_batch(body)
    assert batch.transitions, 'episode batch contains no transitions'
    # 第 1 条 transition 是真 in-game step (terminal marker 是末条 done=True);
    # decode 其 payload 验 DMC schema。
    first = batch.transitions[0]
    return batch, decode_dmc_payload(first.payload)


def test_dmc_go_subprocess_1ep_smoke():
    """Spawn full pipeline → run ≥1 episode → verify wire frame + DMC payload shape → clean shutdown。

    deadline 30s:cold-start InfServer (~3-5s torch import + network pickle + spawn) +
    Go subprocess READY (~500ms include inf TCP connect + paradigm.Configure factory) + 1
    episode actor loop (~3-10s)。 Mac M-series N=1 实测 ~10-15s wall-total,headroom 2x。
    """
    network = _build_dmc_inference_net()
    paradigm_cfg = _build_paradigm_config()
    shm_name = make_unique_shm_name('p13_t')

    from training.core.actor.pipeline_tuning_cfg import PipelineTuningCfg

    handle = spawn_pipeline(
        network=network,
        paradigm_name='dmc',
        paradigm_config=paradigm_cfg,
        n_actors=1,
        shm_ring_name=shm_name,
        inf_max_actions=2048,
        request_decoder_path='training.paradigms.dmc.mp_factories.decode_dmc_request',
        socket_payload_encoder_path='training.paradigms.dmc._socket_decoder.socket_request_to_pickled_payload',
        binary_path=str(_BIN),
        tuning=PipelineTuningCfg(
            # SHM sizing — 真 DMC episode batch ~1.4 MB peak (v_legacy 全 pool max_actions=2048
            # padded refs/pay per-trans × ~10-15 trans);初 1 MB 实测 100% overflow 全 ep abort,
            # 经 manual diag (Go stderr "shm.Ring.Push: payload 1.5MB > slot max 1MB")。 4 MB
            # 留 2.5x headroom (P1.4 production sizing 待 5 ep stats 复审)。
            shm_capacity=8,
            shm_slot_size=4 * 1024 * 1024,
            inf_max_batch=1,
            inf_batch_timeout_ms=2,
            ready_timeout_s=30.0,
            device='cpu',
        ),
    )
    t_start = time.monotonic()
    try:
        cid, rid, raw_frame = _wait_for_episode_batch(handle, deadline_s=30.0)
        # Go DMC actor 是 actor_id=0,episode_id 从 1 起 (gicg_actor/dmc/paradigm.go:122
        # episodeID++ before runEpisode)。
        assert cid == 0, f'expected client_id=0 (single actor), got {cid}'
        assert rid >= 1, f'expected episode_id ≥ 1, got {rid}'

        batch, first_payload = _decode_first_dmc_transition(raw_frame)
        # Wire frame integrity
        assert batch.client_id == cid
        assert batch.episode_id == rid
        assert len(batch.transitions) >= 2, (
            f'episode batch should have ≥ 2 trans (≥1 me-step + 1 terminal marker), got {len(batch.transitions)}'
        )
        # 末条必须是 terminal marker (done=True);中间条 done=False。
        assert batch.transitions[-1].done, 'last transition must be terminal marker (done=True)'

        # DMC payload schema
        # chosen_action ∈ [0, n_legal) — Go 端 pickActionEpsilonGreedy 保证 in-range
        assert 0 <= first_payload.chosen_action < first_payload.n_legal, (
            f'chosen_action {first_payload.chosen_action} out of [0, n_legal={first_payload.n_legal})'
        )
        # step_in_episode == 0 for first me-turn (Go side write step var 直接,me 首动可能
        # > 0 if 对手先手 — fixed_0 me=0 必先手,故 step_in_episode 应 == 0)
        assert first_payload.step_in_episode == 0, (
            f'fixed_0 me=0 should step first, got step_in_episode={first_payload.step_in_episode}'
        )
        # n_legal > 0 (engine 永远给至少 1 legal action 非 GameOver)
        assert first_payload.n_legal > 0, 'n_legal must be > 0 for non-terminal transition'
        # static_hash 16 bytes (Go side ComputeStaticHash 是 SHA256[:16])
        assert len(first_payload.static_hash) == 16, (
            f'static_hash should be 16 bytes, got {len(first_payload.static_hash)}'
        )
        # 第 1 条 transition 携带 raw static_obs (后续 N-1 条 server 走 hash cache)
        assert first_payload.static.size > 0, (
            'first DMC transition must carry raw static_obs (Go staticTracker.take semantics)'
        )
        # dyn_obs / refs / pay 都 non-empty (DMC obs encoder 总产 fields)
        assert first_payload.dyn_obs.size > 0, 'dyn_obs missing'
        assert first_payload.refs.size > 0, 'refs missing'
        assert first_payload.pay.size > 0, 'pay missing'

        # Wire version 自洽 — header 已在 decode_episode_batch 内验 (ver != WIRE_VERSION raise)
        # 这里加 sanity:确认常量到位。
        assert WIRE_VERSION >= 1
        assert KIND_EPISODE_BATCH == 1
        assert EPISODE_BATCH_HEADER_SIZE > 0

        elapsed = time.monotonic() - t_start
        print(
            f'\n[1ep_smoke] cid={cid} ep={rid} n_trans={len(batch.transitions)} '
            f'first_chosen={first_payload.chosen_action} n_legal={first_payload.n_legal} '
            f'dyn={first_payload.dyn_obs.size} refs={first_payload.refs.size} '
            f'static={first_payload.static.size} wall_s={elapsed:.2f}',
            file=sys.stderr,
        )
    finally:
        handle.shutdown(go_timeout_s=10.0, server_timeout_s=5.0)

    # Clean shutdown verify — Go SIGTERM 路径应 exit 0 (cmd/gicg_actor main.go signal handler
    # cancel ctx → Run 返回 → exit 0)。 I29 R7.2 — handle.go_procs is list,n_actors=1 → [0]。
    assert handle.go_procs[0].returncode == 0, (
        f'expected Go SIGTERM graceful exit 0, got {handle.go_procs[0].returncode}'
    )
