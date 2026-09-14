"""Independent full-game card exposure/use audit; does not select checkpoints."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
import hashlib
from pathlib import Path

from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.deck_curriculum import card_grades
from tools.experiments.semantic_training.teams import eval_cases, with_teams
from training.core.config.loader import load_cfg
from training.core.artifact_io import provenance
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer


def game(job):
    index, side, case, seed = job
    cfg = with_teams(ev._CFG, case.team_0, case.team_1)
    env = make_env_factory(cfg, None, seed)(index)
    opponent = GreedyPlayer(
        features='F1', depth=2, dice_greedy=True, seed=derive_seed(seed, 'opponent', index * 2 + side)
    )
    try:
        env.reset(seed=case.env_seed, deck_seeds=(case.deck_seed_p0, case.deck_seed_p1))
        if isinstance(ev._AGENT, GreedyPlayer):
            ev._AGENT.rng.seed(derive_seed(seed, 'own', index * 2 + side))
        else:
            ev._AGENT.game_start(env.static_obs)
        names = env._engine.get_card_names()
        starting = Counter(names[r] for r in list(env._engine.hand_refs(side)) + list(env._engine.deck_refs(side)))
        seen, legal, used = set(), set(), Counter()
        for _ in range(cfg.paradigm['max_game_steps']):
            seen.update(names[r] for r in env._engine.hand_refs(side))
            if env.done:
                break
            own = env.acting_player == side
            action = (ev._AGENT if own else opponent).select_action(env)
            if own:
                labels = env.get_action_labels()
                legal.update(name for kind, name, _ in labels if kind == 'Card')
                kind, name, _ = labels[action]
                if kind == 'Card':
                    used[name] += 1
            env.step(action)
        if not env.done or env.winner not in (0, 1):
            raise RuntimeError('card audit did not reach a decided terminal state')
        return dict(
            index=index,
            side=side,
            team=case.team_0 if side == 0 else case.team_1,
            starting=dict(starting),
            seen=sorted(seen),
            legal=sorted(legal),
            used=dict(used),
            win=int(env.winner == side),
        )
    finally:
        env.close()


def run(config, checkpoint, output, scenarios=240, workers=16, seed=310000):
    destination = Path(output)
    if destination.exists():
        raise FileExistsError(destination)
    cases = eval_cases(load_cfg(config), seed, scenarios)
    jobs = [(i, side, case, seed) for i, case in enumerate(cases) for side in (0, 1)]
    with ProcessPoolExecutor(max_workers=workers, initializer=ev.initialize, initargs=(config, checkpoint)) as pool:
        rows = list(pool.map(game, jobs))
    cards = {}
    for name, grade in card_grades().items():
        groups = {}
        for team in sorted({'+'.join(sorted(row['team'])) for row in rows}):
            subset = [row for row in rows if '+'.join(sorted(row['team'])) == team]
            groups[team] = dict(
                games=len(subset),
                copies=sum(row['starting'].get(name, 0) for row in subset),
                included_games=sum(name in row['starting'] for row in subset),
                seen_games=sum(name in row['seen'] for row in subset),
                legal_games=sum(name in row['legal'] for row in subset),
                used_games=sum(name in row['used'] for row in subset),
                play_events=sum(row['used'].get(name, 0) for row in subset),
            )
        cards[name] = dict(
            grade=grade,
            by_team=groups,
            **{
                key: sum(group[key] for group in groups.values())
                for key in ('copies', 'included_games', 'seen_games', 'legal_games', 'used_games', 'play_events')
            },
        )
    result = dict(
        status='complete',
        checkpoint=str(checkpoint),
        config=config,
        seed=seed,
        cards=cards,
        games=rows,
        provenance=provenance(),
        checkpoint_sha256=None
        if checkpoint == 'teacher-d2'
        else hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(
        {
            name: {k: row[k] for k in ('included_games', 'seen_games', 'legal_games', 'used_games')}
            for name, row in cards.items()
        },
        flush=True,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('checkpoint')
    parser.add_argument('output')
    parser.add_argument('--scenarios', type=int, default=240)
    parser.add_argument('--workers', type=int, default=16)
    args = parser.parse_args()
    run(args.config, args.checkpoint, args.output, args.scenarios, args.workers)
