"""Replay dumper — used by tools.eval.ckpt --record-replays.

`play_and_record` retained from former dmc_dump_replay.py (signature / logic
unchanged); `dump_replays_for_ckpt` added to batch-iterate baseline × scenario."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def play_and_record(cfg, scenario, agent, opponent, *, agent_side: int, max_steps: int):
    """Play one game with the engine event log enabled; return
    (outcome, replay_yaml, action_log). outcome: +1/-1/0 from agent view."""
    from gicg_env import GicgEnv

    env = GicgEnv(
        team_0=scenario.team_0,
        team_1=scenario.team_1,
        card_pool=cfg.scenario.card_pool,
        seed=scenario.env_seed,
        data_dir=cfg.scenario.data_dir or 'data',
        max_rounds=cfg.scenario.max_rounds,
        obs_mask=cfg.scenario.obs_mask,
        deck_padding=cfg.scenario.deck_padding,
        pool=cfg.scenario.pool,
    )
    deck_seeds = None
    if scenario.deck_seed_p0 is not None and scenario.deck_seed_p1 is not None:
        deck_seeds = (scenario.deck_seed_p0, scenario.deck_seed_p1)
    env.reset(seed=scenario.env_seed, deck_seeds=deck_seeds)

    actions = []  # list of dicts: {step, acting, action_idx, kind, n_legal}
    if env.done:
        winner = env._engine.winner
        outcome = 0 if winner == 2 or winner < 0 else (1 if winner == agent_side else -1)
        return outcome, env.export_replay(), actions

    agent.game_start(env.static_obs)
    if hasattr(opponent, 'game_start'):
        opponent.game_start(env.static_obs)

    for step_idx in range(max_steps):
        if env.done:
            break
        kinds, _ = env.get_legal_actions()
        n_legal = len(kinds)
        if n_legal == 0:
            break
        acting = env.acting_player
        is_agent_turn = acting == agent_side
        if is_agent_turn:
            saved_eps = agent.epsilon
            agent.epsilon = 0.0
            try:
                action_idx = agent.select_action(env)
            finally:
                agent.epsilon = saved_eps
        else:
            action_idx = opponent.select_action(env)
        if action_idx < 0 or action_idx >= n_legal:
            action_idx = 0
        kind_str = int(kinds[action_idx]) if hasattr(kinds, '__getitem__') else 'unknown'
        actions.append(
            {
                'step': step_idx,
                'acting': acting,
                'side': 'agent' if is_agent_turn else 'opponent',
                'action_idx': int(action_idx),
                'kind': kind_str,
                'n_legal': n_legal,
            }
        )
        env.step(action_idx)

    winner = env._engine.winner
    if winner < 0 or winner == 2:
        outcome = 0
    elif winner == agent_side:
        outcome = 1
    else:
        outcome = -1
    replay_yaml = env.export_replay()
    env.close()
    return outcome, replay_yaml, actions


def dump_replays_for_ckpt(
    *,
    cfg,
    agent,
    ckpt_label: str,
    baselines: list[str],
    output_dir: Path,
    save_both_win: bool,
    only_sid: int,
    scenarios_seed: Optional[int],
    paradigm: str,
):
    """For each baseline × scenario, run case A (agent_side=0) + case B
    (agent_side=1), dump yaml + actions JSON. Respect save_both_win + only_sid."""
    from tools.eval._dmc_scenarios import generate_eval_scenarios
    from tools.eval._paradigm import resolve

    build_baseline = resolve(paradigm, 'build_baseline')
    seed = scenarios_seed if scenarios_seed is not None else cfg.eval.scenarios_seed
    scenarios = generate_eval_scenarios(
        seed=seed,
        n=cfg.eval.n_scenarios,
        team_0=cfg.scenario.team_0,
        team_1=cfg.scenario.team_1,
        char_pool=cfg.scenario.char_pool,
        team_size=cfg.scenario.team_size,
        disjoint_teams=cfg.scenario.disjoint_teams,
    )
    for baseline_name in baselines:
        b_dir = output_dir / f'vs_{baseline_name}'
        b_dir.mkdir(parents=True, exist_ok=True)
        for s in scenarios:
            if only_sid >= 0 and s.scenario_id != only_sid:
                continue
            opp_a = build_baseline(baseline_name, seed=s.env_seed, cfg=cfg)
            out_a, yaml_a, act_a = play_and_record(cfg, s, agent, opp_a, agent_side=0, max_steps=cfg.max_game_steps)
            opp_b = build_baseline(baseline_name, seed=s.env_seed + 1, cfg=cfg)
            out_b, yaml_b, act_b = play_and_record(cfg, s, agent, opp_b, agent_side=1, max_steps=cfg.max_game_steps)
            both_win = out_a > 0 and out_b > 0
            if save_both_win and not both_win:
                continue
            for tag, yaml_str, act_list in (('caseA', yaml_a, act_a), ('caseB', yaml_b, act_b)):
                (b_dir / f'sid{s.scenario_id}_{tag}.yaml').write_text(yaml_str)
                (b_dir / f'sid{s.scenario_id}_{tag}_actions.json').write_text(json.dumps(act_list, indent=2))
            print(
                f'  {ckpt_label} vs {baseline_name} sid={s.scenario_id} '
                f'A={out_a:+d} B={out_b:+d}{" ✓both" if both_win else ""}'
            )
