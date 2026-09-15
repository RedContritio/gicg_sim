"""Background daemon threads driven by ``MetricsLogger``。

``_ResourceSamplerThread`` 周期 call 一个 ``_sample_*`` 并把 payload 交给
``logger.log``;``_QueueDrainerThread`` drain 跨进程 queue 的 ``(kind, payload)``
tuple 转发给同一个 ``logger.log``。两者都只依赖 ``logger.log`` 接口,故不 import
``MetricsLogger``。
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from training.core.logging import MetricsLogger


class _ResourceSamplerThread(threading.Thread):
    """Daemon thread emitting one ``kind=<kind>`` row per ``interval_s``。

    Generic sampler — ``sample_fn`` returns payload dict, thread logs via
    ``logger.log(kind, payload)``。 Uses ``Event.wait()`` (not ``sleep``) so
    ``stop()`` returns promptly on close instead of waiting up to a full
    interval。"""

    def __init__(
        self,
        logger: 'MetricsLogger',
        kind: str,
        interval_s: float,
        sample_fn,
        prime_fn=None,
    ) -> None:
        super().__init__(name=f'MetricsLogger{kind.capitalize()}Sampler', daemon=True)
        self._logger = logger
        self._kind = kind
        self._interval_s = interval_s
        self._sample_fn = sample_fn
        self._prime_fn = prime_fn
        self._stop_event = threading.Event()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=timeout)

    def run(self) -> None:
        if self._prime_fn is not None:
            try:
                self._prime_fn()
            except Exception:  # noqa: BLE001
                pass
        # Initial sample (so close-before-first-interval still emits ≥1 row).
        self._sample_once()
        while not self._stop_event.is_set():
            if self._stop_event.wait(self._interval_s):
                break
            self._sample_once()

    def _sample_once(self) -> None:
        try:
            payload = self._sample_fn()
        except Exception:  # noqa: BLE001 — sampler must never kill train
            return
        self._logger.log(self._kind, payload)


class _QueueDrainerThread(threading.Thread):
    """Daemon thread draining (kind, payload) tuples from a cross-process
    queue + forwarding each to ``logger.log(kind, payload)``。

    用于跨进程 stats push:子进程(InfServer / actor)主动 push 自己采的指标
    到这条 mp.Queue,master process 的 logger 起本 thread drain,无需子进程
    直接持 metrics.jsonl 文件句柄 — 文件 locking 跨进程在 Win 不可靠,本
    模式让所有写都在 master 走 _write_lock。

    支持的 queue 接口:任何 ``get(timeout=N)`` / ``empty()`` 兼容(mp.Queue,
    queue.Queue,Manager.Queue 都行)。empty 时 thread 用 0.1s timeout
    polling — 不阻塞 stop()。stop() 设 Event,run() loop 每 iter 检。

    Queue item 形状必须是 ``(kind: str, payload: dict)`` 二元组;不合规
    silently drop(防 stats push 端 bug kill drainer)。"""

    def __init__(self, logger: 'MetricsLogger', queue, name: str = 'external') -> None:
        super().__init__(name=f'MetricsLoggerQueueDrainer-{name}', daemon=True)
        self._logger = logger
        self._queue = queue
        self._source_name = name
        self._stop_event = threading.Event()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=timeout)

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.1)
            except Exception:  # noqa: BLE001 — queue.Empty / OSError / EOFError
                continue
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            kind, payload = item
            if not isinstance(kind, str) or not isinstance(payload, dict):
                continue
            self._logger.log(kind, payload)
