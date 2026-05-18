"""Small shared helpers: trajectory ingestion, cpu state_dict, arena dispatch.

Phase 2-ζ (FU-W4-AZ-rewrite, T2.ζ) — inlined from
``training.paradigms.az.legacy.train_loop.helpers``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def ingest_trajectory(
    res: dict,
    buffer,
    result,
    log,
    main_weight_version: int = 0,
) -> None:
    """Push one worker result into the buffer and update RunResult."""
    buffer.add_trajectory(res['game_static'], res['steps'])
    result.n_games_played += 1
    result.selfplay_winners.append(res['winner'])
    result.selfplay_n_steps.append(res['n_steps'])
    worker_wv = int(res.get('weight_version_at_start', -1))
    stale_gap = (main_weight_version - worker_wv) if worker_wv >= 0 else -1
    event = {
        'game': res['game_idx'] + 1,
        'worker_id': res['worker_id'],
        'n_steps': res['n_steps'],
        'winner': res['winner'],
        'discovery': res['discovery_count'],
        'buffer_size': len(buffer),
        'wall_s': res.get('wall_s', -1),
        'weight_version': worker_wv,
        'stale_gap': stale_gap,
    }
    if 'effective_lambda' in res:
        event['effective_lambda'] = res['effective_lambda']
    if res.get('mcts_profile'):
        event['mcts_profile'] = res['mcts_profile']
    if 'team_0' in res:
        event['team_0'] = res['team_0']
        event['team_1'] = res['team_1']
    log('selfplay', event)


def cpu_state_dict(agent) -> dict:
    """Serialize the agent's net state_dict to CPU tensors suitable
    for queue transport to worker processes."""
    return {k: v.detach().cpu() for k, v in agent.net.state_dict().items()}


def maybe_arena(
    config,
    challenger,
    champion,
    env_factory,
    game_marker: int,
    result,
    log,
    artifacts_dir: Optional[Path],
) -> None:
    """Arena challenger-vs-champion eval; on replacement, save the new
    champion ckpt to ``<artifacts_dir>/ckpts/champion_g<NNNNN>.pt``.

    Spec ref: ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-
    design.md`` §Per-run dir 行 76-96 / §ckpts/ naming 行 606-613
    (``ckpts/`` 含所有 ``.pt``).

    Width: 5-digit zero-pad on ``game_marker``. This is AZ-internal
    convention (larger than gauntlet's 4-digit) and is intentionally
    NOT unified — see T-30 plan note (historical OK).
    """
    from training.paradigms.az.arena import arena_match

    arena = arena_match(
        challenger=challenger,
        champion=champion,
        env_factory=env_factory,
        n_games=config.arena_games,
        max_game_steps=config.arena_max_game_steps,
        seed=config.seed + 10_000 + game_marker,
    )
    result.arena_results.append((game_marker, arena))
    log(
        'arena',
        {
            'game': game_marker,
            'challenger_wins': arena.challenger_wins,
            'champion_wins': arena.champion_wins,
            'draws': arena.draws,
            'win_rate': arena.challenger_win_rate,
        },
    )
    if arena.challenger_win_rate >= config.arena_replace_threshold:
        champion.net.load_state_dict(challenger.net.state_dict())
        result.champion_replacements.append(game_marker)
        log('replace', {'game': game_marker, 'win_rate': arena.challenger_win_rate})
        if artifacts_dir is not None:
            ckpts_dir = artifacts_dir / 'ckpts'
            ckpts_dir.mkdir(parents=True, exist_ok=True)
            challenger.save(str(ckpts_dir / f'champion_g{game_marker:05d}.pt'))
