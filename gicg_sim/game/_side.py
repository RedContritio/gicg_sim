from typing import List

from ..constants.id import CharacterID
from .card import Card
from .character import Character
from .dice import DiceState
from .summon import SummonToken
from .supporter import SupporterToken


class _GameSide:
    def __init__(self) -> None:
        self.cards_tile: List[Card] = []
        self.cards_hand: List[Card] = []
        self.characters: List[Character] = []
        self.backup_characters: List[List[Character]] = []
        self.summons: List[SummonToken] = []
        self.supporters: List[SupporterToken] = []
        self.dices: DiceState = DiceState()
        self.active_character_id: CharacterID | None = None

    def _add_character(self, character: Character):
        self.characters.append(character)

        if self.active_character_id is None:
            self.active_character_id = character.id

    def get_active_character(self) -> Character:
        if self.active_character_id is None:
            raise ValueError("No active character")
        for character in self.characters:
            if character.id == self.active_character_id:
                return character
        raise ValueError("No active character")

    @property
    def active_character(self) -> Character:
        return self.get_active_character()

    def _set_dice(self, dices: DiceState):
        self.dices = dices
