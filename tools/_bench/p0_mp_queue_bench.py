"""Micro-bench: Python mp.Queue round-trip per-call cost。

Pairing with P0 SHM micro-bench — verify Python mp baseline inference IPC actual cost
(P2 subagent FAIL_REPORT 假说 Python mp 走 SHM 5µs/call,实际 verify 走 mp.Queue,需 measure 真值)。

Usage:
  .venv/bin/python -m tools._bench.p0_mp_queue_bench --payload-size 12288 --n-ops 10000
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import time


def _echo_worker(req_q, resp_q, ready_evt):
    ready_evt.set()
    while True:
        item = req_q.get()
        if item is None:
            break
        resp_q.put(item)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--payload-size', type=int, default=12288)
    ap.add_argument('--n-ops', type=int, default=10000)
    args = ap.parse_args()

    ctx = mp.get_context('spawn')
    req_q = ctx.Queue()
    resp_q = ctx.Queue()
    ready_evt = ctx.Event()
    p = ctx.Process(target=_echo_worker, args=(req_q, resp_q, ready_evt))
    p.start()
    ready_evt.wait(timeout=10.0)

    payload = b'X' * args.payload_size

    # Warm
    for _ in range(100):
        req_q.put(payload)
        resp_q.get()

    t0 = time.monotonic()
    for _ in range(args.n_ops):
        req_q.put(payload)
        resp_q.get()
    elapsed = time.monotonic() - t0

    us_per_op = 1e6 * elapsed / args.n_ops
    ops_per_s = args.n_ops / elapsed
    print(f'[mp.Queue bench] payload={args.payload_size}B n_ops={args.n_ops} '
          f'elapsed={elapsed:.2f}s µs/round-trip={us_per_op:.1f} ops/s={ops_per_s:,.0f}')

    req_q.put(None)
    p.join(timeout=5.0)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
