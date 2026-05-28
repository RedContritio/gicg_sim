"""CrossLangShmRing Python-side correctness tests.

Tests cover: create/close lifecycle, single-thread req ring roundtrip, ring full/empty
edge cases, resp slot write+read, and payload-too-large guard.

Cross-language correctness (Go producer ↔ Python consumer) is already verified by
tools/_dev/shm_ring_spike.py (Phase 1); these tests only cover Python-side behaviour.

Phase 4 (2026-05-24): Windows support added (libshm.dll via mingw gcc); these
tests now run on all three platforms. If the test fails to compile libshm on
Win the module-level import will raise — gating on shutil.which('gcc') keeps
CI failures actionable (most Win Python envs without MSYS2 won't have gcc).
"""

from __future__ import annotations

import shutil
import sys

import pytest

# Win-only gate: the libshm.dll auto-build needs mingw gcc on PATH. CI agents
# without it should skip rather than report a misleading compile failure.
if sys.platform == 'win32' and shutil.which('gcc') is None:
    pytest.skip(
        'CrossLangShmRing: libshm.dll auto-build needs mingw gcc on PATH (install MSYS2)',
        allow_module_level=True,
    )

from training.core.actor.ipc.ring_shm import CrossLangShmRing  # noqa: E402


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _unique_name(prefix: str) -> str:
    """Generate a unique SHM name safe for POSIX shm_open (no leading slash)."""
    import os
    import time

    ts = int(time.monotonic_ns()) & 0xFFFFFF
    return f'{prefix}_{os.getpid()}_{ts}'


# ─── Lifecycle ────────────────────────────────────────────────────────────────


class TestCreateAndClose:
    def test_create_then_close_does_not_crash(self):
        """Minimal lifecycle: create → close must not segfault."""
        name = _unique_name('shmt_cc')
        ring = CrossLangShmRing(name, capacity=4, slot_payload_max=64, create=True)
        ring.close()

    def test_context_manager_closes(self):
        """with-statement close path must not raise."""
        name = _unique_name('shmt_ctx')
        with CrossLangShmRing(name, capacity=4, slot_payload_max=64, create=True):
            pass

    def test_double_close_is_safe(self):
        """close() called twice must not raise."""
        name = _unique_name('shmt_dc')
        ring = CrossLangShmRing(name, capacity=4, slot_payload_max=64, create=True)
        ring.close()
        ring.close()

    def test_classmethod_attach_equals_create_false(self):
        """CrossLangShmRing.attach(...) creates a non-owner view without crashing."""
        name = _unique_name('shmt_att')
        owner = CrossLangShmRing(name, capacity=4, slot_payload_max=64, create=True)
        try:
            worker = CrossLangShmRing.attach(name, capacity=4, slot_payload_max=64)
            worker.close()
        finally:
            owner.close()

    def test_invalid_capacity_raises(self):
        with pytest.raises(ValueError, match='capacity must be > 0'):
            CrossLangShmRing(_unique_name('shmt_ic'), capacity=0, slot_payload_max=64, create=True)

    def test_invalid_slot_payload_max_raises(self):
        with pytest.raises(ValueError, match='slot_payload_max must be > 0'):
            CrossLangShmRing(_unique_name('shmt_ip'), capacity=4, slot_payload_max=0, create=True)


# ─── Req ring: single-thread roundtrip ────────────────────────────────────────


class TestSingleThreadRoundtrip:
    def test_push_and_pop_single_item(self):
        """push 1 item → pop returns exactly that payload."""
        name = _unique_name('shmt_st1')
        with CrossLangShmRing(name, capacity=8, slot_payload_max=64, create=True) as ring:
            payload = b'hello ring'
            assert ring.push(payload) is True
            got = ring.try_pop()
            assert got == payload

    def test_push_and_pop_multiple_items_in_order(self):
        """push N items → pop N items in FIFO order with correct payloads."""
        name = _unique_name('shmt_stN')
        capacity = 8
        with CrossLangShmRing(name, capacity=capacity, slot_payload_max=32, create=True) as ring:
            payloads = [f'msg-{i:04d}'.encode() for i in range(capacity)]
            for p in payloads:
                assert ring.push(p) is True
            for expected in payloads:
                got = ring.try_pop()
                assert got == expected, f'expected {expected!r}, got {got!r}'

    def test_push_pop_interleaved(self):
        """Interleaved push/pop must maintain FIFO order."""
        name = _unique_name('shmt_il')
        with CrossLangShmRing(name, capacity=4, slot_payload_max=32, create=True) as ring:
            for i in range(12):
                payload = f'item-{i:03d}'.encode()
                assert ring.push(payload) is True
                got = ring.try_pop()
                assert got == payload

    def test_try_pop_with_meta_returns_client_id_and_req_id(self):
        """try_pop_with_meta must return the client_id/req_id written by push."""
        name = _unique_name('shmt_meta')
        with CrossLangShmRing(name, capacity=4, slot_payload_max=32, create=True) as ring:
            ring.push(b'payload', client_id=7, req_id=42)
            result = ring.try_pop_with_meta()
            assert result is not None
            cid, rid, payload = result
            assert cid == 7
            assert rid == 42
            assert payload == b'payload'

    def test_empty_payload_roundtrip(self):
        """Zero-length payload must push and pop without error."""
        name = _unique_name('shmt_empty_pl')
        with CrossLangShmRing(name, capacity=4, slot_payload_max=32, create=True) as ring:
            assert ring.push(b'') is True
            got = ring.try_pop()
            assert got == b''


# ─── Ring full / empty edge cases ─────────────────────────────────────────────


class TestRingFull:
    def test_push_returns_false_when_full(self):
        """push to a full ring must return False (not raise)."""
        name = _unique_name('shmt_full')
        capacity = 4
        with CrossLangShmRing(name, capacity=capacity, slot_payload_max=32, create=True) as ring:
            for i in range(capacity):
                assert ring.push(f'x{i}'.encode()) is True
            # Ring is now full — next push must return False.
            assert ring.push(b'overflow') is False

    def test_ring_usable_after_pop_from_full(self):
        """After popping from a full ring, one more push must succeed."""
        name = _unique_name('shmt_recover')
        capacity = 4
        with CrossLangShmRing(name, capacity=capacity, slot_payload_max=32, create=True) as ring:
            for i in range(capacity):
                ring.push(f'x{i}'.encode())
            # Drain one slot.
            ring.try_pop()
            # Now one slot is free.
            assert ring.push(b'new_item') is True


class TestRingEmpty:
    def test_try_pop_returns_none_on_empty_ring(self):
        """try_pop on an empty ring must return None."""
        name = _unique_name('shmt_emp')
        with CrossLangShmRing(name, capacity=4, slot_payload_max=32, create=True) as ring:
            assert ring.try_pop() is None

    def test_try_pop_with_meta_returns_none_on_empty_ring(self):
        name = _unique_name('shmt_emp_meta')
        with CrossLangShmRing(name, capacity=4, slot_payload_max=32, create=True) as ring:
            assert ring.try_pop_with_meta() is None

    def test_try_pop_returns_none_after_draining_all_items(self):
        """After draining all items, subsequent try_pop must return None."""
        name = _unique_name('shmt_drain')
        with CrossLangShmRing(name, capacity=4, slot_payload_max=32, create=True) as ring:
            ring.push(b'one')
            ring.push(b'two')
            ring.try_pop()
            ring.try_pop()
            assert ring.try_pop() is None


# ─── Resp slot ────────────────────────────────────────────────────────────────


class TestRespSlot:
    def test_resp_write_then_read_blocking(self):
        """resp_write + resp_read_blocking on capacity=1 ring returns correct data."""
        name = _unique_name('shmt_resp')
        with CrossLangShmRing(name, capacity=1, slot_payload_max=128, create=True) as ring:
            payload = b'inference_response_data'
            ok = ring.resp_write(payload, req_id=99, timeout_ms=500)
            assert ok is True
            got = ring.resp_read_blocking(timeout_ms=500)
            assert got == payload

    def test_resp_read_blocking_timeout_returns_none(self):
        """resp_read_blocking with no producer must return None after timeout."""
        name = _unique_name('shmt_resp_to')
        with CrossLangShmRing(name, capacity=1, slot_payload_max=32, create=True) as ring:
            result = ring.resp_read_blocking(timeout_ms=50)
            assert result is None

    def test_resp_write_timeout_returns_false_if_slot_never_emptied(self):
        """resp_write with a FULL slot (unread) and short timeout must return False."""
        name = _unique_name('shmt_resp_wto')
        with CrossLangShmRing(name, capacity=1, slot_payload_max=32, create=True) as ring:
            # Fill the slot.
            ring.resp_write(b'first', timeout_ms=500)
            # Second write must time out because slot is still FULL (nobody read it).
            result = ring.resp_write(b'second', timeout_ms=50)
            assert result is False

    def test_resp_read_blocking_requires_positive_timeout(self):
        """resp_read_blocking with timeout_ms <= 0 must raise ValueError."""
        name = _unique_name('shmt_resp_v')
        with CrossLangShmRing(name, capacity=1, slot_payload_max=32, create=True) as ring:
            with pytest.raises(ValueError, match='timeout_ms must be > 0'):
                ring.resp_read_blocking(timeout_ms=0)


# ─── Payload too large ────────────────────────────────────────────────────────


class TestPushPayloadTooLarge:
    def test_push_raises_value_error_if_payload_exceeds_slot_max(self):
        """push with payload > slot_payload_max must raise ValueError immediately."""
        name = _unique_name('shmt_big')
        with CrossLangShmRing(name, capacity=4, slot_payload_max=16, create=True) as ring:
            with pytest.raises(ValueError, match='slot_payload_max'):
                ring.push(b'x' * 17)

    def test_resp_write_raises_value_error_if_payload_exceeds_slot_max(self):
        name = _unique_name('shmt_resp_big')
        with CrossLangShmRing(name, capacity=1, slot_payload_max=16, create=True) as ring:
            with pytest.raises(ValueError, match='slot_payload_max'):
                ring.resp_write(b'y' * 17)

    def test_push_at_exact_slot_max_succeeds(self):
        """payload == slot_payload_max must succeed (boundary is inclusive)."""
        name = _unique_name('shmt_exact')
        slot_max = 16
        with CrossLangShmRing(name, capacity=4, slot_payload_max=slot_max, create=True) as ring:
            assert ring.push(b'a' * slot_max) is True
            got = ring.try_pop()
            assert got == b'a' * slot_max


# ─── peek_count_and_full_at_head (H3 race-aware diagnostic) ───────────────────


class TestPeekCountAndFullAtHead:
    """H3 (2026-05-28 audit):race-aware ring inspection — 区分 over-reserve race
    (count > 0 但 slot 全 EMPTY) vs actor stall (count = 0) vs healthy ring。
    bc6b1b8 fix 留瞬时窗口 (count++ 早于 status=FULL),master 端 debug 必备。"""

    def test_empty_ring_returns_zero_zero(self):
        """empty ring (no push yet) → count=0, n_full=0。"""
        name = _unique_name('shmt_pkz')
        with CrossLangShmRing(name, capacity=4, slot_payload_max=32, create=True) as ring:
            count, n_full = ring.peek_count_and_full_at_head()
            assert count == 0
            assert n_full == 0

    def test_fully_pushed_ring_count_equals_full(self):
        """N push 后未 pop → count==n_full==N (healthy ring 正常路径)。"""
        name = _unique_name('shmt_pkf')
        capacity = 4
        with CrossLangShmRing(name, capacity=capacity, slot_payload_max=32, create=True) as ring:
            for i in range(capacity):
                assert ring.push(f'item-{i}'.encode()) is True
            count, n_full = ring.peek_count_and_full_at_head()
            assert count == capacity
            assert n_full == capacity

    def test_partial_push_count_equals_full(self):
        """部分 push (K < capacity) → count==n_full==K。"""
        name = _unique_name('shmt_pkp')
        with CrossLangShmRing(name, capacity=8, slot_payload_max=32, create=True) as ring:
            for i in range(3):
                assert ring.push(f'item-{i}'.encode()) is True
            count, n_full = ring.peek_count_and_full_at_head()
            assert count == 3
            assert n_full == 3

    def test_simulated_over_reserve_race(self):
        """模拟 bc6b1b8 race window:手动 poke header.count=K 但 slot status 全 EMPTY,
        peek_count_and_full_at_head 应返 (K, 0) 区分出来 (vs healthy 时是 (K, K))。

        这是 production B-go-sustained-collection-deadlock debug 的关键 case — Win
        N=16 25min 后 peek_count 持续报 > 0 但 master pop 拿不到,本测验证 race-aware
        probe 能给出"count vs full 不一致"信号让 debugger 一眼看出 over-reserve race。
        """
        import struct as _s

        name = _unique_name('shmt_pkr')
        capacity = 4
        with CrossLangShmRing(name, capacity=capacity, slot_payload_max=32, create=True) as ring:
            # 直接 poke SHM header count 字段 = 3,但不调 push (slot status 仍 EMPTY=0)。
            # 模拟 producer CAS-count 成功但还没 store status=FULL 的瞬时窗口。
            _s.pack_into('<i', ring._shm.buf, 8, 3)  # offset 8 = count int32
            count, n_full = ring.peek_count_and_full_at_head()
            assert count == 3, f'count poke expected 3, got {count}'
            assert n_full == 0, f'over-reserve race → n_full must be 0 (slots still EMPTY), got {n_full}'
            # 复位避免 close() 反操作 (slot 已 empty,只 count > 0 → close 不读 count)。
            _s.pack_into('<i', ring._shm.buf, 8, 0)

    def test_simulated_partial_window_race(self):
        """中间状态:count=K, 但只前 M<K 个 slot 已 FULL → 返 (K, M)。

        实际生产里少见 (CAS-count 串行,partial commit 几乎是 nanosecond 级)，但本测
        守住 wrap-around 处理 + 部分 FULL 计数逻辑正确。
        """
        import struct as _s

        name = _unique_name('shmt_pkpw')
        capacity = 4
        with CrossLangShmRing(name, capacity=capacity, slot_payload_max=32, create=True) as ring:
            # 真 push 2 个 → count=2, slot[0..1].status=FULL
            ring.push(b'a')
            ring.push(b'b')
            # 然后 poke count = 4 (模拟 producer 已 CAS 但 slot[2..3] 还 EMPTY)
            _s.pack_into('<i', ring._shm.buf, 8, 4)
            count, n_full = ring.peek_count_and_full_at_head()
            assert count == 4, f'count poke expected 4, got {count}'
            assert n_full == 2, f'partial window → n_full=2 (first 2 slots FULL), got {n_full}'
            # 复位 count 给 close() 看到 sane state
            _s.pack_into('<i', ring._shm.buf, 8, 2)

    def test_wrap_around_full_count(self):
        """Ring wrap-around (head > 0):push N, pop M, push M 后 head=M, count=N,
        peek 应正确 wrap idx = (head + i) % capacity 不越界。"""
        name = _unique_name('shmt_pkw')
        capacity = 4
        with CrossLangShmRing(name, capacity=capacity, slot_payload_max=32, create=True) as ring:
            for i in range(capacity):
                ring.push(f'p{i}'.encode())
            # pop 2 → head=2, count=2
            ring.try_pop()
            ring.try_pop()
            # 再 push 2 → head=2, tail wrap, count=4
            ring.push(b'p4')
            ring.push(b'p5')
            count, n_full = ring.peek_count_and_full_at_head()
            assert count == capacity
            assert n_full == capacity, f'wrap-around should still find all {capacity} FULL, got {n_full}'
