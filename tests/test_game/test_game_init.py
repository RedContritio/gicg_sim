import gicg_sim.game


def test_game_side_count():
    game = gicg_sim.game.Game()
    assert gicg_sim.game.GAME_SIDE_COUNT == len(game.sides)


def test_game_side_members():
    members = ['cards_tile', 'cards_hand', 'summons',
               'supporters', 'characters', 'dices']
    game = gicg_sim.game.Game()
    for side in game.sides:
        for member in members:
            assert hasattr(side, member)
