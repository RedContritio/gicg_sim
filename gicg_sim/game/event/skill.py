from ...constants.id import CharacterID
from ...constants.skill import SkillType
from ._base import BaseEvent


class SkillEvent(BaseEvent):
    def __init__(self, name: str, type: SkillType,
                 src_character: CharacterID) -> None:
        self.name = name
        self.type = type
        self.src_character = src_character
        super().__init__()
        pass
