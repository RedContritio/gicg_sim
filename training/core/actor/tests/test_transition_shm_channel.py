"""I29 redesign P0.3 — TransitionShmChannel thin wrapper test。

Cover:
- owner create + worker attach + cross-process push/pop wire 完整性
- push 满 ring 返 False (backpressure 信号源)
"""

from training.core.actor.transition_shm_channel import TransitionShmChannel


def test_owner_create_then_external_attach():
    name = 'gicg_test_p03_trans'
    ch = TransitionShmChannel.create_owner(name, capacity=4, slot_size=64)
    try:
        # external attach (worker side — same process here for unit test;Go side 实际跑 cross-process)
        worker = TransitionShmChannel.attach_worker(name, capacity=4, slot_size=64)
        try:
            assert worker.push(b'hello world', client_id=0, req_id=1)
            item = ch.try_pop_with_meta()
            assert item is not None
            cid, rid, payload = item
            assert (cid, rid, payload) == (0, 1, b'hello world')
            # empty after pop
            assert ch.try_pop_with_meta() is None
        finally:
            worker.close()
    finally:
        ch.close()


def test_push_full_returns_false():
    name = 'gicg_test_p03_full'
    ch = TransitionShmChannel.create_owner(name, capacity=2, slot_size=16)
    try:
        worker = TransitionShmChannel.attach_worker(name, capacity=2, slot_size=16)
        try:
            assert worker.push(b'a')
            assert worker.push(b'b')
            # 第 3 push 应返 False (ring 满 — backpressure signal)
            assert not worker.push(b'c')
        finally:
            worker.close()
    finally:
        ch.close()


def test_multi_push_pop_preserves_order():
    """N push → N pop 顺序保留 (single-producer for now;multi-producer 顺序不保证,但 N=1 时保)。"""
    name = 'gicg_test_p03_order'
    ch = TransitionShmChannel.create_owner(name, capacity=8, slot_size=32)
    try:
        worker = TransitionShmChannel.attach_worker(name, capacity=8, slot_size=32)
        try:
            for i in range(5):
                assert worker.push(f'msg_{i}'.encode(), client_id=0, req_id=i)
            for i in range(5):
                item = ch.try_pop_with_meta()
                assert item is not None
                cid, rid, payload = item
                assert (cid, rid, payload) == (0, i, f'msg_{i}'.encode())
            assert ch.try_pop_with_meta() is None
        finally:
            worker.close()
    finally:
        ch.close()
