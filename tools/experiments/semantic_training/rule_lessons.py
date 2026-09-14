"""Engine-labelled numeric rule lessons; synthetic data, not match evaluation."""

from dataclasses import replace
from itertools import product
from pathlib import Path
import random
import tempfile

from tools.experiments.semantic_training.rule_probe import SKILLS, case, oracle, variant
from tools.experiments.semantic_training.teams import with_teams
from training.core.env_factory import make_env_factory
from tools.rule_validation.outcomes import choose, seek


def specifications():
    train = [(low, high) for low, high in product((1, 3, 5), (10, 12, 14))]
    heldout = [(low, high) for low, high in product((2, 4), (11, 13))]
    return train, heldout


def trio_case(cfg, data, seed, layout):
    rng = random.Random(seed)
    others = [name for name in cfg.scenario.char_pool if name != '凯亚']
    cfg = with_teams(cfg, ['凯亚'] + rng.sample(others, 2), rng.sample(cfg.scenario.char_pool, 3))
    cfg = replace(cfg, scenario=replace(cfg.scenario, data_dir=str(data), fix_dice=[0] * 7 + [8]))
    env = make_env_factory(cfg, None, seed)(0, layout_seed=layout)
    try:
        return env, seek(env, [('Skill', name) for name in SKILLS], player=0)
    except BaseException:
        env.close()
        raise


def damage_oracle(env, indices):
    """Only compares immediate HP loss, never claims full-game optimality."""
    return choose(env, indices, 'enemy_hp_loss')


def build(cfg, agent, seed=93800):
    """Disjoint literal values; equivalent syntax is held out from optimization."""
    train, heldout = specifications()
    rows = []
    with tempfile.TemporaryDirectory(prefix='gicg-rule-lessons-') as temp:
        for split, pairs, indirect in [('train', train, False), ('values', heldout, False), ('syntax', heldout, True)]:
            for index, pair in enumerate(pairs):
                for reverse in (False, True):
                    damages = pair[::-1] if reverse else pair
                    data = Path(temp) / f'{split}_{index}_{int(reverse)}'
                    digest = variant(cfg.scenario.data_dir, data, damages, indirect)
                    game_seed = seed + index + (1000 if split != 'train' else 0)
                    for mode in ('duel', 'trio'):
                        env, indices = (
                            case(data, game_seed, game_seed + 1)
                            if mode == 'duel'
                            else trio_case(cfg, data, game_seed, game_seed + 1)
                        )
                        try:
                            if mode == 'duel':
                                preferred, amounts = oracle(env, indices), None
                                candidates = list(range(len(env.get_action_labels())))
                            else:
                                preferred, amounts = damage_oracle(env, indices)
                                candidates = [a for group in indices for a in group]
                            agent.game_start(env.static_obs)
                            rows.append(
                                dict(
                                    split=split,
                                    mode=mode,
                                    damages=damages,
                                    indirect=indirect,
                                    seed=game_seed,
                                    data_sha256=digest,
                                    observed_damage=amounts,
                                    obs=agent.observation(env),
                                    tied=indices[preferred],
                                    candidates=candidates,
                                )
                            )
                        finally:
                            env.close()
    return rows
