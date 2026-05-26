"""TransitionShmChannel — N-producer single-ring transition channel (I29 redesign 2026-05-25)。

Thin alias over training.core.actor.ipc.ring_shm.CrossLangShmRing。 把通用 ring 封成
specific 用例:N goroutine push transition,master driver single-thread try_pop ingest。

Wire format:payload 字节 = wire v3 episode-batch (gicg_actor/transition_wire.go encode)。
本 channel 不 decode,只搬运 raw bytes (decoder 在 paradigm-specific `_decoder.py`)。

Lifecycle:
- Master 端 create_owner (allocate SHM block + init header,owner 负责 unlink)
- Go subprocess attach_worker (经 stdin Config 传 name + capacity + slot_size)
- Master close() unlink SHM;worker close() 只 detach

详 docs/superpowers/specs/2026-05-25-i29-redesign-design.md §4.2。
"""

from __future__ import annotations

from typing import Optional

from training.core.actor.ipc.ring_shm import CrossLangShmRing


class TransitionShmChannel:
    """Single-ring N-producer transition channel。 owner = master,workers = Go goroutines。"""

    def __init__(self, ring: CrossLangShmRing) -> None:
        self._ring = ring

    @classmethod
    def create_owner(cls, name: str, *, capacity: int, slot_size: int) -> 'TransitionShmChannel':
        """Master 端 create:allocate SHM block + 初始化 header。 调 close() 时 unlink。"""
        ring = CrossLangShmRing(name, capacity, slot_size, create=True)
        return cls(ring)

    @classmethod
    def attach_worker(cls, name: str, *, capacity: int, slot_size: int) -> 'TransitionShmChannel':
        """Worker 端 attach:只 attach 已存在 SHM block,不 init header,不 unlink。"""
        ring = CrossLangShmRing(name, capacity, slot_size, create=False)
        return cls(ring)

    def push(self, payload: bytes, *, client_id: int = 0, req_id: int = 0) -> bool:
        """Non-blocking push — ring 满返 False (worker 端 retry / spin)。"""
        return self._ring.push(payload, client_id=client_id, req_id=req_id)

    def try_pop(self) -> Optional[bytes]:
        """Non-blocking pop payload。 empty 返 None。"""
        return self._ring.try_pop()

    def try_pop_with_meta(self) -> Optional[tuple[int, int, bytes]]:
        """Non-blocking pop 含 (client_id, req_id, payload) — debug / wire test 用。"""
        return self._ring.try_pop_with_meta()

    def close(self) -> None:
        """Detach mmap;owner 也 unlink。"""
        self._ring.close()

    def __enter__(self) -> 'TransitionShmChannel':
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
