"""Model ranking is separate from the engine's rule assertions."""


def rank(agent, env, groups):
    agent.game_start(env.static_obs)
    logits = agent.logits(env)
    chosen = int(logits.argmax())
    return dict(
        chosen=chosen,
        chosen_label=env.get_action_labels()[chosen],
        group_scores=[float(logits[group].max()) for group in groups],
        group_ranks=[1 + int((logits > logits[group].max()).sum()) for group in groups],
    )
