"""Five-character balance matrices under paired seats, policy and deck controls."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

from training.core.artifact_io import provenance
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer
from training.core.matchup.outcome import terminal_outcome

CHARS = ['赤蝶', '墨客', '猫咪', '刻师傅', '天星']
PROFILES = {'current8': (False, 8), 'blank8': (True, 8), 'current10': (False, 10)}
_CFG = None


def initialize(config):
    global _CFG
    _CFG = load_cfg(config)


def play(job):
    profile, depth, a, b, index, swap, seed = job
    blank, cap = PROFILES[profile]
    teams = [[a], [b]] if swap == 0 else [[b], [a]]
    scenario = replace(
        _CFG.scenario,
        team_0=teams[0],
        team_1=teams[1],
        max_rounds=cap,
        card_pool=['碌碌无为'] if blank else _CFG.scenario.card_pool,
    )
    cfg = replace(_CFG, scenario=scenario)
    physical_seed = derive_seed(seed, 'balance-game', index)
    env = make_env_factory(cfg, None, physical_seed)(
        0, layout_seed=derive_seed(seed, 'balance-layout', index * 2 + swap)
    )
    # Character A/B retain their deck and tie-breaking seeds when swapping player slots.
    decks = [derive_seed(seed, f'deck-{k}', index) for k in (0, 1)]
    ties = [derive_seed(seed, f'policy-{k}', index) for k in (0, 1)]
    if swap:
        decks.reverse()
        ties.reverse()
    players = [GreedyPlayer(features='F1', depth=depth, dice_greedy=True, seed=s) for s in ties]
    try:
        env.reset(seed=physical_seed, deck_seeds=tuple(decks))
        initial = env.acting_player
        for step in range(512):
            if env.done:
                break
            env.step(players[env.acting_player].select_action(env))
        if not env.done:
            raise RuntimeError(f'balance step budget exceeded: {job}')
        outcome = terminal_outcome(env.winner, swap)
        view = env.export_view()
        return dict(
            profile=profile,
            depth=depth,
            a=a,
            b=b,
            index=index,
            swap=swap,
            score=(outcome + 1) / 2,
            win=int(outcome == 1),
            draw=int(outcome == 0),
            winner=env.winner,
            initial_player=initial,
            steps=step,
            final_view=view,
        )
    finally:
        env.close()


def run(config, output, scenarios=128, workers=16, seed=139000):
    if scenarios < 1:
        raise ValueError('positive scenario count required')
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    cfg = load_cfg(config)
    jobs = [
        (profile, depth, a, b, i, swap, seed)
        for profile in PROFILES
        for depth in (1, 2)
        for ai, a in enumerate(CHARS)
        for b in CHARS[ai:]
        for i in range(scenarios)
        for swap in (0, 1)
    ]
    status = dict(
        status='running',
        scenarios=scenarios,
        workers=workers,
        seed=seed,
        characters=CHARS,
        profiles=PROFILES,
        policies=['F1-D1 dice_greedy', 'F1-D2 dice_greedy'],
        base_scenario=asdict(cfg.scenario),
        provenance=provenance(),
        total_games=len(jobs),
        games_done=0,
        tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    start = time.monotonic()

    def save():
        status['wall_s'] = time.monotonic() - start
        tmp = root / 'result.tmp'
        tmp.write_text(json.dumps(status, indent=2, ensure_ascii=False))
        tmp.replace(root / 'result.json')

    save()
    try:
        with (root / 'games.jsonl').open('w', encoding='utf-8') as log:
            with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(config,)) as pool:
                for row in pool.map(play, jobs, chunksize=8):
                    log.write(json.dumps(row, ensure_ascii=False) + '\n')
                    status['games_done'] += 1
                    if status['games_done'] % 512 == 0:
                        log.flush()
                        save()
                        print(
                            {'games': status['games_done'], 'total': len(jobs), 'wall_s': status['wall_s']}, flush=True
                        )
        status['status'] = 'complete'
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        raise
    finally:
        save()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('output')
    p.add_argument('--scenarios', type=int, default=128)
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--seed', type=int, default=139000)
    a = p.parse_args()
    run(a.config, a.output, a.scenarios, a.workers, a.seed)
