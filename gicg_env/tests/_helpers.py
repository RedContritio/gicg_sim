from gicg_env import ACTION_REROLL


def keep_all_rerolls(game):
    for _ in range(20):
        kinds, _ = game.get_legal_actions()
        if len(kinds) == 0 or any(kind != ACTION_REROLL for kind in kinds):
            return
        game.step(0)
    raise AssertionError('round-start reroll did not finish')
