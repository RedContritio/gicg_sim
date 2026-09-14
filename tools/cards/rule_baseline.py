"""Freeze/check the local custom-rule baseline; hashes do not certify rules."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / 'openspec/changes/pre-rl-ready-v14/source-manifest.json'


def sources(root: Path, manifest: Path) -> dict[str, str]:
    paths = set()
    for directory in ('data/system', 'data/pools/v_legacy', 'data/pools/test_basic'):
        paths.update(p for p in (root / directory).rglob('*') if p.is_file())
    for directory in ('gicg_engine', 'gicg_mcts', 'gicg_actor'):
        paths.update((root / directory).rglob('*.go'))
    paths.update((root / 'tools/cards').rglob('*.go'))
    paths.update((root / 'tools/cards').rglob('*.py'))
    paths.update((root / 'training/tests').rglob('*.py'))
    for directory in (
        'gicg_env',
        'training/core',
        'training/paradigms',
        'tools/experiments',
        'tools/dataset',
        'tools/runs',
        'tools/eval',
        'tools/_dev',
    ):
        paths.update((root / directory).rglob('*.py'))
    for name in (
        'training/core/step_encoding.py',
        'training/core/obs_constants.py',
        'training/core/rule_learning.py',
        'tools/cards/rule_cost_probe.py',
    ):
        if (root / name).is_file():
            paths.add(root / name)
    paths.update(p for p in (root / 'configs').rglob('*.toml') if 'archive' not in p.parts)
    paths.update(root / name for name in ('go.mod', 'go.sum') if (root / name).exists())
    paths.update(
        manifest.parent / name
        for name in (
            'protocol.md',
            'overload-failure.json',
            'removed-artifacts.json',
            'verification.json',
            'rules.md',
            'interactions.md',
            'coverage.md',
            'observability.md',
            'effect-inventory.json',
            'learning-results.json',
            'cost-results.json',
            'primitive-results.json',
            'repeat-verification.json',
            'results.md',
            'aux-revision.md',
            'aux-final.md',
            'aux-failures.json',
            'aux-results.json',
            'target-results.json',
            'environment-results.json',
            'rl-protocol.md',
        )
        if (manifest.parent / name).is_file()
    )
    if (root / 'tools/cards/rule_baseline.py').is_file():
        paths.add(root / 'tools/cards/rule_baseline.py')
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def freeze(root: Path, manifest: Path, version: str) -> None:
    payload = {
        'schema_version': 1,
        'baseline': version,
        'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        'identity_note': 'Worktree content hashes are authoritative; base_commit alone cannot reproduce this baseline.',
        'scope_note': 'Conservative dependency superset; inclusion does not imply card behavior certification.',
        'sha256': sources(root, manifest),
    }
    # Exclusive creation protects an existing baseline from silent refresh.
    with manifest.open('x') as out:
        json.dump(payload, out, indent=2, ensure_ascii=False)
        out.write('\n')
    print(f'FROZEN {len(payload["sha256"])} files: {manifest.relative_to(root)}')


def check(root: Path, manifest: Path) -> bool:
    payload = json.loads(manifest.read_text())
    if payload.get('schema_version') != 1:
        raise ValueError('unsupported baseline manifest schema')
    expected = payload['sha256']
    current = sources(root, manifest)
    added = sorted(current.keys() - expected.keys())
    removed = sorted(expected.keys() - current.keys())
    changed = sorted(p for p in current.keys() & expected.keys() if current[p] != expected[p])
    for label, entries in (('ADDED', added), ('REMOVED', removed), ('CHANGED', changed)):
        for path in entries:
            print(f'{label} {path}')
    if added or removed or changed:
        print('Baseline drift: review rules/tests and freeze a new version; do not refresh this manifest.')
        return False
    print(f'MATCH {payload["baseline"]}: {len(expected)} files; rule correctness is a separate review.')
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT)
    parser.add_argument('--version', help='explicit new version ID; required with --freeze')
    parser.add_argument('--freeze', action='store_true', help='create a new manifest; refuses overwrite')
    args = parser.parse_args()
    manifest = args.manifest.resolve()
    if args.freeze:
        if not args.version:
            parser.error('--freeze requires --version')
        freeze(ROOT, manifest, args.version)
    elif not check(ROOT, manifest):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
