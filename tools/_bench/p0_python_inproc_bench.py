"""Python in-process SHMRing push+pop micro-bench — measure master pop ctypes overhead。

Pairing with gicg_actor/shm/shm_bench_test.go (Go same-process pure bench)。

Mac M4 expected:
  - Go same-proc push+pop 12KB: 475 ns/op = 2.10M ops/s
  - Python same-proc 应 ~5-10x slower if ctypes overhead dominant
"""

from __future__ import annotations

import argparse
import time

from training.core.actor.transition_shm_channel import TransitionShmChannel


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--payload-size', type=int, default=12288)
    ap.add_argument('--n-ops', type=int, default=1_000_000)
    args = ap.parse_args()

    ch = TransitionShmChannel.create_owner('py_inproc_bench', capacity=16, slot_size=args.payload_size)
    try:
        payload = b'X' * args.payload_size
        # warm
        for i in range(1000):
            ch.push(payload, client_id=0, req_id=i)
            ch.try_pop()

        t0 = time.monotonic()
        for i in range(args.n_ops):
            ch.push(payload, client_id=0, req_id=i)
            ch.try_pop()
        elapsed = time.monotonic() - t0
        ns_per_op = 1e9 * elapsed / args.n_ops
        ops_per_s = args.n_ops / elapsed
        print(
            f'[py-inproc bench] payload={args.payload_size}B n_ops={args.n_ops} '
            f'elapsed={elapsed:.2f}s ns/op={ns_per_op:.1f} ops/s={ops_per_s:,.0f}'
        )
    finally:
        ch.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
