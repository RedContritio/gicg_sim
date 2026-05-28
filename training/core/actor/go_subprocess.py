"""GoSubprocessHandle — Python spawner for cmd/gicg_actor standalone executable (I29 redesign)。

Master Python 用 subprocess.Popen spawn Go binary,经 stdin 传 Config JSON,等
subprocess 输出一行 "READY" 表示初始化完毕。 Lifecycle:
spawn → wait_ready (内部) → alive → terminate (SIGTERM + timeout SIGKILL) → join。

deal-breaker invariant #1 of docs/superpowers/specs/2026-05-25-i29-redesign-design.md:
master 0 cgo lib loaded,Go-actor 跑独立 OS subprocess。
"""

from __future__ import annotations

import json
import queue
import re
import signal
import subprocess
import threading
import time
from typing import Any, Optional

# Backpressure stderr line emit by `gicg_actor/dmc/paradigm.go runActor` 每 50 episode:
#   [gicg_actor backpressure] actor=N ep=K push_total=T push_wait_ms=W.W push_drops=D
# master 端 _drain_stderr 内联 parse → atomic 累计 per-actor latest snapshot,collector.collect
# 调 get_backpressure_stats() aggregate 进 runtime_metrics → metrics.jsonl "backpressure" kind。
_BACKPRESSURE_RE = re.compile(
    r'\[gicg_actor backpressure\] actor=(\d+) ep=(\d+) '
    r'push_total=(\d+) push_wait_ms=([\d.]+) push_drops=(\d+)'
)


def _drain_lines_to_queue(stream, q: 'queue.Queue[Optional[str]]') -> None:
    """Background reader thread:blocking readline → queue.put。 EOF → put None 终止。

    替代 select.select(pipe) — Win select 不支持 file descriptor,只支持 socket
    (`OSError: [WinError 10038]`)。 thread + queue 跨平台 POSIX/Win 等价工作。
    """
    try:
        for line in iter(stream.readline, ''):
            q.put(line)
    except Exception:
        pass  # subprocess closed pipe — drained naturally
    finally:
        q.put(None)  # EOF sentinel


class GoSubprocessHandle:
    """Handle for a running Go-actor subprocess。 Not thread-safe;one handle per process。"""

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc
        self.returncode: Optional[int] = None

    @classmethod
    def spawn(
        cls,
        binary_path: str,
        config: dict[str, Any],
        *,
        ready_timeout_s: float = 30.0,
    ) -> 'GoSubprocessHandle':
        """Spawn Go subprocess + 写 Config JSON 到 stdin + 等 'READY' on stdout。

        Fail-loud:若 ready_timeout_s 内 subprocess 退出或未输出 READY,raise RuntimeError
        含 stderr 完整内容。

        Win-compat:用 background thread + queue 读 stdout,非 select.select (Win
        不支持 pipe file descriptor select,POSIX 也工作)。

        H4 (2026-05-28) GOMEMLIMIT 切 cfg-driven path:caller 在 config dict 加
        'go_mem_limit_mb' int 字段 (0 = unbounded / > 0 = MB cap),Go binary parseConfig
        fail-loud on missing。 不再 inject env var GOMEMLIMIT (per [[feedback_cfg_driven_only]]
        runtime 行为不走 env)。
        """
        proc = subprocess.Popen(
            [binary_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )
        # 写 Config JSON + close stdin → Go parseConfig 返回。
        assert proc.stdin is not None
        try:
            proc.stdin.write(json.dumps(config) + '\n')
            proc.stdin.flush()
            proc.stdin.close()
        except BrokenPipeError:
            pass  # subprocess died before write — 下面 readline 会 catch

        # 起 background reader thread (跨平台,Win select 不支持 pipe)。 thread daemon=True
        # 让 main exit 时不阻塞;EOF / subprocess die 时 thread 自然 put None 终止。
        assert proc.stdout is not None
        stdout_q: 'queue.Queue[Optional[str]]' = queue.Queue()
        reader_thr = threading.Thread(
            target=_drain_lines_to_queue,
            args=(proc.stdout, stdout_q),
            daemon=True,
            name=f'gicg_actor[{proc.pid}]_stdout_reader',
        )
        reader_thr.start()

        # Drain stderr in parallel — Win OS pipe buffer (~4 KB) fills if not drained,
        # Go binary 阻塞 next stderr write → 永不 emit READY → master deadlock。
        # 收集 stderr lines 到 list (memoryless) — 错误路径 read 全部 lines。
        # 同时 inline parse `[gicg_actor backpressure]` line → bp_stats per-actor latest snapshot,
        # collector.collect 调 get_backpressure_stats() aggregate 进 metrics.jsonl。
        assert proc.stderr is not None
        stderr_lines: list[str] = []
        bp_stats: dict[int, dict[str, Any]] = {}
        bp_lock = threading.Lock()

        def _drain_stderr() -> None:
            try:
                for line in iter(proc.stderr.readline, ''):
                    stderr_lines.append(line)
                    m = _BACKPRESSURE_RE.search(line)
                    if m:
                        actor_id = int(m.group(1))
                        with bp_lock:
                            bp_stats[actor_id] = {
                                'ep': int(m.group(2)),
                                'push_total': int(m.group(3)),
                                'push_wait_ms': float(m.group(4)),
                                'push_drops': int(m.group(5)),
                            }
            except Exception:
                pass

        stderr_thr = threading.Thread(
            target=_drain_stderr,
            daemon=True,
            name=f'gicg_actor[{proc.pid}]_stderr_reader',
        )
        stderr_thr.start()

        deadline = time.monotonic() + ready_timeout_s
        while True:
            if proc.poll() is not None:
                # subprocess 在 READY 前退出 — 等 stderr reader thread drain 完 (poll 后给 100ms 让残留 stderr 排空) → 拼 fail-loud message。
                stderr_thr.join(timeout=0.5)
                stderr = ''.join(stderr_lines)
                raise RuntimeError(f'Go subprocess exited (rc={proc.returncode}) before READY: {stderr}')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                proc.wait(timeout=5.0)
                raise RuntimeError(f'Go subprocess did not signal READY within {ready_timeout_s}s')
            try:
                line = stdout_q.get(timeout=min(remaining, 0.1))
            except queue.Empty:
                continue
            if line is None:
                # EOF — subprocess closed stdout (about to exit);loop 让 poll() catch
                continue
            line = line.strip()
            if line == 'READY':
                break
            # 其他 stdout (warnings 等) — 透传到 master stderr
            print(f'[gicg_actor stdout] {line}', flush=True)

        handle = cls(proc)
        handle._bp_stats = bp_stats  # type: ignore[attr-defined]
        handle._bp_lock = bp_lock  # type: ignore[attr-defined]
        return handle

    def get_backpressure_stats(self) -> dict[int, dict[str, Any]]:
        """Snapshot per-actor backpressure stats (atomic copy under lock)。
        每 actor 最新 50-episode 累计 (push_total / push_wait_ms / push_drops + ep#)。
        spawn 后 stderr 第一行 backpressure 出之前返空 dict。"""
        bp_stats = getattr(self, '_bp_stats', None)
        bp_lock = getattr(self, '_bp_lock', None)
        if bp_stats is None or bp_lock is None:
            return {}
        with bp_lock:
            return {aid: dict(s) for aid, s in bp_stats.items()}

    def alive(self) -> bool:
        """subprocess 仍在跑?False 时同步设 returncode。"""
        if self._proc.poll() is None:
            return True
        self.returncode = self._proc.returncode
        return False

    def terminate(self, *, timeout_s: float = 10.0) -> None:
        """SIGTERM + wait + SIGKILL fallback。 已死直接 return。"""
        if not self.alive():
            return
        self._proc.send_signal(signal.SIGTERM)
        try:
            self.returncode = self._proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self.returncode = self._proc.wait(timeout=5.0)
