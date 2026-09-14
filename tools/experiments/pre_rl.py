"""Read-only final preflight. Does not launch training or allocate a run."""

import hashlib
import json
import math
from pathlib import Path

from gicg_env.engine import get_lib_path
from tools.cards.rule_baseline import DEFAULT, ROOT, check
from training.core.artifact_io import fingerprint
from training.core.config.loader import load_cfg


def validate_evidence(evidence, source, library):
    if evidence.get('ready_for_small_rl') is not True:
        raise ValueError('pre-RL preparation is not complete')
    if evidence.get('source_observation_sha256') != source:
        raise ValueError('preparation source fingerprint changed')
    if evidence.get('engine_sha256') != library:
        raise ValueError('native library differs from the verified library; rerun the gate after rebuild')
    for name in ('environment_gate', 'action_alias_gate', 'regression', 'full_smoke', 'seeding', 'exact_resume'):
        if evidence.get(name) != 'passed':
            raise ValueError(f'missing passing evidence: {name}')
    if set(evidence.get('target_seeds', [])) != {41, 42, 43}:
        raise ValueError('target learnability seeds incomplete')
    if set(evidence.get('rule_seeds', [])) != {41, 42, 43}:
        raise ValueError('rule learnability seeds incomplete')
    for name, width in (('target_accuracy', 1), ('rule_balanced_accuracy', 3)):
        rows = evidence.get(name, {})
        if set(rows) != {'41', '42', '43'}:
            raise ValueError(f'incomplete metrics: {name}')
        for values in rows.values():
            if len(values) != width or any(not math.isfinite(v) or not 0.9 <= v <= 1 for v in values):
                raise ValueError(f'learnability threshold failed: {name}')
    erased = evidence.get('target_erased_accuracy', {})
    if set(erased) != {'41', '42', '43'} or any(v != 0.5 for v in erased.values()):
        raise ValueError('target ablation evidence incomplete')


def main():
    if not check(ROOT, DEFAULT):
        raise SystemExit('frozen source baseline differs; do not train against stale evidence')
    evidence = json.loads((DEFAULT.parent / 'verification.json').read_text())
    library = hashlib.sha256(Path(get_lib_path()).read_bytes()).hexdigest()
    validate_evidence(evidence, fingerprint(), library)
    cfg = load_cfg('configs/dmc/pre_rl_small.toml')
    if cfg.meta.paradigm != 'dmc' or cfg.pipeline.mode != 'serial':
        raise ValueError('first RL budget requires serial DMC')
    if cfg.paradigm['total_frames'] != 3000 or cfg.paradigm['max_game_steps'] != 512:
        raise ValueError('first RL budget changed')
    if cfg.scenario.team_size > 2 or 'enemy_dice' not in cfg.scenario.obs_mask:
        raise ValueError('scenario exceeds verified observation scope')
    if {'以逸待劳', '速速茶点'}.intersection(cfg.scenario.card_pool):
        raise ValueError('reserved transfer rules leaked into initial training')
    print('READY for the registered 1v1/2v2 small-RL scope; no training started.')
    print('Protocol:', DEFAULT.parent / 'rl-protocol.md')


if __name__ == '__main__':
    main()
