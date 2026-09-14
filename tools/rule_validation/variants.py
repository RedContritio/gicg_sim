"""Typed, per-game rule variants shared by demonstration, RL and evaluation."""

from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path
import random
import tempfile
import tomllib

from tools.rule_validation.patches import Patch, apply


def specification(path):
    raw = Path(path).read_bytes()
    spec = tomllib.loads(raw.decode('utf-8'))
    if spec['version'] != '1.0.0' or not 1 <= spec['max_changes'] <= 2:
        raise ValueError('unsupported variant specification')
    ids = set()
    for p in spec['parameters']:
        if p['id'] in ids or p['kind'] not in ('cost', 'damage', 'heal'):
            raise ValueError('invalid variant parameter')
        ids.add(p['id'])
        if set(p['train']) & set(p['heldout']):
            raise ValueError('train/heldout values overlap')
        for split in ('train', 'heldout'):
            if not any(v != p['base'] for v in p[split]):
                raise ValueError('empty effective variation')
            if any(type(v) is not int or not 1 <= v <= 8 for v in p[split]):
                raise ValueError('invalid literal range')
    return spec, hashlib.sha256(raw).hexdigest()


def sample(spec, seed, characters, split='train'):
    if split not in ('train', 'heldout'):
        raise ValueError('invalid variant split')
    rng = random.Random(seed)
    eligible = [p for p in spec['parameters'] if p['character'] in characters]
    if not eligible:
        raise ValueError('no parameters for selected team')
    chosen = rng.sample(eligible, rng.randint(1, min(spec['max_changes'], len(eligible))))
    patches, changes = [], []
    for p in chosen:
        value = rng.choice([v for v in p[split] if v != p['base']])
        after = p['template'].replace('VALUE', str(value)).replace('BONUS', str(value + 2))
        patches.append(Patch(p['path'], p['before'], after))
        changes.append(dict(id=p['id'], kind=p['kind'], before=p['base'], after=value))
    return patches, changes


@contextmanager
def environment_config(cfg, path, seed, index, *, split='train'):
    # Each four-game block contains two native/two variants and both actor sides.
    if path is None:
        yield cfg, dict(variant=False)
        return
    spec, digest = specification(path)
    manifest = dict(
        variant=split == 'heldout' or index % 4 in (1, 2), specification_sha256=digest, seed=seed, split=split
    )
    if not manifest['variant']:
        yield cfg, manifest
        return
    if cfg.scenario.pool != 'native_latest':
        raise ValueError('native variant catalog requires native_latest')
    patches, changes = sample(spec, seed, cfg.scenario.team_0 + cfg.scenario.team_1, split)
    with tempfile.TemporaryDirectory(prefix='gicg-variant-') as temp:
        manifest.update(apply(cfg.scenario.data_dir, temp, patches), changes=changes)
        yield replace(cfg, scenario=replace(cfg.scenario, data_dir=temp)), manifest
