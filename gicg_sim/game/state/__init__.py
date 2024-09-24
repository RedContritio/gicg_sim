
from ...constants.id import CharacterID


class State(dict):
    @property
    def current_character(self) -> CharacterID:
        raise NotImplementedError
