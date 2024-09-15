from collections import deque
from typing import MutableSequence

from ..constants.global_ import GAME_SIDE_COUNT
from ._side import _GameSide
from .event import BaseEvent


class Game:
    def __init__(self) -> None:
        self.sides = [_GameSide() for _ in range(GAME_SIDE_COUNT)]
        self.current_side = 0
        self.event_queue: MutableSequence[BaseEvent] = deque()

    def get_current_side(self) -> _GameSide:
        return self.sides[self.current_side]

    def player_input(self, operation: str):
        pass

    def player_use_skill(self, skill: str):
        character = self.get_current_side().get_active_character()
        character.use_skill(self.event_queue, skill)
