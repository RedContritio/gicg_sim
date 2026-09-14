"""Audit effects using resolved training configs and the production Go factory.

python -m tools.cards.effect_audit --output /tmp/effect-audit.json
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from training.core.config.loader import load_with_extends

DEFAULTS = [f'configs/{p}/default.toml' for p in ('az', 'bc', 'cfr', 'dmc', 'ppo')]
DEFAULTS += ['configs/dmc/stage3_b_v_legacy.toml']


def game_config(path):
    scenario = load_with_extends(Path(path)).get('scenario', {})
    players = []
    for p in range(2):
        team = scenario.get(f'team_{p}')
        if not team:
            raise ValueError(f'{path}: explicit team_{p} required for reproducible audit')
        player = {'chars': [{'name': name} for name in team]}
        if scenario.get(f'deck_{p}') is not None:
            player['deck'] = scenario[f'deck_{p}']
        players.append(player)
    result = {'players': players, 'seed': 42, 'pools': scenario.get('pool', ['v_legacy'])}
    for key in ('card_pool', 'data_dir', 'max_rounds', 'deck_padding'):
        if key in scenario:
            result[key] = scenario[key]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', action='append', help='training TOML, repeatable; defaults to six live configs')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reports = {}
    failed = False
    env = dict(os.environ)
    env.setdefault('GOCACHE', '/private/tmp/gicg-review-go-cache')
    with tempfile.TemporaryDirectory(prefix='gicg-effect-audit-') as tmp:
        binary = str(Path(tmp) / 'audit')
        subprocess.run(['go', 'build', '-o', binary, './tools/cards/audit_effects'], check=True, env=env)
        for name in args.config or DEFAULTS:
            cfg = game_config(name)
            config = Path(tmp) / 'config.json'
            config.write_text(json.dumps(cfg, ensure_ascii=False))
            result = subprocess.run([binary, '-config', str(config)], capture_output=True, text=True)
            if result.returncode not in (0, 1) or not result.stdout.strip().startswith('{'):
                raise RuntimeError(f'{name}: {result.stderr}')
            report = json.loads(result.stdout)
            reports[name] = {'configuration': cfg, **report}
            failed |= result.returncode != 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + '\n')
    count = sum(len(r['Effects']) for r in reports.values())
    issues = sum(len(r['Issues'] or []) for r in reports.values())
    print(f'{len(reports)} configurations, {count} effect bindings, {issues} issues: {args.output}')
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
