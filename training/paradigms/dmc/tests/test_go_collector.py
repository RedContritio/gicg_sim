"""DMCGoActorCollector 单测 — _drain_queue_assemble lazy-ingest + collect/_enqueue 接线
(I29 T-RR.3)。

backpressure 端到端重构:listener 只把 raw transition 推进有界 queue;driver 线程在
collect() 调 _drain_queue_assemble 从 queue lazy-ingest —— 只取够 target 个 episode
的 transition,余下留 queue(queue 满 → listener 阻塞 put → socket 回压 → Go 限流)。

本文件单测:_drain_queue_assemble 的 lazy / deadline / interleaved 行为;collect() 从
queue 取 episode 的接线;_enqueue 的 put / stop-丢弃。 真 backpressure(socket → Go
阻塞)+ close() 不 hang 走 Win stress(T-RR.9)。
"""

from __future__ import annotations

import queue
import threading
import time
import types

import numpy as np

from training.core.actor.transition_sink_wire import Transition, encode_dmc_payload
from training.paradigms.dmc._go_assembler import DmcTransitionAssembler
from training.paradigms.dmc.go_collector import DMCGoActorCollector, _drain_queue_assemble

_SCENARIO = {
    'n_counter_slots': 32,
    'n_hooks': 64,
    'max_ops_per_hook': 8,
    'fields_per_op': 5,
    'max_actions': 30,
}


def _static_obs() -> np.ndarray:
    from training.core.obs_constants import OBS_CHAR_SKILL_REFS_SIZE, OBS_CHAR_ELEMENT_SLOTS

    total = (
        _SCENARIO['n_counter_slots'] * 3
        + OBS_CHAR_SKILL_REFS_SIZE
        + _SCENARIO['n_hooks'] * _SCENARIO['max_ops_per_hook'] * _SCENARIO['fields_per_op']
        + OBS_CHAR_ELEMENT_SLOTS
    )
    return np.arange(total, dtype=np.int32)


def _transition(episode_id: int, step: int, *, done: bool, with_static: bool, reward: float = 0.0) -> Transition:
    # I29 P2 wire v3 — refs/pay 是 nlegal-sized,不 pad 到 max_actions。
    n_legal = 5
    payload = encode_dmc_payload(
        chosen_action=0,
        step_in_episode=step,
        reward=reward,
        n_legal=n_legal,
        static_hash=b'\x01' * 16,
        dyn_obs=np.arange(4096, dtype=np.float32),
        refs=np.arange(n_legal * 3, dtype=np.int64),
        pay=np.arange(n_legal * 8, dtype=np.float32),
        static=_static_obs() if with_static else None,
    )
    return Transition(client_id=0, episode_id=episode_id, step=step, done=done, payload=payload)


def _done_episode(episode_id: int) -> Transition:
    """单条 done transition 的 episode(自带 static)。"""
    return _transition(episode_id, 0, done=True, with_static=True, reward=1.0)


# --- _drain_queue_assemble --------------------------------------------------


def test_drain_queue_assemble_lazy_leaves_remainder():
    """只 ingest 够 target 个 episode 的 transition,余下留 queue —— collect 不 over-drain。

    backpressure 的关键:queue 是唯一 backlog 蓄水池,collect 不抽干,故 producer 快于
    consumer 时 queue 涨到上限触发 socket 回压;若抽干则无界增长搬到 _ready。
    """
    asm = DmcTransitionAssembler(**_SCENARIO)
    q: queue.Queue = queue.Queue()
    for ep in range(1, 4):  # 3 个单步 episode
        q.put(_done_episode(ep))
    out = _drain_queue_assemble(q, asm, target=2, deadline_s=2.0)
    assert len(out) == 2
    assert q.qsize() == 1  # 第 3 个 episode 未被 ingest


def test_drain_queue_assemble_interleaved():
    """N actor 交错推送下,lazy-ingest 仍只取够 target 个完整 episode。

    queue 序:ep1-real, ep2-real, ep1-done, ep2-done。 target=1 → 取到 ep1-done 即停,
    ep2-done 留 queue。
    """
    asm = DmcTransitionAssembler(**_SCENARIO)
    q: queue.Queue = queue.Queue()
    q.put(_transition(1, 0, done=False, with_static=True))
    q.put(_transition(2, 0, done=False, with_static=True))
    q.put(_transition(1, 1, done=True, with_static=False, reward=1.0))
    q.put(_transition(2, 1, done=True, with_static=False, reward=-1.0))
    out = _drain_queue_assemble(q, asm, target=1, deadline_s=2.0)
    assert len(out) == 1
    assert out[0].episode_id == 1
    assert q.qsize() == 1  # ep2-done 留在 queue


def test_drain_queue_assemble_deadline_returns_partial():
    """queue 不够 target → deadline 到返回已组装的(< target)。"""
    asm = DmcTransitionAssembler(**_SCENARIO)
    q: queue.Queue = queue.Queue()
    q.put(_done_episode(1))
    out = _drain_queue_assemble(q, asm, target=5, deadline_s=0.3)
    assert len(out) == 1


def test_drain_queue_assemble_deadline_bounds_walltime():
    """queue 持续非空但无 episode 完成时,deadline 仍在墙钟上界 break。

    I29 T-RR.3 reviewer #4:deadline 检查必须在循环顶无条件执行 —— 若只在 queue.Empty
    分支检查,producer 高速时 q.get 永不抛 Empty,deadline 形同虚设,collect 不返回。
    """
    asm = DmcTransitionAssembler(**_SCENARIO)
    q: queue.Queue = queue.Queue()
    stop = threading.Event()

    def producer() -> None:
        # 自停 2s —— 即便 deadline bug 在,测试也不会无限 hang(bug 版本 ~2s 返回,
        # fix 版本 ~0.5s 返回)。 全 non-done transition,episode 永不完成。
        end = time.monotonic() + 2.0
        step = 0
        while time.monotonic() < end and not stop.is_set():
            step += 1
            q.put(_transition(episode_id=(step % 5) + 1, step=step, done=False, with_static=True))
            time.sleep(0.002)

    pt = threading.Thread(target=producer, daemon=True)
    pt.start()
    try:
        t0 = time.monotonic()
        out = _drain_queue_assemble(q, asm, target=1, deadline_s=0.5)
        elapsed = time.monotonic() - t0
    finally:
        stop.set()
        pt.join(timeout=2.0)
    assert out == []
    assert elapsed < 1.0, f'deadline 0.5s 未生效:collect 耗 {elapsed:.2f}s(deadline 只在 Empty 分支?)'


def test_drain_queue_assemble_target_zero():
    """target=0 → 立即返回(while n_ready() < 0 即 false)。 锚定边界行为。"""
    asm = DmcTransitionAssembler(**_SCENARIO)
    q: queue.Queue = queue.Queue()
    q.put(_done_episode(1))
    out = _drain_queue_assemble(q, asm, target=0, deadline_s=2.0)
    assert out == []
    assert q.qsize() == 1  # 未 ingest


# --- DMCGoActorCollector.collect / _enqueue 接线 -----------------------------


def _stub_collector() -> DMCGoActorCollector:
    """构造一个不起 socket stack 的 collector(stub network/cfg)。 测试用 _spawned=True
    跳过 _bootstrap,直接喂 _trans_queue 验 collect / _enqueue 接线。"""
    net = types.SimpleNamespace(
        net=types.SimpleNamespace(
            n_counter_slots=_SCENARIO['n_counter_slots'],
            n_hooks=_SCENARIO['n_hooks'],
            max_ops_per_hook=_SCENARIO['max_ops_per_hook'],
            fields_per_op=_SCENARIO['fields_per_op'],
        )
    )
    return DMCGoActorCollector(
        cfg=types.SimpleNamespace(),
        network=net,
        paradigm_cfg_dict={'max_actions': _SCENARIO['max_actions']},
        n_actors=1,
    )


def test_collector_collect_lazy_from_queue():
    """collect() 从有界 queue lazy-ingest,只取 n_episodes 个 episode,余下留 queue。"""
    c = _stub_collector()
    c._spawned = True  # 跳过 _bootstrap(不起 InfServer / listener / Go pool)
    for ep in (1, 2, 3):
        c._trans_queue.put(_done_episode(ep))

    out = c.collect(n_episodes=1, provider=None)
    assert out.runtime_metrics['n_dmc_episodes'] == 1
    assert c._trans_queue.qsize() == 2  # ep2 / ep3 留在 queue,不丢弃

    out2 = c.collect(n_episodes=1, provider=None)
    assert out2.runtime_metrics['n_dmc_episodes'] == 1
    assert c._trans_queue.qsize() == 1


def test_collector_enqueue_puts_then_drops_on_stop():
    """_enqueue:正常推进 queue;listener stop set 后丢弃(不阻塞)。"""
    c = _stub_collector()
    c._trans_listener_stop = threading.Event()
    c._enqueue(_done_episode(1))
    assert c._trans_queue.qsize() == 1

    c._trans_listener_stop.set()  # shutting down
    c._enqueue(_done_episode(2))
    assert c._trans_queue.qsize() == 1  # 丢弃,未增加
