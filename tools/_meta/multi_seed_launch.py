"""Multi-seed launcher — paradigm-agnostic.

Wraps the unified ``tools.runs.train`` entry (2026-05-18 clean-slate
redesign; pre-redesign launcher was ``tools.run``, deleted in T-23):
for each seed listed in the TOML, dispatches one
``python -m tools.runs.train <cfg> --override meta.seed=<s>
--override meta.run_label=<base>_seed<s>`` invocation.

Replaces the previous AZ-specific wrapper that subprocess-invoked the
legacy ``launch_config`` entry (since archive-removed) directly — that
entry was paradigm-locked (AZ only) and the FU-W2A cleanup moves
multi-seed to the same single-entry pipeline as everything else
(TL2.1 / TL2.3).

TOML schema (additions over a single-seed cfg)::

    seeds       = [42, 43, 44]                 # required
    seed_labels = ["r010_x", "r011_x_seed43",  # required; len == len(seeds)
                   "r012_x_seed44"]            # first = bare, rest = _seedN

Each row in seed_labels follows the existing registry convention used by
``tools._meta.register_run`` (first seed = bare ``<type><NNN>_<slug>``,
rest = ``<type><NNN>_<slug>_seed<N>``).

The cfg itself must already declare ``[meta]`` with ``paradigm``,
``seed`` and ``run_label`` (FU-W1B schema). The wrapper overrides only
``meta.seed`` / ``meta.run_label`` per invocation; everything else
passes through tools.runs.train untouched (inheritance / paradigm
dispatch / pipeline mode all handled by the standard loader).

After all seeds finish, aggregates ``gauntlet_results.jsonl`` from each
``artifacts/*_<seed_label>/`` dir into mean ± std per baseline and
prints the dual judge (curriculum ≥ 0.65 vs random / stricter ≥ 0.40
vs F1-D2, per memory ``project_az_stage0_3_baselines``).

Usage::

    .venv/bin/python -m tools._meta.multi_seed_launch configs/x.toml
    .venv/bin/python -m tools._meta.multi_seed_launch configs/x.toml --host

Resume semantics: a seed whose latest artifact dir already contains a
non-empty gauntlet_results.jsonl is treated as done and reused. Pass
``--no-resume`` to force re-run.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from tools._meta.register_run import (
    REGISTRY_PATH,  # noqa: F401  (re-exported for backwards compat)
    SECTION_HEADERS,  # noqa: F401
    _locate_table,  # noqa: F401
    _next_nnn,  # noqa: F401
    _split_sections,  # noqa: F401
)


def _load_toml(path: Path) -> dict:
    with open(path, 'rb') as f:
        return tomllib.load(f)


def _register(type_prefix: str, label: str, summary: str) -> str:
    """Register one seed's row in the run registry.

    Reuses existing entry on duplicate (re-launch after a kill leaves
    the label registered from the prior attempt); everything else
    stays fatal. Mirrors the pre-rewrite behaviour."""
    res = subprocess.run(
        [
            '.venv/bin/python',
            '-m',
            'tools._meta.register_run',
            '--type',
            type_prefix,
            '--label',
            label,
            '--config',
            summary,
            '--status',
            'pending',
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        if 'label already registered' in res.stderr:
            print(f'[multi_seed_launch] reuse existing registry entry for {label}', flush=True)
            return label
        raise RuntimeError(f'register_run failed for {label}: {res.stderr.strip()}')
    return res.stdout.strip()


def _launch_one(cfg_path: Path, seed: int, label: str, host: bool) -> int:
    """Dispatch one seed through tools.runs.train with overrides.

    Uses ``meta.seed`` + ``meta.run_label`` overrides per TrainingConfig
    schema (FU-W1B). Container vs host-native chosen by ``--host``;
    container path uses an anonymous DOCKER_CONFIG so public-image pulls
    work in keychain-locked Claude sessions (per dc.sh wrapper)."""
    log_path = Path(f'/tmp/{label}.log')
    base = f'python -u -m tools.runs.train {cfg_path.as_posix()} --override meta.seed={seed} --override meta.run_label={label}'
    if host:
        # Host-native: container PyTorch on arm64 Linux is 2-12× slower
        # than host (likely missing Apple Accelerate / NEON BLAS).
        cmd = f'.venv/bin/{base} > {log_path} 2>&1'
    else:
        cmd = f'DOCKER_CONFIG=/tmp/docker-config-anon docker compose run --rm train {base} > {log_path} 2>&1'
    print(f'[multi_seed_launch] {label} (seed={seed}) → {log_path} (host={host})', flush=True)
    return subprocess.run(cmd, shell=True).returncode


def _find_artifact_dir(label: str) -> Path | None:
    candidates = sorted(Path('artifacts').glob(f'*_{label}'), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _read_gauntlet(artifact_dir: Path) -> dict[str, float]:
    path = artifact_dir / 'gauntlet_results.jsonl'
    if not path.exists():
        return {}
    out: dict[str, float] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        opp = row['players'][1]
        if opp['type'] == 'random':
            name = 'random'
        elif opp['type'] == 'mcts_pure':
            name = f'mcts_pure_{opp["n_simulations"]}'
        elif opp['type'] == 'greedy':
            name = f'F{opp["features"][1:]}-D{opp["depth"]}'
        else:
            name = opp['type']
        out[name] = row['aggregate']['win_rate']
    return out


def _aggregate(per_seed_results: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    keys = sorted(set().union(*(r.keys() for r in per_seed_results)))
    agg: dict[str, dict[str, float]] = {}
    for k in keys:
        vals = [r[k] for r in per_seed_results if k in r]
        agg[k] = {
            'mean': statistics.fmean(vals),
            'std': statistics.pstdev(vals) if len(vals) > 1 else 0.0,
            'n': len(vals),
        }
    return agg


def main() -> int:
    ap = argparse.ArgumentParser(prog='tools._meta.multi_seed_launch', description=__doc__)
    ap.add_argument('config', help='TOML with seeds=[...] + seed_labels=[...] fields')
    ap.add_argument('--summary', default='', help='registry config column text')
    ap.add_argument('--host', action='store_true', help='launch on host (skip docker compose)')
    ap.add_argument(
        '--no-resume',
        action='store_true',
        help='re-run every seed even if a complete artifact dir already exists '
        '(default: skip seeds whose gauntlet_results.jsonl is already populated)',
    )
    args = ap.parse_args()

    base_path = Path(args.config)
    cfg = _load_toml(base_path)
    seeds = cfg.get('seeds')
    if not seeds or not isinstance(seeds, list):
        print('ERROR: TOML missing `seeds = [...]` list', file=sys.stderr)
        return 1
    seed_labels = cfg.get('seed_labels')
    if not seed_labels or not isinstance(seed_labels, list) or len(seed_labels) != len(seeds):
        print(
            'ERROR: TOML missing `seed_labels = [...]` aligned with seeds — '
            'must list per-seed labels matching <type><NNN>_<slug>[_seedN] convention. '
            'Example: seed_labels = ["r010_az_xxx", "r011_az_xxx_seed43", "r012_az_xxx_seed44"]',
            file=sys.stderr,
        )
        return 1
    m = re.match(r'^([rs])(\d+)_', seed_labels[0])
    if not m:
        print(f'ERROR: seed_labels[0] {seed_labels[0]!r} not <type><NNN>_...', file=sys.stderr)
        return 1
    type_prefix = m.group(1)
    summary_default = (
        f'{seed_labels[0]} multi-seed n={len(seeds)} '
        f'(auto via tools._meta.multi_seed_launch; seed_labels={seed_labels})'
    )
    summary = args.summary or summary_default

    print(f'[multi_seed_launch] seeds={seeds} labels={seed_labels}', flush=True)
    per_seed: list[tuple[str, dict[str, float]]] = []  # (label, results) — preserve label↔result alignment

    for seed, label in zip(seeds, seed_labels):
        # Resume short-circuit: a label whose latest artifact dir
        # already has a non-empty gauntlet_results.jsonl is treated as
        # done. Skips both register_run (avoids burning a fresh NNN
        # for an already-recorded run) and the train relaunch. Pass
        # --no-resume to force re-run.
        if not args.no_resume:
            existing = _find_artifact_dir(label)
            if existing is not None:
                results = _read_gauntlet(existing)
                if results:
                    print(f'[multi_seed_launch] resume {label}: reuse {existing}', flush=True)
                    per_seed.append((label, results))
                    print(f'[multi_seed_launch] {label} → {results}', flush=True)
                    continue
        rid = _register(type_prefix, label, summary)
        print(f'[multi_seed_launch] registered {rid} ({label})', flush=True)
        rc = _launch_one(base_path, int(seed), label, host=args.host)
        if rc != 0:
            print(f'[multi_seed_launch] launch FAILED {label} rc={rc}', file=sys.stderr)
            continue
        artifact_dir = _find_artifact_dir(label)
        if artifact_dir is None:
            print(f'[multi_seed_launch] no artifact dir for {label}', file=sys.stderr)
            continue
        results = _read_gauntlet(artifact_dir)
        if results:
            per_seed.append((label, results))
            print(f'[multi_seed_launch] {label} → {results}', flush=True)
        else:
            print(f'[multi_seed_launch] no gauntlet results in {artifact_dir}', file=sys.stderr)

    if not per_seed:
        print('[multi_seed_launch] NO RESULTS — all seeds failed', file=sys.stderr)
        return 2

    results_only = [r for (_, r) in per_seed]
    agg = _aggregate(results_only)
    rand = agg.get('random', {}).get('mean', 0.0)
    f1d2 = agg.get('F1-D2', {}).get('mean', 0.0)
    completed_labels = [lbl for (lbl, _) in per_seed]
    print(f'\n=== Multi-seed verdict (labels={completed_labels}) ===', flush=True)
    print(f'  n={len(per_seed)}/{len(seeds)} seeds reporting', flush=True)
    for k, v in agg.items():
        print(f'  {k:20s} {v["mean"]:.4f} ± {v["std"]:.4f}  (n={v["n"]})', flush=True)
    print(f'\n  curriculum_pass (vs random ≥ 0.65): {rand >= 0.65}  ({rand:.4f})', flush=True)
    print(f'  stricter_pass   (vs F1-D2 ≥ 0.40):  {f1d2 >= 0.40}  ({f1d2:.4f})', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
